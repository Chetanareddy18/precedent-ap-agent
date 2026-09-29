# Precedent — Project Overview

**An accounts-payable agent that resolves invoice exceptions the way your team resolved them last time, powered by Hindsight agent memory.**

Repository: https://github.com/Chetanareddy18/precedent-ap-agent
Team: Chetana Reddy

## 1. One-line pitch

Precedent remembers *why* your AP team resolved each invoice exception (the cap, the tolerance, the effective date, the contract clause). The next time a vendor does the same thing, it checks those conditions, resolves the invoice by itself and cites the precedent. When a condition fails, it hands the invoice to a human with a precise suggestion.

## 2. The problem

- Every company pays vendors after a **3-way match**: invoice vs purchase order (PO) vs goods receipt (GRN).
- A few percent of invoices fail the match and become **exceptions**. Each one takes a senior clerk 10–20 minutes.
- Most exceptions are **repeats**: the same vendor with the same habit. The knowledge to resolve them lives in one senior person's head or in unread CRM notes.
- A stateless LLM gives *generic* advice ("freight not on PO, hold it"). That is correct in general and wrong for this company.
- The cost: slow payments, missed early-payment discounts, duplicate payments, and fraud (fake bank-detail changes).

## 3. The solution

| Step | What happens |
|---|---|
| 1. Match | A deterministic engine finds and measures exceptions: price, quantity, unit of measure, short receipt, unplanned charges, FX, GST place-of-supply, duplicates, early-payment terms, bank changes. |
| 2. Recall | Hindsight returns this vendor's past resolutions (citable) and the same exception at other vendors (hints only). |
| 3. Decide | The LLM checks every condition written in the recalled reasons (e.g. ₹2,750 ≤ ₹3,000 cap) and chooses an action and a payable basis. The code computes the amount. |
| 4. Guardrails | The agent may act alone only if it cites a same-vendor precedent with confidence ≥ 0.75. Bank changes and missing POs always go to a human. |
| 5. Learn | Every human decision is retained with its reason, including overrides. A note can become a standing policy (directive). Each vendor gets an auto-refreshing playbook (mental model). |

## 4. How Hindsight memory is used (the core of the project)

| Hindsight feature | Use in Precedent |
|---|---|
| Memory bank + mission + retain_mission + disposition | Tuned for accounting: keep caps, tolerances, dates and clauses; skepticism 5, literalism 4. |
| retain (timestamp, tags, metadata, document_id) | One memory per resolved exception: vendor, measured exception, outcome, payable basis and the clerk's **reason**. Idempotent per invoice. |
| recall with tags (`vendor:V001`, `exc:unplanned_charge`, strict matching) | Two parallel recalls. Same-vendor precedents are citable; other vendors' are hints only. |
| Directives | A clerk ticks "make this a standing policy" and it applies to every future decision (e.g. bank-change fraud). |
| Mental models | A per-vendor playbook that Hindsight re-synthesises as memories consolidate. |
| Reflect | "Ask your AP memory": questions across the whole history (caps, fraud attempts, repeat offenders). |
| Temporal memory | Precedents are shown with dates ("33 days before this invoice"), which is what makes effective-date logic work. |

**Before vs after:** with memory off, all 25 exceptions in the 12-week inbox go to a human. With memory on, the repeats resolve themselves, while look-alikes (over the cap, over the FX band, different vendor) still reach a person.

## 5. The demo story (12 weeks, 11 vendors, 29 invoices, 25 exceptions)

