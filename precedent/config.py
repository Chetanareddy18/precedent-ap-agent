"""Runtime configuration, read from environment / .env."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    hindsight_base_url: str | None = os.getenv("HINDSIGHT_BASE_URL") or None
    hindsight_api_key: str | None = os.getenv("HINDSIGHT_API_KEY") or None
    bank_id: str = os.getenv("HINDSIGHT_BANK_ID", "godavari-ap")
    llm_api_key: str | None = os.getenv("GROQ_API_KEY") or os.getenv("LLM_API_KEY") or None
    llm_base_url: str = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
    llm_model: str = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")
    llm_fallback_model: str = os.getenv("LLM_FALLBACK_MODEL", "qwen/qwen3-32b")
    auto_confidence: float = float(os.getenv("AUTO_RESOLVE_CONFIDENCE", "0.75"))
    minutes_per_exception: float = float(os.getenv("MINUTES_PER_EXCEPTION", "18"))
    data_dir: Path = ROOT / "data"


settings = Settings()
