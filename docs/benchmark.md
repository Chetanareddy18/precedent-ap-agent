# Memory OFF vs ON — replaying 12 weeks of the AP inbox

`python scripts/run_benchmark.py` replays all 29 invoices (25 exceptions) twice, with the simulated AP lead responding
with the decisions recorded in `data/clerk_ground_truth.json`. Raw output goes to `docs/benchmark.json`.

## Deterministic baseline (`--offline`: LocalMemory test double + heuristic, no LLM)

| metric | memory OFF | memory ON |
|---|---:|---:|
| exceptions | 25 | 25 |
| human touches | **25** | **18** |
| auto-resolved correctly | 0 | 7 |
| wrong auto-decisions | 0 | 2 |
| accuracy (right route + right action) | 0.56 | 0.84 |
| clerk minutes saved | 0 | 126 |

The two wrong auto-decisions are the reason the LLM is in the loop. The heuristic copies *"same vendor, same exception,
magnitude within range → same action"*:

- **INV-014 Apex**: copies July's short-pay, but the recalled reason says the new price is *effective 1 Aug* and this
  invoice is dated 10 Aug. The correct action is approve.
- **INV-027 Deccan**: copies September's capped short-pay onto a ₹2,900 freight that is *within* the ₹3,000 cap.

With Hindsight + the LLM, the agent reads the reason in the recalled memory and checks the condition, so these two
become correct auto-resolutions.

## Live stack (Hindsight + LLM)

Run `python scripts/run_benchmark.py` with your `.env` configured. It writes `docs/benchmark.json`, which has the
per-invoice timeline used by the UI's learning-curve chart.
