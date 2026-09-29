"""The Precedent agent: resolve AP invoice exceptions the way *this* company resolved them before.

    invoice ──► 3-way match ──► exceptions ──► recall (Hindsight) ──► decide (LLM) ──► guardrails
                                                   ▲                                       │
                                                   └──────── retain ◄── clerk resolution ◄─┘

The agent may only act alone when a precedent from the same vendor covers the case and every
condition in that precedent holds. Everything else goes to a human — and whatever the human
decides is retained, so the next occurrence doesn't have to.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Any

from .config import Settings
from .llm import LLM
from .matching import three_way_match
from .memory import MemoryStore, precedent_tags
from .models import (
    Action, ClerkResolution, Decision, ExceptionFinding, GoodsReceipt, Invoice, Precedent, PurchaseOrder,
    Route, Vendor,
)

log = logging.getLogger("precedent.agent")

PAYABLE_BASES = ["full", "at_po_price", "received_qty_only", "without_charges", "cap_charges",
                 "early_payment_discount", "zero"]
NEVER_ALONE = {"bank_change", "missing_po"}  # hard controls: memory can inform, never auto-release

SYSTEM_PROMPT = """You are Precedent, the accounts-payable exception analyst at Godavari Consumer Products, Hyderabad.
A deterministic 3-way match (invoice vs PO vs goods receipt vs vendor master) has flagged exceptions on an invoice.
Your job: decide how to resolve them, the way THIS company's AP team resolved them before.

Rules:
1. You may set can_auto_resolve=true ONLY if a precedent from THIS vendor (ids P1, P2 ...) or a standing directive clearly
   covers the current case AND every condition it states (caps, tolerances, effective dates, units, clauses) is satisfied
   by the current invoice. Check numbers and dates explicitly and write each check in conditions_checked.
2. If a precedent's condition is NOT met (amount above a cap, variance above a tolerance, invoice dated before an
   effective date, different circumstances) then it does not cover the case: can_auto_resolve=false, and recommend what
   the precedent implies a careful clerk would do.
3. Hints from OTHER vendors (ids H1, H2 ...) describe a pattern only. Contracts differ per vendor; never auto-resolve on
   a hint alone.
4. With no precedents, give your best generic AP recommendation with can_auto_resolve=false and low confidence.
5. Choose payable_basis from the options given; the system computes the amount. Use cap_charges with charge_cap for
   "pay freight/charges up to X". Use zero for reject/hold.
6. Directives are company policy and override precedents.

