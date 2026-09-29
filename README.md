# Precedent — an AP exception agent that resolves invoices the way your team did last time

> **Invoice exceptions are not new problems. They are the same vendor doing the same thing again.**
> Precedent remembers how your Accounts Payable team resolved every exception, the *reason* they gave, and
> every cap, tolerance and effective date buried in that reason, using [Hindsight](https://github.com/vectorize-io/hindsight)
> agent memory. The second time a vendor does it, the agent resolves it alone and cites the precedent. The first time, and whenever a condition doesn't hold, it hands the invoice to a human and learns from what they decide.

![Precedent workbench](docs/screenshots/workbench.png)

---

## The problem

A mid-size manufacturer's AP desk processes thousands of invoices a month. A few percent fail the 3-way match
(invoice vs purchase order vs goods receipt). Each exception costs a senior clerk 10-20 minutes, and **most of them
are repeats**:

| Vendor habit | What a new hire (or a stateless LLM) does | What the AP lead knows |
|---|---|---|
| Deccan Steel adds ₹2,400 freight that isn't on the PO | "Freight not on PO, hold and request PO amendment" | Clause 7.2 allows freight up to **₹3,000** per delivery. Approve. Above that, short-pay to ₹3,000. |
| Sharma Packaging bills 100 **BDL** against a PO for 1,200 **NOS** | "Quantity mismatch, hold" | Their ERP bills in bundles of 12. Value matches, so approve. |
| Apex Chemicals bills +6% on SLES | "Price variance, short-pay" | New rate card is effective **1 Aug**. Short-pay before that date, approve after. |
| Nimbus Cloud bills in USD at 84.2 vs budget 83.0 | "FX variance, hold" | Treasury absorbs up to **2%**. Above 2%, hold. |
| Coastal Freight sends `CFL/INV-4471-R` | Pays it twice | They resend unpaid invoices with `-R`. Reject. |
| Vertex Office Supplies "changed banks" | Pays the new account | It's business-email-compromise fraud. **Never** pay changed bank details without a call-back. |

That knowledge lives in one person's head and in a CRM notes field nobody reads. When they're on leave, the
exceptions pile up, or get paid wrong.

## What Precedent does

```
invoice ─► deterministic 3-way match ─► exceptions ─► Hindsight recall ─► LLM decision ─► guardrails ─┬─► auto-resolve (cites precedent)
                                                          ▲                                           └─► human (with a drafted suggestion)
                                                          └────────────── Hindsight retain ◄── clerk decision + reason
```

1. **A rules engine finds exceptions but never guesses.** [precedent/matching.py](precedent/matching.py) checks price, quantity, UoM,
   receipts, unplanned charges, FX, GST place-of-supply (IGST vs CGST+SGST), duplicate resubmissions, early-payment terms
   and remit-to bank changes, and *measures* each one (₹ over, % variance, days).
2. **Hindsight recall, scoped by tags.** Same-vendor precedents (`vendor:V001`) are citable. Cross-vendor patterns
   (`exc:unplanned_charge`) are shown as *hints only*, because contracts differ per vendor.
3. **The LLM checks the conditions and doesn't copy the decision.** It must write each check it made (`freight ₹2,750 ≤ ₹3,000 cap (P1)`)
   and pick a *payable basis*. The code does the arithmetic, so the LLM never computes money.
4. **Guardrails decide who acts.** The agent may act alone only if it cites a same-vendor precedent, its confidence is ≥ 0.75,
   and no hard control applies (bank changes and missing POs always go to a human, with memory adding context).
5. **Every human decision is retained** with its reason, tags and metadata. Overrides are retained as corrections.
   A clerk can promote a note to a **Hindsight directive** (standing policy), and each vendor gets an auto-refreshing
   **mental model** (its "playbook").

### Watch it learn

The demo inbox covers 12 weeks (Jul-Sep 2026) for Godavari Consumer Products, Hyderabad: 11 vendors, 29 invoices,
25 exceptions. It's built so each vendor's habit shows up first on an empty memory, then recurs, sometimes with a twist
that breaks "copy the last decision":

| # | Invoice | What happens |
|---|---|---|
| 1 | Deccan freight ₹2,400 | No memory → human. AP lead: *"clause 7.2, cap ₹3,000"*. **Retained.** |
| 11 | Deccan freight ₹2,750 | Recalls #1 → checks 2,750 ≤ 3,000 → **auto-approves, cites #1** |
| 14 | Apex +6%, dated 10 Aug | Recalls #7 (short-paid because *before 1 Aug*) → date is now after → **approves**. Copying #7 would have been wrong. |
| 19 | Nimbus FX **+3.6%** | Recalls the 2% band → **escalates** instead of auto-approving |
| 20 | Deccan freight **₹6,800** | Over the cap → **escalates**, suggests short-pay to ₹3,000 |
| 24 | *Krishna Polymers* freight ₹1,800 | Looks like Deccan, but it's another vendor → hint only → **human**. (Krishna's PO is FOR-destination. Generalising would have overpaid.) |
| 6, 17, 29 | Vertex bank change ×3 | Always human. By #17 the agent says *"second attempt, same pattern as 20 Jul, verify by call-back"* from a directive the AP lead created. |

