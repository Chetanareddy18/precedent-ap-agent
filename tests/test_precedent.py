"""Offline tests: deterministic match engine, payable maths, guardrails, JSON hardening, learning loop.
Run: pytest -q   (no network, no API keys — uses the LocalMemory test double)"""
from __future__ import annotations

import asyncio
import json

import pytest

from precedent.agent import APAgent
from precedent.config import settings
from precedent.llm import LLM, parse_json_object
from precedent.matching import normalize_invoice_number
from precedent.memory import LocalMemory
from precedent.models import Action, Route
from precedent.session import Session


def run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def agent():
    return APAgent(settings, LocalMemory(), LLM(None, "", []))


@pytest.fixture()
def truth():
    return {t["invoice_id"]: t for t in json.loads((settings.data_dir / "clerk_ground_truth.json").read_text("utf-8"))}


def test_every_invoice_has_expected_exceptions(agent, truth):
    s = Session.load(agent)
    expected = {"INV-001": ["unplanned_charge"], "INV-003": ["uom_mismatch"], "INV-004": ["fx_variance"],
                "INV-006": ["bank_change"], "INV-007": ["price_variance"], "INV-008": ["duplicate_suspect"],
                "INV-009": ["received_short"], "INV-010": ["tax_type_mismatch"], "INV-015": ["early_payment_discount"]}
    for inv in s.invoices:
        found = [e.code for e in agent.detect(inv)]
        agent.post(inv)
        if inv.invoice_id in expected:
            assert found == expected[inv.invoice_id], inv.invoice_id
        if truth[inv.invoice_id]["expected_route"] == "straight_through":
            assert found == [], inv.invoice_id


def test_ground_truth_amounts_match_payable_options(agent, truth):
    s = Session.load(agent)
    for inv in s.invoices:
        t = truth[inv.invoice_id]
        if t["clerk_action"] in ("reject", "hold"):
            continue
        opts = agent.payable_options(inv, t["charge_cap"])
        assert abs(opts[t["basis"]] - t["payable_amount"]) < 1, (inv.invoice_id, t["basis"])


def test_resubmission_suffixes_normalise():
    assert normalize_invoice_number("CFL/INV-4471-R") == normalize_invoice_number("CFL/INV-4471")
    assert normalize_invoice_number("ABC-99 REV2") == "ABC99"
    assert normalize_invoice_number("DSW/26-27/0412") != normalize_invoice_number("DSW/26-27/0507")


@pytest.mark.parametrize("raw", [
    '{"action": "approve"}',
    '<think>let me reason {not json}</think>{"action": "approve"}',
    '```json\n{"action": "approve"}\n```',
    'Sure! Here is the decision: {"action": "approve", "note": "brace } in string"} hope that helps',
])
def test_parse_json_object_is_robust(raw):
    assert parse_json_object(raw)["action"] == "approve"


def test_parse_json_object_raises_on_garbage():
    with pytest.raises(ValueError):
        parse_json_object("no json here")


def test_no_memory_means_every_exception_goes_to_a_human(agent):
    s = Session.load(agent, use_memory=False)
    while not s.done:
        run(s.autopilot_step())
    assert all(st.decision.route in (Route.HUMAN, Route.STRAIGHT_THROUGH) for st in s.steps)
    assert s.metrics()["human_touches"] == s.metrics()["exceptions"] == 25


def test_memory_reduces_human_touches_and_bank_changes_never_auto(agent):
    s = Session.load(agent, use_memory=True)
    while not s.done:
        run(s.autopilot_step())
    m = s.metrics()
    assert m["auto_resolved"] >= 5
    assert m["human_touches"] < m["exceptions"]
    for st in s.steps:
        if any(e.code == "bank_change" for e in st.decision.exceptions):
            assert st.decision.route == Route.HUMAN
            assert "Hard control" in (st.decision.guardrail or "")


def test_first_occurrence_is_never_auto(agent):
    s = Session.load(agent, use_memory=True)
    seen = set()
    while not s.done:
        st = run(s.autopilot_step())
        if st.decision.exceptions and st.invoice.vendor_id not in seen:
            assert st.decision.route == Route.HUMAN, st.invoice.invoice_id
        if st.decision.exceptions:
            seen.add(st.invoice.vendor_id)


def test_policy_note_becomes_directive(agent):
    s = Session.load(agent, use_memory=True)
    while s.cursor < 6:  # through INV-006, the first Vertex fraud attempt
        run(s.autopilot_step())
    directives = run(agent.memory.directives())
    assert any("Vertex" in d["name"] for d in directives)


def test_llm_disabled_returns_none():
    obj, model = run(LLM(None, "", ["x"]).json("s", "u"))
    assert obj is None and model is None


def test_resolve_requires_pending(agent):
    s = Session.load(agent)
    with pytest.raises(ValueError):
        run(s.resolve(None))
    assert Action("approve_adjusted") == Action.APPROVE_ADJUSTED
