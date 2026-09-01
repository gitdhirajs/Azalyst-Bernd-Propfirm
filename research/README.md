# research/ — the audit trail behind the engine

This is the measurement work that produced the flags and defect fixes in
`Propfirm Trading Dashboard/`. It is evidence, not runtime code: nothing here is imported
by the scanner.

## Read in this order

| file | what it is |
|---|---|
| `RUN.md` | **the commands to run, and what they will and will not do**. Start here. |
| `HOLDOUT_RESULTS.md` | out-of-sample results, 2024-04-01 → 2026-08-25 |
| `audit/CODE_FINDINGS.md` | the technical record, C-01 … C-127. Every claim with its sample size. |
| `PASTE_THIS_TO_CLAUDE.md` | handoff prompt for continuing the work |
| `SESSION_2026-08-*.md` | per-session narrative |

## The state of the system, in one paragraph

Direction accuracy is **52.75%** on 510 cases against **50.39%** for answering "long"
every time (p=0.279, not significant). Stage-1 accuracy is arithmetically closed: a
lookup table memorising the best answer for every combination of the bias components
caps at 71.4% **in-sample**, and out-of-sample a search over 575 feature subsets across
three independent families returns a best result of **−0.47 points versus a constant**.
**Nothing in this project is statistically significant** — the one result that reached
p<0.05 was inflated by duplicate readings of a single position tool and is 4:0, p=0.125
once collapsed (C-127). Five engine flags are implemented and **all default OFF**; none
has passed `goldtest/verdict.py`.

## Why the tooling looks paranoid

Every false positive in this project passed at least one honest-looking test:

- *"74/160 on the goldtest"* — in-sample, ~20 tuning phases against those very cases
- *"+0.60R at market"* — the sample was 33 of 34 long in 2023; that is drift, not edge
- *"midpoint entry helps"* — a different trade population, not a different entry
- *"level_on_top is dead"* — measured on a call site that never trades
- *"their entries beat market, p=0.039"* — one position tool re-read seven times

So `goldtest/verdict.py` runs four gates together and reports the **weakest**. A change is
only as real as its worst test.

## gemini/

Vision tooling that read 10,700+ course and session frames to extract what the trader
actually drew and stated. `keys.local.json` is **not** in this repository and must never
be — the tools read it from disk at runtime, or from the `GEMINI_API_KEYS` environment
variable.

Two hard-won rules live in these files:

- **A drawn zone is not a trade** (C-115). Zones merely marked on a chart measure 18
  points *below* a drift-matched null; only zones committed to with a position tool beat
  it. Never pool the two.
- **Never pool corpora** (C-117, C-122). `signals` (issued) runs +9.6 points versus its
  null while `weekly` (anticipated) runs −13.0. Merging them — the obvious move for
  sample size — cancels the only positive signal in the project.
