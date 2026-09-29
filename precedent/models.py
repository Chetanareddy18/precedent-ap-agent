"""Domain models for invoices, purchase orders, goods receipts and agent decisions."""
from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Action(str, Enum):
    APPROVE = "approve"
    APPROVE_ADJUSTED = "approve_adjusted"  # short-pay to a corrected amount
    REJECT = "reject"
    HOLD = "hold"  # stop payment pending investigation
    SCHEDULE_EARLY_PAYMENT = "schedule_early_payment"


class Route(str, Enum):
    STRAIGHT_THROUGH = "straight_through"  # clean 3-way match, no exceptions
    AUTO = "auto"  # agent resolved an exception on its own, backed by precedent
    HUMAN = "human"  # routed to an AP clerk


class BankAccount(BaseModel):
    bank: str
    ifsc: str
    account: str

    def same_as(self, other: "BankAccount") -> bool:
        return self.ifsc == other.ifsc and self.account == other.account


class Vendor(BaseModel):
    vendor_id: str
    name: str
    gstin: str | None = None
    state_code: str | None = None  # first two digits of GSTIN; None for foreign vendors
    city: str
    category: str
    payment_terms: str
    currency: str = "INR"
    bank_account: BankAccount


class POLine(BaseModel):
    sku: str
    description: str
    hsn: str
    qty: float
    uom: str
    unit_price: float
    tax_rate: float


class PurchaseOrder(BaseModel):
    po_number: str
    vendor_id: str
    date: date
    currency: str = "INR"
    budget_fx_rate: float = 1.0  # INR per unit of PO currency, locked at PO time
    lines: list[POLine]


class GRNLine(BaseModel):
    sku: str
    qty_received: float


class GoodsReceipt(BaseModel):
    grn_number: str
    po_number: str
    date: date
    lines: list[GRNLine]


class InvoiceLine(BaseModel):
    sku: str
    description: str
    qty: float
    uom: str
    unit_price: float
    tax_rate: float


class Charge(BaseModel):
    type: str  # freight, packing, handling ...
    description: str
    amount: float


class Invoice(BaseModel):
    invoice_id: str  # internal id
    invoice_number: str  # vendor's number
    vendor_id: str
    po_number: str | None
    date: date
    received_on: date
    currency: str = "INR"
    fx_rate: float = 1.0  # INR per unit of invoice currency on invoice date
    tax_type: str = "CGST+SGST"  # CGST+SGST | IGST | RCM
    payment_terms: str
    bank_account: BankAccount
    lines: list[InvoiceLine]
    charges: list[Charge] = Field(default_factory=list)

    @property
    def subtotal(self) -> float:
        return round(sum(l.qty * l.unit_price for l in self.lines) + sum(c.amount for c in self.charges), 2)

    @property
    def tax(self) -> float:
        if self.tax_type == "RCM":
            return 0.0
        line_tax = sum(l.qty * l.unit_price * l.tax_rate for l in self.lines)
        # charges follow the tax rate of the principal supply (first line)
        charge_rate = self.lines[0].tax_rate if self.lines else 0.0
        return round(line_tax + sum(c.amount for c in self.charges) * charge_rate, 2)

    @property
    def total(self) -> float:
        return round(self.subtotal + self.tax, 2)

    @property
    def total_inr(self) -> float:
        return round(self.total * self.fx_rate, 2)


class ExceptionFinding(BaseModel):
    """A discrepancy found by the deterministic 3-way match engine."""

    code: str
    severity: str  # info | warning | critical
    summary: str
    magnitude: dict[str, Any] = Field(default_factory=dict)


class Precedent(BaseModel):
    """A memory recalled from Hindsight that the agent may cite."""

    id: str
    text: str
    type: str | None = None
    occurred: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)
    scope: str = "vendor"  # vendor | pattern (same exception, other vendors)


class Decision(BaseModel):
    invoice_id: str
    route: Route
    action: Action | None  # the action taken (auto) or suggested to the clerk (human)
    payable_amount: float | None = None
    payable_basis: str | None = None
    charge_cap: float | None = None
    confidence: float = 0.0
    reasoning: str = ""
    conditions_checked: list[str] = Field(default_factory=list)
    exceptions: list[ExceptionFinding] = Field(default_factory=list)
    precedents: list[Precedent] = Field(default_factory=list)
    precedents_used: list[str] = Field(default_factory=list)
    directives_applied: list[str] = Field(default_factory=list)
    guardrail: str | None = None  # why the agent was not allowed to act alone
    decided_by: str = "llm"  # llm | heuristic | rules
    memory_enabled: bool = True
    latency_ms: int = 0


class ClerkResolution(BaseModel):
    invoice_id: str
    action: Action
    payable_amount: float | None = None
    note: str = ""
    make_policy: bool = False
    clerk: str = "Priya Nair (AP Lead)"