Run it yourself: `python scripts/run_benchmark.py` replays the inbox with memory **off**, then **on**
([results](docs/benchmark.md)).

---

## How Hindsight memory is used

Memory is the product here, not an add-on. Without it the agent routes 25 of 25 exceptions to a human.
Full write-up: **[docs/HINDSIGHT_MEMORY.md](docs/HINDSIGHT_MEMORY.md)**.

| Hindsight feature | Where | What it does in Precedent |
|---|---|---|
| **Memory bank** with mission, `retain_mission`, disposition (skepticism 5, literalism 4) | [memory.py](precedent/memory.py) `ensure_bank` | Tells extraction to keep caps, tolerances, effective dates and clauses, because those decide the next case. |
| **retain** with `timestamp`, `tags`, `metadata`, `document_id` | [agent.py](precedent/agent.py) `learn` | One memory per resolved exception: outcome, payable basis, the clerk's reason, overrides. `document_id=resolution-INV-xxx` makes re-resolution idempotent. |
| **recall** with `tags` + `tags_match="any_strict"` | [agent.py](precedent/agent.py) `decide` | Two scoped recalls in parallel: this vendor's precedents (citable) and the same exception at other vendors (hints). |
| **directives** | `learn` → `add_directive` | A clerk ticks *"make this a standing policy"* and it becomes a Hindsight directive injected into every future decision. |
| **mental models** with `refresh_after_consolidation` | `ensure_playbook` | A per-vendor playbook Hindsight re-synthesises as memories consolidate. Shown in the UI. |
| **reflect** | `/api/ask` | "Which vendors keep costing us time?", "Summarise every fraud attempt": questions across the whole AP history. |
| Temporal grounding | `timestamp=` on retain | The agent sees *"P1 (05 Jul 2026, 33 days before this invoice)"*, and effective-date logic depends on it. |

---

## Quickstart

```bash
git clone https://github.com/Chetanareddy18/precedent-ap-agent && cd precedent-ap-agent
python -m venv .venv && .venv/Scripts/activate        # Windows  (source .venv/bin/activate on macOS/Linux)
pip install -r requirements.txt
cp .env.example .env                                   # then fill in keys (below)
uvicorn precedent.api:app --port 8000                  # open http://localhost:8000
```

Pick a memory backend in `.env`:

| Option | `.env` |
|---|---|
| **Hindsight Cloud** (fastest) | `HINDSIGHT_BASE_URL=https://api.hindsight.vectorize.io` and `HINDSIGHT_API_KEY=...` (promo code `MEMHACK99`) |
| **Self-hosted Hindsight** | `GROQ_API_KEY=... docker compose up -d`, then `HINDSIGHT_BASE_URL=http://localhost:8888` |
| **Fully local** (no keys at all) | Hindsight in Docker on Ollama, agent on Ollama. See [docs/LOCAL_OLLAMA.md](docs/LOCAL_OLLAMA.md) |

