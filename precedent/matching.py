"""Deterministic 3-way match: invoice vs purchase order vs goods receipt vs vendor master.

This layer never guesses. It only *finds* discrepancies and measures them. Deciding what a
discrepancy means for this vendor is the agent's job, and that is where memory comes in.
"""
from __future__ import annotations

import re
from datetime import timedelta

from .models import ExceptionFinding, GoodsReceipt, Invoice, PurchaseOrder, Vendor

PRICE_TOLERANCE = 0.01  # 1% unit-price tolerance before we call it a variance
UOM_TOTAL_TOLERANCE = 0.005
COMPANY_STATE_CODE = "36"  # Telangana

_RESUBMIT_SUFFIX = re.compile(r"[\s\-/_]*(R|REV|RESUB(MIT)?|DUP(LICATE)?|COPY)\d*$", re.IGNORECASE)
_EARLY_DISCOUNT = re.compile(r"(\d+(?:\.\d+)?)\s*/\s*(\d+)\s*,?\s*net\s*(\d+)", re.IGNORECASE)


def normalize_invoice_number(number: str) -> str:
    """'CFL/INV-4471-R' -> 'CFLINV4471'. Strips resubmission suffixes and punctuation."""
    stripped = _RESUBMIT_SUFFIX.sub("", number.strip())
    return re.sub(r"[^A-Z0-9]", "", stripped.upper())


def _money(x: float) -> str:
    return f"₹{x:,.0f}"


