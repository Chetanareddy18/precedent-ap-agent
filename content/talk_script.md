# Precedent — What to Say (Video, Live Demo, Q&A)

Speak naturally. Don't read word for word. **Bold** = what to click. *Italic* = what to point at.

**Before you start:** run `uvicorn precedent.api:app --port 8000`, open http://localhost:8000, zoom the browser to 110%,
turn off notifications, click **Reset** twice (memory wiped).

---

## A. 30-second elevator pitch (use to open anything)

"Every company pays vendors only after matching the invoice, the purchase order and the goods receipt. When they don't
match, a senior clerk spends 15 minutes figuring it out, and most of the time it's the *same vendor doing the same
thing again*. That knowledge lives in one person's head.

We built **Precedent**, an accounts-payable agent with Hindsight memory. It remembers *why* the team resolved each
exception: the cap, the tolerance, the effective date. So the next time, it checks those conditions and resolves the
invoice by itself, citing the precedent. And when a condition fails, it knows to call a human."

---

## B. 3-minute YouTube video script

### 0:00–0:30 · Intro (face on camera + app)
"Hi, I'm Chetana. This is Precedent, an AP agent that resolves invoice exceptions the way your team resolved them last
time. AP teams waste hours on exceptions that are really reruns, and a normal chatbot forgets everything, so it can't help."

### 0:30–1:00 · The problem: no memory
**Toggle Hindsight memory OFF → Next invoice** → open Deccan Steel.
"Deccan billed ₹2,400 of freight that isn't on the purchase order. Without memory the agent says: hold it, ask for a PO
amendment. That's textbook, and it's wrong for us, because Deccan's contract allows freight up to ₹3,000. Without memory,
every single exception lands on a human, 25 out of 25."

### 1:00–2:30 · The demo: retain → recall
**Toggle memory ON → Next invoice** (Deccan). Type the reason in *Why?*:
"Clause 7.2 allows freight up to ₹3,000 per delivery" → **Resolve & retain**.
"The decision *and my reason* go into Hindsight, tagged with the vendor and the exception type." *Point at the green
Retained box and the feed on the right.*

**▶ Autopilot**, pause at invoice #11 (Deccan ₹2,750).
"Five weeks later Deccan does it again. *Recalled from Hindsight*: my July note, 33 days earlier. The agent checked
₹2,750 against the ₹3,000 cap and approved it by itself, and it cites the precedent."
**Compare without memory** → "Same model, memory off: hold it. Memory on: approved with proof. That's the difference."

Continue to **#14 Apex**: "Same 6% price rise that we short-paid in July. But my reason said the new rate starts
1 August. This invoice is 10 August, so it approves. Copying the old decision would have been wrong."

**#20 Deccan ₹6,800**: "Over the cap, so it escalates and suggests paying exactly ₹3,000."
**#24 Krishna**: "Same exception, different vendor. It shows the pattern as a hint but refuses to generalise another
company's contract."
Finish autopilot. *Point at the chart*: "The orange line is without memory. The blue line is with Hindsight. They split
apart as the agent learns."
**Ask your AP memory → Caps & tolerances**: "And I can ask the memory itself. Hindsight reflects over every past decision."

### 2:30–3:00 · Takeaway
"What surprised me: when I stored only the *decision*, the agent copied it blindly. When I stored the *reason*, with
the cap and the date inside, it became careful. Memory isn't just remembering. It's remembering why. Code's on
GitHub, link below."

---

## C. 5-minute live demo for judges