Agent LLM: `GROQ_API_KEY` with `openai/gpt-oss-120b` (fallback `qwen/qwen3-32b`), or any OpenAI-compatible
endpoint via `LLM_BASE_URL`/`LLM_MODEL`.

```bash
pytest -q                                   # 14 offline tests, no keys needed
python scripts/run_benchmark.py             # memory OFF vs ON on the live stack
python scripts/run_benchmark.py --offline   # same, with the local test double + deterministic heuristic
python scripts/generate_data.py             # regenerate the dataset
```

### Using the workbench

- **Next invoice**: the agent processes one invoice. If it needs you, fill in *Action / Pay / Why?* and hit
  **Resolve & retain**. The *Why?* note is what the agent will remember.
- **▶ Autopilot** replays the AP lead's recorded decisions ([data/clerk_ground_truth.json](data/clerk_ground_truth.json))
  so you can watch the human-touch curve bend in two minutes.
- **Compare without memory** on any exception shows what the same agent says with recall switched off.
- **Hindsight memory** toggle restarts the inbox with memory off, for the before/after.
- **Ask your AP memory** (reflect), **Vendor playbook** (mental model), **Retained to Hindsight** (live retain feed).

---

## Engineering notes

- **Money is never computed by the LLM.** It chooses a basis (`full`, `at_po_price`, `received_qty_only`,
  `without_charges`, `cap_charges` + cap, `early_payment_discount`, `zero`). [`payable_options`](precedent/agent.py)
  does the maths, and the tests check every ground-truth amount against it.
- **Hardened structured output** ([llm.py](precedent/llm.py)): JSON mode, `<think>`/fence stripping, brace-matching
  extraction, one repair retry, fallback model, then a deterministic heuristic. A 429 or a `json_validate_failed`
  never blocks an invoice.
- **Fails safe.** If Hindsight is unreachable, recall returns nothing, so there are no precedents, so everything goes to a human.
  Memory can only *add* autonomy, never remove a control.
- **The offline heuristic shows why the LLM is there.** Without it, pure "same exception → same action" copies
  the pre-effective-date short-pay onto Apex's August invoice and the capped freight onto Deccan's in-cap invoice. Both are wrong.
  Checking the conditions written in the recalled reason fixes that.
- `LocalMemory` is a test double with the same interface, so the pipeline is unit-testable without a network. It is not
  a substitute for Hindsight: no extraction, consolidation, temporal reasoning or mental models.

```
precedent/
  matching.py   deterministic 3-way match + exception measurement
  memory.py     Hindsight adapter (bank, retain, recall, directives, mental models, reflect) + test double
  agent.py      decide → guardrails → learn; payable maths; LLM prompt
  llm.py        Groq/OpenAI-compatible JSON client with repair + fallbacks
  session.py    inbox stream, clerk simulator, grading, KPIs
  api.py        FastAPI endpoints + static UI
web/            single-page workbench (vanilla JS, no build step)
data/           vendors, POs, GRNs, invoices, AP lead's recorded decisions
scripts/        generate_data.py, run_benchmark.py
tests/          offline test-suite
docs/           Hindsight write-up, benchmark, content (article, LinkedIn, video script)
```

## Why this is a business, not a demo

- **Buyer:** AP managers and shared-services leads at companies processing 2k-50k invoices a month.
- **Value:** at 4% exceptions × 18 min, a 10k-invoice/month company spends **120 clerk-hours a month** on exceptions.
  Automating the repeat ones saves most of that. Precedent also catches duplicates, short-shipments and GST
  place-of-supply errors, and captures early-payment discounts that are otherwise missed.
- **Path to adoption:** read-only first (the agent drafts, humans click accept), then auto-resolve per vendor once
  its precedents have a clean override record. Plugs into Tally / SAP / Zoho Books exports, so no rip-and-replace.

## Built with

[Hindsight](https://hindsight.vectorize.io/) by Vectorize ·
[What is agent memory?](https://vectorize.io/what-is-agent-memory) ·
Groq (`openai/gpt-oss-120b`, `qwen/qwen3-32b`) · FastAPI · vanilla JS

Team: Chetana Reddy ([@Chetanareddy18](https://github.com/Chetanareddy18))