Reply with ONLY a JSON object:
{"action": "approve|approve_adjusted|reject|hold|schedule_early_payment",
 "payable_basis": "full|at_po_price|received_qty_only|without_charges|cap_charges|early_payment_discount|zero",
 "charge_cap": number or null,
 "can_auto_resolve": true|false,
 "confidence": 0.0-1.0,
 "reasoning": "<= 70 words, cite precedent ids and dates",
 "conditions_checked": ["short statement with the numbers compared"],
 "precedents_used": ["P1"],
 "directives_applied": ["directive name"]}"""


def _inr(x: float | None) -> str:
    return "—" if x is None else f"₹{x:,.0f}"


def _load(path: Path, model):
    return [model(**row) for row in json.loads(path.read_text(encoding="utf-8"))]


class APAgent:
    def __init__(self, settings: Settings, memory: MemoryStore, llm: LLM):
        self.settings = settings
        self.memory = memory
        self.llm = llm
        d = settings.data_dir
        self.vendors = {v.vendor_id: v for v in _load(d / "vendors.json", Vendor)}
        self.pos = {p.po_number: p for p in _load(d / "purchase_orders.json", PurchaseOrder)}
        self.grns = {g.po_number: g for g in _load(d / "goods_receipts.json", GoodsReceipt)}
        self.history: list[Invoice] = []  # invoices already posted (for duplicate detection)

    # ------------------------------------------------------------------ payable maths
    def payable_options(self, inv: Invoice, charge_cap: float | None = None) -> dict[str, float]:
        po = self.pos.get(inv.po_number or "")
        grn = self.grns.get(inv.po_number or "")
        opts = {"full": inv.total_inr, "zero": 0.0}
        if po:
            po_price = {l.sku: l for l in po.lines}
            lines = [l.model_copy(update={"unit_price": po_price[l.sku].unit_price})
                     if l.sku in po_price and po_price[l.sku].uom == l.uom else l for l in inv.lines]
            opts["at_po_price"] = inv.model_copy(update={"lines": lines}).total_inr
        if grn:
            rec = {l.sku: l.qty_received for l in grn.lines}
            lines = [l.model_copy(update={"qty": min(l.qty, rec.get(l.sku, l.qty))}) for l in inv.lines]
            opts["received_qty_only"] = inv.model_copy(update={"lines": lines}).total_inr
        if inv.charges:
            opts["without_charges"] = inv.model_copy(update={"charges": []}).total_inr
            if charge_cap is not None:
                capped = [c.model_copy(update={"amount": min(c.amount, charge_cap)}) for c in inv.charges]
                opts["cap_charges"] = inv.model_copy(update={"charges": capped}).total_inr
        from .matching import _EARLY_DISCOUNT
        m = _EARLY_DISCOUNT.search(inv.payment_terms)
        if m:
            opts["early_payment_discount"] = round(inv.total_inr * (1 - float(m.group(1)) / 100), 2)
        return {k: round(v, 2) for k, v in opts.items()}

    # ------------------------------------------------------------------ decide
    def detect(self, inv: Invoice) -> list[ExceptionFinding]:
        po = self.pos.get(inv.po_number or "")
        return three_way_match(inv, po, self.grns.get(inv.po_number or ""), self.vendors[inv.vendor_id], self.history)

    async def decide(self, inv: Invoice, *, use_memory: bool = True) -> Decision:
        t0 = time.perf_counter()
        vendor = self.vendors[inv.vendor_id]
        exceptions = self.detect(inv)
        if not exceptions:
            return Decision(invoice_id=inv.invoice_id, route=Route.STRAIGHT_THROUGH, action=Action.APPROVE,
                            payable_amount=inv.total_inr, payable_basis="full", confidence=1.0, decided_by="rules",
                            reasoning="Clean 3-way match: price, quantity, receipt, tax and bank details all agree.",
                            memory_enabled=use_memory, latency_ms=int((time.perf_counter() - t0) * 1000))

        codes = [e.code for e in exceptions]
        vendor_prec: list[Precedent] = []
        hints: list[Precedent] = []
        directives: list[dict[str, str]] = []
        if use_memory:
            q = (f"{vendor.name} invoice {inv.invoice_number}: " + "; ".join(e.summary for e in exceptions) +
                 f". How did we resolve {', '.join(codes)} for {vendor.name} before, and what limits, "
                 f"tolerances, effective dates or conditions apply?")
            pq = f"How did AP resolve {', '.join(c.replace('_', ' ') for c in codes)} exceptions for other vendors?"
            results = await asyncio.gather(
                self.memory.recall(q, tags=[f"vendor:{vendor.vendor_id}"], limit=6, scope="vendor"),
                self.memory.recall(pq, tags=[f"exc:{c}" for c in codes], limit=6, scope="pattern"),
                self.memory.directives(),
                return_exceptions=True,
            )
            vendor_prec = results[0] if not isinstance(results[0], BaseException) else []
            hints = [h for h in (results[1] if not isinstance(results[1], BaseException) else [])
                     if f"vendor:{vendor.vendor_id}" not in h.tags][:3]
            directives = results[2] if not isinstance(results[2], BaseException) else []
            for r in results:
                if isinstance(r, BaseException):
                    log.warning("memory call failed: %s", r)

        verdict = await self._llm_decide(inv, vendor, exceptions, vendor_prec, hints, directives)
        decided_by = "llm"
        if verdict is None:
            verdict = self._heuristic_decide(inv, exceptions, vendor_prec)
            decided_by = "heuristic"

        decision = self._apply_guardrails(inv, exceptions, vendor_prec, hints, directives, verdict, use_memory)
        decision.decided_by = decided_by
        decision.latency_ms = int((time.perf_counter() - t0) * 1000)
        return decision

    def _brief(self, inv: Invoice, vendor: Vendor, exceptions, vendor_prec, hints, directives) -> str:
        po = self.pos.get(inv.po_number or "")
        lines = "\n".join(f"  - {l.description}: {l.qty:g} {l.uom} × {l.unit_price:,.2f} {inv.currency} "
                          f"(GST {l.tax_rate:.0%})" for l in inv.lines)
        charges = "\n".join(f"  - {c.description}: ₹{c.amount:,.0f}" for c in inv.charges) or "  (none)"
        opts = self.payable_options(inv, charge_cap=None)
        opt_txt = "\n".join(f"  - {k}: {_inr(v)}" for k, v in opts.items())
        if inv.charges:
            opt_txt += "\n  - cap_charges: goods + each charge capped at charge_cap (you supply charge_cap)"

        def ago(p: Precedent) -> str:
            if not p.occurred:
                return "date unknown"
            try:
                d = datetime.fromisoformat(p.occurred.replace("Z", "+00:00")).date()
                return f"{d:%d %b %Y}, {(inv.received_on - d).days} days before this invoice"
            except ValueError:
                return p.occurred

        prec_txt = "\n".join(f"  [P{i}] ({ago(p)}) {p.text}" for i, p in enumerate(vendor_prec, 1)) or "  (none)"
        hint_txt = "\n".join(f"  [H{i}] ({ago(p)}) {p.text}" for i, p in enumerate(hints, 1)) or "  (none)"
        dir_txt = "\n".join(f"  [D{i}] {d['name']}: {d['content']}" for i, d in enumerate(directives, 1)) or "  (none)"
        return f"""INVOICE {inv.invoice_number} from {vendor.name} ({vendor.vendor_id}, {vendor.category}, {vendor.city})
