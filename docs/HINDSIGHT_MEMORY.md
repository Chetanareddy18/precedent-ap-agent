# How Precedent uses Hindsight memory

Precedent's value depends entirely on memory. With recall switched off, the same agent, prompt, model and
guardrails route **every one of the 25 exceptions** in the demo inbox to a human, because it has no
precedent to cite. With [Hindsight](https://github.com/vectorize-io/hindsight), the repeat exceptions resolve themselves,
and the ones that *look* like repeats but aren't get caught.

## 1. One bank per AP desk, tuned for accountants

```python
# precedent/memory.py
await self.client.acreate_bank(
    bank_id=self.bank_id,
    name="Godavari AP — exception memory",
    mission=BANK_MISSION,             # "track how each vendor's exceptions were resolved ... every condition,
                                      #  limit, threshold, effective date or contract clause"
    retain_mission=RETAIN_MISSION,    # tells fact extraction to keep caps / tolerances / dates / clauses
    disposition_skepticism=5, disposition_literalism=4, disposition_empathy=2,
    enable_observations=True,
)
```

A cap of ₹3,000 means ₹3,000. High skepticism and literalism make reflect answers conservative, which is what an
AP desk wants.

## 2. retain: every resolved exception, with its reason

When a clerk resolves an exception (or confirms/overrides the agent), `APAgent.learn` retains one memory:

```python
await self.memory.retain(
    text,                                           # vendor, invoice, exceptions (measured), outcome, basis, REASON
    timestamp=datetime.combine(inv.received_on, dtime(11, 0)),   # when it happened, for temporal reasoning
    tags=["vendor:V001", "exc:unplanned_charge", "outcome:approve", "source:clerk"],
    metadata={"action": "approve", "basis": "full", "codes": "unplanned_charge", "m_unplanned_charge": "2400", ...},
    document_id="resolution-INV-001",               # idempotent: re-resolving upserts, never duplicates
    context="AP invoice exception resolution",
)
```

Example of what gets retained (verbatim from the app):

```
AP exception resolution, 05 Jul 2026. Vendor Deccan Steel & Wire Pvt. Ltd. (V001). Invoice DSW/26-27/0412 dated
03 Jul 2026 against PO-45012, total ₹250,632.
Exceptions: unplanned_charge: Freight & unloading (Medchal → Plant 2) of ₹2,400 is not on PO-45012
Outcome: APPROVE — payable ₹250,632 (basis: full). Resolved by Priya Nair (AP Lead).
Reason: Deccan's rate contract (clause 7.2) lets them bill freight separately, capped at ₹3,000 per delivery.
₹2,400 is inside the cap — approve. Anything above ₹3,000 needs procurement sign-off.
```

The **reason** carries most of the value, not the outcome. "Approve" alone would teach the agent to approve all freight.
"Approve because it's under the ₹3,000 cap" teaches it when *not* to approve.

Three kinds of retained experience:

| source tag | when | why it matters |
|---|---|---|
| `source:clerk` | a human resolved an escalated exception | new knowledge |
| `source:agent` | the agent auto-resolved and the clerk confirmed | reinforcement, raises confidence |
| `source:override` | the agent auto-resolved and the clerk **overrode** it | a correction that is recalled next time, so the agent doesn't repeat the mistake |

## 3. recall: two scoped queries per invoice

```python
# precedent/agent.py  (decide)
results = await asyncio.gather(
    self.memory.recall(q,  tags=[f"vendor:{vendor.vendor_id}"],   scope="vendor"),   # citable precedents
    self.memory.recall(pq, tags=[f"exc:{c}" for c in codes],     scope="pattern"),  # hints from other vendors
    self.memory.directives(),
)
```

Both use `tags_match="any_strict"`, so untagged or other-vendor memories never leak into the vendor scope.
The split matters because **contracts differ per vendor.** In the demo, Krishna Polymers bills freight exactly like
Deccan Steel, but Krishna's PO is FOR-destination, so freight is already in the price. The pattern hint appears in the UI,
but the guardrail refuses to auto-resolve on another vendor's precedent. A human decides, and that decision becomes
Krishna's own precedent.

Recalled memories reach the LLM with their dates relative to the invoice:

```
PRECEDENTS FROM THIS VENDOR'S HISTORY (Hindsight memory):
  [P1] (05 Jul 2026, 33 days before this invoice) AP exception resolution ... capped at ₹3,000 per delivery ...
```

The model must list the checks it made (`freight ₹2,750 ≤ ₹3,000 cap (P1)`) and the precedent ids it relied on.
The guardrail verifies that at least one **same-vendor** id was cited before the agent may act alone.

## 4. directives: turning a note into policy

The clerk form has a *"Make this a standing policy"* checkbox. When ticked, the note becomes a Hindsight directive:

```python
await self.client.acreate_directive(bank_id=..., name="Vertex Office Supplies — bank change",
                                    content="Never pay to changed bank details until verified by a call-back ...",
                                    priority=10, tags=["vendor:V005", "exc:bank_change"])
```

Directives are listed on every decision and override precedents in the prompt. (Bank changes also have a hard-coded
control. Memory adds context such as *"second attempt, same pattern as 20 Jul"*, but it never unlocks the payment.)

## 5. mental models: a living vendor playbook

After the first resolution for a vendor, Precedent creates a mental model scoped to that vendor's tag:

```python
await self.client.acreate_mental_model(
    bank_id=..., id="playbook-v001", name="Vendor playbook — Deccan Steel & Wire Pvt. Ltd.",
    source_query="How does our AP team handle invoice exceptions from Deccan ... every limit, threshold, "
                 "effective date or condition that changes the outcome.",
    tags=["vendor:V001"], trigger={"refresh_after_consolidation": True},
)
```

Hindsight re-synthesises it as new memories consolidate. It's the page you'd hand a new AP hire, and the UI's
**Vendor playbook** panel reads it live.

## 6. reflect: questions over the whole history

The **Ask your AP memory** box calls `reflect`, which reasons across every retained resolution:

- *"Which vendors have recurring invoice exceptions, and what is our standing resolution for each?"*
- *"What caps, tolerances and effective dates govern auto-approval for each vendor?"*
- *"Summarise every attempted bank-detail fraud and how it was caught."*

## 7. What improves over time

| Interaction | Behaviour |
|---|---|
| 1st exception from a vendor | No precedent. Routed to a human with a generic suggestion. The decision and reason are retained. |
| 2nd, same habit, within limits | Recalls the precedent, checks the condition, **auto-resolves and cites it**. |
| 2nd, same habit, **outside** limits | Recalls the precedent, sees the condition fail (₹6,800 > ₹3,000 cap, FX 3.6% > 2%), **escalates** with a precise suggestion. |
| Same exception, **different vendor** | Shows the pattern as a hint and refuses to generalise. |
| Agent wrong, clerk overrides | The override is retained as a correction and recalled next time. |
| Standing rule | A directive applies to every future decision. |

## 8. Failure modes we designed for

- **Hindsight unreachable:** recall errors are caught, so there are no precedents and every exception goes to a human (fail-safe).
- **LLM unreachable / bad JSON:** repair retry, then fallback model, then deterministic heuristic that follows the most
  recent same-vendor precedent only if the magnitude is within what was accepted before.
- **Memory can't unlock hard controls:** bank changes and missing POs are always human.

Learn more about [agent memory](https://vectorize.io/what-is-agent-memory) and the
[Hindsight docs](https://hindsight.vectorize.io/).
