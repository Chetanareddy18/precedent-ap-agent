"""Generate the demo dataset: a Hyderabad FMCG manufacturer's AP inbox over 12 weeks.

Godavari Consumer Products Pvt. Ltd. buys steel wire, packaging, chemicals, cloud, freight and
facility services from 11 vendors. Each vendor has a *habit* — a recurring exception that a
senior AP clerk knows how to handle and a new hire (or a stateless LLM) does not.

The stream is ordered so each habit appears first when memory is empty, then recurs — sometimes
with a twist that breaks a naive "copy the last decision" strategy:

  * Deccan freight within the ₹3,000 contract cap  -> approve; above the cap -> short-pay
  * Apex +6% price increase before its effective date -> short-pay; after -> approve
  * Nimbus FX variance under 2% -> approve; 3.6% -> hold for treasury
  * Krishna Polymers bills freight like Deccan does, but its PO is FOR-destination -> don't generalise

Run:  python scripts/generate_data.py      (writes data/*.json)
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from precedent.models import (  # noqa: E402
    BankAccount, Charge, GoodsReceipt, GRNLine, Invoice, InvoiceLine, POLine, PurchaseOrder, Vendor,
)

D = lambda m, d: date(2026, m, d)  # noqa: E731

VENDORS = [
    Vendor(vendor_id="V001", name="Deccan Steel & Wire Pvt. Ltd.", gstin="36AABCD4821K1Z3", state_code="36",
           city="Medchal, Telangana", category="Raw material — steel", payment_terms="Net 45",
           bank_account=BankAccount(bank="HDFC Bank", ifsc="HDFC0001234", account="50200012348871")),
    Vendor(vendor_id="V002", name="Sharma Corrugated Packaging", gstin="36AAKFS7719M1ZQ", state_code="36",
           city="Jeedimetla, Hyderabad", category="Packaging", payment_terms="Net 30",
           bank_account=BankAccount(bank="State Bank of India", ifsc="SBIN0020417", account="38915520064")),
    Vendor(vendor_id="V003", name="Nimbus Cloud Services Inc.", gstin=None, state_code=None,
           city="Seattle, USA", category="IT — cloud infrastructure", payment_terms="Net 30", currency="USD",
           bank_account=BankAccount(bank="JPMorgan Chase", ifsc="CHASUS33", account="000483920117")),
    Vendor(vendor_id="V004", name="Coastal Freight Logistics LLP", gstin="37AAPFC3310H1ZK", state_code="37",
           city="Visakhapatnam, Andhra Pradesh", category="Logistics", payment_terms="Net 30",
           bank_account=BankAccount(bank="ICICI Bank", ifsc="ICIC0000456", account="045605003321")),
    Vendor(vendor_id="V005", name="Vertex Office Supplies", gstin="36AATPV6624R1Z9", state_code="36",
           city="Ameerpet, Hyderabad", category="Office consumables", payment_terms="Net 30",
           bank_account=BankAccount(bank="Kotak Mahindra Bank", ifsc="KKBK0007452", account="7412098833")),
    Vendor(vendor_id="V006", name="Apex Specialty Chemicals Ltd.", gstin="36AAECA9087P1ZM", state_code="36",
           city="Patancheru, Telangana", category="Raw material — surfactants", payment_terms="Net 60",
           bank_account=BankAccount(bank="Axis Bank", ifsc="UTIB0000553", account="917020045566120")),
    Vendor(vendor_id="V007", name="Sunrise Agro Foods Pvt. Ltd.", gstin="36AAKCS2231F1Z7", state_code="36",
           city="Nizamabad, Telangana", category="Raw material — edible oils", payment_terms="2/10 Net 30",
           bank_account=BankAccount(bank="Canara Bank", ifsc="CNRB0003321", account="3321201004478")),
    Vendor(vendor_id="V008", name="Hyderabad Electricals & Controls", gstin="36AAHFH5510D1ZW", state_code="36",
           city="Balanagar, Hyderabad", category="MRO — electrical", payment_terms="Net 30",
           bank_account=BankAccount(bank="Union Bank of India", ifsc="UBIN0815772", account="157711100009921")),
    Vendor(vendor_id="V009", name="Metro Facility Services Pvt. Ltd.", gstin="36AAFCM8842L1ZU", state_code="36",
           city="Gachibowli, Hyderabad", category="Facility services", payment_terms="Net 15",
           bank_account=BankAccount(bank="IndusInd Bank", ifsc="INDB0000712", account="201004588213")),
    Vendor(vendor_id="V010", name="Lakshmi Offset Printers", gstin="36AAJFL3321C1Z5", state_code="36",
           city="Chikkadpally, Hyderabad", category="Printing — labels & cartons", payment_terms="Net 30",
           bank_account=BankAccount(bank="Bank of Baroda", ifsc="BARB0CHIKKA", account="29870200001457")),
    Vendor(vendor_id="V011", name="Krishna Polymers Pvt. Ltd.", gstin="36AAGCK1187N1Z2", state_code="36",
           city="Kukatpally, Hyderabad", category="Packaging — HDPE bottles", payment_terms="Net 30",
           bank_account=BankAccount(bank="HDFC Bank", ifsc="HDFC0002290", account="50200077120034")),
]
VMAP = {v.vendor_id: v for v in VENDORS}

FRAUD_ACCOUNTS = [
    BankAccount(bank="Yes Bank", ifsc="YESB0000871", account="087163400001203"),
    BankAccount(bank="RBL Bank", ifsc="RATN0000194", account="309011245780"),
    BankAccount(bank="Yes Bank", ifsc="YESB0000412", account="041263900007788"),
]

# Catalogue: sku -> (description, hsn, uom, po_price, gst)
SKU = {
    "WR55": ("MS Wire Rod 5.5mm (IS 7887)", "7213", "MT", 52500.0, 0.18),
    "CB3P": ("3-ply corrugated shipper box 450x300x250", "4819", "NOS", 18.0, 0.12),
    "K8S": ("Managed Kubernetes cluster — monthly", "998315", "MONTH", 1.0, 0.18),
    "RFHV": ("Road freight HYD–VSKP, 32ft MXL", "996511", "TRIP", 38500.0, 0.12),
    "A4P": ("A4 copier paper 75gsm (ream)", "4802", "REAM", 265.0, 0.18),
    "TNR": ("Toner cartridge HP 88A", "8443", "NOS", 3950.0, 0.18),
    "SLES": ("Sodium Lauryl Ether Sulphate 70%", "3402", "KG", 142.0, 0.18),
    "RPO": ("Refined palm olein, 15kg tin", "1511", "TIN", 1720.0, 0.05),
    "MCCB": ("MCCB 3P 250A 36kA", "8536", "NOS", 14800.0, 0.18),
    "CT95": ("Power contactor 95A AC3", "8536", "NOS", 4650.0, 0.18),
    "HKM": ("Housekeeping manpower — monthly (14 staff)", "998533", "MONTH", 336000.0, 0.18),
    "LBL": ("Printed front labels, 4-colour", "4821", "NOS", 1.85, 0.18),
    "HDB5": ("HDPE bottle 500ml with cap", "3923", "NOS", 6.40, 0.18),
}

POS: list[PurchaseOrder] = []
GRNS: list[GoodsReceipt] = []
INVOICES: list[Invoice] = []
TRUTH: list[dict] = []


def _po(po_number, vendor_id, po_date, lines, currency="INR", fx=1.0, prices=None):
    prices = prices or {}
    po = PurchaseOrder(
        po_number=po_number, vendor_id=vendor_id, date=po_date, currency=currency, budget_fx_rate=fx,
        lines=[POLine(sku=s, description=SKU[s][0], hsn=SKU[s][1], qty=q, uom=SKU[s][2],
                      unit_price=prices.get(s, SKU[s][3]), tax_rate=SKU[s][4]) for s, q in lines],
    )
    POS.append(po)
    return po


def _grn(po, grn_date, received=None):
    received = received or {}
    GRNS.append(GoodsReceipt(
        grn_number=f"GRN-{po.po_number[3:]}", po_number=po.po_number, date=grn_date,
        lines=[GRNLine(sku=l.sku, qty_received=received.get(l.sku, l.qty)) for l in po.lines],
    ))


def _inv(number, vendor_id, inv_date, po, lines, *, charges=(), bank=None, tax_type=None, currency="INR",
         fx=1.0, received_lag=2, terms=None):
    v = VMAP[vendor_id]
    inv = Invoice(
        invoice_id=f"INV-{len(INVOICES) + 1:03d}", invoice_number=number, vendor_id=vendor_id,
        po_number=po.po_number if po else None, date=inv_date, received_on=inv_date + timedelta(days=received_lag),
        currency=currency, fx_rate=fx,
        tax_type=tax_type or ("RCM" if currency != "INR" else ("CGST+SGST" if v.state_code == "36" else "IGST")),
        payment_terms=terms or v.payment_terms, bank_account=bank or v.bank_account,
        lines=[InvoiceLine(sku=s, description=SKU[s][0], qty=q, uom=u or SKU[s][2], unit_price=p,
                           tax_rate=SKU[s][4]) for s, q, u, p in lines],
        charges=[Charge(type=t, description=d, amount=a) for t, d, a in charges],
    )
    INVOICES.append(inv)
    return inv


def _truth(inv, route, action, payable=None, note="", policy=False, basis=None, cap=None):
    """route: what an ideal memory-backed agent should do. action: what the AP lead actually did."""
    TRUTH.append({"invoice_id": inv.invoice_id, "expected_route": route, "clerk_action": action,
                  "payable_amount": round(payable if payable is not None else inv.total_inr, 2)
                  if action not in ("reject", "hold") else 0.0,
                  "note": note, "make_policy": policy,
                  "basis": basis or ("zero" if action in ("reject", "hold") else "full"), "charge_cap": cap})


def taxed(*amounts_and_rates):
    return round(sum(a * (1 + r) for a, r in amounts_and_rates), 2)


def build():
    # ---------------- Week 1-5: memory is empty; every exception goes to a human ----------------
    po = _po("PO-45012", "V001", D(6, 24), [("WR55", 4)]); _grn(po, D(7, 1))
    i = _inv("DSW/26-27/0412", "V001", D(7, 3), po, [("WR55", 4, None, 52500)],
             charges=[("freight", "Freight & unloading (Medchal → Plant 2)", 2400)])
    _truth(i, "human", "approve", note=(
        "Deccan's rate contract (clause 7.2) lets them bill freight separately, capped at ₹3,000 per "
        "delivery. ₹2,400 is inside the cap — approve. Anything above ₹3,000 needs procurement sign-off."))

    po = _po("PO-45019", "V010", D(6, 28), [("LBL", 20000)]); _grn(po, D(7, 4))
    i = _inv("LOP/1187", "V010", D(7, 6), po, [("LBL", 20000, None, 1.85)])
    _truth(i, "straight_through", "approve")

    po = _po("PO-45021", "V002", D(6, 30), [("CB3P", 1200)]); _grn(po, D(7, 6))
    i = _inv("SCP/2026/771", "V002", D(7, 8), po, [("CB3P", 100, "BDL", 216.0)])
    _truth(i, "human", "approve", note=(
        "Sharma's billing system can only invoice in bundles (BDL) of 12. 100 BDL = 1,200 NOS and the value "
        "matches the PO exactly — approve. Not a quantity problem."))

    po = _po("PO-45027", "V003", D(7, 1), [("K8S", 1)], currency="USD", fx=83.0,
             prices={"K8S": 4200.0}); _grn(po, D(7, 10))
    i = _inv("NCS-INV-20931", "V003", D(7, 11), po, [("K8S", 1, None, 4200.0)], currency="USD", fx=84.20)
    _truth(i, "human", "approve", note=(
        "Nimbus bills in USD. Treasury's rule: FX movement vs the PO budget rate of up to 2% is absorbed — "
        "approve. Above 2%, hold and ask treasury to confirm the rate before release."))

    po = _po("PO-45030", "V004", D(7, 2), [("RFHV", 3)]); _grn(po, D(7, 12))
    coastal_4471 = _inv("CFL/INV-4471", "V004", D(7, 15), po, [("RFHV", 3, None, 38500)])
    _truth(coastal_4471, "straight_through", "approve")

    po = _po("PO-45033", "V005", D(7, 8), [("A4P", 200), ("TNR", 10)]); _grn(po, D(7, 16))
    i = _inv("VOS/2207", "V005", D(7, 18), po, [("A4P", 200, None, 265), ("TNR", 10, None, 3950)],
             bank=FRAUD_ACCOUNTS[0])
    _truth(i, "human", "hold", policy=True, note=(
        "Bank change request came from vertex.accounts.billing@gmail.com, not their domain. Called Vertex on "
        "the number in the vendor master — they have NOT changed banks. Attempted business-email-compromise "
        "fraud. Policy: never pay to changed bank details until verified by a call-back to the vendor-master "
        "phone number and signed off by the finance controller."))

    po = _po("PO-45036", "V006", D(7, 10), [("SLES", 1500)]); _grn(po, D(7, 19))
    i = _inv("ASC/INV/3318", "V006", D(7, 20), po, [("SLES", 1500, None, 150.52)], received_lag=2)
    _truth(i, "human", "approve_adjusted", payable=taxed((1500 * 142, 0.18)), basis="at_po_price", note=(
        "Apex sent a revised rate card (+6% on SLES) that is effective only for invoices dated on or after "
        "1 Aug 2026. This invoice is dated 20 Jul, so short-pay to the PO price of ₹142/kg and ask Apex "
        "for a credit note for the difference. From 1 Aug onwards ₹150.52/kg is the agreed price."))

    i = _inv("CFL/INV-4471-R", "V004", D(7, 25), POS[4], [("RFHV", 3, None, 38500)])
    _truth(i, "human", "reject", note=(
        "Duplicate. Coastal re-sends unpaid invoices with an '-R' suffix when the original isn't due yet. "
        "CFL/INV-4471 is already scheduled for payment — reject the resubmission, pay the original only."))

    po = _po("PO-45040", "V008", D(7, 14), [("MCCB", 12), ("CT95", 20)]); _grn(po, D(7, 27), {"MCCB": 8})
    i = _inv("HEC/0923", "V008", D(7, 29), po, [("MCCB", 12, None, 14800), ("CT95", 20, None, 4650)])
    _truth(i, "human", "approve_adjusted", payable=taxed((8 * 14800 + 20 * 4650, 0.18)), basis="received_qty_only", note=(
        "HEC always invoices the full PO even when they dispatch in parts. Pay only what the GRN shows "
        "received (8 of 12 MCCBs). The balance gets paid when the next GRN is posted."))

    po = _po("PO-45044", "V009", D(7, 1), [("HKM", 1)]); _grn(po, D(7, 31))
    i = _inv("MFS/25/0561", "V009", D(8, 2), po, [("HKM", 1, None, 336000)], tax_type="IGST")
    _truth(i, "human", "reject", note=(
        "Metro charged IGST on an intra-state Telangana service. We can't claim input tax credit on that. "
        "Reject and ask for a corrected tax invoice with CGST+SGST — this started after their billing "
        "software migration in June."))

    # ---------------- Weeks 5-9: the same habits recur; memory should carry them ----------------
    po = _po("PO-45048", "V001", D(7, 28), [("WR55", 3)]); _grn(po, D(8, 3))
    i = _inv("DSW/26-27/0507", "V001", D(8, 5), po, [("WR55", 3, None, 52500)],
             charges=[("freight", "Freight & unloading (Medchal → Plant 2)", 2750)])
    _truth(i, "auto", "approve")

    po = _po("PO-45051", "V002", D(8, 1), [("CB3P", 1800)]); _grn(po, D(8, 6))
    i = _inv("SCP/2026/834", "V002", D(8, 8), po, [("CB3P", 150, "BDL", 216.0)])
    _truth(i, "auto", "approve")

    po = _po("PO-45055", "V003", D(8, 1), [("K8S", 1)], currency="USD", fx=83.0,
             prices={"K8S": 4350.0}); _grn(po, D(8, 10))
    i = _inv("NCS-INV-21388", "V003", D(8, 12), po, [("K8S", 1, None, 4350.0)], currency="USD", fx=84.50)
    _truth(i, "auto", "approve")

    po = _po("PO-45058", "V006", D(8, 4), [("SLES", 1200)]); _grn(po, D(8, 9))
    i = _inv("ASC/INV/3402", "V006", D(8, 10), po, [("SLES", 1200, None, 150.52)])
    _truth(i, "auto", "approve")  # the twist: same variance, but now after the effective date

    po = _po("PO-45061", "V007", D(8, 10), [("RPO", 400)]); _grn(po, D(8, 16))
    i = _inv("SAF/2026/118", "V007", D(8, 18), po, [("RPO", 400, None, 1720)])
    _truth(i, "human", "schedule_early_payment", payable=i.total_inr * 0.98, basis="early_payment_discount", note=(
        "Sunrise gives 2% off for payment within 10 days. Always take it — on our monthly palm olein "
        "volume that's ~₹14,000 a month. Schedule in the next payment run."))

    po = _po("PO-45063", "V004", D(8, 12), [("RFHV", 2)]); _grn(po, D(8, 18))
    coastal_4535 = _inv("CFL/INV-4535", "V004", D(8, 20), po, [("RFHV", 2, None, 38500)])
    _truth(coastal_4535, "straight_through", "approve")

    po = _po("PO-45064", "V005", D(8, 14), [("A4P", 150)]); _grn(po, D(8, 19))
    i = _inv("VOS/2291", "V005", D(8, 21), po, [("A4P", 150, None, 265)], bank=FRAUD_ACCOUNTS[1])
    _truth(i, "human", "hold", note=(
        "Second bank-change attempt on Vertex, different account this time. Verified by call-back: fraud "
        "again. Reported to IT security."))

    i = _inv("CFL/INV-4535-R", "V004", D(8, 25), POS[-2], [("RFHV", 2, None, 38500)])
    _truth(i, "auto", "reject")

    po = _po("PO-45068", "V003", D(8, 20), [("K8S", 1)], currency="USD", fx=83.0,
             prices={"K8S": 4300.0}); _grn(po, D(8, 27))
    i = _inv("NCS-INV-21840", "V003", D(8, 28), po, [("K8S", 1, None, 4300.0)], currency="USD", fx=86.0)
    _truth(i, "human", "hold", note=(
        "FX is 3.6% over the budget rate — above treasury's 2% band. Holding; treasury to confirm the "
        "rate / hedge before release."))

    po = _po("PO-45070", "V001", D(8, 24), [("WR55", 5)]); _grn(po, D(8, 30))
    i = _inv("DSW/26-27/0588", "V001", D(9, 1), po, [("WR55", 5, None, 52500)],
             charges=[("freight", "Freight & unloading — 2 trips (Medchal → Plant 2)", 6800)])
    _truth(i, "human", "approve_adjusted", payable=taxed((5 * 52500 + 3000, 0.18)), basis="cap_charges", cap=3000, note=(
        "Freight ₹6,800 is over the ₹3,000 clause 7.2 cap. Paid goods + ₹3,000 freight; the extra ₹3,800 "
        "is on hold until procurement signs off on the second trip."))

    po = _po("PO-45073", "V008", D(8, 26), [("MCCB", 10)]); _grn(po, D(9, 2), {"MCCB": 6})
    i = _inv("HEC/0987", "V008", D(9, 4), po, [("MCCB", 10, None, 14800)])
    _truth(i, "auto", "approve_adjusted", payable=taxed((6 * 14800, 0.18)), basis="received_qty_only")

    po = _po("PO-45075", "V009", D(8, 1), [("HKM", 1)]); _grn(po, D(9, 5))
    i = _inv("MFS/25/0618", "V009", D(9, 8), po, [("HKM", 1, None, 336000)], tax_type="IGST")
    _truth(i, "auto", "reject")

    po = _po("PO-45078", "V007", D(9, 2), [("RPO", 380)]); _grn(po, D(9, 8))
    i = _inv("SAF/2026/131", "V007", D(9, 10), po, [("RPO", 380, None, 1720)])
    _truth(i, "auto", "schedule_early_payment", payable=i.total_inr * 0.98, basis="early_payment_discount")

    # ---------------- Weeks 10-12: a lookalike trap + steady state ----------------
    po = _po("PO-45080", "V011", D(9, 3), [("HDB5", 10000)]); _grn(po, D(9, 10))
    i = _inv("KPP/0045", "V011", D(9, 12), po, [("HDB5", 10000, None, 6.40)],
             charges=[("freight", "Freight charges (Kukatpally → Plant 2)", 1800)])
    _truth(i, "human", "approve_adjusted", payable=taxed((10000 * 6.40, 0.18)), basis="without_charges", note=(
        "New vendor. Krishna's PO is FOR-destination — freight is included in the unit price. Don't apply "
        "Deccan's freight clause here; strike the freight line and pay goods only."))

    po = _po("PO-45082", "V002", D(9, 8), [("CB3P", 2400)]); _grn(po, D(9, 13))
    i = _inv("SCP/2026/902", "V002", D(9, 15), po, [("CB3P", 200, "BDL", 216.0)])
    _truth(i, "auto", "approve")

    po = _po("PO-45084", "V006", D(9, 10), [("SLES", 1000)], prices={"SLES": 142.0}); _grn(po, D(9, 16))
    i = _inv("ASC/INV/3517", "V006", D(9, 18), po, [("SLES", 1000, None, 150.52)])
    _truth(i, "auto", "approve")

    po = _po("PO-45087", "V001", D(9, 14), [("WR55", 4)]); _grn(po, D(9, 20))
    i = _inv("DSW/26-27/0655", "V001", D(9, 22), po, [("WR55", 4, None, 52500)],
             charges=[("freight", "Freight & unloading (Medchal → Plant 2)", 2900)])
    _truth(i, "auto", "approve")

    po = _po("PO-45089", "V010", D(9, 16), [("LBL", 25000)]); _grn(po, D(9, 22))
    i = _inv("LOP/1244", "V010", D(9, 24), po, [("LBL", 25000, None, 1.85)])
    _truth(i, "straight_through", "approve")

    po = _po("PO-45090", "V005", D(9, 18), [("TNR", 12)]); _grn(po, D(9, 23))
    i = _inv("VOS/2356", "V005", D(9, 25), po, [("TNR", 12, None, 3950)], bank=FRAUD_ACCOUNTS[2])
    _truth(i, "human", "hold", note="Third attempt. Verified fraud via call-back; vendor informed.")


def main():
    build()
    out = ROOT / "data"
    out.mkdir(exist_ok=True)
    dump = lambda name, rows: (out / name).write_text(  # noqa: E731
        json.dumps([r.model_dump(mode="json") if hasattr(r, "model_dump") else r for r in rows],
                   indent=2, ensure_ascii=False), encoding="utf-8")
    dump("vendors.json", VENDORS)
    dump("purchase_orders.json", POS)
    dump("goods_receipts.json", GRNS)
    dump("invoices.json", INVOICES)
    dump("clerk_ground_truth.json", TRUTH)
    print(f"wrote {len(VENDORS)} vendors, {len(POS)} POs, {len(GRNS)} GRNs, {len(INVOICES)} invoices -> {out}")


if __name__ == "__main__":
    main()
