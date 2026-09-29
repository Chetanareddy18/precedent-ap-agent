"""LLM access via Groq's OpenAI-compatible API, hardened for structured output.

Models on free tiers fail in boring ways: malformed JSON, `<think>` blocks before the JSON,
tool-call validation errors, 429s. We never let that break an AP decision:

  1. ask for a JSON object (response_format=json_object)
  2. strip reasoning tags / code fences and parse; on failure, retry once with the parse error
  3. fall back to the secondary model
  4. if everything fails, return None and the caller uses its deterministic heuristic
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

log = logging.getLogger("precedent.llm")

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_json_object(raw: str) -> dict[str, Any]:
    """Extract the first JSON object from a model response. Raises ValueError if none."""
    text = _FENCE.sub("", _THINK.sub("", raw or "")).strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                esc = (ch == "\\") and not esc
                if ch == '"' and not esc:
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start:i + 1])
                        if isinstance(obj, dict):
                            return obj
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    raise ValueError("no JSON object found in model output")


class LLM:
    def __init__(self, api_key: str | None, base_url: str, models: list[str]):
        self.models = [m for m in models if m]
        self.enabled = bool(api_key)
        self._client = None
        if self.enabled:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, timeout=45.0, max_retries=2)

    @property
    def label(self) -> str:
        return self.models[0] if self.enabled else "disabled"

    async def json(self, system: str, user: str, *, max_tokens: int = 1200) -> tuple[dict[str, Any] | None, str | None]:
        """Returns (parsed_object, model_used) or (None, None) if every attempt failed."""
        if not self.enabled:
            return None, None
        for model in self.models:
            messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
            for attempt in range(2):
                try:
                    resp = await self._client.chat.completions.create(
                        model=model, messages=messages, temperature=0.1, max_tokens=max_tokens,
                        response_format={"type": "json_object"},
                    )
                    raw = resp.choices[0].message.content or ""
                    return parse_json_object(raw), model
                except ValueError as exc:  # unparseable -> ask the model to repair once
                    log.warning("%s returned non-JSON (attempt %d): %s", model, attempt + 1, exc)
                    messages = messages + [
                        {"role": "assistant", "content": raw[:4000]},
                        {"role": "user", "content": "That was not a single valid JSON object. Reply with ONLY the JSON object."},
                    ]
                except Exception as exc:  # API error, json_validate_failed, rate limit, timeout
                    log.warning("%s call failed (attempt %d): %s", model, attempt + 1, str(exc)[:300])
                    if "json_validate_failed" not in str(exc):
                        break  # move on to the fallback model
        return None, None
