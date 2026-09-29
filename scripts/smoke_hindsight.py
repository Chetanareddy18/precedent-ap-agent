"""Exercise every Hindsight call Precedent makes against a live server.

    python scripts/smoke_hindsight.py            # uses HINDSIGHT_BASE_URL / HINDSIGHT_API_KEY from .env
"""
from __future__ import annotations

import asyncio
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from precedent.config import settings  # noqa: E402
from precedent.memory import HindsightMemory  # noqa: E402


async def main():
    base = settings.hindsight_base_url or "http://localhost:8888"
    mem = HindsightMemory(base, settings.hindsight_api_key, "precedent-smoke")
    t = time.perf_counter()
    await mem.reset()
    print(f"bank ready ({time.perf_counter() - t:.1f}s)")

    t = time.perf_counter()
    await mem.retain(
        "AP exception resolution, 05 Jul 2026. Vendor Deccan Steel & Wire Pvt. Ltd. (V001). Invoice DSW/26-27/0412. "
        "Exceptions: unplanned_charge: freight ₹2,400 not on PO-45012. Outcome: APPROVE. Reason: Deccan's rate contract "
        "(clause 7.2) lets them bill freight separately, capped at ₹3,000 per delivery.",
        timestamp=datetime(2026, 7, 5, 11), tags=["vendor:V001", "exc:unplanned_charge", "outcome:approve"],
        metadata={"vendor_id": "V001", "action": "approve"}, document_id="resolution-INV-001",
        context="AP invoice exception resolution")
    await mem.retain(
        "AP exception resolution, 20 Jul 2026. Vendor Vertex Office Supplies (V005). Bank change on invoice VOS/2207. "
        "Outcome: HOLD. Reason: attempted business-email-compromise fraud; call-back to vendor-master number confirmed "
        "no bank change.", timestamp=datetime(2026, 7, 20, 11), tags=["vendor:V005", "exc:bank_change", "outcome:hold"],
        metadata={"vendor_id": "V005", "action": "hold"}, document_id="resolution-INV-006",
        context="AP invoice exception resolution")
    print(f"retain x2 ({time.perf_counter() - t:.1f}s)")

    t = time.perf_counter()
    hits = await mem.recall("Deccan freight not on PO — how was it resolved and what cap applies?", tags=["vendor:V001"])
    print(f"recall vendor:V001 -> {len(hits)} ({time.perf_counter() - t:.1f}s)")
    for h in hits:
        print("   ", h.type, h.occurred, h.tags, "|", h.text[:140])
    assert hits and all("vendor:V001" in h.tags for h in hits), "tag scoping failed"
    leak = await mem.recall("bank change fraud", tags=["vendor:V001"])
    assert all("vendor:V005" not in h.tags for h in leak), "vendor tag leaked"
    print("tag isolation OK")

    await mem.add_directive("Vertex — bank change", "Never pay to changed bank details without call-back.", ["vendor:V005"])
    ds = await mem.directives()
    print("directives ->", [d["name"] for d in ds])
    assert ds

    await mem.ensure_playbook("V001", "Deccan Steel & Wire Pvt. Ltd.")
    print("mental model created; content (may still be building):", (await mem.playbook("V001") or "")[:160])

    t = time.perf_counter()
    ans = await mem.reflect("What cap applies to Deccan's freight charges?")
    print(f"reflect ({time.perf_counter() - t:.1f}s):", ans.text[:300].replace("\n", " "))
    print("stats:", await mem.stats())
    print("ALL HINDSIGHT CALLS OK")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
