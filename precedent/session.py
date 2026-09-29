"""An AP inbox session: the invoice stream, pending decisions, clerk resolutions and KPIs.

The "clerk simulator" (autopilot) replays what Godavari's AP lead actually decided
(data/clerk_ground_truth.json), so the learning curve can be reproduced end-to-end.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

from .agent import APAgent
from .models import Action, ClerkResolution, Decision, Invoice, Route


@dataclass
class Step:
    invoice: Invoice
    decision: Decision
    grade: str | None = None  # straight_through | correct_auto | wrong_auto | correct_escalation | missed_automation
    final_action: str | None = None
    final_payable: float | None = None
    retained: str | None = None


def grade(decision: Decision, truth: dict[str, Any]) -> str:
    if decision.route == Route.STRAIGHT_THROUGH:
        return "straight_through"
    if decision.route == Route.AUTO:
        ok = decision.action and decision.action.value == truth["clerk_action"] and (
            truth["payable_amount"] == 0 or abs((decision.payable_amount or 0) - truth["payable_amount"]) < 2)
        return "correct_auto" if ok else "wrong_auto"
    return "correct_escalation" if truth["expected_route"] == "human" else "missed_automation"


@dataclass
class Session:
    agent: APAgent
    invoices: list[Invoice]
    truth: dict[str, dict[str, Any]]
    use_memory: bool = True
    steps: list[Step] = field(default_factory=list)
    pending: Step | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    feed: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def load(cls, agent: APAgent, use_memory: bool = True) -> "Session":
        d = agent.settings.data_dir
        invoices = [Invoice(**r) for r in json.loads((d / "invoices.json").read_text(encoding="utf-8"))]
        truth = {t["invoice_id"]: t for t in json.loads((d / "clerk_ground_truth.json").read_text(encoding="utf-8"))}
        return cls(agent=agent, invoices=invoices, truth=truth, use_memory=use_memory)

    @property
    def cursor(self) -> int:
        return len(self.steps)

    @property
    def done(self) -> bool:
        return self.cursor >= len(self.invoices) and self.pending is None

    async def next(self) -> Step | None:
        if self.pending:
            return self.pending
        if self.cursor >= len(self.invoices):
            return None
        inv = self.invoices[self.cursor]
        decision = await self.agent.decide(inv, use_memory=self.use_memory)
        step = Step(invoice=inv, decision=decision)
        self.pending = step
        if decision.route == Route.STRAIGHT_THROUGH:
            await self._finish(step, None, retain=False)  # clears pending
        return step

    async def resolve(self, res: ClerkResolution | None, *, basis: str | None = None,
                      charge_cap: float | None = None) -> Step:
        """res=None means the clerk accepts the agent's auto-resolution as-is."""
        step = self.pending
        if step is None:
            raise ValueError("nothing pending")
        if step.decision.route == Route.STRAIGHT_THROUGH:
            return step
        d = step.decision
        if res is None:
            if d.route != Route.AUTO or d.action is None:
                raise ValueError("this invoice needs a clerk decision")
            basis = basis or d.payable_basis or "full"
            charge_cap = d.charge_cap
            res = ClerkResolution(invoice_id=d.invoice_id, action=d.action, payable_amount=d.payable_amount,
                                  note="")
        else:
            basis = basis or ("zero" if res.action in (Action.REJECT, Action.HOLD) else "full")
            if res.payable_amount is None:
                opts = self.agent.payable_options(step.invoice, charge_cap)
                res.payable_amount = 0.0 if res.action in (Action.REJECT, Action.HOLD) else opts.get(basis, step.invoice.total_inr)
        await self._finish(step, res, retain=True, basis=basis, charge_cap=charge_cap)
        return step

    async def autopilot_step(self) -> Step | None:
        """Process the next invoice and let the simulated AP lead respond with the recorded decision."""
        async with self.lock:
            step = await self.next()
            if step is None or step.grade is not None:
                return step
            t = self.truth[step.invoice.invoice_id]
            g = grade(step.decision, t)
            if g == "correct_auto":
                await self.resolve(None)
            else:
                note = t["note"] or (f"Correct outcome is {t['clerk_action']} ({t['basis']}) — the agent's "
                                     f"proposal of {step.decision.action.value if step.decision.action else 'n/a'} was wrong.")
                await self.resolve(ClerkResolution(invoice_id=t["invoice_id"], action=Action(t["clerk_action"]),
                                                   note=note, make_policy=t["make_policy"] and self.use_memory),
                                   basis=t["basis"], charge_cap=t["charge_cap"])
            return step

    async def _finish(self, step: Step, res: ClerkResolution | None, *, retain: bool,
                      basis: str | None = None, charge_cap: float | None = None) -> None:
        step.grade = grade(step.decision, self.truth[step.invoice.invoice_id])
        if res is not None and step.decision.route == Route.AUTO and res.action != step.decision.action:
            step.grade = "wrong_auto"
        step.final_action = (res.action.value if res else step.decision.action.value)
        step.final_payable = res.payable_amount if res else step.decision.payable_amount
        if retain and res is not None and self.use_memory:
            step.retained = await self.agent.learn(step.invoice, step.decision, res, basis=basis or "full",
                                                   charge_cap=charge_cap)
            self.feed.insert(0, {"invoice_id": step.invoice.invoice_id, "vendor": self.agent.vendors[step.invoice.vendor_id].name,
                                 "text": step.retained, "policy": bool(res.make_policy)})
        self.agent.post(step.invoice)
        self.steps.append(step)
        self.pending = None

    # ------------------------------------------------------------------ reporting
    def metrics(self) -> dict[str, Any]:
        mins = self.agent.settings.minutes_per_exception
        exc = [s for s in self.steps if s.grade != "straight_through"]
        auto_ok = sum(s.grade == "correct_auto" for s in exc)
        wrong = sum(s.grade == "wrong_auto" for s in exc)
        human = sum(s.decision.route == Route.HUMAN for s in exc) + wrong
        protected = 0.0
        discount = 0.0
        for s in exc:
            if s.final_payable is None:
                continue
            gap = s.invoice.total_inr - s.final_payable
            if s.final_action == "schedule_early_payment":
                discount += gap
            elif gap > 0:
                protected += gap
        last10 = exc[-10:]
        return {
            "processed": len(self.steps), "total": len(self.invoices),
            "straight_through": sum(s.grade == "straight_through" for s in self.steps),
            "exceptions": len(exc), "auto_resolved": auto_ok, "wrong_auto": wrong, "human_touches": human,
            "missed_automation": sum(s.grade == "missed_automation" for s in exc),
            "auto_rate": round(auto_ok / len(exc), 3) if exc else 0.0,
            "auto_rate_last10": round(sum(s.grade == "correct_auto" for s in last10) / len(last10), 3) if last10 else 0.0,
            "accuracy": round((auto_ok + sum(s.grade == "correct_escalation" for s in exc)) / len(exc), 3) if exc else 0.0,
            "minutes_saved": round(auto_ok * mins),
            "value_protected_inr": round(protected, 2), "discount_captured_inr": round(discount, 2),
        }

    def timeline(self) -> list[dict[str, Any]]:
        out, human, baseline = [], 0, 0
        for i, s in enumerate(self.steps, 1):
            is_exc = s.grade != "straight_through"
            baseline += is_exc
            human += is_exc and (s.decision.route == Route.HUMAN or s.grade == "wrong_auto")
            out.append({"n": i, "invoice_id": s.invoice.invoice_id, "date": s.invoice.received_on.isoformat(),
                        "vendor": self.agent.vendors[s.invoice.vendor_id].name, "grade": s.grade,
                        "route": s.decision.route.value, "human_cum": int(human), "baseline_cum": int(baseline)})
        return out
