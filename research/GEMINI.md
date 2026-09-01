# GEMINI.md — context for the Gemini CLI on the Bernd audit

Gemini CLI auto-loads this file. It is the Gemini-side mirror of
`PASTE_THIS_TO_CLAUDE.md`, which stays the canonical brief. If the two ever
disagree, `PASTE_THIS_TO_CLAUDE.md` wins and this file is stale — say so
instead of guessing.

## What this project is

We are checking a Python prop-firm trading system
(`D:\Trading\Azalyst Bernd Skorupinski\Propfirm Trading Dashboard\`) against the
calls made by Bernd Skorupinski and three Online Trading Campus instructors
working under him (Jan Skorupinski, Clemens Winkler, Chris Dietenberger). They
all teach HIS method with HIS indicator pack. Decided 2026-08-26 by the user:
score against ALL FOUR POOLED (479 cases), not Bernd alone.

The user lost 2 prop-firm challenges trusting earlier "verified / 100% correct"
claims that were not actually verified. **Never tell him something is correct.**
State what was measured, on how many samples, and what it got wrong. Every claim
carries its sample size. A claim with no sample size is not a claim.

## Read before answering anything substantive

```
D:\Trading\Claude for Bernd\PASTE_THIS_TO_CLAUDE.md          <- the canonical brief
D:\Trading\Claude for Bernd\SESSION_2026-08-26.md            <- current state; OPEN list in section 11
D:\Trading\Claude for Bernd\audit\CODE_FINDINGS.md           <- C-01..C-87 with evidence
D:\Trading\Azalyst Bernd Skorupinski\Propfirm Trading Dashboard\goldtest\PRESENTER_AND_HONEST_SCORE.md
```

`NEXT_WEEK_START_PROMPT.md` and `RESUME_NEXT_SESSION.md` are **SUPERSEDED**.
Both still contain a "paste this to Claude" block. Do not follow either block.

`D:\Trading\Azalyst Bernd Skorupinski\CLAUDE.md` and `AGENTS.md` are the deep
technical reference for the code, and they are also the largest source of stale
claims in the project. Their goldtest numbers (Stage-1 ~61.5%, Stage-2 13/160,
"zero false positives", "production-safe") are **in-sample** — see below. Use
those files for how the code works, never for how well it works.

## The measured state, out of sample, 479 pinned cases

- **Stage 1 (direction): no demonstrable edge over a constant "always long".**
  Bernd rows 176/339 = 51.9% vs always-long 47.8%, McNemar p=0.279.
  Instructors 79/140 = 56.4% vs always-long 62.1%, p=0.341.
- **Stage 2 (execution):** fired 8 times in 472 cases (1.7%) — but 3 of those 8
  were `entry == stop == every target` (PL=F 1010.0), i.e. **zero-risk orders that
  cannot be traded**. C-88 guards them, so the real count is 5 in 479, all LONG. It
  has never produced a short out of sample. A walk-forward over 546 symbol-weeks
  fired 3 times (0.55%).
- **"Zero Stage-2 false positives" is an IN-SAMPLE property. Do not repeat it.**
- **Trade outcomes are measurable now** — `goldtest/replay_trades.py` drives the real
  `PaperTrader` bar-by-bar over pinned bars. E-03 on it: both filled trades scratched
  at 0.00R with `breakeven_at_half_target` ON, reached T3 (+3.00R each) with it OFF.
  n=2 and **both path-ambiguous**, so the direction is established and the magnitude
  is not. Default not flipped.
- Root cause of the flatness: Valuation is silent on 64% of cases, COT on 73%,
  both on 45%. On half the corpus the two decisive indicators contribute nothing.
- **Hard ceiling — do not try to tune past it.** The ground truth contradicts
  itself: Bernd shorts an equity index on 3 of 71 index calls (4%), Jan/Clemens
  on 14 of 30 (47%). 48 agreements and 11 direct contradictions on the same
  symbol within 10 days. No deterministic rule set can match both sides.
- **The indicators are not the problem.** They reproduce Bernd's lecture frames
  exactly (COT 85.10 / 18.10 / 74.56). The bias-consensus rule layer on top is
  what has no measured out-of-sample skill.

## Rules of work — learned the hard way, do not skip

1. Never score a hypothesis only on the rows the engine got wrong. That
   guarantees any alternative wins. It falsely "proved" C-63 and C-68.
2. Use `goldtest\ab_paired.py` for every A/B — paired, case-level, McNemar. Raw
   percentages are unsafe: runs differ in how many cases error out (31 vs 35), so
   a ±2 delta can be pure attrition.
3. Compare arms that differ in ONE variable.
4. Every experimental change goes in as a flag, **default OFF**. Measure, then
   decide. Ten hypotheses tested this way; nine rejected.
5. After applying any flag, re-run with NO env vars and confirm 0 rows differ.
   "Applied" is not "active".
6. Grounding in what the traders say/do raises the prior. It does not replace the
   measurement. C-87 had 219 frames behind it and still failed.
7. Before trusting a finding in a session note, check it against the code and the
   git log. E-03's headline claim did not survive that check.
8. Parse timestamps. `str(ts)[:10] < '2026-07-27'` on "19 Jul 2026 22:11" compares
   the string "19 Jul 202" and gave a confident, exactly-backwards answer.
9. Never treat a value eyeballed off a video still as a parameter. Require
   agreement across model reads. "@SOXY" sat in CLAUDE.md for months as an
   unidentified symbol; across 4,446 frame reads that slot is "$DXY" 1081 times
   and "@SOXY" 7 times. It was OCR noise.

## How anything gets measured

```
cd "D:\Trading\Azalyst Bernd Skorupinski\Propfirm Trading Dashboard\goldtest"
for i in 0 1 2 3 4 5; do
  MYFLAG=1 python -u run_goldtest.py --cases-file full_shard$i.yaml \
    --cot-snapshot read --ohlcv-snapshot read --output myarm$i.json > myarm$i.log 2>&1 &
done
python ab_paired.py 'c88guard?.json' 'myarm?.json'   # c88guard = current-default baseline
python score_by_presenter.py 'myarm?.json'
```

Snapshots are PINNED — CFTC revises history and Yahoo re-splices. Two unpinned
runs of identical code scored 54.2% and 51.7%: ~2.5pp of noise, larger than most
effects tested. Six shards take ~50 minutes; run them in the background.

## Your role alongside Claude

Claude Code drives the session, owns the code edits, and owns the A/B decisions.
You are the second reader. What you are good for here:

- **Bulk reading.** 1M-token context. `CLAUDE.md` is 197KB, `CODE_FINDINGS.md`
  227KB, `audit/per_chapter/` is 52 files. You can hold them at once; Claude
  cannot without summarising, and summarising is where claims lose their sample
  sizes.
- **Independent cross-checks.** When Claude asserts a finding, re-derive it from
  the primary file and report agreement or disagreement — do not restate it.
- **Frame reads.** `gemini/vision_pass.py` and `gemini/gemini_vision.py` are the
  existing pipeline. A single read is never evidence; require agreement across
  reads, per rule 9.
- **Grepping for stale claims** across the doc set.

What you must NOT do without the user saying so: edit code in
`Propfirm Trading Dashboard\`, flip a config default, or run a goldtest arm that
overwrites an existing `*.json` results file.

## API reality, checked 2026-08-26

Both keys in `gemini/keys.local.json` are free-tier. Pro models
(`gemini-3.1-pro-preview`, `gemini-pro-latest`, `gemini-2.5-pro`) return **429 —
no free quota**. Working models:

| model | acct-A | acct-B | context |
|---|---|---|---|
| `gemini-3.7-flash` | yes | rate-limited | 1M |
| `gemini-3.5-flash` | yes | yes | 1M |
| `gemini-3-flash-preview` | rate-limited | yes | 1M |
| `gemini-2.5-flash` | yes | 404 (retired for this key) | 1M |

`acct-A`'s key is flagged for rotation in `SESSION_2026-08-26.md` §11.
`keys.local.json` is gitignored. Do not print either key.

**Before blaming the API for being slow, check C-91.** The `GeminiFrameBacklog`
scheduled task fires every 30 minutes for 3650 days on backlogs that are 100%
complete, spending these same two keys. It is why a one-word call took 196 seconds
in this project and why the pro models 429.