Invoice date {inv.date:%d %b %Y}; received {inv.received_on:%d %b %Y}; PO {inv.po_number} dated {po.date:%d %b %Y}
Currency {inv.currency}{f' @ {inv.fx_rate} INR' if inv.currency != 'INR' else ''}; tax {inv.tax_type}; terms {inv.payment_terms}
Lines:
{lines}
Charges:
{charges}
Invoice total: {_inr(inv.total_inr)}

EXCEPTIONS FROM 3-WAY MATCH:
""" + "\n".join(f"  - {e.code} [{e.severity}]: {e.summary}" for e in exceptions) + f"""

PAYABLE OPTIONS (computed by the system):
{opt_txt}

PRECEDENTS FROM THIS VENDOR'S HISTORY (Hindsight memory):
{prec_txt}

HINTS FROM OTHER VENDORS (pattern only):
{hint_txt}

STANDING DIRECTIVES:
{dir_txt}"""

    async def _llm_decide(self, inv, vendor, exceptions, vendor_prec, hints, directives) -> dict[str, Any] | None:
        brief = self._brief(inv, vendor, exceptions, vendor_prec, hints, directives)
        obj, model = await self.llm.json(SYSTEM_PROMPT, brief)
        if obj is None:
            return None
        try:
            action = Action(str(obj.get("action", "hold")).strip().lower())
        except ValueError:
            action = Action.HOLD
        basis = str(obj.get("payable_basis") or "").strip().lower()
        if basis not in PAYABLE_BASES:
            basis = "zero" if action in (Action.REJECT, Action.HOLD) else "full"
        cap = obj.get("charge_cap")
        try:
            cap = float(cap) if cap not in (None, "", "null") else None
        except (TypeError, ValueError):
            cap = None
        try:
            conf = max(0.0, min(1.0, float(obj.get("confidence", 0))))
        except (TypeError, ValueError):
            conf = 0.0
        pmap = {f"P{i}": p.id for i, p in enumerate(vendor_prec, 1)}
        pmap.update({f"H{i}": p.id for i, p in enumerate(hints, 1)})
        used = [pmap[x.strip()] for x in obj.get("precedents_used") or [] if isinstance(x, str) and x.strip() in pmap]
        return {
            "action": action, "basis": basis, "charge_cap": cap, "confidence": conf,
            "can_auto": bool(obj.get("can_auto_resolve")), "reasoning": str(obj.get("reasoning", ""))[:900],
            "conditions": [str(c)[:240] for c in (obj.get("conditions_checked") or [])][:6],
            "used": used, "directives": [str(d) for d in (obj.get("directives_applied") or [])][:4],
            "model": model,
        }

    def _heuristic_decide(self, inv: Invoice, exceptions, vendor_prec: list[Precedent]) -> dict[str, Any]:
        """Deterministic fallback when no LLM is reachable: follow the most recent same-vendor precedent
        with the same exception set, provided the current magnitude is within what was approved before."""
        codes = sorted(e.code for e in exceptions)
        for p in sorted(vendor_prec, key=lambda p: p.occurred or "", reverse=True):
            md = p.metadata
            if sorted((md.get("codes") or "").split(",")) != codes or not md.get("action"):
                continue
            within = all(_magnitude(e) <= float(md.get(f"m_{e.code}", "inf")) + 1e-6 for e in exceptions)
            cap = float(md["charge_cap"]) if md.get("charge_cap") not in (None, "", "None") else None
            return {"action": Action(md["action"]), "basis": md.get("basis", "full"), "charge_cap": cap,
                    "confidence": 0.8 if within else 0.4, "can_auto": within,
                    "reasoning": (f"Heuristic: same exceptions as {md.get('invoice_number')} "
                                  f"({md.get('action')}); magnitude {'within' if within else 'OUTSIDE'} "
                                  f"what was accepted then."),
                    "conditions": [f"{e.code}: {_magnitude(e):g} vs precedent {md.get(f'm_{e.code}')}" for e in exceptions],
                    "used": [p.id], "directives": [], "model": None}
        return {"action": Action.HOLD, "basis": "zero", "charge_cap": None, "confidence": 0.2, "can_auto": False,
                "reasoning": "No matching precedent for this vendor — needs a human.", "conditions": [],
                "used": [], "directives": [], "model": None}

    def _apply_guardrails(self, inv, exceptions, vendor_prec, hints, directives, v, use_memory) -> Decision:
        codes = {e.code for e in exceptions}
        opts = self.payable_options(inv, v["charge_cap"])
        basis = v["basis"] if v["basis"] in opts else ("zero" if v["action"] in (Action.REJECT, Action.HOLD) else "full")
        payable = 0.0 if v["action"] in (Action.REJECT, Action.HOLD) else opts.get(basis, inv.total_inr)

        guardrail = None
        used_vendor = [pid for pid in v["used"] if pid in {p.id for p in vendor_prec}]
        if not use_memory:
            guardrail = "Memory off: no institutional knowledge, every exception goes to a human."
        elif codes & NEVER_ALONE:
            guardrail = f"Hard control: {', '.join(sorted(codes & NEVER_ALONE))} is never released without a human."
        elif not vendor_prec:
            guardrail = "No precedent for this vendor yet — a human decides, and the agent learns from it."
        elif not v["can_auto"]:
            guardrail = "Precedent found but it doesn't fully cover this case."
        elif not used_vendor:
            guardrail = "Decision didn't cite a same-vendor precedent."
        elif v["confidence"] < self.settings.auto_confidence:
            guardrail = f"Confidence {v['confidence']:.2f} below auto-resolve threshold {self.settings.auto_confidence:.2f}."
        elif v["action"] == Action.HOLD:
            guardrail = "A hold always needs a human investigation."

        return Decision(
            invoice_id=inv.invoice_id, route=Route.HUMAN if guardrail else Route.AUTO, action=v["action"],
            payable_amount=round(payable, 2), payable_basis=basis, charge_cap=v["charge_cap"],
            confidence=v["confidence"], reasoning=v["reasoning"],
            conditions_checked=v["conditions"], exceptions=exceptions, precedents=vendor_prec + hints,
            precedents_used=v["used"], directives_applied=v["directives"], guardrail=guardrail,
            memory_enabled=use_memory,
        )

    # ------------------------------------------------------------------ learn
    def post(self, inv: Invoice) -> None:
        """Record the invoice as processed so later resubmissions are caught as duplicates."""
        if all(h.invoice_id != inv.invoice_id for h in self.history):
            self.history.append(inv)

    async def learn(self, inv: Invoice, decision: Decision, res: ClerkResolution, *, basis: str,
                    charge_cap: float | None = None) -> str:
        """Retain the final outcome of an exception into Hindsight. Returns the retained text."""
        vendor = self.vendors[inv.vendor_id]
        codes = [e.code for e in decision.exceptions]
        overridden = decision.route == Route.AUTO and decision.action != res.action
        if decision.route == Route.AUTO and not overridden:
            who = "Precedent agent auto-resolved it; the AP lead confirmed the decision"
        elif overridden:
            who = (f"Precedent agent proposed {decision.action.value} but {res.clerk} OVERRODE it to "
                   f"{res.action.value}")
        else:
            who = f"Resolved by {res.clerk}"
        payable = res.payable_amount if res.payable_amount is not None else 0.0
        reason = res.note or decision.reasoning
        text = (
            f"AP exception resolution, {inv.received_on:%d %b %Y}. Vendor {vendor.name} ({vendor.vendor_id}). "
            f"Invoice {inv.invoice_number} dated {inv.date:%d %b %Y} against {inv.po_number}, total {_inr(inv.total_inr)}.\n"
            "Exceptions: " + " | ".join(f"{e.code}: {e.summary}" for e in decision.exceptions) + "\n"
            f"Outcome: {res.action.value.upper()} — payable {_inr(payable)} (basis: {basis}"
            f"{f', charges capped at ₹{charge_cap:,.0f}' if charge_cap else ''}). {who}.\n"
            f"Reason: {reason}"
        )
        metadata = {
            "vendor_id": vendor.vendor_id, "invoice_id": inv.invoice_id, "invoice_number": inv.invoice_number,
            "action": res.action.value, "basis": basis, "charge_cap": str(charge_cap) if charge_cap else "",
            "codes": ",".join(sorted(codes)), "decided_by": "agent" if decision.route == Route.AUTO else "clerk",
            "overridden": str(overridden).lower(),
            "summary": f"{inv.invoice_number}: {', '.join(codes)} → {res.action.value} ({basis})",
            **{f"m_{e.code}": str(_magnitude(e)) for e in decision.exceptions},
        }
        tags = precedent_tags(vendor.vendor_id, codes) + [f"outcome:{res.action.value}",
                                                          "source:override" if overridden else f"source:{metadata['decided_by']}"]
        ts = datetime.combine(inv.received_on, dtime(11, 0))
        await self.memory.retain(text, timestamp=ts, tags=tags, metadata=metadata,
                                 document_id=f"resolution-{inv.invoice_id}", context="AP invoice exception resolution")
        if res.make_policy and res.note:
            await self.memory.add_directive(
                name=f"{vendor.name} — {', '.join(c.replace('_', ' ') for c in codes)}",
                content=res.note, tags=[f"vendor:{vendor.vendor_id}", *[f"exc:{c}" for c in codes]])
        try:
            await self.memory.ensure_playbook(vendor.vendor_id, vendor.name)
        except Exception as exc:
            log.warning("playbook refresh failed: %s", exc)
        return text


def _magnitude(e: ExceptionFinding) -> float:
    m = e.magnitude
    for key in ("amount", "variance_pct", "unreceived_value", "discount_pct", "amount_at_risk", "value_diff"):
        if key in m:
            try:
                return abs(float(m[key]))
            except (TypeError, ValueError):
                pass
    return 0.0