| Time | Say | Do |
|---|---|---|
| 0:00 | Elevator pitch (section A) | App open, empty inbox |
| 0:40 | "Let me show you the first day, with no memory." | **Next invoice** → Deccan freight. Point at the 3-way match table (red "not on PO"), the exception, and "No precedent for this vendor yet". |
| 1:10 | "I'm the AP lead. I resolve it and say why." | Type the clause 7.2 note → **Resolve & retain**. Show the retained memory. |
| 1:40 | "Now let's fast-forward twelve weeks of invoices." | **▶ Autopilot**. Talk over it: "Each human decision is being retained into Hindsight." |
| 2:20 | "Here's the payoff." | Click invoice **#11** in the inbox → cited precedent, checks, auto-resolved. |
| 2:50 | "And it's not copying." | Click **#14 Apex** (date logic), then **#20** (over cap → human). |
| 3:30 | "Fraud." | Click **#17 Vertex** → hard control, directive from the AP lead's note. "Memory adds context but can never unlock a payment." |
| 4:00 | "Results." | Chart + KPIs: human touches with vs without memory, hours saved, ₹ protected. |
| 4:30 | "And memory you can question." | Reflect chip, then **Vendor playbook → Deccan** (mental model). |
| 4:50 | Close | "Precedent: invoice exceptions resolved the way your team did last time. Built on Hindsight." |

**If something breaks live:** stay calm, open an already-processed invoice from the inbox (the detail is stored), or
show the README screenshot. Say: "The LLM is rate-limited right now, so the agent falls back to a deterministic safe mode
and everything goes to a human. That's by design."

---

## D. Judge Q&A: likely questions and good answers

**Q: How is this different from other AP agents that also use memory?**
A: Most store the *outcome* and recall similar events. We store the *reason* with its conditions and make the model
check them (₹2,750 ≤ ₹3,000). Recall is split into citable same-vendor precedents and hint-only patterns, and a
guardrail verifies the citation. Clerk notes can become Hindsight directives, and each vendor gets a mental-model playbook.

**Q: What if the memory is wrong or outdated?**
A: Overrides are retained as corrections tagged `source:override`, so the next recall includes them. Effective dates live
inside the reasons and the agent compares them with the invoice date. And the agent needs confidence ≥ 0.75 plus a
same-vendor citation to act alone.

**Q: Why not just write rules?**
A: Rules need an engineer every time a vendor changes a habit. Here the AP clerk teaches the agent in plain English
while doing their normal job. The deterministic part (matching and money) *is* rules; the judgment part is memory.

**Q: Can the LLM make a payment mistake?**
A: It never computes money. It chooses a payable basis and the code calculates the amount (tests verify every
amount). Bank changes and missing POs always need a human.

**Q: What happens if Hindsight or Groq goes down?**
A: If recall fails there are no precedents, so everything goes to a human (fail safe). If the LLM fails, it repairs the JSON,
tries a fallback model, then uses a deterministic heuristic.

**Q: Is the data real?**
A: It's synthetic but realistic: Indian GSTINs, HSN codes, IGST vs CGST+SGST place-of-supply, bundle-vs-unit billing,
FX on cloud invoices, "-R" duplicate resubmissions, bank-change fraud. These are real AP problems.

**Q: Who would pay for this?**
A: AP managers at mid-size companies with 2k–50k invoices a month. At 4% exceptions × 18 minutes, 10k invoices is
about 120 clerk-hours a month. Start read-only, then turn on auto-resolve per vendor.

**Q: Which Hindsight features did you use?**
A: Bank with mission and disposition, retain with timestamps, tags, metadata and document IDs, tag-scoped recall
(`any_strict`), directives, mental models with refresh-after-consolidation, and reflect.

**Q: What was the hardest part?**
A: Stopping the agent from over-generalising. The first version copied decisions. Storing reasons and separating
same-vendor precedents from cross-vendor hints fixed it.

---

## E. Project name options

| Name | Why |
|---|---|
| **Precedent** (current, recommended) | Legal/accounting idea of "decided before, cited now". Matches the core feature and is already on GitHub. |
| LedgerLore | The tribal knowledge of the ledger |
| ClauseKeeper | Remembers the contract clauses clerks rely on |
| Rerun | "Most exceptions are reruns" |
| APrecedent | AP + precedent, very searchable |
| Tally Memory | Nod to India's Tally ERP |
| SecondTime | "The second time a vendor does it, the agent handles it" |

Recommendation: **keep "Precedent"**. It's distinct from other teams' names (for example, "LedgerMind"), it describes the
innovation, and the repo, article and posts already use it.
