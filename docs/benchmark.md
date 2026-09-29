# Memory OFF vs ON — replaying 12 weeks of the AP inbox

`python scripts/run_benchmark.py` replays all 29 invoices (25 exceptions) twice, with the simulated AP lead responding
with the decisions recorded in `data/clerk_ground_truth.json`. Raw output: `docs/benchmark.json`.

## Live stack: Hindsight Cloud + Groq `openai/gpt-oss-120b`

| metric | memory OFF | memory ON |
|---|---:|---:|
| exceptions | 25 | 25 |
| human touches | **25** | **15** |
| auto-resolved correctly | 0 | **10** |
| wrong auto-decisions | 0 | **0** |
| accuracy (right route + right action) | 0.56 | **0.96** |
| clerk minutes saved (18 min / exception) | 0 | 180 |

Same model, same prompt, same guardrails. The only difference is Hindsight recall.

### Invoice by invoice (memory ON)

```
INV-001 05 Jul Deccan Steel      unplanned_charge        → human      (first time: no precedent)
INV-011 07 Aug Deccan Steel      unplanned_charge        ✔ auto       approve  (₹2,750 ≤ ₹3,000 cap)
INV-012 10 Aug Sharma Packaging  uom_mismatch            ✔ auto       approve  (100 BDL = 1,200 NOS)
INV-013 14 Aug Nimbus Cloud      fx_variance             ✔ auto       approve  (1.81% ≤ 2% band)
INV-014 12 Aug Apex Chemicals    price_variance          ✔ auto       approve  (dated after 1 Aug effective date)
INV-017 23 Aug Vertex            bank_change             → human      (hard control)
INV-018 27 Aug Coastal Freight   duplicate_suspect       ✔ auto       reject   (-R resubmission)
INV-019 30 Aug Nimbus Cloud      fx_variance             → human      (3.61% > 2% band)
INV-020 03 Sep Deccan Steel      unplanned_charge        → human      (₹6,800 > ₹3,000 cap; suggests short-pay)
INV-021 06 Sep Hyderabad Elec.   received_short          ✔ auto       short-pay to GRN qty
INV-022 10 Sep Metro Facility    tax_type_mismatch       → human      (safe miss: could have been auto)
INV-023 12 Sep Sunrise Agro      early_payment_discount  ✔ auto       pay early, 2% captured
INV-024 14 Sep Krishna Polymers  unplanned_charge        → human      (other vendor's precedent = hint only)
INV-025 17 Sep Sharma Packaging  uom_mismatch            ✔ auto       approve
INV-026 20 Sep Apex Chemicals    price_variance          ✔ auto       approve
INV-027 24 Sep Deccan Steel      unplanned_charge        ✔ auto       approve  (₹2,900 ≤ cap, despite the capped #20 precedent)
INV-029 27 Sep Vertex            bank_change             → human      (hard control, third attempt)
```

What a stateless agent said (memory OFF, same model): Deccan freight → *"short-pay, strike the freight"*; Sharma bundles → *"hold"*;
Apex +6% → *"hold"*; Coastal `-R` → *"hold"*. All defensible in general, and all wrong for this company.

## Deterministic baseline (`--offline`: LocalMemory test double + heuristic, no LLM)

| metric | memory OFF | memory ON |
|---|---:|---:|
| human touches | 25 | 18 |
| auto-resolved correctly | 0 | 7 |
| wrong auto-decisions | 0 | **2** |
| accuracy | 0.56 | 0.84 |

The heuristic ("same vendor, same exception, magnitude within range → same action") makes the two mistakes the LLM avoids:

- **INV-014 Apex**: copies July's short-pay, but the recalled reason says the new price is *effective 1 Aug*.
- **INV-027 Deccan**: copies September's capped short-pay onto a ₹2,900 freight that is *within* the cap.

Reading the reason in the recalled memory, instead of copying the label, is the difference.
