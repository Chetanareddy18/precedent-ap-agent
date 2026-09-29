"""Memory layer. Hindsight is the production backend; LocalMemory is an offline test double.

Everything the agent knows about *how this company handles its vendors* lives here:

  retain     -> every resolved exception (clerk decisions, overrides, confirmed agent decisions)
  recall     -> vendor-scoped precedents (tag vendor:<id>) + cross-vendor patterns (tag exc:<code>)
  directives -> standing policies a clerk promotes from a note ("never pay changed bank details...")
  mental     -> one auto-refreshing "vendor playbook" per vendor, synthesised by Hindsight
  models
  reflect    -> free-form questions over the whole AP history ("which vendors cost us the most time?")
"""
from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from .models import Precedent

log = logging.getLogger("precedent.memory")

BANK_MISSION = (
    "You are the institutional memory of the Accounts Payable team at Godavari Consumer Products, "
    "a Hyderabad FMCG manufacturer. Track how each vendor's invoice exceptions were resolved, the "
    "reasons the AP clerk gave, and every condition, limit, threshold, effective date or contract clause "
    "that decides whether a similar exception can be approved next time."
)
RETAIN_MISSION = (
    "Extract: vendor name and id, invoice number and date, exception type, the measured amounts or "
    "percentages, the final action (approve / short-pay / reject / hold / pay early), the payable amount, "
    "who decided, and — most importantly — the clerk's reasoning, including caps, tolerances, effective "
    "dates, contract clauses and anything the clerk said should happen next time."
)


@dataclass
class ReflectAnswer:
    text: str
    sources: list[Precedent] = field(default_factory=list)


class MemoryStore(Protocol):
    backend: str

    async def ensure_bank(self) -> None: ...
    async def reset(self) -> None: ...
    async def retain(self, content: str, *, timestamp: datetime, tags: list[str], metadata: dict[str, str],
                     document_id: str, context: str) -> None: ...
    async def recall(self, query: str, *, tags: list[str], limit: int = 6, scope: str = "vendor") -> list[Precedent]: ...
    async def directives(self) -> list[dict[str, str]]: ...
    async def add_directive(self, name: str, content: str, tags: list[str]) -> None: ...
    async def ensure_playbook(self, vendor_id: str, vendor_name: str) -> None: ...
    async def playbook(self, vendor_id: str) -> str | None: ...
    async def reflect(self, query: str, tags: list[str] | None = None) -> ReflectAnswer: ...
    async def stats(self) -> dict[str, Any]: ...


def _items(resp: Any) -> list[Any]:
    if resp is None:
        return []
    if isinstance(resp, list):
        return resp
    for attr in ("items", "results", "directives", "mental_models"):
        val = getattr(resp, attr, None)
        if val is not None:
            return list(val)
    return []


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


class HindsightMemory:
    """Thin async adapter over the official hindsight-client."""

    backend = "hindsight"

    def __init__(self, base_url: str, api_key: str | None, bank_id: str):
        from hindsight_client import Hindsight

        self.bank_id = bank_id
        self.client = Hindsight(base_url=base_url, api_key=api_key or None, timeout=120.0)
        self._bank_ready = False
        self._playbooks: set[str] = set()

    async def ensure_bank(self) -> None:
        if self._bank_ready:
            return
        try:
            await self.client.acreate_bank(
                bank_id=self.bank_id,
                name="Godavari AP — exception memory",
                mission=BANK_MISSION,
                retain_mission=RETAIN_MISSION,
                # AP should be sceptical and literal: a limit of ₹3,000 means ₹3,000.
                disposition_skepticism=5, disposition_literalism=4, disposition_empathy=2,
                enable_observations=True,
            )
        except Exception as exc:  # already exists -> fine
            log.info("create_bank: %s", str(exc)[:160])
        self._bank_ready = True

    async def reset(self) -> None:
        try:
            await self.client.adelete_bank(self.bank_id)
        except Exception as exc:
            log.info("delete_bank: %s", str(exc)[:160])
        self._bank_ready = False
        self._playbooks.clear()
        await self.ensure_bank()

    async def retain(self, content, *, timestamp, tags, metadata, document_id, context) -> None:
        await self.ensure_bank()
        await self.client.aretain(
            bank_id=self.bank_id, content=content, timestamp=timestamp, context=context,
            document_id=document_id, metadata=metadata, tags=tags, retain_async=False,
        )

    async def recall(self, query, *, tags, limit=6, scope="vendor") -> list[Precedent]:
        await self.ensure_bank()
        resp = await self.client.arecall(
            bank_id=self.bank_id, query=query, tags=tags, tags_match="any_strict",
            budget="mid", max_tokens=2048,
        )
        out: list[Precedent] = []
        for r in _items(resp)[:limit]:
            out.append(Precedent(
                id=str(r.id), text=r.text, type=getattr(r, "type", None),
                occurred=_iso(getattr(r, "occurred_start", None) or getattr(r, "mentioned_at", None)),
                tags=list(getattr(r, "tags", None) or []),
                metadata={k: str(v) for k, v in (getattr(r, "metadata", None) or {}).items()},
                scope=scope,
            ))
        return out

    async def directives(self) -> list[dict[str, str]]:
        await self.ensure_bank()
        try:
            resp = await self.client.alist_directives(bank_id=self.bank_id)
        except Exception as exc:
            log.warning("list_directives failed: %s", exc)
            return []
        return [{"name": d.name, "content": d.content} for d in _items(resp)
                if getattr(d, "is_active", True)]

    async def add_directive(self, name, content, tags) -> None:
        await self.ensure_bank()
        await self.client.acreate_directive(bank_id=self.bank_id, name=name, content=content,
                                            priority=10, tags=tags)

    async def ensure_playbook(self, vendor_id, vendor_name) -> None:
        if vendor_id in self._playbooks:
            return
        model_id = f"playbook-{vendor_id.lower()}"
        try:
            await self.client.acreate_mental_model(
                bank_id=self.bank_id, id=model_id, name=f"Vendor playbook — {vendor_name}",
                source_query=(f"How does our AP team handle invoice exceptions from {vendor_name}? List each "
                              f"recurring exception, the standard resolution, and every limit, threshold, "
                              f"effective date or condition that changes the outcome."),
                tags=[f"vendor:{vendor_id}"], max_tokens=600,
                trigger={"refresh_after_consolidation": True},
            )
        except Exception as exc:  # exists already
            log.info("create_mental_model %s: %s", model_id, str(exc)[:160])
            try:
                await self.client.arefresh_mental_model(self.bank_id, model_id)
            except Exception:
                pass
        self._playbooks.add(vendor_id)

    async def playbook(self, vendor_id) -> str | None:
        try:
            mm = await self.client.aget_mental_model(self.bank_id, f"playbook-{vendor_id.lower()}", detail="content")
        except Exception:
            return None
        return getattr(mm, "content", None) or None

    async def reflect(self, query, tags=None) -> ReflectAnswer:
        await self.ensure_bank()
        resp = await self.client.areflect(
            bank_id=self.bank_id, query=query, budget="mid", tags=tags,
            tags_match="any" if tags else "any", include_facts=True,
        )
        sources = []
        based_on = getattr(resp, "based_on", None)
        for f in (getattr(based_on, "memories", None) or [])[:8]:
            sources.append(Precedent(id=str(f.id), text=f.text, type=getattr(f, "type", None),
                                     occurred=_iso(getattr(f, "occurred_start", None)),
                                     tags=list(getattr(f, "tags", None) or [])))
        return ReflectAnswer(text=resp.text or "", sources=sources)

    async def stats(self) -> dict[str, Any]:
        try:
            resp = await self.client.alist_memories(bank_id=self.bank_id, limit=1)
            return {"memories": getattr(resp, "total", None)}
        except Exception:
            return {"memories": None}


