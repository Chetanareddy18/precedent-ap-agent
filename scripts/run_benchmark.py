"""Replay the 12-week AP inbox twice — memory OFF, then memory ON — and print the difference.

    python scripts/run_benchmark.py              # uses .env (Hindsight + Groq)
    python scripts/run_benchmark.py --offline    # LocalMemory test double + deterministic heuristic
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from precedent.agent import APAgent  # noqa: E402
from precedent.config import settings  # noqa: E402
from precedent.llm import LLM  # noqa: E402
from precedent.memory import LocalMemory, build_memory  # noqa: E402
from precedent.session import Session  # noqa: E402

MARK = {"straight_through": "·", "correct_auto": "✔ auto", "wrong_auto": "✘ WRONG", "correct_escalation": "→ human",
        "missed_automation": "→ human (could be auto)"}


async def run(use_memory: bool, offline: bool, bank_suffix: str) -> Session:
    if offline:
        memory, llm = LocalMemory(), LLM(None, "", [])
    else:
        memory = build_memory(settings.hindsight_base_url, settings.hindsight_api_key, settings.bank_id + bank_suffix)
        llm = LLM(settings.llm_api_key, settings.llm_base_url, [settings.llm_model, settings.llm_fallback_model])
    await memory.reset()
    agent = APAgent(settings, memory, llm)
    s = Session.load(agent, use_memory=use_memory)
    print(f"\n=== memory {'ON ' if use_memory else 'OFF'} | backend={memory.backend} | llm={llm.label} ===")
    while not s.done:
        t = time.perf_counter()
        step = await s.autopilot_step()
        d = step.decision
        v = agent.vendors[step.invoice.vendor_id].name[:28]
        codes = ",".join(e.code for e in d.exceptions) or "-"
        print(f"{step.invoice.invoice_id} {step.invoice.received_on:%d %b} {v:<28} {codes:<24} "
              f"{MARK[step.grade]:<26} {(d.action.value if d.action else ''):<22} {time.perf_counter() - t:5.1f}s")
    return s


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--only-on", action="store_true")
    args = ap.parse_args()
    off = None if args.only_on else await run(False, args.offline, "-bench-off")
    on = await run(True, args.offline, "-bench-on")
    rows = [("", "memory OFF", "memory ON")]
    keys = ["exceptions", "human_touches", "auto_resolved", "wrong_auto", "auto_rate", "auto_rate_last10",
            "accuracy", "minutes_saved", "value_protected_inr", "discount_captured_inr"]
    mo, mn = (off.metrics() if off else {}), on.metrics()
    print("\n" + "=" * 60)
    for k in keys:
        print(f"{k:<24}{str(mo.get(k, '-')):>16}{str(mn.get(k)):>16}")
    out = ROOT / "docs" / "benchmark.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"off": mo, "on": mn, "timeline_on": on.timeline()}, indent=2), encoding="utf-8")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