| Invoice | What happens | Why it matters |
|---|---|---|
| #1 Deccan freight ₹2,400 | No memory → human. The AP lead writes: clause 7.2, cap ₹3,000. Retained. | The first time is always a human decision. |
| #11 Deccan freight ₹2,750 | Recalls #1 → 2,750 ≤ 3,000 → **auto-approves, cites #1** | Memory creates autonomy. |
| #14 Apex +6%, dated 10 Aug | #7 was short-paid because the rate card started 1 Aug. Now it's after → **approves** | Reads the reason instead of copying the decision. |
| #19 Nimbus FX +3.6% | 2% treasury band exceeded → **escalates** | Knows the limits of a precedent. |
| #20 Deccan freight ₹6,800 | Over the ₹3,000 cap → **escalates, suggests ₹3,000** | A precise suggestion for the human. |
| #24 Krishna Polymers freight | Looks like Deccan but is another vendor → hint only → **human** | Refuses to generalise contracts. |
| #6, #17, #29 Vertex bank change | Always human, enriched with fraud history and a directive | Memory never unlocks a hard control. |

## 6. What makes Precedent different

Other memory agents, including other AP agents, typically **store outcomes** and recall "similar" events. Precedent differs in five ways:

1. **It retains the reason, not the label.** It learns *when not to* approve, not only *what* was approved.
2. **Citable vs hint recall.** Tag-scoped recall separates this vendor's contract terms from other vendors' patterns, with a guardrail that verifies the citation.
3. **Conditions are checked and shown.** Every auto-decision lists the checks with numbers (₹2,750 ≤ ₹3,000).
4. **The LLM never computes money.** It picks a payable basis and the code does the arithmetic, verified by tests.
5. **Uses more of Hindsight:** retain, tag-scoped recall, reflect, directives, mental models and temporal grounding, plus overrides retained as corrections.

## 7. Technical architecture

- **Backend:** Python, FastAPI, `hindsight-client` (async), Groq OpenAI-compatible API (`openai/gpt-oss-120b`, fallback `qwen/qwen3-32b`).
- **Frontend:** single-page workbench in vanilla JS (inbox, invoice and 3-way-match table, agent decision with cited precedents, compare-without-memory, learning-curve chart, reflect box, vendor playbook, retain feed).
- **Robustness:** JSON repair and model fallback, then a deterministic heuristic. Hindsight outage → fail safe to human. Idempotent retains.
- **Quality:** 14 offline tests, a live Hindsight smoke test, and a memory OFF vs ON benchmark script.
- **Modules:** `matching.py` (3-way match), `memory.py` (Hindsight adapter), `agent.py` (decide / guardrails / learn), `llm.py` (hardened LLM client), `session.py` (inbox and KPIs), `api.py` (endpoints).

## 8. Real-world impact and business case

- **Buyer:** AP managers and shared-services leads at companies processing 2,000–50,000 invoices a month.
- **Value:** at 4% exceptions × 18 minutes, a 10,000-invoice/month company spends about 120 clerk-hours a month on exceptions. Precedent automates the repeats, catches duplicates, short shipments and GST errors, blocks bank-change fraud, and captures early-payment discounts.
- **Adoption path:** start read-only (the agent drafts, humans accept), then enable auto-resolve per vendor once its precedents have a clean override record. Works from Tally / SAP / Zoho Books exports.
- **Pricing idea:** ₹4,000–₹8,000 (about $50–$100) per AP seat per month, which easily passes the "would someone pay $50/month?" test.

## 9. Mapping to the judging criteria

| Criterion | Weight | Where Precedent scores |
|---|---|---|
| Innovation | 30% | Reason-level memory, citable-vs-hint recall, condition checks, clerk notes turned into policy. Well beyond a chatbot. |
| Use of Hindsight memory | 25% | Memory is the product: 25/25 exceptions go to a human without it. Uses 6+ Hindsight features. Visible learning curve. |
| Technical implementation | 20% | Clean modules, guardrails, JSON hardening, no LLM arithmetic, tests, benchmark, smoke test. |
| User experience | 15% | One-screen workbench, autopilot story, compare button, chart, playbooks, reflect. |
| Real-world impact | 10% | Real AP pain, rupee value, Indian GST realism, clear path to adoption. |

## 10. Future work

- ERP connectors (Tally, SAP B1, Zoho Books) and email/OCR invoice intake.
- Per-vendor autonomy levels learned from override rates.
- Multi-entity banks (one bank per legal entity) with shared fraud directives.
- An audit export of every auto-decision with its cited memories.
