"""Ops Watch: a basic health monitor for the Precedent agent.

Every few seconds (and after every invoice) it runs 4 health checks:

    1. memory_down   Hindsight memory calls are failing
    2. llm_down      the LLM is not answering
    3. slow          decisions are taking longer than the target time
    4. fraud         one vendor keeps asking to change bank details

If a check fails, it opens an incident with: what is wrong, what happens if nobody acts, and how to fix it.
Incidents show on the /ops page and, if INCIDENT_WEBHOOK_URL is set, are sent to an incident portal
(Slack / ServiceNow / PagerDuty). When the check passes again the incident closes itself
(fraud incidents stay open until a person resolves them).
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any

log = logging.getLogger("precedent.monitor")

# What each problem means and how to fix it (the "runbook").
PLAYBOOK: dict[str, dict[str, Any]] = {
    "memory_down": dict(
        severity="SEV2", title="Hindsight memory is failing",
        impact="The agent cannot recall past decisions, so every exception goes to a human and the AP queue grows.",
        fix=["Check HINDSIGHT_BASE_URL and HINDSIGHT_API_KEY (401/403 = bad key, timeout = network).",
             "Self-hosted: run `docker compose ps` and restart the Hindsight container if it is down.",
             "Do not reset the memory bank; the data is fine, only the connection is broken."]),
    "llm_down": dict(
        severity="SEV2", title="LLM is not answering",
        impact="Decisions fall back to simple rules that can miss conditions like dates, so wrong auto-decisions become possible.",
        fix=["Check the server log: 429 = rate limit, 401 = bad GROQ_API_KEY, timeout = provider slow.",
             "Switch LLM_MODEL to a model on a different quota.",
             "Until fixed, set AUTO_RESOLVE_CONFIDENCE=0.9 so more decisions go to a human."]),
    "slow": dict(
        severity="SEV3", title="Decisions are getting slow",
        impact="Slow calls usually come before timeouts. Then decisions fail and pile up for humans.",
        fix=["Check Groq and Hindsight response times in the server log.",
             "Use a faster model or lower max_tokens."]),
    "fraud": dict(
        severity="SEV1", title="Repeated bank-detail change requests from one vendor",
        impact="Classic invoice-fraud pattern. The agent blocks it, but a busy clerk could still approve it by hand.",
        fix=["Freeze bank-detail changes for this vendor.",
             "Verify by calling the number on the original contract, not the one in the email.",
             "Inform treasury / security."]),
}


@dataclass
class Incident:
    id: str
    rule: str
    severity: str  # SEV1 = act now, SEV2 = act today, SEV3 = early warning
    title: str
    impact: str
    fix: list[str]
    evidence: str = ""
    status: str = "open"  # open | resolved
    opened_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    resolved_at: str | None = None


class WatchedMemory:
    """Wraps the memory store and records whether each call worked."""

    def __init__(self, inner, monitor: "Monitor"):
        self.inner, self.monitor = inner, monitor

    def __getattr__(self, name):
        attr = getattr(self.inner, name)
        if name not in {"recall", "retain", "directives", "add_directive", "reflect", "stats"}:
            return attr

        async def call(*args, **kwargs):
            try:
                if "memory_down" in self.monitor.simulated:
                    raise ConnectionError("simulated: Hindsight unreachable")
                result = await attr(*args, **kwargs)
                if name == "stats" and result.get("memories") is None:  # Hindsight's stats() hides errors
                    raise ConnectionError("no answer from Hindsight")
            except Exception as exc:
                self.monitor.memory_ok.append(False)
                self.monitor.last_memory_error = str(exc)[:200]
                raise
            self.monitor.memory_ok.append(True)
            return result
        return call


class WatchedLLM:
    """Wraps the LLM client and records whether each call got an answer."""

    def __init__(self, inner, monitor: "Monitor"):
        self.inner, self.monitor = inner, monitor

    def __getattr__(self, name):
        return getattr(self.inner, name)

    async def json(self, system: str, user: str, **kwargs):
        if "llm_down" in self.monitor.simulated:
            obj, model = None, None
        else:
            obj, model = await self.inner.json(system, user, **kwargs)
            if not self.inner.enabled:
                return obj, model  # no API key = rule-based mode on purpose, not an outage
        self.monitor.llm_ok.append(model is not None)
        return obj, model


class Monitor:
    def __init__(self, *, interval_s: float = 10, latency_slo_ms: int = 12000, webhook_url: str | None = None):
        self.interval_s, self.latency_slo_ms, self.webhook_url = interval_s, latency_slo_ms, webhook_url
        self.memory = None
        self.memory_ok: deque[bool] = deque(maxlen=10)  # last 10 calls: True = worked
        self.llm_ok: deque[bool] = deque(maxlen=10)
        self.last_memory_error = ""
        self.latencies: deque[int] = deque(maxlen=10)  # last 10 decision times (ms)
        self.bank_changes: dict[str, list[str]] = {}  # vendor -> invoices asking for a bank change
        self.incidents: list[Incident] = []
        self.simulated: set[str] = set()  # demo switches: "memory_down", "llm_down"
        self.last_check: str | None = None

    def attach(self, memory, llm):
        self.memory = WatchedMemory(memory, self)
        return self.memory, WatchedLLM(llm, self)

    async def observe_step(self, step) -> None:
        """Called by the session after every invoice."""
        d = step.decision
        if d.route.value != "straight_through":
            self.latencies.append(d.latency_ms)
        if any(e.code == "bank_change" for e in d.exceptions):
            self.bank_changes.setdefault(step.invoice.vendor_id, []).append(step.invoice.invoice_number)
        await self.check()

    def new_run(self) -> None:
        self.latencies.clear()
        self.bank_changes.clear()

    # ------------------------------------------------------------------ health checks
    def _problems(self) -> dict[str, str]:
        """Returns {rule: evidence} for every check that is failing right now."""
        found = {}
        if self.memory_ok.count(False) >= 3:
            found["memory_down"] = f"{self.memory_ok.count(False)} of last {len(self.memory_ok)} calls failed. " \
                                   f"Last error: {self.last_memory_error}"
        if self.llm_ok.count(False) >= 3:
            found["llm_down"] = f"{self.llm_ok.count(False)} of last {len(self.llm_ok)} calls got no answer."
        if len(self.latencies) >= 3:
            avg = sum(self.latencies) / len(self.latencies)
            if avg > self.latency_slo_ms:
                found["slow"] = f"Average {avg / 1000:.1f}s per decision (target {self.latency_slo_ms / 1000:.0f}s)."
        for vendor, invoices in self.bank_changes.items():
            if len(invoices) >= 2:
                found[f"fraud:{vendor}"] = f"Vendor {vendor}, invoices: {', '.join(invoices)}"
        return found

    async def check(self) -> None:
        """Open an incident for each new problem; close the ones that recovered."""
        self.last_check = datetime.now().isoformat(timespec="seconds")
        found = self._problems()
        open_now = {i.rule: i for i in self.incidents if i.status == "open"}
        seen = {i.rule for i in self.incidents}

        for rule, evidence in found.items():
            if rule in open_now:
                open_now[rule].evidence = evidence
            elif not (rule.startswith("fraud:") and rule in seen):  # raise each fraud case once
                inc = Incident(id=f"INC-{len(self.incidents) + 1:03d}", rule=rule, evidence=evidence,
                               **PLAYBOOK[rule.split(":")[0]])
                self.incidents.append(inc)
                log.warning("%s %s %s", inc.id, inc.severity, inc.title)
                await self._send_to_portal(inc)

        for rule, inc in open_now.items():
            if rule not in found and not rule.startswith("fraud:"):
                self.resolve(inc.id)

    def resolve(self, inc_id: str) -> Incident:
        inc = next((i for i in self.incidents if i.id == inc_id), None)
        if inc is None:
            raise KeyError(inc_id)
        inc.status, inc.resolved_at = "resolved", datetime.now().isoformat(timespec="seconds")
        return inc

    async def _send_to_portal(self, inc: Incident) -> None:
        """Send the incident to an external incident portal (any JSON webhook), if one is configured."""
        if not self.webhook_url:
            return
        try:
            import httpx

            async with httpx.AsyncClient(timeout=5) as client:
                await client.post(self.webhook_url, json={"text": f"[{inc.severity}] {inc.title}", "incident": asdict(inc)})
        except Exception as exc:
            log.warning("could not reach incident portal: %s", exc)

    # ------------------------------------------------------------------ background loop
    async def run_forever(self) -> None:
        """Ping memory every few seconds, even when no invoices are flowing, then run the checks."""
        while True:
            try:
                if self.memory is not None:
                    await self.memory.stats()
            except Exception:
                pass  # already recorded as a failed memory call
            try:
                await self.check()
            except Exception as exc:
                log.warning("monitor check failed: %s", exc)
            await asyncio.sleep(self.interval_s)

    def snapshot(self) -> dict[str, Any]:
        def health(calls: deque[bool]) -> str:
            return "no data" if not calls else "failing" if calls.count(False) >= 3 else "ok"
        avg = sum(self.latencies) / len(self.latencies) / 1000 if self.latencies else None
        return {
            "last_check": self.last_check, "interval_s": self.interval_s, "simulated": sorted(self.simulated),
            "memory": health(self.memory_ok), "llm": health(self.llm_ok),
            "avg_decision_s": round(avg, 1) if avg is not None else None, "target_s": self.latency_slo_ms / 1000,
            "incidents": [asdict(i) for i in sorted(self.incidents, key=lambda i: (i.status != "open", i.severity, i.id))],
            "open": sum(i.status == "open" for i in self.incidents),
        }