# --------------------------------------------------------------------------------------------
_TOKEN = re.compile(r"[a-z0-9₹]+")


def _tokens(text: str) -> set[str]:
    return {t for t in _TOKEN.findall(text.lower()) if len(t) > 2}


class LocalMemory:
    """Offline stand-in with the same interface. Used by the test-suite and when no Hindsight
    endpoint is configured. It stores the raw text and ranks by token overlap — no extraction,
    no consolidation, no temporal reasoning, no mental models. It exists so the pipeline can be
    tested deterministically, not as an alternative to Hindsight."""

    backend = "local-test-double"

    def __init__(self):
        self._rows: list[dict[str, Any]] = []
        self._directives: list[dict[str, str]] = []
        self._playbooks: dict[str, str] = {}

    async def ensure_bank(self) -> None:
        return None

    async def reset(self) -> None:
        self._rows.clear(); self._directives.clear(); self._playbooks.clear()

    async def retain(self, content, *, timestamp, tags, metadata, document_id, context) -> None:
        self._rows = [r for r in self._rows if r["document_id"] != document_id]  # upsert like Hindsight
        self._rows.append({"id": f"mem-{len(self._rows) + 1}", "text": content, "tags": tags,
                           "metadata": metadata, "document_id": document_id, "ts": timestamp})

    async def recall(self, query, *, tags, limit=6, scope="vendor") -> list[Precedent]:
        q = _tokens(query)
        hits = []
        for r in self._rows:
            if tags and not set(tags) & set(r["tags"]):
                continue
            score = len(q & _tokens(r["text"])) + 0.001 * r["ts"].timestamp() / 1e9
            hits.append((score, r))
        hits.sort(key=lambda x: x[0], reverse=True)
        return [Precedent(id=r["id"], text=r["text"], type="experience", occurred=r["ts"].isoformat(),
                          tags=r["tags"], metadata=r["metadata"], scope=scope) for _, r in hits[:limit]]

    async def directives(self) -> list[dict[str, str]]:
        return list(self._directives)

    async def add_directive(self, name, content, tags) -> None:
        self._directives.append({"name": name, "content": content})

    async def ensure_playbook(self, vendor_id, vendor_name) -> None:
        rows = [r for r in self._rows if f"vendor:{vendor_id}" in r["tags"]]
        self._playbooks[vendor_id] = "\n".join(f"- {r['metadata'].get('summary', r['text'][:160])}" for r in rows)

    async def playbook(self, vendor_id) -> str | None:
        return self._playbooks.get(vendor_id)

    async def reflect(self, query, tags=None) -> ReflectAnswer:
        hits = await self.recall(query, tags=tags or [], limit=5)
        return ReflectAnswer(text="(local test double — no synthesis) Closest memories:\n" +
                             "\n".join(f"• {h.text[:200]}" for h in hits), sources=hits)

    async def stats(self) -> dict[str, Any]:
        return {"memories": len(self._rows)}


def build_memory(base_url: str | None, api_key: str | None, bank_id: str) -> MemoryStore:
    if base_url:
        return HindsightMemory(base_url, api_key, bank_id)
    log.warning("HINDSIGHT_BASE_URL not set — using LocalMemory test double. Set it to use Hindsight.")
    return LocalMemory()


def precedent_tags(vendor_id: str, codes: Sequence[str]) -> list[str]:
    return [f"vendor:{vendor_id}", *[f"exc:{c}" for c in codes]]