def three_way_match(
    invoice: Invoice,
    po: PurchaseOrder | None,
    grn: GoodsReceipt | None,
    vendor: Vendor,
    history: list[Invoice],
) -> list[ExceptionFinding]:
    """Return every exception on this invoice. An empty list means straight-through processing."""
    findings: list[ExceptionFinding] = []

    # --- vendor master checks -------------------------------------------------------------
    if not invoice.bank_account.same_as(vendor.bank_account):
        findings.append(ExceptionFinding(
            code="bank_change",
            severity="critical",
            summary=(f"Remit-to bank changed: invoice says {invoice.bank_account.bank} "
                     f"{invoice.bank_account.ifsc} a/c ••{invoice.bank_account.account[-4:]}, "
                     f"vendor master has {vendor.bank_account.bank} {vendor.bank_account.ifsc} "
                     f"a/c ••{vendor.bank_account.account[-4:]}"),
            magnitude={"invoice_ifsc": invoice.bank_account.ifsc, "master_ifsc": vendor.bank_account.ifsc,
                       "amount_at_risk": invoice.total_inr},
        ))

    # --- duplicate detection --------------------------------------------------------------
    norm = normalize_invoice_number(invoice.invoice_number)
    for prior in history:
        if prior.vendor_id != invoice.vendor_id or prior.invoice_id == invoice.invoice_id:
            continue
        same_number = normalize_invoice_number(prior.invoice_number) == norm
        same_amount_window = (abs(prior.total - invoice.total) < 1
                              and abs((prior.date - invoice.date).days) <= 14
                              and prior.po_number == invoice.po_number)
        if same_number or same_amount_window:
            findings.append(ExceptionFinding(
                code="duplicate_suspect",
                severity="critical",
                summary=(f"Looks like a resubmission of {prior.invoice_number} dated {prior.date:%d %b %Y} "
                         f"({_money(prior.total_inr)})"),
                magnitude={"original_invoice": prior.invoice_number, "original_date": prior.date.isoformat(),
                           "matched_on": "invoice_number" if same_number else "amount+po+date"},
            ))
            break

    # --- tax type (GST place-of-supply) ---------------------------------------------------
    if vendor.state_code and invoice.tax_type != "RCM":
        expected = "CGST+SGST" if vendor.state_code == COMPANY_STATE_CODE else "IGST"
        if invoice.tax_type != expected:
            findings.append(ExceptionFinding(
                code="tax_type_mismatch",
                severity="warning",
                summary=(f"Invoice charges {invoice.tax_type} but supplier state {vendor.state_code} and "
                         f"our state {COMPANY_STATE_CODE} require {expected} — input tax credit at risk"),
                magnitude={"charged": invoice.tax_type, "expected": expected, "tax_amount": invoice.tax},
            ))

    # --- payment terms opportunity --------------------------------------------------------
    m = _EARLY_DISCOUNT.search(invoice.payment_terms)
    if m:
        pct, days = float(m.group(1)), int(m.group(2))
        findings.append(ExceptionFinding(
            code="early_payment_discount",
            severity="info",
            summary=(f"Terms '{invoice.payment_terms}': {pct:g}% off if paid within {days} days "
                     f"(by {(invoice.date + timedelta(days=days)):%d %b}) — worth {_money(invoice.total_inr * pct / 100)}"),
            magnitude={"discount_pct": pct, "within_days": days,
                       "discount_amount": round(invoice.total_inr * pct / 100, 2)},
        ))

    if po is None:
        findings.append(ExceptionFinding(
            code="missing_po", severity="critical",
            summary=f"No purchase order {invoice.po_number or '(none quoted)'} found",
        ))
        return findings

    # --- FX -------------------------------------------------------------------------------
    if invoice.currency != "INR":
        po_fc = sum(l.qty * l.unit_price for l in po.lines)
        inv_fc = sum(l.qty * l.unit_price for l in invoice.lines)
        budget_inr = inv_fc * po.budget_fx_rate
        actual_inr = inv_fc * invoice.fx_rate
        pct = (actual_inr - budget_inr) / budget_inr * 100 if budget_inr else 0.0
        if abs(pct) > 0.25:
            findings.append(ExceptionFinding(
                code="fx_variance",
                severity="warning",
                summary=(f"{invoice.currency} {inv_fc:,.2f} at {invoice.fx_rate:.2f} vs PO budget rate "
                         f"{po.budget_fx_rate:.2f}: {pct:+.2f}% ({_money(actual_inr - budget_inr)})"),
                magnitude={"variance_pct": round(pct, 2), "variance_inr": round(actual_inr - budget_inr, 2),
                           "invoice_rate": invoice.fx_rate, "budget_rate": po.budget_fx_rate,
                           "po_amount_fc": po_fc},
            ))

    # --- line-level 3-way match -----------------------------------------------------------
    po_lines = {l.sku: l for l in po.lines}
    grn_qty = {l.sku: l.qty_received for l in grn.lines} if grn else {}
    for line in invoice.lines:
        pl = po_lines.get(line.sku)
        if pl is None:
            findings.append(ExceptionFinding(
                code="line_not_on_po", severity="warning",
                summary=f"'{line.description}' is not on {po.po_number}",
                magnitude={"sku": line.sku, "amount": line.qty * line.unit_price},
            ))
            continue

        inv_value, po_value = line.qty * line.unit_price, pl.qty * pl.unit_price
        if line.uom != pl.uom:
            ratio = pl.qty / line.qty if line.qty else 0
            if po_value and abs(inv_value - po_value) / po_value <= UOM_TOTAL_TOLERANCE:
                findings.append(ExceptionFinding(
                    code="uom_mismatch", severity="warning",
                    summary=(f"'{pl.description}': billed {line.qty:g} {line.uom} @ {_money(line.unit_price)} "
                             f"vs PO {pl.qty:g} {pl.uom} @ {_money(pl.unit_price)} — line value matches "
                             f"({_money(inv_value)}), implied 1 {line.uom} = {ratio:g} {pl.uom}"),
                    magnitude={"sku": line.sku, "invoice_uom": line.uom, "po_uom": pl.uom,
                               "implied_ratio": round(ratio, 3), "value_diff": round(inv_value - po_value, 2)},
                ))
            else:
                findings.append(ExceptionFinding(
                    code="quantity_mismatch", severity="warning",
                    summary=(f"'{pl.description}': {line.qty:g} {line.uom} billed vs {pl.qty:g} {pl.uom} ordered "
                             f"and values differ ({_money(inv_value)} vs {_money(po_value)})"),
                    magnitude={"sku": line.sku, "value_diff": round(inv_value - po_value, 2)},
                ))
            continue  # can't compare price/receipt across units

        if pl.unit_price and (line.unit_price - pl.unit_price) / pl.unit_price > PRICE_TOLERANCE:
            pct = (line.unit_price - pl.unit_price) / pl.unit_price * 100
            findings.append(ExceptionFinding(
                code="price_variance", severity="warning",
                summary=(f"'{pl.description}': {_money(line.unit_price)}/{line.uom} billed vs "
                         f"{_money(pl.unit_price)} on PO (+{pct:.1f}%, {_money((line.unit_price - pl.unit_price) * line.qty)} over)"),
                magnitude={"sku": line.sku, "variance_pct": round(pct, 2), "po_price": pl.unit_price,
                           "invoice_price": line.unit_price,
                           "amount_over": round((line.unit_price - pl.unit_price) * line.qty, 2),
                           "invoice_date": invoice.date.isoformat()},
            ))

        if line.qty > pl.qty:
            findings.append(ExceptionFinding(
                code="over_billed_qty", severity="warning",
                summary=f"'{pl.description}': billed {line.qty:g} but only {pl.qty:g} ordered",
                magnitude={"sku": line.sku, "excess_qty": line.qty - pl.qty},
            ))

        received = grn_qty.get(line.sku, 0.0) if grn else 0.0
        if line.qty > received:
            findings.append(ExceptionFinding(
                code="received_short", severity="warning",
                summary=(f"'{pl.description}': billed {line.qty:g} {line.uom}, GRN "
                         f"{grn.grn_number if grn else '(none)'} shows {received:g} received"),
                magnitude={"sku": line.sku, "billed_qty": line.qty, "received_qty": received,
                           "unreceived_value": round((line.qty - received) * line.unit_price, 2)},
            ))

    # --- charges not on the PO ------------------------------------------------------------
    for charge in invoice.charges:
        findings.append(ExceptionFinding(
            code="unplanned_charge", severity="warning",
            summary=f"{charge.description} of {_money(charge.amount)} is not on {po.po_number}",
            magnitude={"charge_type": charge.type, "amount": charge.amount},
        ))

    return findings
