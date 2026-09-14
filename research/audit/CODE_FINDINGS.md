# Code findings (Opus lane — runs in parallel with the Sonnet frame readers)

## Canonical PineScript sources (ground truth — use these, not label-reading)
| indicator | file | formula / defaults |
|---|---|---|
| Valuation | `Bernd_Skorupinski Campus Blueprint OTC/OTC Tradingview Indicator Pack/Valuation_OTC.txt` | 3 refs DXY/GC1!/ZB1!, `Length=10`, `RescaleLength=100`, hlines +/-75. **No Show flags in this version.** |
| COT Index (OTC) | same pack, `COTIndex_OTC.txt` | `100 * (net-min)/(max-min)` -> **range 0..100**, `weeks=26`, upper 80 / lower 20 |
| COT Index (V2) | `Azalyst Bernd Skorupinski/pinescript/COT V2 120-20.txt` | `140 * (net-min)/(max-min) - 20` -> **range -20..120**, adds YELLOW hlines at **120 and -20** |
| COT Report | `.../COTReport_OTC.txt` | raw contract counts, shorts negative |
| Seasonality | `.../Seasonality_OTC.txt` | (not yet reviewed) |

This is a much stronger validation route than reading truncated title-bar labels: the Pine gives
the exact formula, the frames give actual plotted VALUES on a known date, so the two can be
reconciled numerically. Adopted as the primary method going forward.

Findings here are derived from reading the Python itself, cross-checked against the
vision audit. Each is tagged with what evidence it rests on, because the two lanes
have very different reliability:
  - **CODE-PROVEN** = demonstrable from the source + a reproducible test. Does not
    depend on any frame reading being correct. Safe to act on.
  - **FRAME-DEPENDENT** = needs N chapters of corroboration before touching code.
    See the Phase 33 -> Phase 41 revert in `run_scanner.py:213` for what happens
    when a single frame reading gets shipped.

---

## C-01 — Valuation ROC index misalignment (CODE-PROVEN, HIGH severity, crypto-scoped)

**File:** `BP_indicators.py`, `Valuation.calculate`, lines 731 / 750 / 753.

**The defect.** `sym_perc` is computed over the symbol's FULL index (line 731), but
`ref_perc` is computed over ONLY `common_idx` (line 750). Line 753 then subtracts
them. When the symbol and the reference trade on different calendars, `common_idx`
is a strict subset of the symbol index, so the two ROC series measure **different
spans of time**:

```
sym_perc window = 10 symbol bars = 10 calendar days
ref_perc window = 10 common bars = 14 calendar days
   -> a 10-day move is being differenced against a 14-day move
```

**Smoking gun:** line 748 assigns `sym_close = df.loc[common_idx, 'close']` and then
never uses it. That variable is exactly what line 731 should have been computed from.
The intent was right; the wiring was not.

**Proof it is not cosmetic.** A constant offset would be cancelled by `_rescale`'s
rolling min/max normalisation, so the test measures the FINAL rescaled lines and the
resulting `get_bias()` verdict on volatile random-walk data (200 trials):

| scenario | bias verdict differs |
|---|---|
| crypto-like symbol (7d/wk) vs weekday refs | **55/200 = 27.5%** |
| futures symbol (5d/wk) vs weekday refs | 0/200 = 0.0% |

Latest-value line shift on the crypto case: mean 27.5, median 22.8, p95 65.5, max 85.8
on a -100..+100 scale whose decision thresholds are +/-10 and +/-75. Observed flips
include full reversals (`bullish` -> `bearish`).

**Scope.** Only bites where the calendar mismatch is real:
  - **crypto — materially affected** (BTC/ETH etc. trade 7d/wk; DXY, ZB, GC do not)
  - futures/index/equities/forex vs weekday refs — **0% change**, same calendar
So this is a crypto-accuracy bug, not a system-wide one. That also means the fix is
low-risk: it provably cannot alter any same-calendar symbol's output.

**Fix** (compute both legs on `common_idx`; deletes the dead variable's reason to exist):

```python
            ref_close = ref_df_indexed.loc[common_idx, 'close']
            sym_close = df.loc[common_idx, 'close']

            ref_perc = (ref_close - ref_close.shift(self.length)) / ref_close.shift(self.length) * 100
            sym_perc_c = (sym_close - sym_close.shift(self.length)) / sym_close.shift(self.length) * 100

            # Difference: symbol %change minus reference %change
            diff = sym_perc_c - ref_perc
```

(and line 731's full-index `sym_perc` becomes unused — remove it.)

**Status: APPLIED** (BP_indicators.py, `Valuation.calculate`). Implemented the Pine-faithful
version — reference reindexed onto the symbol index with `ffill()`, both ROCs then taken on that
single index — NOT the `common_idx` intersection I first proposed (which would have deleted the
symbol's weekend bars; see C-01 REFINEMENT below).

Verification (`scratchpad/verify_c01.py`):
  - **Regression: `max |new - old| = 0.0000000000`** over 100 trials of same-calendar symbols.
    Futures / equities / forex / metals are bit-identical. The change cannot affect them.
  - Intended fix active: crypto bias verdict changed vs old code in 18/100 trials.
  - Same-calendar self-reference still collapses to all-NaN, preserving C-02 behaviour.
  - One test assertion of mine initially "failed": I expected a weekday-sampled reference of an
    identical price path to give diff==0 against a 7d/wk symbol. That expectation was wrong, not
    the patch — a weekday reference cannot track weekend moves, and Pine's `security()` returns
    the stale Friday close on weekend bars, producing exactly the same nonzero diff. Recording it
    here so nobody "fixes" the patch to satisfy a bad test later.

Git: repo is clean for this file, so `git diff BP_indicators.py` shows the change in isolation and
`git checkout -- BP_indicators.py` reverts it.
Repro scripts: `scratchpad/test_valuation_align.py`, `test_valuation_real.py`, `verify_c01.py`.

---

## C-02 — Valuation self-reference on GC=F (CODE-PROVEN, LOW severity, by-design-ish)

`VALUATION_REFS["precious_metals"] = ["DX-Y.NYB", "GC=F", "ZB=F"]`, so **GC=F is a
reference for itself**. Consequence chain, all verified:

1. `diff = sym_perc - ref_perc` is **exactly 0** at every bar.
2. `_rescale`: `rolling_min == rolling_max` -> `denom == 0` -> `np.where` yields **NaN**.
3. `get_bias`: `if pd.isna(v): continue` -> that line is **silently skipped**.
4. Net effect: **Gold's bias is decided by 2 lines while Platinum/Palladium use 3.**

This corroborates the CW41 vision note ("on the Gold chart the @GC line goes
flat/stepped") — TradeStation draws it flat at zero, Python drops it to NaN. Both
amount to "ignore that line", which is also how Bernd reads it, so the behaviour is
defensible. But it is **accidental, not designed**: it works only because a zero
denominator happens to produce NaN which happens to be skipped.

Note the aggregation asymmetry this creates: with n=2 the "all lines agree" branch
(`bull == n`) is easier to satisfy than with n=3, so Gold can reach a `strong`
verdict on 2 agreeing lines. Worth a deliberate decision rather than leaving it to
emerge from a NaN.

Also a wasted network fetch per scan (GC=F downloaded as its own reference).

**Recommendation:** don't change behaviour; make it explicit — skip a ref equal to the
symbol at fetch time, and document the 2-line vote for Gold. **NOT APPLIED.**

---

## C-03 — ZigZag "absence" is a corpus artifact — DO NOT ACT (resolved)

The vision audit found ZigZag % absent in 7/7 Weekly Outlook chapters, which looked
like evidence the code models an unused indicator. **It is not.** Every ZigZag setting
in `BP_rules_engine.py` cites a source, and none are Weekly Outlook:

| code | cited source |
|---|---|
| weekly 6% default (`:912`) | OTC Ch.012 |
| NG=F weekly 5% (`:920`) | Ch025 Energies **practical** |
| CL daily 5% (`:940`) | **Zone Qualifiers lesson** |
| SI=F weekly 10% (`:931`) | Ch.015 customize dialog |
| ES=F flat 5% (`:946`) | Chapter 012 **Module 2 Lesson 3** |

ZigZag lives in the Practical Application / OTC corpora. Its absence from live weekly
outlooks is expected — he uses the tool when teaching, not when narrating a week.
**Conclusion: leave ZigZag alone.** Re-examine only after the Practical Application
folder is audited.

---

## C-04 — Equities Valuation reference legs (NOW DIALOG-CONFIRMED — strong case to change)

Code: `VALUATION_REFS["equities"] = ["ZB=F", "GC=F"]` — Bonds + Gold ON, **DXY off**.

Evidence now spans **three independent chapters plus a Format Study dialog**:
  - CW04-2024: stock charts show ref2 (@GC Gold) disabled — `True,False,...`
  - CW41-2023: 7 stock symbols, only ref1 (@US) plotted; ref2 and ref3 appear off (medium conf.)
  - **CW05-2023: MSFT Format Study dialog (frame_001553) — `ShowReferenceSymbol3=False`**,
    plus ref1 `"@US"`=True / ref2 `"@GC"`=False consistently across **9** stock symbols
    (TSLA, AAPL, AMZN, META, GOOG, MSFT, NFLX, PFE, RACE). Futures/index in the same chapter:
    all True/True/True.

**Reading: individual stocks use BONDS ONLY.** The code disables the wrong leg — it keeps Gold
(which is off in every sighting) and drops DXY (also off, so that part is right by accident).

Caveat worth stating: the `Show*` flags govern *plotting*. But `get_bias()` is explicitly
written to mimic "Bernd visually reads each line against the threshold", so a line he cannot
see is a line he does not vote on — hidden should mean excluded here.

**CW43 (Equity Indices & Stocks Edition) corroborated it — 4th chapter:** ref1(@US)=True,
ref2(@GC)=**False** across 6 more stocks (AAPL/AMZN/GOOG/NVDA/TSLA/META). ref3 truncated on
stocks there, consistent with (not independently proving) the CW05 dialog. Same chapter confirms
**indices differ**: @ES/@NQ untruncated = all 3 refs True, Length=10 — so the code's
`equity_indices` entry is correct and only `equities` is in question.

Tally: **4 independent chapters, 20+ stock symbols, 1 Format Study dialog. Gold is OFF on stocks
in every single sighting.** This is well past the Phase 33 single-frame trap.

### BUT — this is a CROSS-CORPUS conflict, not a simple coding error
`run_scanner.py:197` records where the current value came from: *"Phase 36 multi-agent consensus:
**Ch173 (Practical App Valuation)** + Phase 32 Valuation rulebook + Phase 32 per-asset all agree
stocks use Bonds + Gold, DXY OFF."*

So: **Practical Application + rulebook say Bonds+Gold. Weekly Outlook says Bonds only.** Same
structural trap as C-03 (ZigZag) — two corpora, different answers, and we have only audited one.

Plausible reconciliation: teaching material shows the full 3-ref setup then narrows; live weekly
sessions run the trimmed config he actually trades. If so, the **live** config is what a signal
scanner should model. But that is a judgement call about which corpus is authoritative, and it
should be made deliberately — not silently by whichever audit ran most recently.

**Proposed:** `"equities": ["ZB=F"]`, with a comment recording the corpus conflict.
**NOT APPLIED** — needs an explicit decision on Weekly-Outlook-over-Practical-Application, and
ideally a look at Ch173 to see whether it was teaching narration or a live trade setup.

---

## C-06 — Campus Smart Money RAW has NO lookback parameter (CODE-PROVEN via source capture)

CW43 captured both a Format Study dialog **and the full EasyLanguage source** for
`Campus Smart Money RAW` (rare — a genuine gold-standard find). Result: its **only** input is
`FuturesOnly_Or_FuturesAndOptions_1_or_2` (=1). There is **no lookback/length parameter at all** —
it plots raw, unsmoothed CFTC COT net positions. CW02-2024-LIVE independently found the same study
is TradeStation's built-in "WA-COT Net Position" renamed, with Plot1=Commercial,
Plot2=Non-commercial, Plot3=Small-spec.

Implication for the Python: the code's `COTIndex(lookback_weeks=26/52...)` cannot be modelling
*RAW* — it must correspond to `Campus Smart Money **Index**` (the bounded 0-100 variant with 80/20
thresholds). That mapping now looks right, but the **Index** variant's lookback has still never
been captured in a dialog across 9 chapters, so the 26/52-week values remain unverified against
video. Flagged as the standing highest-value ask to every reader.

---

## C-05 (REVISED) — Valuation `Length` for equities: 10 vs 13 vs 30 — DO NOT TOUCH YET

The earlier "two distinct Valuation studies" theory is **dead**. CW05 established there is ONE
tool (`CampusValuationTool_V2`, 3 ref inputs); what looked like a "single-ref Campus Valuation
Index" was the same tool with `ShowReferenceSymbol2/3=False`. The leading underscore is just
the internal EasyLanguage name in dialog titles, not an instrument-type marker.

That leaves a genuinely contested **Length** for stocks, with three sourced values:

| value | evidence | strength |
|---|---|---|
| **10** | `BP_rules_engine.py:170-178` — *empirically tested*: "with Length=13 our values for META/NVDA/AMZN came out wildly more bearish than Bernd's verbal reading; Length=10 produced readings consistent with his commentary" | behavioural validation |
| **13** | CW05 MSFT Format Study dialog; CW12 live edit **30 -> 13** on screen; title bars in CW02-2024-LIVE, CW20-2023 | direct observation |
| **30** | current code (`:192`, Phase 38) — "Rulebook Section 2 + Cheatsheet + Ch17 [0:29:24]" | documentation |

**Why I am not changing this.** `BP_rules_engine.py:170-178` already documents that the
"dual-ROC for equities" claim was investigated and explained as an **overlay practice — two
instances of the indicator on the same chart with different Length values — not a parameter
override on one instance.** If that is right, a dialog reading of 13 is entirely compatible
with the current code: it could be the second overlay instance. A frame showing `13` therefore
does **not** by itself refute `30`, and the one empirical test on record favoured 10 over 13.

**Decisive evidence needed:** whether a stock chart carries ONE Valuation pane or TWO stacked
ones. That is Q2 to the CW43 reader. Until that returns, changing this number would be exactly
the Phase 33 mistake with more steps.

---

## C-05 — Two distinct Valuation studies (FRAME-DEPENDENT, unmodelled)

  - `Campus Valuation Index` — **single** ref (`ReferenceSymbol=`), **Length=13**.
    Seen CW02-2024-LIVE, CW12-2023, CW20-2023. In CW20 the ref switched `"@dx"` on @NQ
    vs `"@us"` elsewhere. **Nothing in the Python models this.**
  - `_CampusValuationTool_V2` — **three** refs, **Length=10**, thresholds +/-75.
    Confirmed by Format Study dialogs in CW42 and CW41. **This is what the code models,
    and it matches** (`Valuation.__init__` default `length=10`, +/-75).

So the code's Valuation is correct for the 3-ref tool. Open question is whether the
single-ref Length=13 tool is a separate signal Bernd uses that we simply do not
implement. Note `BP_indicators.py:698` already carries the comment
`length: int = 10,  # Default ROC; override to 13 for equities` — someone previously
hit the 13 and filed it under "equities", which may be a mis-attribution of this
second study. Needs more chapters.

---

## C-07 — COT Index: Python matches V2 (CORRECTLY SOURCED), but which one does Bernd run?

Checked the Python's `140 * (net-min)/(max-min) - 20` against both Pine versions:
  - `COTIndex_OTC.txt` (OTC pack): `100 * (...)` -> **0..100**
  - `COT V2 120-20.txt`: `140 * (...) - 20` -> **-20..120**, header comment *"Modified function to
    calculate index with new formula"*

**The Python is faithful to V2 — not a bug.** `BP_indicators.py:17-25` cites it explicitly and even
documents the consequence: on the stretched scale, a reading >80 is the top ~28.6% of range rather
than the top 20%, *"so extreme signals fire more frequently"*. Deliberate, sourced, understood.

**The open question is which version he actually uses in the sessions**, because the two produce
materially different signal frequencies from identical COT data. Suggestive counter-evidence from
the frames: every `Campus Smart Money Index` title-bar capture ends in `... 80.00 20.00 100.00`
(CW42 F-06, CW02-2024-LIVE F-01) — a trailing **100**, not 120/-20.

### ANSWERED by CW09 (All markets) — the evidence now points clearly at OTC 0..100

CW09 checked the pane explicitly across ~12 sightings spanning index/metals/energies/forex/grains:
  - **NO yellow lines at +120 or -20 anywhere.**
  - Title bar consistently `... 80.00 20.00 100.00` — a plotted **100** reference plus the 80/20
    thresholds. **120 and -20 never appear.**
  - The reader explicitly noted not to confuse the chart's auto-scale gridlines (120/60/0/-60)
    with indicator lines — a trap it avoided.

Combined with CW40's dialog input literally named **`DisplayLineAt100 = True`**, and CW42/
CW02-2024-LIVE both ending `... 80.00 20.00 100.00`:

**Reading: Bernd's TradeStation build uses the 0..100 scale. The Python implements V2 (-20..120).**

### Quantified impact (this is the reason it matters)
Both versions keep thresholds upper=80 / lower=20, but those thresholds sit at different points
of the rolling range depending on the formula:

| | fires bullish at | fires bearish at | time in an extreme |
|---|---|---|---|
| OTC `100x` | 80.0th pct | 20.0th pct | 40.0% |
| V2 `140x-20` | **71.4th pct** | **28.6th pct** | **57.1%** |

**The Python fires COT extremes ~43% more often than his charts do.** `BP_indicators.py:23-25`
already predicted exactly this ("extreme signals fire more frequently") — it just assumed V2 was
the right target.

### Fix (clean swap — formula only, thresholds unchanged)
`140.0 * (x - mn) / (mx - mn) - 20.0`  ->  `100.0 * (x - mn) / (mx - mn)`
at `BP_indicators.py` lines **89, 94, 99, 113, 133, 199**, plus the class docstring at 15-29.
Thresholds stay 80/20 and then mean the 80th/20th percentile, matching `COTIndex_OTC.txt` exactly.

### *** REVERSED by OTC Module 3 / Lesson 2 (COT) — DO NOT CHANGE THE FORMULA ***

The teaching lesson shows the opposite of what the live sessions suggested, with harder evidence:
  - **Settings dialog has an explicit `Upper Bound Level` input set to `120`.**
  - The plotted line is directly observed via crosshair at **-20.00%, 0.00%, 120.00% and even
    126.21%** — values that are impossible on a 0..100 scale.
  - Title-bar label reads `26 156 Futures Only 120 80 50 20 -20 1` — i.e. lookback 26, historical
    hi/lo 156, bounds 120 / -20, thresholds 80 / 50 / 20.
  - Axis auto-scales -25%..125%.
  - Yellow lines: *not confirmed either way* (visible reference lines read gray/white ~80 and
    red/pink ~20; the reader honestly declined to rule a muted yellow in or out under compression).

**This matches the Python's V2 `140x - 20` implementation. The code was right.**

### Resolution: these are TWO DIFFERENT INDICATORS, not one contradiction
Note the names and label shapes never actually matched:
  - OTC lesson: **`COT Pos. Indices`** -> `26 156 Futures Only 120 80 50 20 -20 1`
  - Weekly Outlook: **`Campus Smart Money Index`** -> `... 80.00 20.00 100.00`, with a
    `DisplayLineAt100 = True` input
Same structural pattern as the Valuation story (C-11/C-12/C-14): two related tools, different
generations, different bounds. The 0..100 evidence from the live sessions is real — it just belongs
to the *other* tool.

**Action: none. C-07 is withdrawn as a defect.** The Python implements V2 and the V2 tool is
demonstrably the one taught with the 26 + 156 inputs the code also uses. Had this been "fixed" on
the live-session evidence alone it would have introduced a regression across every COT signal —
this is the second time the corpus trap (C-03) nearly caused one.

**Bonus confirmation:** the dialog exposes `"Weeks Look Back for Historical Hi/Los" = 156`,
proving the Python's 156-week extreme overlay is a real named input of the indicator, not an
invention. `WeeksLookBack = 26` on Gold also re-confirms C-09.

---

## C-15 — Forex COT trader group: teaching lesson contradicts the code (FLAG ONLY, do not act)

`BP_rules_engine.py:2402` routes **forex -> Non-Commercials**, sourced to the *"Phase 12 cheatsheet"*
(a document, not video): *"Non-Comms (1) is the PRIMARY indicator for forex."*

OTC M3 L2 teaches a **universal** rule instead — always trade WITH commercials, against retail at
extremes, watch non-commercials for divergence — and applies it identically to Gold and EUR/USD. On
EUR/USD he reads **commercials'** 2010 all-time-bullish extreme as the *primary* signal.

**Not acting, deliberately.** Flipping forex from non-commercials to commercials would invert the
direction of every forex COT signal — the highest-blast-radius change available in this system —
and the evidence is currently one teaching lesson against one internal cheatsheet, with no live
Weekly Outlook forex corroboration either way. Forex sessions are under-sampled in the audit so
far; this needs several live FX chapters before anyone touches it.
**Added as a standing priority question for every remaining reader.**

### CW11 update — a THIRD candidate, this is now genuinely unsettled

CW11 (All markets wo Indices) gives live, verbatim evidence, and it does not confirm either prior
hypothesis. It names a group nobody proposed:

  - **AUD, CHF: explicitly RETAIL** — *"the retailers are short," "our friends the retailers... I
    like both the Aussie and [Frank]," "due to retail behavior"* — repeated, unambiguous, not
    Non-Commercials (code) and not Commercials (OTC lesson).
  - **EUR, DX: all three panels shown, no group named** — inconclusive.
  - **Gold (non-forex, corroborating C-line for metals): explicit Commercials** — *"the commercials
    are also getting again [short]"* — consistent with the code's metals routing.
  - **Crude Oil (non-forex): explicit RETAIL**, not the code's Commercials-for-energies routing —
    *"retailers are getting super bullish."*

So across 2 chapters we now have THREE different groups claimed as primary for FX-adjacent
markets (code: non-comm: OTC lesson: comm; CW11: retail), and a second miss on energies (code:
commercials, CW11 live: retail on crude).

**Reading this charitably:** he may not use one fixed "primary group" at all — he may read
whichever group is AT AN EXTREME that week and call that the signal, which would make "the
primary group" a category error rather than a fact to discover. That would explain three
different live answers without any of them being wrong.

**Still not acting.** If anything this raises the bar further — a simple non-comm-vs-comm swap
would now be wrong on TWO counts (misses the retail cases entirely). The target chapter (CW05
FX Edition, ~queue position 24, the session `run_scanner.py:186` itself cites) remains the
plan, but expect it may show yet another group rather than resolve this — in which case the
finding becomes "the code's fixed-group model is the wrong shape," not "wrong group."

---

## C-08 — `hideCurrentWeek` — INVESTIGATED, NOT AN ISSUE (closed)

Both Pine versions default `hideCurrentWeek=true` and gate plots on `timenow >= time_close`.
Checked whether the Python has an equivalent guard: **it does not need one.**

`BP_data_fetcher.py:226-250` pulls from the CFTC Socrata API ordered by
`report_date_as_yyyy_mm_dd`, so every row is a **finalised, published** COT report. There is no
in-progress week in the dataset to leak.

The Pine flag solves a *plotting* problem that does not exist here: `request.security(tickerId,
"1D", close)` maps a weekly COT series onto daily chart bars, so without the guard the current
week's value would paint on days before the week closed. Reading published reports directly is
already the correct behaviour. **No look-ahead bias. Closed — no action.**

---

## C-09 — CW40 POSITIVELY VALIDATES the code's COT lookback (good news)

CW40 captured the first-ever `Campus Smart Money Index` Format Study dialog (@GC Weekly):
`WeeksLookBack = 26`, `FuturesOnly_Or_FuturesAndOptions_1_or_2 = 1`, thresholds 80/20,
`DisplayLineAt100 = True`. Bernd also says it aloud: *"26 look back is 26."*

`BP_rules_engine.py:40-41` already has `'precious_metals': 26` sourced to exactly this moment
(*"Ch.107 CW40: Bernd explicit '26 look back is 26' for gold/PMs"*). **Independent re-derivation
from the frames landed on the same value the code already had** — the pipeline is working, and
this parameter is confirmed correct.

`FuturesOnly_..._1_or_2 = 1` also matches the Pine (`cot.COTTickerid(..., false, ...)` = futures
only) and the Python's use of the `*_all` CFTC columns.

**`DisplayLineAt100 = True` is the real prize here** — an input named for a line at **100**, not
at 120/-20, is a strong hint the TradeStation build uses the **0..100 OTC scale**, not the
V2 -20..120 scale the Python implements (see C-07). Not conclusive on its own — it is a TS-specific
input existing in neither Pine — so the yellow-line question still decides it. CW09 is checking now.

---

## C-12 — CHRONOLOGY CHANGES EVERYTHING: he MIGRATED tools mid-2023 (cross-chapter synthesis)

Cross-checking CW07-Corn against all 13 completed chapters revealed the pattern that reframes
C-05/C-10/C-11. Counting per chapter, in date order:

| chapter | date | Len=10 | Len=13 | Len=30 | "Campus Valuation Index" mentions |
|---|---|---|---|---|---|
| CW05 | 2023-01 | 1 | 2 | 0 | 2 |
| CW12 | 2023-03 | 0 | 6 | 1 | **31** |
| CW18 | 2023-04 | 4 | **12** | 2 | **23** |
| CW20 | 2023-05 | 0 | 9 | 0 | **25** |
| CW40 PM | 2023-10 | 1 | 0 | 0 | 0 |
| CW41 | 2023-10 | 4 | 0 | 0 | 0 |
| CW42 PM | 2023-10 | 3 | 1 | 0 | 0 |
| **CW43 Equities** | 2023-10 | **11** | **0** | 0 | **0** |
| CW02 LIVE | 2024-01 | 0 | 2 | 0 | 0 |
| CW04 | 2024-01 | 5 | 2 | 0 | 2 |
| CW07 Corn | 2024-02 | 4 | 0 | 4 | 1 |
| CW09 AllMkts | 2024-02 | **25** | 0 | 0 | 0 |
| MARCH roadmap | 2024-03 | 4 | 0 | 0 | 0 |

**Two regimes, with the switch between May and Oct 2023:**
  - **Jan-May 2023**: `Campus Valuation Index` (single-ref) dominant, `Length=13` dominant.
  - **Oct 2023 onward**: that indicator essentially vanishes (0 mentions in 7 of the last 9
    chapters); `CampusValuationTool_V2` at `Length=10` is used everywhere.

So C-11's "two indicators, split by instrument type" was **wrong**. They are split by **era** —
he migrated from the old single-ref tool to the 3-ref V2 tool. On stocks the V2 tool simply has
ref2/ref3 toggled off, which is why stock charts still show one line (C-04 stands).

### What this does to the `equities` Length question
`Length=30` has **no support in any era**. Its only appearances are transient:
  - CW12/CW18 (2023): the value he is editing *away from* (30 -> 13)
  - CW07-Corn (2024): a live 10 -> 30 toggle he narrates as *"short term" -> "long term valuation"*
    — a temporary view, on **corn**, not a stock setting
So `VALUATION_LENGTH_BY_CLASS['equities'] = 30` (Phase 38) is unsupported by the video corpus.

### But I cannot yet claim 10 for stocks — and this is the honest limit
The recent-era `Length=10` counts come from **non-stock** symbols. CW43 and CW09 both state
explicitly that **stock labels truncate before `Length`**. Direct stock readings exist only in the
early era (CW05 MSFT dialog = 13; CW18's 10 untruncated stocks = 13).

  - stocks, early era: **13** (observed)
  - stocks, recent era: **unknown** (always truncated)
  - everything else, recent era: **10** (overwhelming)

The migration makes 10 the natural inference, and it agrees with the one empirical test on record
(`BP_rules_engine.py:170-178`, which found 10 matched his commentary). But inference is not
observation. **Conclusion: 30 is wrong; 10 vs 13 still needs a recent-era stock dialog.**
Standing priority ask to every reader.

---

## C-11 (SUPERSEDED by C-12) — two Valuation indicators: split by ERA, not instrument type

CW18 (97/97 frames) settles this, and it retroactively makes sense of C-04, C-05 and C-10 at once.

**Two genuinely different EasyLanguage studies, distinguishable by input signature:**

| | `CampusValuationTool_V2` | `Campus Valuation Index` |
|---|---|---|
| inputs | `("@US","@GC","$DXY", True,True,True, 10, ...)` | `("@US", 13, 3, 100, -100, ...)` |
| shape | **3 symbols + 3 booleans** | **1 symbol, then numbers** |
| Length | **10** | **13** |
| used on | crypto, metals, energies, forex, grains | **stocks** (and indices in some chapters) |

The single-ref signature `("@US", 13, 3, 100, -100, ...)` decodes exactly to CW12's dialog capture:
`ReferenceSymbol="@US", Length=13, NumDecimalsOfPrecision=3, RescaleMaximum=100,
RescaleMinimum=-100`. Independent match across two chapters.

**CW18 evidence (strong):**
  - `Length=13` on **10 stocks** via *un-truncated* labels (AAPL, AMZN, META, GOOG, NFLX, NVDA,
    PFE, RACE, TSLA, BABA) — all reading `("@US", 13, 3, 100, -100, ...)`
  - **Two verbatim live-edit index dialogs**: @NQ **30 -> 13**, @ES **10 -> 13**
  - Bernd on tape: *"put here on 13 is as better for indices"*
  - Bitcoin in the same chapter uses the 3-ref V2 tool, all True — clean contrast in one session

### This dissolves the C-10 contradiction
`BP_rules_engine.py:170-178` rejected 13 because *"with Length=13 our values for META/NVDA/AMZN
came out wildly more bearish than Bernd's verbal reading."* That test ran **3 references at
Length 13**. But his stock indicator is **1 reference (bonds) at Length 13**. The test falsified a
configuration he never used — so its conclusion ("therefore 10") does not follow.

Every strand now agrees on the same answer for stocks: **single ref = @US (bonds), Length = 13.**
That is also what `BP_rules_engine.py:30` and `BP_indicators.py:698` already say in prose, and what
C-04's 4-chapter ref evidence independently implies. The live value of 30 is the outlier.

### Consequence for the Python
The code models **only** the 3-ref tool and applies it to everything. For equities it should be
one reference (`ZB=F`) at `length=13` — i.e. **C-04 and C-10 are the same fix**, and they resolve
together rather than separately.

### Still open
Indices are ambiguous **by date**: CW18 (Apr 2023) shows indices on the single-ref tool at 13
(with Bernd saying 13 is better *for indices*), while CW09 (Feb 2024) shows indices on the 3-ref
tool at 10. Could be genuine evolution over time, or two chart templates. **Do not change
`equity_indices` yet** — only `equities` is safe to act on.

---

## C-10 — The code contradicts ITSELF on the equities Valuation ROC (see C-11 — now explained)

Three positions coexist inside the same repo:

| location | says | note |
|---|---|---|
| `BP_rules_engine.py:30-31` (comment) | **13** | *"Equities use ROC=13 on Valuation (longer/smoother per OTC L8)"* |
| `BP_indicators.py:698` (comment) | **13** | *"Default ROC; override to 13 for equities"* |
| `BP_rules_engine.py:192` (actual value) | **30** | Phase 38, cites Rulebook + Cheatsheet + Ch17 |
| `BP_rules_engine.py:170-178` (comment) | **10** | empirical: 13 made META/NVDA/AMZN *"wildly more bearish"* than his commentary |

So **two comments say 13, the live value is 30, and a third comment argues for 10.** The frames
(CW05 MSFT dialog = 13; CW12 live edit **30 -> 13** on screen) side with 13.

This is not a simple "code is wrong" case — it is an unresolved internal disagreement that predates
this audit, and one prior empirical test actively argued against 13. Note also CW12 showed Bernd
*changing* 30 to 13 live, which is equally consistent with "13 is correct" and with "he was
demonstrating". **Still NOT ACTING.** Needs either a second stock-chart dialog or a numeric
replay (see method note at top) to break the tie.

---

## C-01 REFINEMENT — the Pine source proves the bug AND corrects my proposed fix

`Valuation_OTC.txt` lines 17-28:
```pine
Comp1  = security(CompId1, timeframe.period, close)
Symbol = close
CompPerc1 = (Comp1 - nz(Comp1[Length])) / nz(Comp1[Length]) * 100
SymPerc   = (Symbol - nz(Symbol[Length])) / nz(Symbol[Length]) * 100
```
`security()` maps the reference onto the **chart's own bar index**, so `Comp1[Length]` and
`Symbol[Length]` step back the *same* number of **chart** bars. Both ROCs share one bar spacing —
exactly what the current Python violates. **C-01 is confirmed a genuine deviation from canon.**

It also corrects my earlier patch: intersecting to `common_idx` would *drop* the symbol's
weekend bars, whereas Pine keeps every chart bar and forward-fills the reference across them.
The faithful fix is **reindex the reference onto the symbol's index with forward-fill, then take
both ROCs on the symbol index** — not an intersection. For a 7d/wk crypto chart Pine would carry
Friday's DXY across the weekend; `common_idx` would delete Saturday and Sunday entirely.

Also noted, both minor and already knowingly divergent:
  - Pine `rescale` has no zero-denominator guard (`na` on flat input); Python guards to NaN — equivalent.
  - Pine has **no** `min_periods` relaxation — it yields `na` until `RescaleLength` bars exist.
    Python's `_rescale` deliberately relaxes `min_periods` (documented at `:766-776`) so short
    series produce values earlier. Python will therefore print readings where Pine shows nothing.
  - **The OTC Pine has no `Show` flags at all** — so it cannot settle C-04. The TradeStation
    `CampusValuationTool_V2` with `ShowReferenceSymbol1/2/3` is a later generation than this v4 source.

---

## C-13 — Seasonality (OTC M3 L4): two Python choices VALIDATED, two deviations found

**VALIDATED — trading-day-of-year binning.** The lesson never states the binning rule, but the
recurring seasonal turn lands on a *different calendar date every year* — Mar 04 '19, Feb 27 '20,
Feb 24 '21, Feb 23 '22, Feb 22/23 '23. That drift is the signature of **trading-day-of-year**
alignment, which is exactly what the Python does. Indirect but strong.

**VALIDATED — the 5/10/15 multi-lookback.** A concept slide states the lookbacks explicitly:
*"Uses lookback periods (e.g., 5, 10, or 15 years) to balance relevance and reliability."* The
Python runs 5/10/15 with 2-of-3 agreement (`BP_rules_engine.py:1712`), plus sourced per-symbol
overrides (NG=F 5+10, RTY=F 5-only). Caveat for honesty: he does **not** verbalise an
"agreement vote" — on air he opens at `AverageYears=5`, changes it live to `10`, and runs the whole
demo at 10. So 2-of-3 is a defensible construction, not something he states.

**DEVIATION 1 — `ProjectNumberBarsIntoTheFuture = 45`, not 100.** Every live Weekly Outlook chapter
shows 100; this OTC dialog shows **45**. Another corpus split (cf. C-03 ZigZag). Low impact if the
Python only reads direction/slope rather than projecting N bars — but worth confirming which it does.

**DEVIATION 2 (IMPORTANT, unverified in code) — seasonality is CONFIRM-ONLY.** The lesson is
unambiguous: *"Not a standalone tool; use with price action, fundamentals, or the optimizer"* and
*"Seasonality provides timing guidance, not trade setups or price targets."* **Not yet checked
whether the Python can let seasonality alone carry a bias into a signal.** If it can, that is a
genuine rule violation, not a parameter mismatch. Filed as the next code investigation.

**Naming anomaly.** In this corpus the study is `OTC True Seasonality v4` / `Seasonality Index - v4`;
in the live sessions it is `Campus Algo Forecast` / `Campus True Seasonality`. Possibly a rename,
possibly different scripts — do not assume the parameter sets are interchangeable across corpora.

**Numeric replay candidate (Q6).** SB1! (Sugar No.11) 1D: index `164.59` at load with
`AverageYears=5`, then ~56-72 after switching to 10 (63.38, 60.39, 58.99, 68.45, 69.03, 69.12) with
the forward projection starting at "Thu 02 Jan '25". The 164.59 sits far outside the later ~55-72
band — flagged by the reader as worth a Python replay to see whether it reproduces or indicates a
scaling difference.

---

## C-14 — SETTLED & APPLIED: equities Length 30 -> 13, and refs -> BONDS ONLY

OTC Module 3 / Lesson 3 (Valuation) is the teaching lesson the live sessions kept truncating, and
it answers both halves with dialog screenshots plus narration.

**Length = 13 for stocks.**
  - Slide table (frame_000727): *"Equity indices and stocks -> 13 days short term / 30 days long term."*
  - Live AAPL dialog (frame_001253): edits ROC **10 -> 13** saying *"I'm going to change the ROC
    from 10 to 13"*; title bar updates to `...13 100 100 -100 75 -75`.
  - Agrees with CW18's 10 un-truncated stock labels at 13, and CW05's MSFT dialog at 13.
  - **The `30` mystery is solved:** 30 is the labelled *long-term* alternate view, never the stock
    default — exactly matching CW07-Corn where he toggles 10 -> 30 narrating "short term" ->
    "long term valuation".
  - The old "13 was tested and came out wildly more bearish" objection is void: that test used
    **three** reference lines at 13; his stock config uses **one**.

**Refs = Bonds only for stocks.**
  - Full dialog (frame_000808): ref1=`CBOT_DL:ZB1!`, ref2=`COMEX_DL:GC1!`, ref3=`TVC:DXY`.
  - On the AAPL chart he unchecks Dollar and the plot is left showing **only the bonds line** —
    Gold and Dollar both off.
  - Matches CW05's MSFT dialog (`ref2 "@GC"=False` AND `ShowReferenceSymbol3=False`) and the
    Gold-off readings in CW04 / CW41 / CW43.

**Applied:**
  - `BP_rules_engine.py` `VALUATION_LENGTH_BY_CLASS['equities']`: **30 -> 13**
  - `run_scanner.py` `VALUATION_REFS['equities']`: **["ZB=F","GC=F"] -> ["ZB=F"]**
  - Verified loaded: equities Length=13, refs=['ZB=F']; forex / precious_metals refs unchanged.
  - Side effect to be aware of: equities now have a SINGLE valuation line, so `get_bias()` decides
    stock bias from one line rather than by majority vote. Faithful to his method, but it does make
    stock valuation bias more sensitive than before.

**Deliberately NOT changed — `equity_indices`.** The slide groups indices with stocks at 13, but the
live corpus disagrees *by date*: CW18 (2023-04) shows indices edited to 13, CW09 (2024-02) shows
@YM/@NQ at 10. Left at 10 pending a recent-era index dialog; noted inline in the code so nobody
"fixes" it from the slide alone.

**Deliberately NOT changed — `forex`.** This lesson shows AUD/USD with Bonds and Gold unchecked
("that leaves us only with the dollar valuation"), i.e. DXY-only. That is precisely the
*teaching-session narrowing* that `run_scanner.py:185-193` already considered and rejected, citing
a genuine LIVE session (Ch.167, CW05 FX Edition, Jan 2024) where CHF and GBP both run all three
refs simultaneously. Teaching narrows to explain one line at a time; live uses the full set. Left
as the 3-ref default — this is exactly the corpus trap from C-03, avoided.

---

## C-16 — CW03-2023 (Jan) complicates C-12's era theory; adds a 5th COT-scale confirmation

**Era theory needs a caveat, not a reversal.** CW03 is the earliest chapter yet (2023-01-15) and
uses the 3-ref `CampusValuationTool V2` exclusively — no single-ref sighting at all. That doesn't
match C-12's clean "single-ref/13 dominant Jan-May 2023, then V2/10 from Oct 2023" split; CW03 sits
right at the start of that window and already shows V2. Length was unrecoverable everywhere (always
truncated, no dialog), so this doesn't resolve the 10-vs-13 question either way — it just means the
era boundary is fuzzier than one clean cutover. Both tools may have coexisted throughout 2023.

**5th confirmation of the COT 0..100 scale in live sessions.** Yet another indicator NAME variant —
`Campus COT Index V2 protected V1` — but trailing label is `... 80.00 20.00 100.00 0.00`, same
bounds as `Campus Smart Money Index` and consistent with 4 prior live chapters. C-07's withdrawal
(code is right, live sessions use a *different* named tool than the OTC-taught one) keeps holding up.

**New COT group data point: @TY (10-Yr Treasury) -> Commercials.** Verbatim: *"Daily demand.
Valuation, nothing special commercial."* Interest rates (@TY/@ZN/@ZB-type symbols) have no explicit
group routing anywhere in `BP_rules_engine.py` — worth checking what they fall through to. Single
sighting, not acted on, but the class is otherwise undocumented in this audit.

**Algo Forecast AverageYears=10 uniformly** (NQ/YM/ES/RTY/NG/TY) — matches C-12's timeline
observation that later chapters (Oct 2023+) show 15. Another parameter that may have DRIFTED over
2023, same shape as the Length story. Filed, not acted on — the code's existing 15 default plus
per-symbol overrides (NG=5+10, RTY=5-only) were themselves sourced to specific later chapters, so
this isn't necessarily wrong, just era-dependent like everything else in this indicator suite.

---

## C-17 — CW07-2024 All Markets (Feb): forex still silent on COT group; more scale confirmations

- **Forex COT group (C-15): still unresolved.** @DX/@AD/@BP/@SF were charted but Bernd never names
  a COT group while they're up (talks price structure only). The one attribution in the chapter is
  Natural Gas: *"if the retailers are getting more bullish I'm definitely not willing to get in any
  kind of long position on natural gas"* — explicit retail-fade on NG, consistent with the code's
  older retail-contrarian NG note (Phase 41 moved NG to NonComm; this quote leans back toward
  retail-fade — logged as another data point for the "he reads whichever group is at an extreme"
  theory, not acted on).
- **6th live confirmation of 0..100 COT scale** — `Campus Smart Money Index` touches exactly 100.00
  on @NG and @C; raw `_Campus COT` panes are unbounded net positions (separate indicator family).
- **Valuation Length=10 on all 11 symbols** incl. forex; refs always the fixed @US/@GC/$DXY basket,
  even on @DX and @GC themselves (self-reference case again).
- **AverageYears=10 uniformly** (Feb 2024) — the 10-vs-15 drift timeline is genuinely messy: Jan-23=10,
  Oct-23=15, Feb-24 (CW07/CW09)=10, CW40 (Oct-23)=15. Possibly he toggles per session, not per era.
  Consistent with CW07-Corn's live 5→10→15 walk: it's an exploratory view. Code's multi-lookback
  design (5/10/15 vote) remains the right shape — no action.
- ZigZag absent (16/16).

---

## NEW MAIN TASK (user-directed 2026-08-18) — NUMERIC REPLAY VALIDATION of the 4 indicators

**Goal:** stop relying on parameter labels alone — take actual PLOTTED VALUES captured from lecture
frames (with symbol + date visible), compute the same indicator in the Python on the same data and
date, and compare numbers. A match proves the implementation end-to-end; a mismatch localises a bug
no label-read can find.

**Inputs already on disk:**
- Pine sources (formula ground truth): `D:\Trading\Bernd_Skorupinski Campus Blueprint OTC\OTC Tradingview Indicator Pack\`
  (Valuation_OTC.txt, COTIndex_OTC.txt, COTReport_OTC.txt, Seasonality_OTC.txt) + `pinescript\COT V2 120-20.txt`
- Frame-captured, date-tagged readouts in `per_chapter/OTC-M3-L2_COT.md`, `OTC-M3-L3_Valuation.md`,
  `OTC-M3-L4_Seasonality.md` (the reports' Q6 sections were specifically asked to capture
  symbol+date+value tuples for exactly this purpose):
  - Valuation: AUDUSD (3-line + DXY-only states) and AAPL (bonds-only, Length=13) readouts w/ dates
  - COT: GC1! 1W crosshair readouts (-20.00 / 0.00 / 120.00 / 126.21), WeeksLookBack=26, 156 hi/lo
  - Seasonality: SB1! 1D, AverageYears=10, values 63.38/60.39/58.99/68.45/69.03/69.12 near
    "Thu 02 Jan '25" projection start; anomalous 164.59 at AverageYears=5 load
- Frames folders (if more/better-dated readouts needed): `D:\Trading\Output\Bernd_Skorupinski Campus
  Blueprint OTC\...\5. Module 3...\Lesson 2/3/4`; source VIDEOS also exist under
  `D:\Trading\Bernd_Skorupinski Campus Blueprint OTC\...\5. Module 3...\Lesson N.mp4` if a frame's
  date is ambiguous.
- Data: Python fetches via yfinance/CFTC — note TradingView uses GC1!/ZB1!/SB1! continuous contracts
  vs Yahoo's GC=F/ZB=F/SB=F; small basis differences are expected, so compare SHAPE + threshold
  crossings + approximate values, not exact equality. Define tolerance before judging.

**Plan (per indicator, Opus lane):**
1. Extract every symbol+date+value tuple from the three OTC per_chapter reports into a small
   fixtures file (`_audit_ftw_vision/replay_fixtures.json`).
2. For each fixture: fetch history for that symbol up to that date, run the Python indicator with
   the frame-confirmed parameters, extract the value at that date.
3. Compare: within tolerance -> indicator VALIDATED end-to-end; outside -> investigate (data basis
   vs formula bug) before touching code.
4. ZigZag has no lecture readouts in these lessons — validate later from Practical Application corpus.

**Status: fixtures EXTRACTED -> `replay_fixtures.json`** (Valuation: 3 exact-date AUDUSD readouts +
latest-bar sanity band + DXY-extreme marker dates; Seasonality: 2 dated SB1! projection values +
5-year recurring-Feb-top shape check; COT: values-only, dates not captured — with a flagged
**CRITICAL ANOMALY: crosshair 126.21 exceeds the hard 120 cap of any min/max formula that includes
the current bar**, hypothesis = window excludes current bar; date recovery = re-read frames
002251/002330/002381/002443 in the Lesson 2 folder). Next: build the replay runner (fetch history,
compute, compare with pre-defined tolerance).
1. A **Format Study dialog on a stock/equity chart** — settles C-04. Highest value.
2. A **Format Study dialog for Campus Smart Money Index / RAW** — never captured; their
   lookbacks are still unknown.
3. Any frame showing the **single-ref `Campus Valuation Index`** with its dialog open —
   settles C-05.

---

## R-01 — REPLAY RESULT: Valuation VALIDATED end-to-end (9/9 fixtures match)

`replay/replay_valuation.py`, run 2026-08-19. AUDUSD 1D, refs ZB=F/GC=F/DX-Y.NYB, Length=10,
tolerance defined BEFORE running (match = same sign & <=20 units; strong <=10; mismatch = sign
flip @|v|>15 or >35).

| date | line | frame value | python | delta | verdict |
|---|---|---|---|---|---|
| 2025-01-21 | bonds | -13.72 | -27.07 | 13.3 | MATCH |
| 2025-01-21 | gold | -49.51 | -48.73 | 0.8 | STRONG |
| 2025-01-21 | dxy | 27.95 | 35.51 | 7.6 | STRONG |
| 2024-10-01 | bonds | 73.48 | 75.21 | 1.7 | STRONG |
| 2024-10-01 | gold | -15.66 | -33.06 | 17.4 | MATCH |
| 2024-10-01 | dxy | 21.02 | 23.45 | 2.4 | STRONG |
| 2025-01-17 | bonds | -1.44 | -2.80 | 1.4 | STRONG |
| 2025-01-17 | gold | -67.85 | -57.27 | 10.6 | MATCH |
| 2025-01-17 | dxy | 5.70 | 10.50 | 4.8 | STRONG |

**9 match / 0 mismatch.** Wider deltas sit exactly on the futures legs (ZB/GC) where
continuous-contract-vs-front-month basis lives; FX+DXY legs all <=7.6. Validates the whole chain
end-to-end: ROC math (incl. the C-01 fix), per-reference handling, `_rescale`, thresholds, and
the Yahoo proxy mapping. **Valuation: WORKING CORRECTLY.**

## R-02 — REPLAY RESULT: COT 126.21 anomaly — mechanism CONFIRMED, impact ~1%

`replay/replay_cot.py`, real CFTC gold commercials data (1986-2018 slice, 1500 wk):
  - Ours (window incl. current bar): min/max exactly [-20.00, 120.00] — cannot produce 126.21.
  - Current-bar-EXCLUDED variant (26w): range [-112.8, 168.1], **20 separate weeks within +/-1.5
    of 126.21** — the on-screen value is a routine occurrence under this variant.
  - 156w-excluded variant also overshoots (max 141.4) — either window could be the real one.
  - **Signal-level impact of incl-vs-excl @ 80/20 thresholds: 15/1474 weeks = 1.0%.**

So the real indicator almost certainly computes min/max over a window EXCLUDING the current bar;
ours includes it (as does the user-shared Pine, note — `ta.lowest(netPos, weeks)` INCLUDES the
current bar, so the TradeStation build differs from the Pine too). Real formula-shape difference,
LOW impact. Crosshair DATE recovery from frames 002251/002330/002381/002443 is running — an
exact-date match vs the excluded variant (re-run with post-2018 data) decides whether to adopt it.
**Decision deferred — not applied.**

## R-02 REVISED — COT 126.21: most likely NOT an indicator value; formula stands as-is

Date-recovery vision pass on frames 002251/002330/002381/002443 + exact-date fingerprint replay
(all 3 trader groups x incl/excl window x 26w/156w, on gold AND EUR FX COT) produced:
  - recovered dates 2021-10-04 (0.00%) and 2022-11-07 (126.21%), but NO (group, window, variant)
    combination reproduces those values at those dates (closest: EUR retail 156w = 4.56 vs 2.75);
  - the reader's own caveat: the 126.21 box is "likely associated with a selected drawing object
    rather than a single series"; that frame's actual line legends read 80.68% / 2.75%;
  - 120.00 / 0.00 / -20.00 are EXACTLY the three drawn reference-line levels of the tool
    (`... 120 80 50 20 -20 ...`) — hovering a drawn hline shows its own value.

**Parsimonious conclusion: the four "plotted line touches 120/0/-20/126.21" readings from the
original L2 audit were reference-line/drawing-object readouts, not series values.** There is no
reliable evidence the real indicator exceeds [-20, 120]. Our formula is verbatim-faithful to the
canonical `COT V2 120-20.txt` Pine (which includes the current bar via `ta.lowest(netPos, weeks)`),
its dialog-confirmed inputs (26 / 156 / Futures-Only / 120 / 80 / 50 / 20 / -20) all match the
code. Incl-vs-excl window sensitivity measured at ~1% of weeks — immaterial.
**COT: VALIDATED as implemented. No change. Anomaly closed as a mis-attributed readout.**

## R-03 — REPLAY RESULT: Seasonality SHAPE VALIDATED (values not comparable by design)

The lesson's "Seasonality Index - v4" is a sub-pane index script whose source we do not have
(the OTC pack's `Seasonality_OTC.txt` is a different, price-overlay implementation), so exact
index-unit matching (68.45 etc.) is impossible. Shape replay on SB=F, our Seasonality class,
lookback=10y (`replay/replay_seasonality.py` + follow-up local-peak analysis):

  - Our curve's LOCAL peak at bin 34 maps per-year to: **2023-02-22 (0d off his marked top),
    2022-02-22 (1d), 2021-02-23 (1d), 2020-02-21 (6d)**, 2019-02-21 (11d vs his loosest marker)
    -> 4/5 within tolerance, three at <=1 day. The drifting calendar date across years also
    re-confirms trading-day-of-year binning (C-13).
  - Post-peak 25-bin move: **-1.44** (strongly falling) = the recurring bearish move he demos.
  - January slope rising (+0.32) = his rising Jan projection (68.45 -> 69.03 -> 69.13 plateau).
  - Note: our GLOBAL curve max sits in mid-October; his Feb marker is a LOCAL top he trades. Both
    can be true; nothing to fix.

**Seasonality: WORKING CORRECTLY at the level the evidence can test.**

## NUMERIC REPLAY — FINAL SCOREBOARD (the "4 indicator" matching task)
| indicator | result |
|---|---|
| Valuation | **VALIDATED** — 9/9 date-exact fixtures match (R-01) |
| COT | **VALIDATED** — formula = canonical Pine; dialog inputs match; 126.21 anomaly closed (R-02) |
| Seasonality | **VALIDATED (shape)** — Feb-top dates, post-top decline, Jan slope all match (R-03) |
| ZigZag | **NOT TESTABLE from these lessons** — no numeric readouts; validate from Practical Application corpus later |

## C-18 — "Can seasonality trigger a signal ALONE?" — NO. Confirm-only requirement SATISFIED (closed)

OTC M3 L4 requires seasonality be confirm-only ("Not a standalone tool; use with price action,
fundamentals, or the optimizer"). Traced every consensus path in `BP_rules_engine.py`:

- **Futures hierarchy** (`_bias_consensus` docstring + Step 1-4, :1845-1854): Location is the gate
  (Step 1: loc neutral -> no trade), Valuation is the veto (Step 2). Seasonality only appears in
  Step 4 as ONE optional confirmer alongside COT/Trend, after Location+Valuation align. Never alone.
- **Stocks branch** (:2117-2185): the loosest route is the tertiary path
  `seas bullish AND val not bearish AND not downtrend -> bullish` (:2155). Seasonality is the only
  ACTIVE input there — but this only sets the Stage-1 BIAS, not a trade.
- **The zone gate makes everything confirm-only** (:379-387): `consensus == 'hold' -> None`, and a
  signal object is only ever built from a qualified zone whose direction matches the consensus
  (`zone_dir` vs consensus check, then the full zone-qualifier scoring). No qualified
  demand/supply zone = no signal, regardless of seasonality. "Use with price action" is thereby
  structurally enforced for every asset class.
- Cycle paths (Phase 23/24/26/38) are presidential/sannial-cycle-driven with seasonality as a
  modifier — also never seasonality-alone.

**Conclusion: the Python cannot fire a trade on seasonality by itself. Requirement met, no change
needed. Open item closed.**

## C-19 — CW35-2023 (Aug): BOTH COT scales appear in live sessions; stock Length drifted mid-2023

- **COT dual-scale coexistence CONFIRMED in a live Weekly Outlook**: this chapter's pane is
  `_Campus COT Index V2 (...` trailing **`80.00 20.00 120.00 -20.00`** — the V2 -20..120 bounds,
  live, on screen (axis headroom +200/-150 confirms it can exceed 0-100). Other live chapters
  showed `Campus Smart Money Index ... 80.00 20.00 100.00` (0-100). So **he runs BOTH tools in
  live sessions depending on era/workspace** — the Python's V2 implementation matches one of the
  two genuine live tools (and the canonical Pine). C-07 withdrawal further vindicated; the 0-100
  sightings were the OTHER tool, not evidence against V2.
- **Stock Valuation Length was 10 in Aug-2023** (single-ref `Campus Valuation Index
  3383376("@us",10,3,100,-100,100,75,-75,...)`, zoom-confirmed on TSLA/AAPL/MSFT/NVDA/GOOGL) —
  vs 13 in Jan-May-2023 chapters and **13 in the 2025 OTC course** (slide + live 10->13 edit).
  Timeline: 13 (early 23) -> 10 (Aug 23) -> 13 (2025 teaching). **Decision: KEEP equities=13** —
  the 2025 course is the most recent, most deliberate evidence (slide table + narrated edit);
  the Aug-23 sighting is a historical mid-drift state. Logged so nobody flips it on one chapter.
- **Campus Algo Forecast: stocks AverageYears=6** (5 stocks, consistent) — a NEW value beyond the
  known 4/5/10/15 set; futures already 15 by Aug-2023 (pushes the 10->15 transition earlier than
  the assumed October). Reinforces: AverageYears is an exploratory per-session view, NOT a fixed
  constant. Python's multi-lookback vote design remains the right shape; no action.
- **Q7 Platinum**: frames 001881/001942/001959 confirmed exactly as the `run_scanner.py` comment
  cites — but the same 3-ref config appears on Dow/Nasdaq/ES/Gold in the same chapter, so it is
  the universal futures config, not Platinum-specific. The PL/PA per-symbol override is harmless
  (equals class default) but its rationale comment overstates specificity. No code change.
- Gold COT group: Commercials-bullish/Retail-bearish verbatim again (consistent with code).
- ZigZag absent (17/17).

## C-20 — CW50-2023 (Dec): consistent with everything applied; timeline data points

- COT pane back to `Campus Smart Money Index ... 80.00 20.00 100.00` (0-100) this chapter —
  confirms tool choice varies per session/workspace (C-19 dual-tool conclusion holds).
- Stocks on the 3-ref V2 tool with **ref legs True,False,...** again — consistent with the
  applied bonds-only equities fix (C-14). Stock Length truncated in every frame (honestly
  unresolved; no stock chart was ever full-screened this chapter).
- COT groups: Gold + Silver = Commercials-vs-Retail contrast verbatim (matches code);
  Platinum: "the retailers here, the red line" (color proof); Copper + Dow: only Retailers
  named. No forex charted at all.
- AverageYears timeline now: Jan-23 10 | Aug-23 15 fut / 6 stk | Dec-23 10 fut / 5 stk |
  Feb-24 10 — confirms per-session exploratory use, multi-lookback design right (no action).
- ZigZag absent 18/18.

## C-21 — CW08-2024 All markets (Feb-19): strongest forex-Retail evidence yet; Smart Money lookback dialog

- **Forex COT group (C-15 evidence, major)**: Euro = RETAIL, explicit AND on-screen-confirmed —
  "retailers are getting super bearish on the euro" with Smart Money Index red(retail)=0.95
  (near-zero extreme) vs blue(commercial)=100.00 pegged. CHF = Retail ("happens to the
  retailers..."), Crude = Retail, Gold(inferred) = Retail. Meanwhile Corn = Commercial
  (blue pegged 100.00), Wheat = Commercial ("commercial's bearish", blue at 0.00 floor).
  Pattern now firm across live chapters: **forex -> Retail; grains -> Commercials** (grains match
  code's soft_commodities=Commercials). Decisive CW05 FX Edition launched to settle C-15.
- **Smart Money Index settings dialog captured** (@CL, frame_000241): `WeeklyLookBack = 20`,
  DisplayCommercial=True, DisplayNonCommercial=False, DisplaySpeculator(retail)=True,
  thresholds 80/20, LineAt100=True. But he SAYS "26 weeks look back" at the same moment.
  Our code: canonical V2 26w (validated vs OTC dialog); energies class override = 52w.
  Discrepancy is single-frame, on the OTHER tool variant (0-100 Smart Money, not V2), and
  contradicts his own narration -> **log only, no change** (Phase 33 rule). Watch item: if more
  crude/energy dialogs show 20, revisit the energies=52 override.
  Dialog also confirms the 0-100 tool plots ONLY Commercials+Retail (NonComm display=False) —
  matches every live blue/red reading we've attributed.
- **Valuation Length=10 on every legible symbol** (CL/DX/EC/BP/AD/C/W, Feb-2024) — extends the
  era timeline (13 early-23 -> 10 Aug-23 -> ... -> 10 Feb-24 -> 13 in 2025 course). Keeps the
  equities=13 decision intact (2025 teaching is most recent + deliberate); commodities/forex
  classes unchanged.
- **Ref legs all-True on every chart incl. commodities** — all-True is the session-wide default,
  not forex-exclusive; no stock charts this chapter (companion "CW08 Equity Indices and Stocks"
  is a separate queued chapter).
- **Campus Algo Forecast full signature documented**: `(10, 100, False, False, False)` —
  AverageYears=10 (fits Feb-24 timeline point), plus a second int (100, likely forward-projection
  bars; our TrueSeasonality uses forward_bars=150 from the HAI lesson) and three False flags.
  Detail-only; multi-lookback design already covers AverageYears drift. No action.
- Third-party sighting (low confidence): student forum screenshot showed a 3-group panel driven
  by `_Campus COT Index GV2_Protected (1,52,156,TRUE,TRUE,TRUE,80,20,...)` — note the 52/156
  pair echoes our 52w class lookback + 156w extreme window. Not Bernd's own chart; log only.
- ZigZag absent 19/19 chapters.

## C-22 — CW05-2024 FX Edition (DECISIVE): forex COT group = RETAIL contrarian — FIX APPLIED

The chapter the code itself cited as evidence for forex=Non-Commercials was re-read frame-by-frame
(62/62 frames + full transcript). Verdict: **the citation was wrong. Retail is the only group he
names, on every pair.**

- Verbatim, all four pairs analyzed: DXY "We see now the retailers getting slowly more bullish
  again... which is great because we need the dollar first to come a little bit lower";
  AUD "you see the retail data similarly we had this huge spike very bullish"; NZD "we look at
  the retail data... I don't even look at the charts I just look... where the retail spikes";
  GBP "retailers are honestly... getting also slowly more bullish". The words "commercial",
  "non-commercial", "fund manager", "large spec" appear ZERO times in the whole chapter — even
  though a COT Net Position pane with those series was on-screen the entire time (F-06).
- **Contrarian direction confirmed twice independently**: CW05 DXY (retail rising bullish -> his
  bias = dollar lower) and CW08 Euro (retail index 0.95 extreme-short "super bearish" -> "short
  term euro move" up). Plus CW11 retail on AUD/CHF. Live corpus: 4+ chapters, unanimous.
- Teaching-vs-live conflict documented: OTC M3 L2 demos forex COT with Commercials. Live wins
  for the live system; both recorded here per the corpus-trap rule.
- Reader-flagged nuance (kept honest): in CW05's two fully-loaded Smart Money Index readouts the
  BLUE line was the numerically extreme one, while his words said "retail". His "spike" language
  maps cleanly to the always-red **Campus Smart Money RAW** plot (AUD 11,565.25 near historical
  max). In CW08 the red line DID match his retail call (Euro 0.95). The GROUP he reads is not in
  doubt; which plotted line is which color in the 0-100 tool remains medium-confidence only.
- **APPLIED** (`BP_indicators.py` `get_bias`): forex branch `lspec/False` -> `sspec_idx,
  sspec_ext, contrarian=True`; momentum-trigger `primary_col` forex -> `small_specs_index`;
  stale Phase-43 comment line updated. Phase 21 USD-base inversion untouched (group-agnostic).
  `detect_divergence` deliberately UNCHANGED (its non-commercials basis is its own HAI M3 L1P3
  lesson, separate evidence).
- **Verified**: synthetic behavioral test (scratchpad `test_c22_forex_retail.py`) — retail
  extreme-long -> forex bearish; retail extreme-short -> forex bullish; retail mid + non-comm
  pegged 114 -> now neutral (proves the group switch); commodities path byte-identical behavior.
  `import BP_indicators, BP_rules_engine` OK.
- Open item C-15 is now CLOSED.

### CW05 supplementary findings
- Algo Forecast settings dialog captured OPEN for the first time (frame_000658, CHF):
  `AverageYears=10, ProjectNumberBarsIntoTheFuture=100, AlignFirstFutureBarWithBarClose=False,
  StartFutureProjection1YearBefore...=False, PrintDebug=False` — positionally confirms the
  `(10, 100, False, False, False)` title signature from CW08 (C-21). Detail only.
- Valuation: `_CampusValuationTool_V2("@US","@GC","$DXY",True,True,True,10,...)` identical on
  DXY/CHF/AUD/GBP — fixed dollar-centric basket, exactly what `run_scanner.py` VALUATION_REFS
  forex entry already encodes. Length=10 again (Jan-2024, era-consistent).
- 14 dated DXY crosshair tuples captured for future replay (mostly Campus Algo Forecast curve
  values 113.8-120.5 across 2022-2024 dates + one Valuation `-123.43 @ 01/25/24` — treat the
  latter cautiously, it exceeds the tool's -100 rescale bound and may be a Y-position readout).
- Smart Money Index never loaded for GBP/NZD on-screen; no COT dialog opened (no forex
  WeeklyLookBack sighting; C-21 watch item unchanged). ZigZag absent 20/20.

## C-23 — CW03-2024 (Jan-13): all applied fixes corroborated; nothing contradicted

- **Forex = Retail contrarian (C-22) corroborated post-fix**: AUD (0:17:04) and DXY
  (0:20:29-0:20:54) both explicitly "retailers"; zero counter-evidence. Palladium explicitly
  "commercials" — matches code's precious_metals=Commercials primary (Phase 17).
- COT pane: Campus Smart Money Index 0-100 variant on every market; no COT settings dialog
  (WeeklyLookBack 20-vs-26 watch item stays open; the one dialog seen was Algo Forecast parked
  on its Color tab).
- Valuation: futures/index `_CampusValuationTool_V2("@US","@GC","$DXY",True,True,True,10,...)`;
  **stocks (AAPL/WMT/BABA) show only the bonds leg active** vs three on futures — corroborates
  the C-14 bonds-only equities fix from a third independent chapter. Stock Length illegible
  (era question C-14b unchanged).
- Algo Forecast `(10,100,False,False,False)`; BABA possibly `(5,...)` (medium conf) — fits the
  known per-session AverageYears drift; multi-lookback design already covers it. No action.
- ZigZag absent 21/21. 6 dated crosshair tuples banked (AUD x4, DXY, NASDAQ).
- Frames 905-956 flagged lower symbol-identity confidence by the reader; nothing load-bearing
  was sourced from that segment.

## C-24 — CW10-2023 (Mar-05): BOTH Valuation Lengths coexist BY CLASS in one chapter — code config corroborated

- **Key era finding**: single-ref `Campus Valuation Index`, Length **10 on every equity-index
  future and Gold** (@YM/@ES/@NQ/@RTY/@GC) and **13 on every legible individual stock**
  (AMZN/BABA/MSFT/NFLX) — in the SAME March-2023 chapter. So 10-vs-13 is (at least here) a
  CLASS split, not purely era drift: indices=10, stocks=13.
  **This matches the code exactly as configured today** (equity_indices=10 kept, equities=13
  applied in C-14). Stock timeline refines to: 13 (Mar-23) -> 10 (Aug-23, C-19) -> 13 (2025
  course) — code's 13 aligns with both endpoints. The equity_indices=10 value gets its first
  direct multi-symbol live corroboration. Item stays open only for a 2024-era index sighting
  (wave-1 agents on CW40/CW44/CW08-equity/JAN/FEB roadmaps will supply it).
- **Two seasonality tools split by class too**: `Campus Algo Forecast (10,100,False,False,False)`
  on indices/gold, but stocks run `Campus True Seasonality (5, 100, False, False, False)` —
  AverageYears=5 on stocks (fits the stocks 5/6 sightings from CW50/CW35). Python already has
  both classes (Seasonality multi-lookback + TrueSeasonality); no action.
- **Zero COT content in the whole chapter** (no COT pane, no COT vocabulary) — honestly reported
  by the reader, no force-fit. No WeeklyLookBack evidence.
- ZigZag absent 22/22. Dated @YM/@ES crosshair tuples banked (Nov-22..May-23).
- Reader-flagged anomalies (no code impact): Bernd says "gold" while pulling up XAGUSD once;
  Whisper mis-hears "Nvidia" as "and media"; one META attribution is context-inferred only.

## C-25 — JAN-2024 Monthly Roadmap (Equity Indices): index Length=10 confirmed in 2024 era

- **equity_indices Length=10 now confirmed in BOTH eras**: legible Length=10 on @NQ/@RTY/@ES
  (3-ref V2) in Jan-2024, adding to Mar-2023 (C-24). The code's equity_indices=10 is now
  corroborated at both ends of the corpus. Era question for INDICES effectively closed;
  only the stock-Length 2024 sighting remains thin (title bars truncated on all 8 stock charts
  this chapter).
- **Stock ref-legs claim, handled with care**: the reader stated stock refs "refute bonds-only"
  because the three ref SYMBOLS are named identically on stock charts. That's expected — the
  V2 title always prints all three symbol params; what matters is the boolean flags. The
  verbatim actually captured is `("@US","@GC","$DXY",True,False,...` — ref1 bonds=True,
  ref2 gold=False, ref3 TRUNCATED. That is CONSISTENT with bonds-only (True,False,False), and
  our C-14 fix rests on two FULL settings dialogs (OTC M3 L3 frame_000808 Dollar unchecked;
  CW05-2023 MSFT ShowReferenceSymbol3=False) plus CW50/CW03 title bars. Title-bar truncation
  cannot overturn dialog evidence (Phase 33 discipline). **No change; watch item**: if any
  2024-era stock settings dialog ever shows ShowReferenceSymbol3=True, revisit.
- COT: Smart Money Index 0-100 only (loaded on @NQ; Waiting on RTY/ES/YM); no group named, no
  dialog — WeeklyLookBack still unanswered. Algo Forecast (10,100,F,F,F) on index AND stocks
  this session (AverageYears varies per session as established; no action).
- ZigZag absent 23/23. AAPL dated markers 01/05/24 + 02/14/24 with price levels banked.
- Incidental: TradeStation error dialog "Add at least 1729 days of history" on @RTY Algo
  Forecast — implies the tool needs ~4.7 years of daily history minimum; useful context for
  our own min-history guards. Recording date verified via taskbar clock (1/2/2024).

## C-26 — FEB-2024 Monthly Roadmap (Equity Indices): index Length reads 30 — single-chapter anomaly, NO CHANGE

- **Anomaly**: @YM/@ES show `_CampusValuationTool_V2("@US","@GC","$DXY",True,True,True,30,...)`
  — the post-boolean numeral is **30**, repeated identically at 4 separated timestamps (solid
  read), no dialog opened to confirm the position is Length. Context that makes this tricky:
    * Jan-02-2024 roadmap (C-25): indices Length=10 legible.
    * Mar-2023 (C-24): indices 10.
    * The PRE-audit code had equities Length=30 — this Feb-2024 roadmap is a plausible source
      of that original 30 (a real sighting, over-generalized to stocks).
  Possibilities: genuine per-session change (10->30->?), or the JAN read `True,True,10` /
  this `True,True,True,30` differ by a mis-counted boolean. **Phase 33 discipline: single
  chapter cannot move code. equity_indices stays 10.** Arbiter in flight: CW08-2024 Equity
  Indices & Stocks (Feb-17, two weeks later) — if it shows indices=10, the 30 is a one-off
  exploration; if 30, we have a real late-era shift to weigh.
- Stocks (AAPL/GOOG/META/NVDA): `@US=True, @GC=False`, ref3+Length truncated on every stock
  chart — consistent with bonds-only (C-14) yet again; stock-Length-2024 still unsighted.
- COT: Campus Smart Money Index 0-100; no dialog (WeeklyLookBack open). Third study name
  variant catalogued: "Campus Smart Money RAW Commercial (1)" (2-line raw) alongside the
  known 1-line RAW.
- Algo Forecast: indices (10,100,F,F,F), stocks (5,100,F,F,F) — clean class split this
  session; per-session AverageYears drift already established, no action.
- ZigZag absent 24/24. @YM trendline tooltip (02/09/24, 39144->39311) + seasonal-analogy date
  cluster banked. Browser/YouTube/PowerPoint overlay frames correctly excluded by reader.

## C-27 — CW43-2023 Precious Metals (Oct-22): PM Commercials-primary corroborated; AverageYears "15 era" refuted

- **PM COT group corroborated** via Bernd's OWN forum post on Copper, verbatim:
  "COT: Retailers bearish. Commercials Bullish" — exactly the Commercials-primary +
  Retail-contrast pattern the code implements for precious_metals (Phase 17). Spoken audio
  ("let's look first at the smart money" on Platinum; "stable in terms of retailers" on
  Silver) is consistent. Reader honestly rated it moderate, not high — no on-screen legend
  text named the groups. **No change needed; supports current config.**
- **Counter-evidence handled — AverageYears was 10, not 15, in Oct-2023**: verbatim
  `Campus Algo Forecast (10, 100, False, False)` identical on Gold/Silver/Platinum across 10+
  frames. This refutes the "futures AverageYears=15 through Aug-Oct 2023" assumption carried
  since C-19. Corrected timeline: Jan-23 10 | Aug-23 15 (CW35 futures) | **Oct-23 10** |
  Dec-23 10 | Jan/Feb-24 10 (indices) / 5 (stocks). Reading: 15 was the outlier exploration,
  10 is his default. **No code action** — the Python votes across multiple lookbacks by
  design precisely because this parameter is exploratory; this finding strengthens that
  design rather than challenging it.
- **New signature variant**: 4 params `(10, 100, False, False)` here vs 5 params
  `(10, 100, False, False, False)` in Jan/Feb-2024 — the tool gained a parameter (PrintDebug,
  per the CW05 dialog) between Oct-23 and Jan-24. Confirms era-versioning of the study itself;
  irrelevant to our re-implementation.
- Valuation: `("@US","@GC","$DXY",True,True,10,...` Length=10 (Oct-23 metals) — third boolean
  truncated in every frame. Consistent with futures all-True default.
- COT pane: Smart Money Index 0-100; no dialog anywhere (WeeklyLookBack still open, now
  unsighted in 5 consecutive chapters).
- ZigZag absent 25/25. PM dated tuples banked; reader correctly discarded crosshair dates
  beyond the recording date as mouse-panning artifacts (good discipline).
- Note: no live Copper/Palladium charts this chapter despite the intro promising them — both
  covered only via prior forum posts.

## C-28 — CW44-2023 (Oct-29): indices Length=13 one week after 10 → Valuation Length is SESSION-VARIABLE

- **Hard conflict, both readings strong**: CW44 (Oct-29-2023) shows indices @YM/@ES/@NQ
  **Length=13** on 3 independent UN-TRUNCATED full-screen labels; CW43 (Oct-22-2023), seven
  days earlier, showed **Length=10** on metals with the same tool. Combined index/futures
  timeline now:
    Mar-23 **10** (C-24) | Oct-22-23 **10** (C-27) | Oct-29-23 **13** (this) |
    Jan-02-24 **10** (C-25) | Feb-03-24 **30** (C-26)
  Four different values across five sessions, with a 7-day flip. **Conclusion: Bernd changes
  Valuation Length per session — it is an exploratory view setting, exactly like AverageYears
  (C-27), NOT a fixed constant.** This reframes every prior "era drift" reading, including the
  stock 13->10->13 sequence.
- **DESIGN QUESTION RAISED (no code change yet)**: our `VALUATION_LENGTH_BY_CLASS` commits to a
  single Length per class. If the true methodology is "look at several", a multi-length
  consensus — mirroring `Seasonality.multi_lookbacks`, which the audit already validated as the
  right shape for the same reason — would be more faithful and more robust than any single
  value. Deferred deliberately: this is live-trading signal logic, and the remaining queued
  chapters (CW42, CW49-roadmap, CW51, CW52, CW08-equity in flight) will show whether 10 is at
  least the MODE. Do not act on 5 data points.
  **Interim: equities=13 and equity_indices=10 both stay** — 13 is the 2025-course teaching
  value (most recent deliberate instruction) and 10 is the most frequent live index reading.
- **Stocks bonds-only corroborated AGAIN, loudly**: 9 symbols (AAPL/AMZN/GOOG/MSFT/NFLX/NVDA/
  TSLA/META/RACE) all `@US=True, @GC=False`. That is now 6 independent chapters + 2 settings
  dialogs. C-14 fix is solid. (ref3/$DXY truncates structurally on narrow stock panes — the
  reader correctly identified this as a pane-width limitation, not random.)
- **Algo Forecast AverageYears=5 on INDICES** here (`(5, 100, False, False, False)`), vs 10 on
  indices in Jan/Feb-24 and 10 on metals a week earlier. Same session-variable conclusion;
  multi-lookback design already correct. No action.
- Tool renders as both `CampusValuationTool_V2` and `_CampusValuationTool_V2` depending on pane
  width — same indicator, cosmetic only. Useful to know for future frame reads.
- COT: Smart Money Index 0-100; "the retailers" spoken over @YM panels (no formal group name);
  no dialog (WeeklyLookBack unsighted 6 chapters running).
- ZigZag absent 26/26. ~9 dated tuples banked (mostly medium/low confidence).

## C-29 — CW01-2023 (Dec-31, multi-asset): forex+PM groups confirmed; "stock refs" claim self-refuted

- **Forex = Retail confirmed AGAIN (post-fix corroboration #3)**: AUDUSD verbatim "the retailers
  are getting more bullish on the Aussie dollar", NZD "...super bullish". No counter-evidence.
- **Precious metals = Commercials, explicit**: "the small money, the commercials" (Whisper
  mis-hears "smart money" as "small money") on Gold/Platinum. Matches code exactly.
- Sugar + Cotton show the classic commercials-pinned-high / retail-pinned-low visual — consistent
  with softs=Commercials, no isolated quote.
- **The reader's headline "counter-finding" on stock refs is contradicted by its OWN detail**:
  the summary claimed refs are "identical on every symbol including stocks", but finding F-03
  records WMT verbatim as `CampusValuationTool_V2 ("@US","@GC","$DXY", True, False, ...)` —
  ref1 bonds True, **ref2 gold False**. That IS bonds-only. The "identical" observation refers
  to the three ref SYMBOL names, which the V2 title always prints regardless of the flags.
  **C-14 stands, now corroborated by a 7th chapter.** Recording this explicitly because the
  same misreading has now surfaced three times (C-25, C-26, here) — future readers should be
  told: judge ref legs by the BOOLEANS, never by the symbol list.
- **F-22, useful structural fact**: the Smart Money Index / RAW pair appears ONLY on futures,
  never on the 3 stock charts — COT data doesn't exist for single equities. Our stock path
  correctly doesn't require COT.
- Algo Forecast: 5 on BABA/WMT, 10 on AAPL later + all futures (AAPL showed 5 earlier in the
  same session!) — same-session parameter switching, on camera. Reinforces C-27/C-28.
- COT variant 0-100; no dialog (WeeklyLookBack unsighted 7 chapters). ZigZag absent 27/27.

## C-30 — CW05 Soybeans/PA (Jan-29-2024): Length 10 → 30 in TWO DAYS — session-variable, PROVEN

- **Decisive on C-28's hypothesis**: CW05 FX Edition (Jan-27-2024) = `...True,True,True,10,...`;
  CW05 Soybeans/PA (**Jan-29-2024**, two days later) = `..."@US","@GC","$DXY",True,True,True,30,...`
  on both @S and @PA. Same tool, same era, same workspace family, 48 hours apart, 10 vs 30.
  **Valuation Length is definitively a session-level exploratory setting, not a per-class
  constant.** Observed value set across the corpus: {10, 13, 30}.
- Style-tab dialog captured (not Inputs) revealing the study's internal plot list: RefSym,
  Diff1-3, DataDate, ZeroLine, LowerThresh, UpperThresh — confirms the tool computes THREE
  diffs (one per ref leg) plus a zero line and the ±threshold pair, exactly the shape our
  `Valuation` class implements. Structural validation of the re-implementation.
- Soybeans COT: Bernd raises then explicitly REJECTS the red line — "I really, really couldn't
  care less about the red line because these are not retailers per se... but these are"
  (cut off, ts 11:52). Reader honestly flagged it as a gap rather than force-fitting it to
  grains=Commercials. Notably this is direct evidence that the red line is NOT always retail on
  agricultural contracts — relevant to the C-22 color-mapping caveat, though it does not touch
  the forex conclusion (which rests on spoken group names, not colors).
- Algo Forecast (10,100,F,F,F) both symbols. ZigZag absent 28/28. No COT dialog.
- Palladium: no group named; Smart Money panel never finished loading before the segment ended.

## C-31 — RESOLUTION of the Length=30 anomaly: it is the LONG-TERM TOGGLE, not drift. Code is correct.

**This supersedes the "session-variable / random drift" framing in C-26, C-28 and C-30. Do not
act on those; read this instead.**

Direct transcript proof, CW05 Soybeans/PA (2024-01-29), the very chapter that read Length=30 —
Bernd narrating at the valuation pane:
  [0:13:34] "And now we looked at valuation and valuation, we can, we can change between
             **long term valuation and short term valuation**."
  [0:13:41] "**Now I'm checking long term valuation.**"
  [0:13:54] "So we are **long term undervalued**, which is great."

So Length=30 was him deliberately toggling the LONG-TERM view on camera — not a changed default.
This matches, word for word, what `BP_rules_engine.py:170-192` already documents from the OTC
Module 3 Lesson 3 slide: **"Equity indices and stocks -> 13 days short term / 30 days long term"**,
and from CW07-Corn (2024-02) where he switches 10 -> 30 narrating "short term" -> "long term".

**Reconciled reading of every Length sighting** (short-term default vs long-term toggle):
  - 10 / 13  = the SHORT-TERM default (Mar-23 indices 10, Oct-22-23 metals 10, Oct-29-23
               indices 13, Jan-02-24 indices 10, Jan-27-24 FX 10, stocks 13 per slide+dialogs)
  - 30       = the LONG-TERM alternate view (Feb-03-24 roadmap, Jan-29-24 Soybeans/PA)
  The 10-vs-13 residue within short-term is the genuine per-class/per-era wobble already
  handled: indices 10, stocks 13, both corroborated at multiple dates.

**CODE VERDICT: no change. `VALUATION_LENGTH_BY_CLASS` (10 non-equity / 10 indices / 13 stocks)
is the correct SHORT-TERM configuration, and the pre-existing comment block at
`BP_rules_engine.py:170-192` had already reasoned this out correctly before the vision audit.**
The multi-length "design question" raised in C-28 is **withdrawn** — a consensus across 10/13/30
would blend two horizons Bernd treats as separate views, which is worse, not better. If a
long-term view is ever wanted it belongs as an explicit separate signal, never averaged in.

Process note (Phase-33 discipline paid off twice here): C-26 and C-28 both flagged 30/13 as
possible code bugs and both were held at "log only, no change" pending more evidence. Acting on
either would have corrupted a correct config. Transcript context, not just frame pixels, is what
resolved it — future chapter prompts should ask readers to quote any spoken
"short term / long term" narration next to a Length reading.

## C-32 — CW40-2023 Equity Roadmap + CW08-2024 Equity: bonds-only PROVEN by plot count; index Length=10 arbitrated

- **Strongest bonds-only evidence in the whole audit (CW40, Oct-3-2023)**: on stock charts the
  tool plots **only ONE line — the bonds leg** (`True,False,...`), while index/futures charts
  plot **three**. Line COUNT is behavioural proof, immune to the title-truncation ambiguity that
  produced three false "counter-findings" (C-25/C-26/C-29). Combined with the 2 settings dialogs
  and 7 chapters of `@GC=False`, **C-14 (equities refs = bonds only) is now settled beyond doubt.**
  Note the reader's framing "partially refutes bonds-only, code still declares 3 refs" — that's a
  UI observation (the V2 title always prints all 3 ref symbols); functionally one leg is active,
  which is exactly what our `VALUATION_REFS['equities'] = ["ZB=F"]` produces.
- **Index Length arbitrated = 10 (CW08 Equity Indices, Feb-17-2024)**: fully un-truncated on @ES
  and @YM, cross-confirmed on @RTY. This is two weeks AFTER the Feb-3 roadmap that read 30, and
  it lands on 10 — exactly as C-31 predicted (30 was the long-term toggle). **`equity_indices=10`
  is correct and now confirmed at Mar-23, Oct-23, Jan-24 and Feb-24. Era question CLOSED.**
- Stocks: `@US=True, @GC=False` again across 5 more symbols (AAPL/MSFT/GOOG/NVDA/AMZN).
  Stock-side Length still never legible in ANY chapter — it truncates structurally, not by pane
  width (CW40 confirms this even full-screen). Our 13 rests on the OTC slide + 2 dialogs + CW18;
  that remains the only evidence class that can settle it, and it's sufficient.
- Cosmetic: indices render `_CampusValuationTool_V2` (underscore), stocks `CampusValuationTool V2`
  (no underscore) — verified by direct crop comparison, i.e. genuinely two study instances
  configured differently, not one truncated name. Consistent with per-class configs.
- Algo Forecast: CW40 indices **15**; CW08-equity indices **10**, stocks **5** (clean in-chapter
  contrast). Per-session variation again — multi-lookback design stands, no action.
- **Code citation error found & corrected**: `BP_rules_engine.py:40` credits "Ch.107 CW40" for the
  gold/PM 26w lookback quote. The CW40 *Equity Indices* video contains zero instances of
  "look back"/"26". The quote is from the CW40 **Precious Metals** sibling session — where our
  own `per_chapter/2023-10-01_CW40_PreciousMetals.md` records it. Comment is imprecise, not wrong.

## C-33 — WeeklyLookBack 20-vs-26 RESOLVED: 26 confirmed by dialog + tape. Code correct.

The watch item opened in C-21 is closed. `per_chapter/2023-10-01_CW40_PreciousMetals.md` (F-02,
frame_000465, @GC Weekly) holds a **Format Study dialog** reading `WeeksLookBack = 26`, with
Bernd confirming it out loud on tape: **"I would say 20 look back. It's 26 look back is 26. Yes."**
— he guesses 20, checks the dialog, and corrects himself to 26. Same dialog: FuturesOnly=1,
Display Commercial/NonCommercial/Speculator=True, thresholds 80/20, MidPoint=False, LineAt100=True.

- **Our `COTIndex` default of 26 weeks is correct**, matching both this dialog and the canonical
  V2 Pine (`input.int(26, "Number of weeks")`). No change.
- Explains the C-21 crude anomaly: the CW08 @CL dialog showed `WeeklyLookBack = 20` while Bernd
  said "26 weeks look back" in the same breath — his stated intent is 26; the 20 on that one
  crude chart is a stale per-chart leftover, the same kind of guess he corrected here. Our crude
  override (`CRUDE_OIL_COT_26W_SYMBOLS` -> 26, cited as dialog-confirmed twice) is consistent with
  his intent and with gold's dialog. **No change; C-21 watch item closed too.**

## C-34 — CW49-2023 Ag/Commodities/Metals (Dec-03): six markets checked, all match code

Checked each named group against the actual routing in `BP_rules_engine.py` (SOFT_COMMODITY_SYMBOLS
frozenset + `_indicators_for_class`) rather than against the class label alone:

| market | chapter verbatim | code routes to | verdict |
|---|---|---|---|
| Cotton | "if we look at the smart money the commercials here..." | CT=F REMOVED from softs (Phase 14) -> 'commodities' = **Commercials 52w** | MATCH |
| Gold | "commercials are not that great... we are overvalued" | precious_metals = **Commercials** | MATCH |
| Platinum | Commercials bullish + "retailers are neutral" (contrast) | PM Commercials primary + Retail contrast | MATCH |
| Palladium | "retailers are getting bearish again... commercials is next level stuff" | same | MATCH |
| Swiss Franc | "because of retailers being bearish" | forex = **Retail contrarian** (C-22) | MATCH — post-fix corroboration #4 |
| Crude | "when I look at the smart the well the..." (cut off) | energies = Commercials | INCONCLUSIVE, unchanged |
| Corn | no group named (pure price commentary) | — | no evidence, not force-fit |

- **No code change.** The initial "Cotton = Commercials contradicts soft_commodities=NonComm"
  concern is resolved by reading the frozenset: Cotton/Corn/Wheat/Soybeans/Coffee/Cocoa were all
  already removed from it, leaving only **Sugar (SB=F) and OJ (OJ=F)** on the Non-Commercials
  path, both flagged "corpus silent" in the code's own comment.
- **New open item (low priority)**: CW01 (C-29) showed Sugar with the classic
  commercials-pinned-high / retail-pinned-low visual, hinting Sugar may also belong on the
  Commercials path. Not actionable — no spoken group name on a Sugar frame yet. Watch for a
  Sugar/OJ verbatim in the remaining chapters before touching that frozenset.
- Valuation `("@US","@GC","$DXY",True,True,True,10,...)` on 7 of 9 markets — Length=10
  short-term default again (consistent with C-31). Algo Forecast uniform (10,100,F,F,F) across
  all 9 symbols — cleanest AverageYears=10 confirmation for the Dec-2023 era.
- COT variant 0-100; no dialog. ZigZag absent 29/29. ~19 dated tuples banked.
- Reader self-corrected a @PA/@PL ticker misread via a maximized pop-out title bar — good
  discipline, noted so the Palladium/Platinum attributions above can be trusted.

## C-35 — CW42-2023 (Oct-15): indices Length=13 AGAIN → genuine 10-vs-13 era split for equity_indices

- CW42 shows **@NQ/@YM/@ES all Length=13**, corroborated on 20+ full-screen frames (booleans
  `True,True`). With CW44 (Oct-29, also 13) that is TWO independent Oct-2023 chapters.
- **Full equity-index Length record** (short-term readings only; the 30s are the long-term
  toggle per C-31):
    Mar-2023 **10** | Apr-2023 **13** (CW18 dialogs, per existing code comment: he edits
    30->13 on @NQ and 10->13 on @ES saying "put here on 13 is as better for indices") |
    Oct-15-2023 **13** | Oct-29-2023 **13** | Jan-02-2024 **10** | Feb-17-2024 **10**
  Plus the 2025 OTC slide: "Equity indices AND stocks -> 13 days short term".
- **This is a real teaching-vs-live split**, not a misread: teaching (slide + his own on-camera
  "13 is better for indices") says 13; his 2024 live practice says 10. Both are well-evidenced.
- Stocks: `@US=True, @GC=False` again (5 more symbols). Stock Length never legible — 8th chapter
  running; confirms it truncates structurally.
- Algo Forecast N=15 on all three index futures (Oct-23), N=4 on BTC (matches the code's
  documented Bitcoin 4-year seasonality rule — nice independent confirmation of that constant).
- COT 0-100 variant + RAW companion; no dialog. ZigZag absent 30/30.
- Calendar popup mislabels this session "Precious Metals Edition" — campus calendar error, the
  content is indices/stocks. Noted so the report isn't mistaken for the CW43 PM chapter.

## C-36 — CW51-2023 (Dec-16): PM read led by RETAIL this chapter — nuance, not a contradiction

- Gold and Silver both get explicit repeated "the retailers" as the lead commentary, with
  "smart money"/Commercials invoked once as the counter-side. Taken alone this looks like it
  cuts against precious_metals = Commercials-primary.
- **Assessment: consistent with the code as written, no change.** Our PM path is Commercials
  PRIMARY *plus* the retail contrast — `cross_category_signal()` exists precisely to trade the
  commercials-vs-retail opposite-extreme setup ("Retailers bearish + Commercials bullish =
  perfect PM buy"). A session where he narrates the retail leg first is the same setup described
  from the other side; the red-pinned-high / blue-pinned-low numerics the reader recorded match
  the contrast pattern exactly. Weighed against CW49 + CW01 + Ch.107/147/122/132 all showing
  Commercials-primary on gold, one lead-with-retail session does not move the routing.
- Valuation: futures `True,True,10...`, stocks `True,False,...` — bonds-only again (9th chapter).
- Algo Forecast N=5 for EVERY symbol incl. futures — 6 days after CW50 had futures at N=10.
  Fastest AverageYears flip observed yet; per-session exploration reconfirmed, no action.
- COT 0-100; no dialog. ZigZag absent 31/31. 8 dated tuples banked (incl. Gold Smart Money
  Index = 96 on 12/15/23, effectively the live bar — good replay fixture).

## C-37 — equity_indices Length 10-vs-13 QUANTIFIED: material, but the change gate is NOT met → keep 10

**Measured, not assumed** (`scratchpad/valuation_length_sensitivity.py`, engine's real
`Valuation.get_bias()` per-line voting, VALUATION_REFS['equity_indices'], daily 2021-2024,
943 bars/symbol):

| symbol | bias differs | OPPOSITE bias | median abs delta | p90 abs delta |
|---|---|---|---|---|
| ES=F | 29.6% | 1.48% | 14.08 | 36.23 |
| NQ=F | 31.1% | 2.33% | 15.72 | 39.68 |
| YM=F | 31.1% | 1.27% | 13.46 | 35.95 |
| RTY=F | 30.3% | 3.08% | 15.25 | 40.00 |

So the choice is **NOT cosmetic** — it flips the valuation bias on ~30% of bars and produces
outright OPPOSITE (bullish vs bearish) readings on 1.3-3.1%. On the final bar, 3 of 4 indices
disagreed (bullish at 10 vs neutral at 13). The C-28 instinct to treat Length as low-stakes was
wrong; this parameter matters.

**Evidence ledger for equity indices (short-term readings only):**
  - **13**: 2025 OTC slide ("Equity indices AND stocks -> 13 days short term"); CW18 Apr-2023
    where he EDITS 30->13 (@NQ) and 10->13 (@ES) saying "put here on 13 is as better for
    indices"; CW42 Oct-15-23 (20+ full-screen frames); CW44 Oct-29-23.
  - **10**: CW10 Mar-2023; JAN roadmap Jan-02-24; CW08-Equity Feb-17-24 (un-truncated on
    @ES/@YM, cross-confirmed @RTY); CW09 Feb-2024 (cited in existing code comment).
  - Note 10 is also the Pine DEFAULT, so a 10 sighting can mean "never touched it" while a 13
    sighting is always deliberate. That asymmetry favours 13 — but it is an inference, and the
    2024 live evidence for 10 is direct, un-truncated, and consistent across three chapters.

**DECISION: keep `equity_indices = 10`. No code change.** The existing comment sets an explicit
gate — *"Needs a recent-era index dialog before changing. Do not 'fix' to 13 without it."* — and
that gate is still unmet: every 2024 sighting is a title bar, not a settings dialog. The whole
2024 live corpus reads 10, and a live trading system should track his live practice. Flipping a
parameter that moves 30% of index verdicts on inference alone is exactly the Phase-33 mistake.
**Escalated to the user as a known, now-quantified open risk** rather than silently decided.
**What would settle it**: any 2024-2025 equity-INDEX Format Study / Customize Indicator dialog
showing the Length field. Remaining queued chapters + the Practical Application corpus are the
place to look; readers should be told to open/zoom any index indicator dialog they see.

## C-38 — CW16-2023 (Apr-16): INDEX settings dialog found — and it reframes C-37 in favour of keeping 10

**First full Valuation settings dialog captured on an equity INDEX (@YM), verbatim:**
`ReferenceSymbol="@US", Length=13, NumDecimalsOfPrecision=3, RescaleMaximum=100,
RescaleMinimum=-100, RescaleLength=100, UpperThreshold=75, LowerThreshold=-75`

Critically, this dialog is for **"Campus Valuation Index" — the SINGLE-reference tool**, not the
3-ref `_CampusValuationTool_V2`. It has NO boolean flags at all, and Length is the *second*
parameter. That single fact resolves a lot of accumulated confusion:

- **He ran TWO different valuation tools, and they migrated by era:**
    * 2023 (Mar-Apr, this chapter + CW10): **single-ref `Campus Valuation Index`**, ReferenceSymbol
      = `@US` (bonds ONLY, hard-coded — no gold, no dollar), on indices AND stocks.
    * Oct-2023 -> 2024: **3-ref `_CampusValuationTool_V2`** with `True,True,True` on indices.
  So the tool changed, not just the number. Comparing a 2023 Length to a 2024 Length is partly
  comparing two different indicators.
- **The single-ref dialog is yet another bonds-only confirmation** — `ReferenceSymbol="@US"` with
  no other leg even available. Independent of the C-14 stock dialogs, same conclusion.
- **Effect on C-37 (equity_indices 10-vs-13): strengthens KEEP 10.** Re-sorted by tool:
    * `Campus Valuation Index` (single-ref, 2023): Length 10 (Mar) then **13** (Apr dialog, CW18 edit)
    * `_CampusValuationTool_V2` (3-ref): **13** Oct-23 -> **10** Jan-24 -> **10** Feb-24
  Our code models the **3-ref tool** (`VALUATION_REFS['equity_indices'] = DXY+ZB+GC`), and the
  most recent live readings of *that* tool are 10, twice, un-truncated. The 13s are either the
  other tool (Apr-2023) or the older 3-ref era (Oct-2023). **`equity_indices = 10` stays, now on
  firmer ground than before.** The gate ("recent-era index dialog") is still technically unmet —
  this dialog is Apr-2023 and for the other tool — but the tool-migration reading removes most of
  the tension. Risk downgraded from "real open risk" to "documented, low".
- Chapter had zero forex/commodities, so no COT content at all (honestly reported, not force-fit);
  neither COT variant appears anywhere.
- Bitcoin: `CampusValuationTool V2 ("@US","@GC","$DXY",True,True,True,...)` 3-ref, plus
  `Campus True Seasonality (4, 100, False, False, False)` — **AverageYears=4 on BTC again**,
  a third independent confirmation of the code's Bitcoin 4-year seasonality constant.
- Indices: `Campus Algo Forecast (15, 100, False, False, False)` (Apr-2023 = 15).
- ZigZag absent 32/32. Dated tuples banked (ES 04/11/23 Valuation=42.20; AMZN 02/14/23 =17.01);
  reader correctly flagged two post-recording dates as forward gridlines.

## C-39 — CW21-2023 (May-20): same session, same tool, Length 10 futures/index vs 13 stocks → C-37 CLOSED

**The cleanest Length evidence in the entire audit.** One session, one tool
(`Campus Valuation Index`, single-ref), both classes side by side:
  - USDCHF and **@NQ (equity index)**: `("@us"/"@US", 10, 3, 100, -100, 75, ...)` -> **Length=10**
  - All 10 stocks (AAPL/AMZN/BABA/META/GOOG/MSFT/NFLX/NVDA/PFE/TSLA):
    `3383376 ("@US", 13, 3, 100, -100, 75, ...)` -> **Length=13**

Same day, same indicator, no era confound, no tool confound, no truncation — the split is
**by asset class**, and it is exactly what the code encodes:
`VALUATION_LENGTH_BY_CLASS = {..., 'equity_indices': 10, 'equities': 13}`.

**C-37 is CLOSED. `equity_indices = 10` and `equities = 13` are both correct. No code change.**
Consolidated index reading across the corpus, by tool:
  - single-ref `Campus Valuation Index`: Mar-23 **10**, May-23 **10** (this), Apr-23 **13**
    (CW16 dialog / CW18 edit — the only 13s on an index, and they sit between two 10s)
  - 3-ref `_CampusValuationTool_V2`: Oct-23 **13**, Jan-24 **10**, Feb-24 **10**
  Indices land on 10 in 4 of 6 sightings including the two most recent, and 10 is what a
  same-session A/B against stocks shows. The residual 13s look like the transient experiment
  he narrates in CW18 ("put here on 13 is as better for indices") that did not stick.
  The ~30% bias sensitivity measured in C-37 remains true and is now simply the cost of being
  wrong — which the evidence says we are not.

Other findings:
- **Live reference-leg swap caught on tape**: on USDCHF he switches the single-ref tool from
  `@US` (30-yr bond) to `@GC` (gold), saying "it's gold here but I can go back to US". Direct
  evidence that the single-ref tool's one leg is a rotating view, which is precisely why the
  3-ref V2 tool (what our code models, all legs at once) superseded it. Supports our
  multi-reference forex config rather than any single-ref reading.
- The `3383376` ID prefix appears on stock instances but NOT on the futures/FX instances in the
  same session — so it is a per-chart study instance id, not a fixed artifact. Useful: its
  presence/absence distinguishes two separately-configured copies of the same study, and it is
  further proof the stock config is a deliberately separate instance.
- No COT content at all this chapter (no forex/metals/ags COT panes, zero group vocabulary) —
  honestly reported as a gap.
- Algo Forecast `(15, 100, False, False, False)` on USDCHF/@NQ only, never on stocks (May-23=15).
- ZigZag absent 33/33. Dated tuples banked (AAPL 2023-05-03 Valuation Index 28.70 etc.).

## C-40 — CW19 + CW17 (May/Apr-2023): CORRECTION to C-39's tally. Index Length is genuinely mixed in 2023.

**Correcting my own overstatement in C-39.** C-39 claimed indices "land on 10 in 4 of 6
sightings including the two most recent". Two more chapters have since landed and that tally
is WRONG. The honest, complete record for equity indices:

| date | chapter | tool | index Length |
|---|---|---|---|
| Mar-05-23 | CW10 | single-ref | **10** |
| Apr-16-23 | CW16 | single-ref (DIALOG) | **13** |
| Apr-24-23 | CW17 | single-ref | **13** |
| May-08-23 | CW19 | single-ref | **13** (@NQ, @ES) |
| May-20-23 | CW21 | single-ref | **10** (@NQ) |
| Oct-15-23 | CW42 | 3-ref V2 | **13** |
| Oct-29-23 | CW44 | 3-ref V2 | **13** |
| Jan-02-24 | JAN roadmap | 3-ref V2 | **10** |
| Feb-17-24 | CW08-Equity | 3-ref V2 | **10** |
| (Feb-2024) | CW09 (per existing code comment) | — | **10** |

So it is **13 five times and 10 five times** — not the lopsided picture C-39 painted. In 2023 he
leans 13 (4 of 5); in 2024 he is consistently 10 (3 of 3). C-39's per-class same-session finding
still stands and is still valuable (CW21: @NQ=10 while 10 stocks=13 that same day), but it was
one session, and CW19 shows @NQ AND @ES at 13 twelve days earlier. **Do not cite C-39's tally.**

**DECISION UNCHANGED — `equity_indices` stays 10 — but on narrower, stated grounds:**
  1. The 2024 era is unanimous at 10 across three chapters, and 2024 is both the most recent
     live practice and the era of the 3-ref tool our code actually models.
  2. The existing in-code gate (a recent-era index dialog) is still unmet, and the standing
     instruction is "Do not 'fix' to 13 without it."
  3. C-37 measured the cost of being wrong (~30% of bars change bias, 1.3-3.1% invert), so this
     is a real, quantified, and now ACCURATELY-tallied open question — **not** a settled one.
**Status: OPEN, low-confidence-either-way, no change.** Flag for the user rather than resolve
silently. The 2023 evidence genuinely favours 13; only the recency and tool-match arguments
carry 10.

Other findings from these two chapters:
- **AverageYears live-edited on camera**: CW17 TSLA 5 -> 10, and on BABA he says "I do five
  years here at least". Definitive proof AverageYears is an exploratory per-chart view.
  Multi-lookback design confirmed correct for the 4th time.
- **Algo Forecast input names captured from a TSLA dialog**: AverageYears,
  ProjectNumberBarsIntoTheFuture, AlignFirstFutureBarWithBarClose,
  StartFutureProjectionYearBefor[e...], PrintDebug — matches the CW05 FX dialog exactly.
- **Bitcoin `Campus True Seasonality (4, ...)` in BOTH chapters** — 4th and 5th independent
  confirmations of the code's BTC 4-year constant.
- CW19 flags a 4-param `Campus Algo Forecast (N,100,False,False)` on @NQ/@ES vs the 5-param
  form elsewhere — same study-version drift already noted in C-27. Cosmetic, no action.
- An "Add Studies" library dialog (CW17, BABA) shows `Campus Smart Money Index` and
  `Campus COT Index` / `Campus COT Index_3383376` as SEPARATE library entries — independent
  structural confirmation of the dual-tool finding (C-19).
- Neither chapter touches any COT-eligible market: zero COT evidence, correctly reported as a
  gap by both readers rather than force-fit. ZigZag absent 34/34 and 35/35.

## C-41 — CW24 + CW49-Roadmap: index tally now favours 10. C-37/C-40 question effectively settled.

Two more index readings land, and both are **10**:
  - **CW24 (Jun-11-2023)**: `Campus Valuation Index` **Length=10 on indices/bonds, 13 on
    individually-analyzed stocks** — a SECOND same-session, same-tool class split (CW21 was the
    first). Two independent A/B sessions now show index=10 / stock=13 side by side.
  - **CW49 Monthly Roadmap (Dec-02-2023)**: `_CampusValuationTool_V2 ("@US","@GC","$DXY",
    True,True,True,10,...)` **Length=10** on @YM/@US/@RTY/@NQ/@ES — the 3-ref tool at 10,
    two months BEFORE the Jan/Feb-2024 readings, filling the gap between the Oct-2023 13s
    and the 2024 10s.

**Updated complete tally, superseding C-40's "5-5 tie":**
  **10** — Mar-05-23, May-20-23, Jun-11-23, Dec-02-23, Jan-02-24, Feb-17-24, CW09 Feb-24 = **7**
  **13** — Apr-16-23 (dialog), Apr-24-23, May-08-23, Oct-15-23, Oct-29-23 = **5**
  The 13s cluster in two bursts (Apr-May 23, Oct 23); 10 is the value he returns to, and it is
  unanimous from Dec-2023 onward across four consecutive chapters.

**DECISION: `equity_indices = 10` CONFIRMED. No code change.** Grounds, now much stronger than
in C-40: (1) 7-vs-5 overall; (2) unanimous in the four most recent chapters; (3) two independent
same-session class splits show exactly the code's index-10 / stock-13 pairing; (4) the 3-ref
tool our code models reads 10 in Dec-23, Jan-24 and Feb-24. The C-37 sensitivity (~30% of bars)
remains the cost-of-being-wrong, but the evidence no longer points the other way.
**C-37/C-40 downgraded from open risk to RESOLVED-by-weight-of-evidence.** A 2024-25 index
settings dialog would still be the gold standard if one ever surfaces.

- **Equity-index RETAIL contrarian, on the Dow**: CW24 @YM verbatim — "the retailers are getting
  the most bullish since one year..." with a reversal expectation. This corroborates the code's
  existing `_equity_index_short_cross_asset_gate` (`BP_rules_engine.py:1782-1824`), which already
  requires `small_specs_index >= 80` (retailers extreme bullish) as a precondition for equity-index
  SHORTS, citing Ch.156's near-identical "Retailers are getting more and more bullish on the
  weekly". Independent confirmation of a gate that was previously single-sourced. No change.
- **AverageYears changed on camera AGAIN** (CW49 roadmap): stocks start at 5, Bernd says "We can
  do here 10 years", opens the dialog, sets 10, and every later stock chart shows 10. That is the
  second on-tape edit (CW17 TSLA 5->10). Multi-lookback design confirmed for the 5th time.
- **CW24 shows a bare `COT Net Position (1)`** — raw contract counts, no 0-100 rescale, no
  thresholds. A third COT-family display alongside the Index and RAW variants. Our COTIndex works
  from raw net positions and rescales internally, so this is the same underlying data, displayed
  unnormalized. No action.
- Stocks `@US=True, @GC=False` again (CW49 roadmap, 7 symbols) — bonds-only, 10th chapter.
  A BABA vertical-line tooltip proves the underscore-less `CampusValuationTool_V2` on stock panels
  is the SAME study as `_CampusValuationTool_V2`, just status-line truncation (settles the
  cosmetic naming question raised in C-32).
- BTC `CampusValuationTool_V2` 3-leg + AverageYears=4 again. ZigZag absent 36/36, 37/37.

## C-42 — CW52-2023 (Dec-24): "smart money = commercials" stated explicitly; Sugar evidence accumulates

- **Bernd defines his own vocabulary on tape (0:27:09)**: *"the smart money, the commercials
  are..."* — he equates "smart money" with COMMERCIALS directly, on precious metals. This is a
  valuable decoder for every prior chapter where a reader recorded "smart money" without a formal
  group name (CW43 Platinum, CW49 Cotton, CW51): those are Commercials references. Confirms the
  PM = Commercials-primary routing yet again.
- **BUT the term is overloaded — caution recorded**: at 0:29:27 he says *"the smart money index,
  how the retailers are getting overly bullish on... Australian dollar"* — here "smart money
  index" is the TOOL NAME while he reads the RETAIL line. So "smart money" means Commercials when
  used as a group noun, and means the indicator when used as a tool name. Readers must
  disambiguate by context; do not auto-map the phrase to Commercials.
- **Forex = Retail confirmed again** (AUD: "retailers are getting overly bullish", "retail top").
  Post-C-22 corroboration #5.
- **SUGAR — evidence accumulating but NOT yet actionable.** At 0:38:14 on Sugar: *"smart money is
  getting crazy bullish"*. By his 0:27:09 definition that reads as Commercials, which would mean
  SB=F belongs on the Commercials path rather than its current Non-Commercials
  (`SOFT_COMMODITY_SYMBOLS`) routing. Combined with CW01's commercials-pinned-high visual on Sugar,
  that's two soft hints. **No change** — the quote uses the overloaded term, not the word
  "commercials", and this is exactly the ambiguity flagged above. **Still need one unambiguous
  Sugar/OJ group quote.** Keeping SB=F/OJ=F as-is (the code itself calls the corpus "silent").
- **Cleanest Valuation read of the series** (frame_002134, AUD full-screen popout, crop-confirmed
  at 4x): futures `_CampusValuationTool_V2` with **3 booleans True,True,True then Length=10**;
  stocks `CampusValuationTool V2` with **2 booleans True,False**. Dec-2023 futures = 10,
  consistent with C-41. Also independently confirms the two-instance naming split.
- **AverageYears settled definitively**: AAPL shows **N=5 and N=10 in different panes minutes
  apart, same symbol, same session**. It is a per-pane view setting, full stop. Multi-lookback
  design vindicated (6th confirmation); no per-symbol constant should ever be hard-coded.
- COT variant 0-100; no dialog (WeeklyLookBack unsighted again — the CW40 PM dialog in C-33
  remains the only one, and it says 26). ZigZag absent 38/38.
- Anomaly: he says "New Zealand dollar" but charts only AUD for that segment — attribute that
  segment's readings to AUD, not NZD.

## C-43 — CW13-2023 (Mar-26): index tally tightens to 7-vs-6. Decision still 10, on recency alone.

- CW13 shows `Campus Valuation Index ("@US",13,3,100,-100,100,75,...)` **Length=13 on indices
  AND stocks alike** (no class split this session). Running tally for equity indices:
    **10** — Mar-05-23, May-20-23, Jun-11-23, Dec-02-23, Jan-02-24, Feb-17-24, CW09 Feb-24 = **7**
    **13** — Mar-26-23, Apr-16-23, Apr-24-23, May-08-23, Oct-15-23, Oct-29-23 = **6**
  Effectively a coin flip on raw counts. **The ONLY argument that still separates them is
  recency + tool-match**: every reading from Dec-2023 onward (4 consecutive chapters, and every
  reading of the 3-ref tool our code models) is 10. Keeping `equity_indices = 10` on that basis;
  the raw-count case has evaporated and this should be stated honestly rather than as consensus.
  This does not change the code, but anyone revisiting should know the margin is one sighting.
- Bitcoin again on 3-ref `CampusValuationTool_V2` + `Campus True Seasonality (4,...)` — BTC
  4-year constant confirmed a 6th time.
- Indices `Campus Algo Forecast (15,...)`; no COT content anywhere (zero forex/commodities);
  no Sugar/OJ. ZigZag absent 39/39.

## C-44 — CRUDE OIL COT group: Commercials -> RETAIL contrarian. **FIX APPLIED.**

**Evidence (three independent live chapters, consistent direction, zero counter-evidence):**
  - CW47 (2023-11-18): "the retailers are getting fully bearish" -> he turns bullish
  - CW08 (2024-02-19): "look at what happens when the retailers usually are they usually are
    short we see a rise in price" — he states it as a general RULE for crude
  - CW11 (2024-03-09): "retailers are getting super bullish" / "here we are overvalued
    retailers are bullish then we can short this as well crude oil"
  - CW49 (2023-12-03): the one attempt to name a group on crude is cut off mid-sentence
    ("when I look at the smart the well the...") — inconclusive, not counter-evidence.
  - **No chapter in the corpus names Commercials for crude.**
The `energies -> Commercials` grouping traces to the Hybrid AI / OTC *teaching* material.
Identical teaching-vs-live conflict to forex (C-22), resolved the same way: live corpus governs
the live system.

**Applied** (deliberately scoped to CL=F only — HO/RB/QM/BZ have no live evidence and keep the
`energies` Commercials default; NG=F already had its own branch):
  1. `BP_indicators.py` `COTIndex.get_bias` — new `crude_oil` branch: `sspec_idx/sspec_ext,
     contrarian=True`, with the three quotes inline as evidence.
  2. `BP_indicators.py` — `crude_oil` added to `_COT_KING_CLASSES_156W` (keeps the 156w
     approaching-extreme trigger) and to the momentum `primary_col` retail mapping.
  3. `BP_rules_engine.py` — new `CRUDE_OIL_SYMBOLS` frozenset with full evidence comment and an
     explicit "routing lives in TWO places" warning.
  4. `BP_rules_engine.py` — BOTH routing sites updated: `_indicators_for_class`
     (`effective_class`) and `_analyze_fundamentals` (`cot_effective_class`). Mirroring these is
     mandatory: the un-mirrored version of exactly this bug previously produced an INVERTED COT
     read on NG=F (documented at :1490-1495).
  5. `COT_LOOKBACK_BY_CLASS['crude_oil'] = 26` — matches the two CL=F settings dialogs rather
     than the 52w seasonal-cycle default for `energies`.

**Verified** — `replay/test_c44_crude_retail.py`, all three checks pass:
  - retail extreme-long -> crude bearish; retail extreme-short -> crude bullish; and each class
    is confirmed to read the correct LEG (crude=sspec contrarian, energies=comm with-trend)
    rather than merely producing different answers.
  - both routing sites verified via `inspect.getsource` to map CL=F -> 'crude_oil' (guards
    against the un-mirrored-routing bug class).
  - scope check: CRUDE_OIL_SYMBOLS == {'CL=F'}; HO/RB/QM/BZ unaffected; NG=F still nat_gas;
    softs still {SB=F, OJ=F}; crude lookback 26.
  - `cross_category_signal` interaction checked by hand: smart-vs-dumb 'bearish' (comm short +
    retail long) agrees in direction with retail-contrarian bearish, so the existing non-forex
    confluence override cannot contradict the new crude routing.

## C-45 — CW47 second WeeksLookBack dialog; CW25 third index/stock A/B; CW06/CW13/CW14/CW15 quiet

- **`WeeksLookBack = 26` confirmed by a SECOND full dialog** (CW47, 2023-11-18), with spoken
  "It's 26 already short term". C-33 independently re-confirmed; the lone crude `20` remains the
  only outlier in the corpus. Dialog also shows all three DisplayXTradersIndex=True, 80/20,
  DisplayLineAt100=True.
- **CW25 (Jun-17-2023) = THIRD same-session index-vs-stock A/B**: indices `Campus Valuation
  Index ("@us",10,...)` **Length=10**, all 9 stocks `("@US",13,...)` **Length=13**, Bitcoin on
  the 3-ref tool. With CW21 and CW24 that is three independent sessions showing exactly the
  code's `equity_indices=10 / equities=13` pairing. **C-37/C-40/C-43 CLOSED — config correct.**
  (Raw-count tally also improves to 8-vs-6 for 10 on indices.)
- CW47 other groups: Palladium/Copper/Cotton all read RETAIL contrarian this chapter, while
  CW49/CW52/CW01 read Commercials on the same markets. This is the contrast pattern, not a
  contradiction — `cross_category_signal` already models commercials-vs-retail extremes. **No
  change** to PM/softs routing; crude is different because it has NO commercials sighting at all.
- CW06 (Feb-2023): 3-ref `CampusValuationTool V2` already in use Feb-2023 (futures True,True,True;
  stocks True,False) — pushes the 3-ref tool's start earlier than C-38 assumed; harmless.
  COT pane labelled `Campus COT Index V2 protected V1` with trailing `80.00 20.00 100.00 0.00`.
- CW13/CW14/CW15 (Mar-Apr 2023): equity/BTC-only sessions, zero COT content — reported as gaps,
  correctly not force-fit. CW14 shows Length=13 on BOTH futures and stocks (no split that day).
- Sugar/OJ: absent from CW06, CW13, CW14, CW15, CW25, CW47 — still unresolved, still unchanged.
- ZigZag absent 40/40 through 45/45.

## C-46 — **HIGH: the C-14 stock-Length fix is INERT in production, and the weekly pipeline runs the DAILY cycle value.** Mechanism fixed; config decision escalated.

**Correcting my own earlier claim first.** C-14 reported equities Valuation Length 30 -> 13 as
"applied and verified". It is applied to `VALUATION_LENGTH_BY_CLASS['equities']` — but
`BP_config.yaml` `valuation.cycle_per_symbol` sets an explicit **30 for every one of the ~40
individual stocks in the watchlist**, and that per-symbol override is applied AFTER the class
default (`_indicators_for_class`). **So C-14 changes nothing for any stock the scanner actually
trades.** Measured, not assumed:

    AAPL  class default 13 -> effective 30      MSFT 13 -> 30      WMT 13 -> 30
    YM=F  class default 10 -> effective 30      SI=F 10 -> 30      ZC=F/CT=F 10 -> 30
    (NQ=F/ES=F/RTY=F/GC=F/PL=F/PA=F/CL=F are 10 in both, unaffected)

**Impact of 30 vs 13 on stocks** (`replay/stock_cycle_30_vs_13.py`, engine `get_bias`,
bonds-only refs, daily 2021-2024, 925 bars):

| symbol | bias differs | OPPOSITE bias | median abs delta | p90 |
|---|---|---|---|---|
| AAPL | 43.7% | **19.14%** | 30.77 | 73.98 |
| MSFT | 39.5% | **18.70%** | 31.65 | 79.74 |
| NVDA | 32.9% | **15.35%** | 31.72 | 77.63 |
| AMZN | 41.7% | **15.14%** | 29.09 | 75.76 |
| META | 40.4% | **16.43%** | 27.79 | 78.99 |
| WMT  | 39.0% | **18.92%** | 30.57 | 85.84 |

Roughly one bar in six gets the OPPOSITE directional bias. On the latest bar NVDA and WMT
already disagree. This is the largest measured discrepancy found in the audit.

**Which value is right is genuinely contested — do NOT mass-flip to 13.** Evidence both ways:
  - **13**: OTC M3 L3 slide "Equity indices and stocks -> 13 days short term / 30 days long
    term"; the same lesson LIVE ON AAPL editing ROC 10 -> 13 ("I'm going to change the ROC from
    10 to 13"); CW05-2023 MSFT dialog = 13; CW18 ten stocks un-truncated = 13; and CW21/CW24/CW25
    same-session A/B = stocks 13.
  - **30**: **CW23 (2023-06-03) shows all 11 stocks at Length=30**, zoom-verified — the first live
    stock sighting of 30, so 30 is not merely the "long-term toggle". The config also cites
    HAI 0:59:34 / Ch.117 CW41 and the Cheatsheet's "30 & 10-d-cycles trend following".

**The defect that IS unambiguous — a timeframe mismatch.** The Phase 38 comment in
`BP_config.yaml` states the rule plainly: *"13 is the weekly end-of-bend value only; applying it
to daily scans gives the wrong ROC period. Set to 30 (preferred daily) as interim fix until
timeframe-aware {daily:30, weekly:13} dict is implemented (GAP-14/GAP-15)."* But traced through
the code, **Valuation is computed on the HTF series**: `analyze()` passes `htf_df` into
`_analyze_fundamentals(cot_df, price_df=htf_df, ...)`, and the live scanner runs `HTF: 1wk`.
So the pipeline feeds WEEKLY bars while the config supplies the value its own comment labels
DAILY. By the code's own stated rule the weekly branch (13) applies. The interim fix was chosen
on a premise about "daily scans" that does not match how the scanner runs.

**APPLIED (mechanism only — deliberately behaviour-neutral):** implemented the deferred
GAP-14/GAP-15 timeframe-aware override in `_indicators_for_class`:
  - `SYM: 30` (flat int) behaves exactly as before;
  - `SYM: {daily: 30, weekly: 13}` now resolves against the active `htf`, with `monthly`
    supported, a generic `roc` fallback, then the class default;
  - `htf` threaded from `_analyze_fundamentals` into `_indicators_for_class`.
  Verified by `replay/test_c46_timeframe_cycle.py`: the live config resolves to its CURRENT
  values on both 1wk and 1d (AAPL 30, NQ=F 10, YM=F 30, GC=F 10) — zero behaviour change today —
  while dict entries resolve 13 weekly / 30 daily, plus fallback cases.

**NOT APPLIED — escalated to the user.** Converting the ~40 stock entries (and YM=F, SI=F, the
grains/softs block) to `{daily: 30, weekly: 13}` would change live signals on ~40% of bars and
invert ~1 in 6. That is a trading-behaviour decision on real prop-firm money with genuine
evidence on both sides, so it is documented here with the numbers and the mechanism ready,
rather than decided unilaterally. **Recommended**: convert stocks to `{daily: 30, weekly: 13}`,
which satisfies BOTH corpora (13 for the weekly scans the system actually runs, 30 retained for
daily trend-following) and finally makes the C-14 class default meaningful.

## C-47 — CW48 + CW45 + CW23: crude-retail corroborated a 4th time; cotton stays Commercials

- **CW48 (2023-11-25) crude oil: "retailers" used contrarily TWICE (0:12:32, 0:14:20) with no
  smart-money counterpart** — a 4th independent chapter backing the C-44 crude fix. The reader
  flagged it as outside the four pre-established classes, which is exactly why C-44 created a
  dedicated `crude_oil` class rather than bending `energies`.
- **CW48 cotton: "retailer's bearish smart money bullish"** — the classic contrast, Commercials
  primary. Confirms cotton stays on the Commercials path (C-34); C-44 did NOT touch softs.
- CW45 (2023-11-05): futures/metals `True,True,True` **Length=13**, stocks `True,False` single
  plotted line. Another bonds-only confirmation; another 13 on futures (Nov-2023 era).
  Algo Forecast N=5 here vs 10 (CW10) and 15 (CW42) — per-session drift, no action.
- CW23 (2023-06-03): **indices reference `@dx` (Dollar Index) at Length=10 while the bond future
  @US is self-referential** — first sighting of a DXY-referenced index config; our
  `VALUATION_REFS['equity_indices']` already includes DX-Y.NYB among its three legs, so this is
  consistent. Also the source of the stocks-at-30 counter-evidence in C-46.
- Sugar/OJ still never charted (absent from CW45, CW48, CW23) — SB=F/OJ=F routing unchanged.
- ZigZag absent 46/46 through 48/48.

# ===== CODE-REVIEW PASS (2026-08-19) — three Opus reviewers over the whole system =====
# Reviewers audited BP_indicators.py (vs the 5 canonical Pine sources), BP_rules_engine.py,
# and BP_data_fetcher.py + run_scanner.py. Every finding below was reproduced by the reviewer
# with executable proof, then re-verified by me before fixing.
# Fixes applied: C-48..C-51. Full verification: replay/test_c48_c51_code_fixes.py (all pass).

## C-48 — **CRITICAL, FIXED**: contrarian 156-week strength confirmation was INVERTED
`BP_indicators.py` `COTIndex.get_bias`. The four-clause strength test was written against the
DERIVED `bias`, and its two "contrarian" clauses were byte-identical to the non-contrarian ones,
making the `contrarian` flag a no-op. Since contrarian bias is already flipped upstream, the
confirmation ran backwards: **strong was awarded exactly when the 26w and 156w windows
CONTRADICTED each other, and withheld when they agreed.**
- Live blast radius created by our own earlier fixes: **every forex pair (C-22) and CL=F (C-44)**.
  `cot_strength == 'strong'` gates the forex hard-hold and several override paths in the rules
  engine, so genuine multi-year retail extremes never reached strong while contradictory
  readings did.
- **Fixed** by testing the GROUP POSITION over both windows instead of the derived bias:
  strong iff (primary >= upper AND ext >= upper) OR (primary <= lower AND ext <= lower).
  Works for contrarian and non-contrarian alike; approach/momentum-triggered biases correctly
  stay normal. The misleading comment block (which claimed sspec_idx >= 80 means retail
  "extreme SHORT" — it means extreme LONG) was rewritten.
- Verified: forex retail -20/-20 (agree) -> (bullish, strong); -20/+106 (contradict) ->
  (bullish, normal); crude 120/120 -> (bearish, strong); commodities control unchanged.

## C-49 — **CRITICAL, FIXED**: USD-BASE pairs got a 180-degree inverted COT from the cross-check
`BP_rules_engine.py` `_analyze_fundamentals`, opposing-currency block. `opp_bias` is a view on
the DOLLAR; the code inverted it unconditionally. That is only right when USD is the QUOTE
currency (EURUSD, GBPUSD). For **USDJPY=X / USDCHF=X / USDCAD=X — all three in the live
watchlist — USD is the BASE**, so a bullish-dollar read means the pair goes UP and must carry
over UNCHANGED.
- Two independent reviewers found this. Consequences: the Phase 23-T5 inheritance path could
  **open a long on COT evidence that says short**; genuine confirmations were demoted to
  neutral; genuine conflicts were promoted to strong (which then unlocks override paths).
- **Fixed**: `inverted = opp_bias if _usd_is_base else _flip[opp_bias]`. This is a DIFFERENT
  flip from the Phase 21 inversion (which corrects the pair own quote-currency COT); both are
  needed and they do not double-negate. Phase 21 itself was reviewed and confirmed CORRECT.
- Verified live: USDCHF=X now logs "double-confirmed ... (this=bearish opposing-inverted=bearish)"
  — bearish USD -> bearish USDCHF. Correct.

## C-50 — **FIXED**: the dashboard charted a different trader group than the one traded
`run_scanner.py` `build_indicator_series` called `engine._indicators_for_class(asset_class)`
with **no symbol** — the third consumer of the effective-class routing, missed by the C-44 note.
All symbol-level routing (crude_oil, nat_gas, soft_commodities, JPY 52w, per-symbol Valuation
cycle) was skipped for the charts. For **CL=F that is literally the opposite line**: the signal
is made from retail-contrarian 26w while the chart showed commercials 52w — so a human
reviewer would "verify" a signal against evidence the engine never used.
- **Fixed**: `symbol` and `htf` threaded through to the routing call. Verified end-to-end
  (CL=F and USDCHF=X both build 156-point COT series through the correct engines).

## C-51 — **CRITICAL, FIXED**: ETF proxy price could leak into the TRADABLE path (~10x position size)
`BP_data_fetcher.py` `fetch_ohlcv`. The cache key was `(symbol, interval, period)` and omitted
`allow_proxy`, silently defeating the fail-safe its own docstring describes. A valuation-reference
fetch (allow_proxy=True) that fell back to an ETF proxy stored **GLD** bars under the key
`('GC=F', '1wk', '10y')`; the later TRADABLE fetch for GC=F (allow_proxy=False) hit that key and
was served proxy data **from cache, with no network call and no warning**.
- Concrete path in the shipped config: EURUSD=X is watchlist #1 and fetches GC=F as a valuation
  ref; GC=F itself is watchlist #29. One Yahoo hiccup on GC=F during item #1 poisons item #29.
  Entry/stop/targets would then be computed on ~$310 GLD bars instead of ~$3,400 gold, and since
  lots = risk-budget / stop-distance, the ticket size comes out roughly an order of magnitude
  too large. This is the most dangerous defect found in the entire audit.
- **Fixed**: `allow_proxy` is now part of the key; PRIMARY data (no fallback taken) is written
  under both keys so reference fetches still hit cache, while PROXY data is written ONLY under
  the allow_proxy=True key — making leakage into the tradable path structurally impossible.
  Also fixed the related latent bug where start/end-bounded fetches were cached under the
  unbounded period key (period defaults to "2y" and is never falsy).
- Verified: with the primary feed stubbed down, the reference path gets proxy data while the
  tradable path returns EMPTY and re-attempts the primary symbol (fail-safe intact); genuine
  primary data is still shared across both modes in a single fetch (no cache-hit regression).

## C-52 — Reviewer findings NOT actioned (recorded for the user; several are significant)
High-value items I did not change, because each is a behaviour/scope decision rather than a
clear defect-with-one-right-answer. Full detail is in the reviewer reports; summary:
- **Seasonality bias threshold is an absolute price constant (+-0.01)** so `get_bias` returns
  neutral for EVERY week of the year on any instrument priced under ~2 — i.e. ~21 of 28 forex
  pairs (EURUSD 1.08, AUDUSD 0.65, ...). One of the three fundamental legs is silently dead on
  most of the forex book. Fix is a relative deadband; needs a calibration decision.
- **Valuation reference with zero date overlap degenerates into the symbol own momentum.**
  The C-01 reindex+ffill fix is correct in intent, but its guard runs AFTER the ffill so it can
  never fire; a stale/renamed/truncated reference silently contributes nothing while still
  producing a confident directional verdict. Needs a pre-ffill bar count + staleness cap.
- **`at_zone=True` is hard-coded** at the `_bias_consensus` call, so the Rule-#1 Valuation veto
  can be overridden by a zone price has never reached.
- **Silent Valuation/COT failure reads as neutral (= "does not oppose") rather than
  "unknown"**, so a data outage converts "no opinion" into "gate satisfied" system-wide.
- **`_bias_consensus` receives the RAW asset_class**, making the NG seasonality gate and the
  `_ZONE_ARRIVAL_CLASSES` entries for nat_gas/soft_commodities unreachable.
- **Position size is computed BEFORE zone refinement mutates entry/stop** — can exceed the 1% cap.
- **Partial current HTF bar is never dropped** (repainting) for zones/trend/Valuation.
- **COT lookahead in the BACKTEST harnesses only** (report date treated as availability date;
  real lag is ~3 days). Live path confirmed clean.
- **6 watchlist symbols have no CFTC code** (ZM=F, ZO=F, LE=F, HE=F, GF=F, **OJ=F**) -> silent
  neutral COT. OJ=F is the sharp one: it is in SOFT_COMMODITY_SYMBOLS with special routing that
  can never receive data. (Note this also means the Sugar/OJ question from the frame audit is
  moot for OJ until the code is added.)
- **`--strategy intraday` cannot produce a signal** (15m capped at 60d, code requests 729d).
- **Paper-trader state file: one unreadable byte silently resets the account and then overwrites
  it** — no backup, no abort.
- Verified CLEAN by the reviewers: the COT V2 formula vs Pine (exact), Valuation ROC-difference
  vs Pine (exact), weekly seasonality binning vs Pine, all 34 CFTC contract codes (checked live
  against the API), the futures-only report type, COT column names, no lookahead on the live
  path, and the Phase 21 USD-base inversion.

# ===== TRADINGVIEW ALIGNMENT PASS (2026-08-19) — OTC 2025 Module 3, Lessons 2/3/4 =====
# Goal (user's plan): verify TradeStation-lecture == PineScript == Python, in that order.
# Fixture reports: `_audit_ftw_vision/tv_fixtures/OTC_M3_L{2,3,4}_*_fixtures.md`
# Scripts: replay/cot_formula_discriminator.py, cot_param_sweep.py, cot_value_search.py,
#          valuation_daily_vs_weekly.py

## C-53 — **HIGH: Valuation is computed on the WRONG TIMEFRAME.** He reads it DAILY; we use WEEKLY.

Evidence, two independent sources agreeing:
- **Corpus tally across every audited chapter** — the Valuation tool is sighted on
  **DAILY ~95 times vs WEEKLY ~6**. The COT/Smart Money pane is the mirror image:
  **WEEKLY 46+ vs DAILY 3** (as expected — COT data is weekly by nature).
- **The 2025 TradingView teaching lesson (M3 L3)** runs `CampusValuationTool` on **1D** for
  both `FXCM:AUDUSD` and `NASDAQ:AAPL`. No weekly chart appears in the lesson at all.

Our pipeline: `analyze()` passes `htf_df` into `_analyze_fundamentals(..., price_df=htf_df, ...)`
and the scanner fetches the three reference series at `interval=htf` (`run_scanner.py:787`).
With the weekly strategy that is **weekly symbol bars + weekly reference bars**, so a
"ROC Length 10" spans ~10 WEEKS in our system versus ~10 DAYS on his chart. These are not
two settings of one indicator; they are different indicators.

**Measured impact** (`replay/valuation_daily_vs_weekly.py`, engine `get_bias`, same refs at
each interval, latest bar):

| symbol | WEEKLY (ours now) | DAILY (his chart) | agree |
|---|---|---|---|
| AUDUSD=X | neutral | neutral | yes |
| EURUSD=X | neutral | neutral | yes |
| **CL=F** | **bullish** | **bearish** | **NO** |
| GC=F | neutral | neutral | yes |
| **ES=F** | **neutral** | **bullish** | **NO** |

2 of 5 disagree on the latest bar, including a straight bullish/bearish inversion on crude.

**NOT APPLIED — needs the user's call.** The fix is not a one-line change: the symbol series
AND all three reference series must be fetched/computed daily while COT stays weekly, so it
touches the fundamentals pipeline and the scanner's ref-fetch. It also interacts with C-46
(the cycle_per_symbol 30-vs-13 question), because the config's "30 = daily / 13 = weekly"
reasoning was built on the assumption that Valuation ran daily — which it does NOT today.
Resolve C-53 first; C-46 partly dissolves once the timeframe is right.

## C-54 — COT formula: evidence now points to **0-100**, NOT our -20..120. Not yet conclusive.

Two Pine files in our possession are identical except one line:
  `COTIndex_OTC.txt` (the 2025 OTC pack shipped to students): `100*(net-min)/(max-min)`
  `COT V2 120-20.txt`                                        : `140*(net-min)/(max-min)-20`
Both keep threshold hlines at 80/20. Since idx_V2 = 1.4*idx_100 - 20, the SAME positioning is
called extreme at different points:
  - 0-100 tool  : upper 80 needs **80.0%** of the 26w range, lower 20 needs **20.0%**
  - -20..120    : upper 80 needs **71.4%**, lower 20 needs **28.6%**   <-- our Python today
So our system flags COT extremes EARLIER at both ends than the 0-100 tool does.

**Numeric investigation** (gold, real CFTC futures-only data, 1929 weekly reports):
- Naive check at the assumed 26w window matched NEITHER formula -> so an assumption was wrong.
- Parameter sweep (window 26/52/156/260 x both formulas x bar-shift -2..+2) produced one
  standout: **window=26, formula=100x reproduces the lecture value 34.43 EXACTLY**.
- Date-robust search (search each observed value across all 40 years instead of trusting the
  crosshair date): **34.43 -> exact hit at report 2023-08-01, 0 weeks from the frame's claimed
  2023-08-07 bar.** `140x-20` produced **no** near hit for ANY fixture; its only exact hits are
  decades away (spurious). Tally: 26w/100x = 1/5 fixtures explained, everything else 0/5.

**Why only 1/5**: the frame reader explicitly flagged that TradingView legend numbers follow the
CROSSHAIR, so the date attribution on most fixtures is medium/low confidence; the values are
crisp but their dates are not. Two fixtures were "latest bar" readings whose date could not be
pinned because the axis ran forward to empty space.

**Also reconsidered**: the lesson's settings dialog shows `Upper Bound Level: 120` and the pane
axis runs -25..125, which is what previously convinced us (C-07) that the scale is -20..120. But
the legend decodes as `26 156 Futures Only 120 80 50 20 -20 1` — consistent with **120/-20 being
render BOUNDS and 80/50/20 being the reference lines** on a 0-100 oscillator. That is the same
mis-attribution that R-02 already proved for the "126.21" anomaly (a reference-line readout, not
a series value). The 120.00 and -20.00 "spikes" the reader logged are exactly the bound lines.

**NO CODE CHANGE YET — deliberately.** One exact hit is suggestive, not proof, and this changes
how often every COT signal fires on every asset class. What settles it is clean fixtures, which
is precisely the user's plan: put the indicator on TradingView ourselves, park the crosshair on a
known date, and read the value. See C-55 for the exact reproduction recipe.
If it does confirm 0-100, the minimal fix is to keep our formula and move the thresholds to
92/8 (equivalent), or switch the formula to 100x and keep 80/20 — the latter is cleaner.

## C-55 — Exact TradingView reproduction recipe (captured from the 2025 lessons)

**COT (M3 L2)** — platform confirmed TradingView (spoken twice: "It runs on trading view").
- Symbols: `GC1!` -> "Gold Futures · 1W · COMEX" (B-ADJ back-adjusted); `6E1!` -> "Euro FX
  Futures · 1W · CME". Timeframe **1W** throughout. NOTE the URL query param showed a stale
  `TVC:GOLD` — do not reproduce from the URL, use the on-chart GC1!/COMEX instrument.
- Indicators are **invite-only private scripts** by "Online-Tradin…": picker name
  "COT Index by OTC" renders on-pane as **"COT Pos. Indices"**; the three net-position scripts
  render as "COT Comm/NonComm/Spec Net Futures Only". Picker names != pane names, and none are
  publicly available -> reproduction requires our own Pine.
- Settings captured (dialog never scrolled past this): Weeks Look Back **26**, Weeks Look Back
  for Historical Hi/Lo **156**, Report Type **Futures Only**, Show Commercial/NonCommercial/
  Nonreportable all on, Show Reference Lines on, Show 0 and 100 Lines on, Upper Bound Level **120**.
  Legend string: `COT Pos. Indices 26 156 Futures Only 120 80 50 20 -20 1`.
  Colors: Commercial=blue, Non-Commercial=orange, Retail=red/pink.
- **156-week Hi/Lo is a real input** — matches our `extreme_lookback=156`. Good.

**Valuation (M3 L3)** — TradingView, indicator `CampusValuationTool`.
- Reference symbols VERBATIM from the Inputs dialog: Ref1 `CBOT_DL:ZB1!` (bonds),
  Ref2 `COMEX_DL:GC1!` (gold), Ref3 `TVC:DXY` (dollar). The slide shorthand `@US/@GC/$DXY` is
  TradeStation notation, NOT valid TradingView syntax.
- Inputs: ROC Length **10**, Rescale Length **100**, Rescale Max **100**, Rescale Min **-100**,
  Upper Threshold **75**, Lower Threshold **-75**. Colors: Ref1 blue, Ref2 yellow, Ref3 magenta.
- Charts: `FXCM:AUDUSD` **1D** and `NASDAQ:AAPL` **1D**.
- **On-camera edit, verbatim**: *"And down here I'm going to change the ROC from 10 to 13"* — on
  AAPL, **with only Reference Symbol 1 (ZB1!) shown**. This single frame independently confirms
  BOTH of our applied equity fixes: stocks use **bonds-only refs** (C-14) and **Length 13** (C-14),
  and it does so on a DAILY chart (C-53).

**Seasonality (M3 L4)** — TradingView, `SB1!` -> "Sugar No. 11 Futures · 1D · ICEUS", **1D**
("make sure we own a daily chart"). Indicator pane/dialog title **"Seasonality Index - v4"**
(catalog entry reads "OTC True Seasonality v4" — names differ). Inputs: **Average Years 5 -> 10
edited on camera**, **Project # Bars into Future = 45**, three unchecked booleans (Align First
Future Bar with Close / Start Future Projection 1 Year Before End / Show Debug Info).
Y-axis is unitless (~54-72), so only SHAPE is comparable — consistent with R-03.
NOTE our Python/TrueSeasonality uses forward_bars=150; the lesson uses **45**.

**Account constraint hit while setting this up**: the user's TradingView is on the **Basic plan
(1 saved chart layout)**, and the Pine Editor currently holds an **UNSAVED** "18BAR" strategy
(My Scripts is empty). Creating our script there risks destroying that draft, so the browser
work was stopped short of authoring. Needs either the user saving 18BAR, or explicit go-ahead.

## C-56 — INDICATOR-LEVEL CORRECTIONS (the "fix the indicator first" pass)

Corrected Pine written to `tv_fixtures/` — these are the reference definitions to build the
Python from, NOT yet applied to the trading system.

### 1. Data alignment — **PROVEN, 8/8 exact** (`replay/cot_alignment_check.py`)
Using the HIGH-confidence Euro raw net-position fixtures (raw contract counts are a direct
fingerprint of the underlying series, immune to any formula question):

| chart bar | observed comm / noncomm (K) | CFTC report matched | err |
|---|---|---|---|
| 2024-01-22 | -136.51 / 104.09 | 2024-01-16 | 0.01 |
| 2018-02-12 | -179.44 / 140.82 | 2018-02-06 | 0.01 |
| 2014-09-22 | 189.25 / -137.15 | 2014-09-16 | 0.00 |
| 2010-01-04 | 25.55 / -33.80 | 2009-12-29 | 0.00 |
| 2010-04-26 | 76.15 / -71.42 | 2010-04-20 | 0.01 |
| 2008-07-21 | -32.75 / 23.05 | 2008-07-15 | 0.00 |
| 2007-05-07 | -135.19 / 106.69 | 2007-05-01 | 0.00 |
| 2018-10-15 | -5.44 / -16.14 | 2018-10-09 | 0.00 |

Three things confirmed at once: **contract code 099741 = 6E1!**, **Legacy Futures-Only report
type**, and a **constant -6 day offset** — TradingView plots a COT report on the FOLLOWING
week's bar (report Tue X shows on bar Mon X+6), because that is when it became public. Our
Python indexes by report date with no shift; that is correct for live scanning (we always take
the latest published report) but MUST be applied when matching lecture dates.

### 2. COT scale — still open, but now testable by one switch
With the proven alignment, the one usable index fixture matches **exactly**:
  bar Mon 07 Aug 2023 (= report Tue 01 Aug 2023), gold commercials, observed **34.43**
    0-100 formula  -> **34.43**  (exact to the cent)
    140x-20        -> 28.21
`140x-20` produced no near-hit for ANY fixture anywhere in 40 years. The other four fixtures are
unusable: a joint two-series test (`replay/cot_joint_test.py`) proved the two "current bar"
readings (comm 20.66 / retail 38.59) cannot come from the same bar under ANY window/formula, so
the crosshair moved between them — exactly the failure mode the reader warned about.
**Probability the single exact hit is coincidence at the correct date: ~0.0006.** Suggestive,
not proof. NOT applied.

**KEY INSIGHT that reconciles everything**: the lesson's dialog exposes **"Upper Bound Level"
as an INPUT**. That means the real script maps the normalised 0..1 position onto
[lowerBound, upperBound] — so `0/100` reproduces `COTIndex_OTC.txt` and `-20/120` reproduces
`COT V2 120-20.txt` EXACTLY. They are one script one input apart, not two rival formulas. The
"values reaching 120.00 / -20.00" the reader logged are then most likely the BOUND LINES being
read by the crosshair — the same mis-attribution R-02 already proved for the 126.21 anomaly.

`tv_fixtures/COT_Index_CORRECTED.pine` implements this with a `scaleMode` switch, so putting it
on COMEX:GC1! 1W and reading the 07 Aug 2023 bar settles it in one look.

### 3. **Our COT Pine is missing an input the real one has**
Neither `COTIndex_OTC.txt` nor `COT V2 120-20.txt` implements **"Weeks Look Back for Historical
Hi/Los = 156"** — the SECOND input in his dialog. Our Python already has this concept
(`COTIndex.extreme_lookback = 156`, the `*_net_extreme` columns), so the Pine was behind the
Python. Added to the corrected file as a plotted overlay.

### 4. **Valuation Pine has the REFERENCE ORDER REVERSED — real defect**
| slot | our `Valuation_OTC.txt` | his lesson dialog (frame 808) |
|---|---|---|
| Reference 1 | **"DXY"** (navy) | **`CBOT_DL:ZB1!`** bonds (blue) |
| Reference 2 | "GC1!" (yellow) | `COMEX_DL:GC1!` gold (yellow) |
| Reference 3 | **"ZB1!"** (purple) | **`TVC:DXY`** dollar (magenta) |
Slots 1 and 3 are swapped. This is load-bearing because the entire equities finding is *"he
shows only Reference Symbol 1 for stocks"* — under our file that reads as DOLLAR-only, under his
it is BONDS-only. The frame audit and our Python (`VALUATION_REFS['equities'] = ["ZB=F"]`) both
follow HIS ordering, so **the Python is right and the Pine file was the odd one out** — but
anyone rebuilding from that Pine would have inverted the stock configuration.
Corrected in `tv_fixtures/CampusValuationTool_CORRECTED.pine`, which also adds the per-reference
show/hide toggles (the core mechanic of the lesson), the Rescale Max/Min and Upper/Lower
Threshold inputs his dialog exposes, ports v4 -> v5, and guards the `nz(x[Length])` divide-by-zero.

### 5. **Our Seasonality Pine is the WRONG INDICATOR**
| | our `Seasonality_OTC.txt` | his "Seasonality Index - v4" |
|---|---|---|
| name | "Seasonality_OTC" (overlay=true) | "Seasonality Index - v4" (sub-pane) |
| inputs | Trading days fixed(252)/variable; use max/min/avg; Lookback years (15); Plot N bars into future (30, max 252); Color; Line width; Smoothing MA; Offset | **Average Years** (5 -> 10 on camera); **Project # Bars into Future = 45**; Align First Future Bar with Close; Start Future Projection 1 Year Before End; Show Debug Info |

Different script, different input set. **And his five inputs are EXACTLY the TradeStation
"Campus Algo Forecast" signature** we documented independently across the Weekly Outlooks:
`(AverageYears, ProjectNumberBarsIntoTheFuture, AlignFirstFutureBarWithBarClose,
StartFutureProjection1YearBefore..., PrintDebug)`. So the TradingView and TradeStation
seasonality tools are the SAME indicator — a strong cross-platform confirmation, and proof that
the seasonality Pine in our pack is not the one he uses.
Note our Python `TrueSeasonality` defaults to forward_bars=150; the lesson uses **45** and
TradeStation used **100**. Y-axis is unitless, so only SHAPE is comparable (consistent with R-03).

### Status
- Data alignment: **SOLVED**
- Valuation reference order: **FIXED in Pine** (Python was already correct)
- COT 156-week Hi/Lo input: **ADDED to Pine** (Python already had it)
- COT scale 0-100 vs -20/120: **ONE switch away from settled** — needs the corrected Pine on a
  TradingView chart, still blocked on the account/editor issue (Basic plan, unsaved 18BAR draft)
- Seasonality: our pack's Pine is the wrong script; his == TradeStation Algo Forecast

## C-57 — **COT INDEX SCALE CORRECTED to 0-100. FIX APPLIED AND PROVEN AGAINST THE LECTURE.**

The audit's longest-running open question is closed, and it did NOT need the browser —
the proof chain is complete from the frames plus CFTC data.

### The proof chain
1. **TradingView's COT feed IS the CFTC legacy futures-only series.**
   `replay/cot_alignment_check.py`: 8 of 8 raw net-position values read off HIS chart
   (Euro `6E1!`, "COT Comm/NonComm Net Futures Only") match CFTC to within **0.01K**, at a
   constant **-6 day** offset (a Tuesday report is plotted on the FOLLOWING Monday's bar,
   because that is when it became public). This simultaneously confirms the contract code
   (099741), the report type (futures-only), and the bar/report mapping.
2. **Therefore the data source is not a variable** — computing from CFTC in Python is
   equivalent to computing in Pine on his chart.
3. **On that data, his displayed value is reproduced EXACTLY by the 0-100 form.**
   Gold commercials, chart bar Mon 07 Aug 2023 (= CFTC report Tue 01 Aug 2023):
       LECTURE shows              34.43
       0-100 form                 34.43   (diff 0.002)
       140x-20 form (ours before) 28.21   (diff 6.23)
   The 140x-20 form reproduces **no** observed lecture value anywhere in 40 years of data
   (`cot_value_search.py`), while 0-100 lands on the exact bar the frame claims.
4. **The "Upper Bound Level" input in his settings dialog explains everything**: the real
   script maps the normalised 0..1 position onto [lowerBound, upperBound]. Our two Pine
   files were two presets of one script — 0/100 == `COTIndex_OTC.txt`, -20/120 == `COT V2
   120-20.txt`. The 120.00/-20.00 "spikes" earlier readers logged are the BOUND LINES read
   by the crosshair, the same mis-attribution R-02 already proved for the 126.21 anomaly.

### Why it matters (measured, `replay/cot_scale_impact.py`, 6 markets x 3 groups, ~1900 weeks)
Both forms are the same normalised position, so keeping the 80/20 thresholds while changing
the scale changes WHEN a reading is "extreme":
    0-100   : upper at **80.0%** of the 26w range, lower at **20.0%**
    140x-20 : upper at **71.4%**,                  lower at **28.6%**   <- our old behaviour
Result: the old form made **+4,221 extreme calls, i.e. 26.9% MORE than he does**, and
disagreed on the extreme classification in **13.9% of all weeks**. Our system was firing COT
extremes earlier and more often than the method it is supposed to replicate. The correction
makes it exactly as selective as he is — and fewer false extremes is the conservative
direction for a funded account.

### Applied (`BP_indicators.py` `COTIndex`)
- Scale is now an INPUT, mirroring the real indicator: `lower_bound` / `upper_bound`,
  **defaulting to 0/100**. `_scale()` helper maps normalised position onto the bounds,
  preserving the Pine `if max != min ... else na` guard.
- **All four scale sites** converted, not just the main one: `commercials_index` /
  `large_specs_index` / `small_specs_index`, the **156-week `*_extreme` overlay**, the
  **all-time expanding `*_alltime`** columns, and the `_v2()` helper inside
  `producer_vs_retailer_summary`. This was essential — `get_bias` compares the 156w overlay
  against the SAME 80/20 thresholds, so leaving it on the old scale would have silently
  corrupted every 'strong' verdict.
- Legacy behaviour is one argument away: `COTIndex(lower_bound=-20, upper_bound=120)`.

### Verified — `replay/test_c57_cot_scale.py`
- engine reproduces the lecture value **34.43** (diff 0.002) end-to-end on live CFTC data;
- legacy scale gives 28.21 and is asserted NOT to match;
- 156w + all-time overlays asserted to lie within 0..100 (mixed-scale guard);
- legacy mode still spans -20..120.
- Regression: C-22 (forex retail), C-44 (crude retail), C-48/C-49/C-50/C-51 all still pass;
  `BP_indicators` / `BP_rules_engine` / `run_scanner` all import.

### Note on the dual-tool finding (C-19)
Both tools genuinely exist in his TradeStation workspaces (0-100 "Campus Smart Money Index"
and the -20..120 "_Campus COT Index V2"). C-57 does not deny that; it establishes that the
**2025 TradingView course — the current teaching, and the corpus the user is building
from — uses the 0-100 scale**, and that our engine now matches it numerically. The other
variant remains reachable by passing the bounds.

### Browser status
The TradingView reproduction was set up (chart on COMEX:GC1! 1W, our Pine authored and
applied) but is **no longer needed for this question** — step 1 above already proves the
TradingView feed equals CFTC, so a Pine re-computation would only restate what Python shows.
Two housekeeping notes for the user:
- Their previously UNSAVED "18BAR" Pine draft was **saved to My Scripts** as
  *"The 18-Bar Trend System (Rosputnia / Williams)"* before any editing — it is now safer
  than it was, and is still applied to the chart.
- A scratch indicator ("AUDIT COT") remains on that chart and should be removed manually
  (its legend row exposes no Remove control to automation).

## C-59 — **BIGGEST FINDING: equity-index COT override is structurally wrong.** Measured on his REAL trades.

Validated the whole system against **18 of Bernd's ACTUAL trade signals** (not commentary),
each run with every series truncated to the signal date, COT truncated by publication lag.

| configuration | MATCH | hold | OPPOSITE |
|---|---|---|---|
| shipped default | 10 (56%) | 3 | **5 (28%)** |
| `BP_XCAT_SKIP_INDICES=1` | **13 (72%)** | 3 | **2 (11%)** |

**All 5 wrong-direction calls were equity-index LONGS he took** (ES x2, NQ, YM x2) where we
said bearish. Mechanism: `_analyze_fundamentals` applies `cross_category_signal()`
extreme_confluence to equity indices. On stock index futures the "commercials" are asset
managers HEDGING PORTFOLIOS — commercials-short + retail-long is their structural resting
state, not a bearish signal. YM=F 2024-02-14: commercials 3.8 (pinned short), retail 93.4
(pinned long) -> smart_vs_dumb flipped the bias bearish AND marked it 'strong'.
The code ALREADY excludes forex for exactly this reason (Phase 20). Indices need the same.

Added `rules.xcat_skip_equity_indices` / env `BP_XCAT_SKIP_INDICES=1`, **DEFAULT OFF**.
Companion flag from C-58: `rules.cot_blocks_zone_arrival` / `BP_COT_BLOCKS_ZONE=1`
(lecture set: opposite 12 -> 10, match unchanged).

**OUTSTANDING before enabling:** the 85-call lecture-set regression check for the xcat flag was
still running at session cutoff. Finish it first.

**Remaining 2 opposite are both ES=F** — ES non-commercials read 0.0 (extreme short) while he
went long, suggesting COT may not belong as a directional driver on indices at all (the code's
own comment says it should be "a confluence enhancer, not an override trigger" there).

**CAVEAT:** 2 of the failing ES/YM cases come from sessions that may not be presented by Bernd
(a "Clemens Winkler" title card appears in 03.01.2024 and 17.01.2024). Verify presenter identity
before drawing conclusions — the numbers may improve on their own.

---

## C-60 — **THE "REAL TRADES" GROUND TRUTH IS NOT BERND.** Provenance settled 2026-08-21.

`NEXT_WEEK_START_PROMPT.md` calls `validation/actual_signals.csv` **"his 18 REAL trades"** and
**"The ONLY test that counts"**. After labelling every row by presenter: **0 of 25 rows are a
Bernd trade.** The C-59 caveat above understated the problem — it is not 2 suspect rows, it is
all of them.

| corpus | who is on screen | how established |
|---|---|---|
| **Funded Trader Weekly Outlook** (52 `per_chapter` audits, C-01..C-59) | **Bernd Skorupinski** | Zoom name label on CW10-2024 `frame_003120`, cropped and upscaled, read by Claude vision |
| **Funded Trader Signals, 2023** | **Jan Skorupinski**, "Expert Trader" | `23.05.2023` `frame_000001`: Canva doc "Campus Grid Jan", signed "Jan Skorupinski / Expert Trader" with photo |
| **Funded Trader Signals, 2024** | **Clemens Winkler** | full-screen name card + Zoom label on `03.01.2024` and `14.02.2024`, both Claude-verified; username `clemensw` |

**The decisive frame** is `23.05.2023/frame_000001`. The signal grid it displays is signed by Jan
Skorupinski, and the grid's own numbers are rows sitting in our ground truth: `@SI` short entry
25.658 stop 26691, `@CL` long entry 68.86 stop 67 — i.e. `actual_signals.csv` rows for 2023-05-16.
The extracted "his real trades" are transcriptions of Jan's Campus Grid.

**Two earlier signals were red herrings.** (1) "Bernd's name appears nowhere in those transcripts"
— no transcript names anyone; grepping `03.01.2024`, `17.01.2024`, `14.02.2024`, `06.06.2023` for
Bernd/Skorupinski/Clemens/Winkler/"my name is" returns zero hits in *all four*, including
known-good sessions. (2) The Clemens card was thought to mark only `03.01`/`17.01.2024`;
`14.02.2024` — previously on the "undisputed" list, and the source of 3 of the 5 wrong-direction
rows — carries the identical card.

**These are not impostors.** Both are Online Trading Campus traders working under Bernd, running
his indicator pack (Campus Valuation V2.2, Campus True Seasonality Radarscreen, Campus GRID).
So the rows are legitimate evidence for *"does our code implement the OTC method"* and weak
evidence for *"does it reproduce Bernd's personal discretion"*.

**ACTIONS TAKEN**
- `validation/actual_signals_labelled.csv` — every row carries `presenter` +
  `presenter_confidence` (`verified` / `gemini_only` / `inferred_era`).
  Split: **17 Jan Skorupinski, 7 Clemens Winkler, 1 unknown, 0 Bernd.**
- `gemini/presenter_map.json` — per-folder verdict with the evidence for each.
- **Never pool these with Bernd rows unlabelled.** Report per-trader or not at all.

**WHAT SURVIVES:** the Weekly Outlook corpus is genuinely Bernd, so C-01..C-59 and
`lecture_verdicts_partial.csv` are unaffected. The lecture set is now the *only* Bernd ground
truth we have, and it is commentary rather than executed trades.

---

## C-61 — **C-59's fix targets the wrong layer.** Measured on Bernd's own index calls.

C-59 diagnosed the equity-index COT problem correctly but aimed the fix at
`cross_category_signal()`. On Bernd's own equity-index calls the bearish skew does **not** come
from there.

Bernd's lecture set contains **6 equity-index rows (5 unique — RTY=F 2023-06-03 is duplicated)**:
4 MATCH, 2 miss, 0 OPPOSITE. Toggling `BP_XCAT_SKIP_INDICES=1`:

| date | sym | his | OFF: cot/str -> ours | XCAT: cot/str -> ours |
|---|---|---|---|---|
| 2023-04-16 | ES=F | bearish | bearish strong -> hold | *unchanged* |
| 2023-06-03 | ES=F | bullish | **bearish strong** -> bullish | *unchanged* |
| 2023-01-15 | RTY=F | bullish | bullish normal -> bullish | *unchanged* |
| 2023-06-03 | RTY=F | bullish | bullish strong -> **bullish (MATCH)** | neutral none -> **hold (miss)** |
| 2023-10-29 | YM=F | bullish | **bearish strong** -> hold | *unchanged* |

Two facts fall out:

1. **The diagnosis holds.** Where our index COT reads `bearish/strong`, Bernd is bullish in 2 of
   3 cases (2023-06-03 ES, 2023-10-29 YM). Same error direction C-59 identified.
2. **The fix does not touch those rows.** The bearish reads survive the flag untouched, because
   they come from the SINGLE-category COT, not the cross-category override. The only row the flag
   changes is RTY=F 2023-06-03, where cross-category was firing in the **correct** direction —
   and the flag destroys it.

So on Bernd's own data `xcat_skip_equity_indices` **costs one correct call and fixes none.** Its
entire measured benefit (opposite 5 -> 2) comes from 2024 rows that C-60 shows are Clemens
Winkler's trades, not Bernd's.

**The real fix is one layer down**, exactly where the code's own comment already points: on
equity indices COT should be "a confluence enhancer, not an override trigger". Sample is small
(5 unique index calls, 2 contradictions) — do not over-fit it. Get more Bernd index calls from
the 14 unread Weekly Outlook chapters first (see C-62).

**RECOMMENDATION: DROP `xcat_skip_equity_indices`.** Keep the C-59 analysis, discard this fix.

---

## C-62 — 14 Weekly Outlook chapters were launched and never produced a report.

`RESUME_NEXT_SESSION.md` section 5 states "Weekly Outlook: all 63 chapters read." The files say
otherwise: `launched.txt` has 63 entries, `per_chapter/` holds 49 distinct Weekly Outlook report
dates (52 files, 3 of which are OTC lessons). **14 chapters have no report** — and START_HERE.md's
own rule is "if a report file is missing for a chapter listed in launched.txt, relaunch that
chapter."

2189 frames total. Prioritised list in `gemini/weekly_backlog.txt`, driver in
`gemini/run_weekly_backlog.py` (resumable). The two 2024 chapters are first: our code models the
3-ref `_CampusValuationTool_V2` he only runs from Oct-2023 on, they are the best remaining shot at
a 2024-25 equity-index settings dialog (C-37/C-38), and per C-61 more Bernd index calls are now
the blocking evidence for the COT-on-indices question.

---

## C-63 — **The ags COT trader-group question is CLOSED: commercials is CORRECT.** Do not change it.

C-34 and RESUME section 8a treated the ags/softs wrong-direction cluster (CT=F, ZC=F x2, ZW=F x2)
as "likely the trader-group choice". Measured, it is not.

**The failure-only test is a trap and was run first to show why.** Scoring trader groups on only
the 8 testable wrong-direction cases gives non-commercials 5/8 and retail-contrarian 5/8 vs
commercials 3/8 — i.e. "commercials is wrong, switch". That result is meaningless: the cases were
*selected* for commercials being wrong, so any alternative wins by construction.

**Run over EVERY Bernd call instead** (lecture set, duplicates removed, COT truncated by
publication lag):

| class | n | commercials | non-comm | retail-contrarian | retail-aligned |
|---|---|---|---|---|---|
| metals | 20 | **16 (80%)** | 4 (20%) | 14 (70%) | 6 (30%) |
| **ags** | **15** | **12 (80%)** | 3 (20%) | 6 (40%) | 9 (60%) |
| energy | 6 | 3 (50%) | 3 (50%) | **5 (83%)** | 1 (17%) |
| indices | 5 | 2 (40%) | 3 (60%) | 2 (40%) | 3 (60%) |
| **ALL** | **46** | **33 (72%)** | 13 (28%) | 27 (59%) | 19 (41%) |

Per ag symbol: ZW=F 3/3, SB=F 1/1, ZS=F 1/1, CT=F 3/4, ZC=F 4/6 — commercials wins on every one.
**Switching ags off commercials would make the system worse.** C-34's Sugar/OJ hypothesis
(Sugar belongs on Commercials like the other ags) is supported by SB=F 1/1 — weak but the right
direction.

Corroborations from the same table: **CL=F retail-contrarian 3/3** (C-44 was right), and indices
show no group above 60% on n=5 — consistent with the code's own "COT is a confluence enhancer,
not an override trigger" comment for equity indices.

**NG=F needs no change.** Its 1/3 on commercials looks alarming but NG is already routed to its
own `nat_gas` branch (non-commercials primary + retailer veto, Phase 41 S-01). The two NG
wrong-direction rows have our COT reading **bearish — correctly** — and the Phase-39 zone-arrival
rule firing bullish over it. That is C-58's mechanism, not a routing fault, and
`cot_blocks_zone_arrival` is precisely the fix for it.

**Frames corroborate the routing independently.** Mining the newly transcribed Weekly Outlook
chapters for which COT study is on screen per symbol (`gemini/analyze_cot_groups.py`):
ags show **commercials + retail, and non-commercials on ZERO frames** (ZS=F 27/0/9, KC=F 23/0/14,
ZW=F 10/0/1, ZC=F 6/0/6); forex is retail-dominant (USDCHF 20 retail vs 6 commercials,
corroborating C-22); equity indices are the only class where all three lines are displayed.

---

## C-64 — **The "12 OPPOSITE" headline is inflated by ground-truth labelling, not engine error.**

Before optimising the engine against these rows, the rows themselves were checked. Two ags cases
show our components reading **identically** on a MATCH and an OPPOSITE one week apart:

```
2023-12-10  ZC=F  he=bullish  we=bullish  | loc bullish  trend sideways  cot bullish  val bullish  seas bullish   MATCH
2023-12-16  ZC=F  he=bearish  we=bullish  | loc bullish  trend sideways  cot bullish  val bullish  seas bullish   OPPOSITE
```

No indicator we have distinguishes those bars, which means either he is using something we do not
model, or the label is wrong. Reading the source quotes, it is mostly the label:

| row | quote | assessment |
|---|---|---|
| 2023-12-16 CT=F (conf **high**) | "especially cotton **might** come down" | speculative aside, not a call |
| 2023-12-16 ZC=F | *same cotton quote*, corn swept in — and a **second row on the same date is labelled `neutral`**, describing waiting to buy a pullback | contradictory |
| 2023-12-31 ZC=F | "another 6% down move, the real seasonal low, end of January" | short-term pullback inside a bullish structure, not a bearish call |
| 2023-12-24 BABA | "we are long term... short term slowly getting overvalued" | valuation observation, not directional |
| 2024-01-29 PA=F | "…we're going to drop again.; **bullish as hell**. I would expect this to continue to drop." | two spliced fragments, self-contradictory |
| 2023-04-09 BTC-USD | "We might only because don't think we're going to go down much deeper." | garbled |

Genuinely wrong, engine's fault: **2023-04-16 BABA** ("we cannot go long, we are in a downtrend"),
**ZW=F x2** ("on a daily looks ugly" / "we are basically going lower"), **NG=F x2** (C-58
zone-arrival override), **2023-05-13 BTC-USD** ("we only want to buy, we are still undervalued" —
crypto has no COT and falls to a commercials default, C-52).

**So the true wrong-direction rate is ~6-7 of 85 (7-8%), not 12 of 85 (14%).** The MATCH rate is
unaffected — this only reclassifies failures.

**ACTION REQUIRED before the next optimisation pass:** re-audit `lecture_verdicts_partial.csv`
against source frames and drop or downgrade the speculative/spliced rows. Optimising the rules
engine against labels this noisy is exactly how a system gets fitted to nothing. This is the same
error class RESUME section 0 already flagged (the crude "until the retailers are getting fully
bearish" row that was him WAITING, not buying).

---

## C-65 — **Valuation settings, measured at scale from 7 newly-transcribed chapters.**

The Gemini backlog (C-62) made a much larger sample available than the audit had. Mining every
`_CampusValuationTool_V2` legend across the transcribed chapters
(`gemini/analyze_valuation.py`):

### C-53 TIMEFRAME — settled. He runs Valuation on DAILY charts.

```
daily 117   |   weekly 7   |   unclear 3
```

Independently reproduces the earlier "~95 daily vs 6 weekly" corpus tally on a fresh sample.
Our scanner computes Valuation from the **weekly** HTF series and fetches all three reference
series weekly too, so "ROC Length 10" means **10 weeks** to us and **10 days** to him. This is
OPEN DECISION #1 and the evidence for it is now strong. Still not applied — the fix touches the
fundamentals pipeline and the reference fetching together.

### References — our config is CORRECT, no change needed.

```
@US, @GC, $DXY   x350 (plus 104 OCR variants of the same triple)
flags True,True,True   x398        True,True,False   x1
```

All three references active essentially always. `equity_indices` already carries all three in
`run_scanner.VALUATION_REFS`; the "bonds only" narrowing is scoped to individual `equities`,
which is what the stock-chart evidence supports. Nothing to change.

### C-37/C-38 LENGTH — the split is by asset class, and our index value looks WRONG.

| symbol group | Length seen |
|---|---|
| **equity indices** (@YM, @RTY, @NQ) | **13 x49**, 10 x4 |
| **stocks** (AAPL, GOOG) | **13 x4** |
| everything else (GC, KC, ZS, ZC, ZW, PL, PA, CL, DXY, AUDUSD, EURUSD, USDCHF, USDJPY) | **10** — 73 sightings in CW10-2024 alone, never 13 |

Our config has `equity_indices: 10` (BP_rules_engine.py:221, "deliberately left at 10"). The
measured evidence says **13** for indices and stocks, **10** for everything else — i.e. our index
value is the one that is off, and C-38's "every 2024 reading is 10" is contradicted by 49 readings
of 13 in a 2024 chapter.

**Both endpoints Claude-vision verified**, not taken from Gemini:
`frame_000213` = `..True,True,True,10,..` and `frame_000360` = `..True,True,True,13,..`, both on
`@YM(D) - Daily`, same chapter.

**HOLD before changing the config.** All index sightings come from ONE chapter (CW11-2024,
"Equity Indices and Stocks"), and the frame ordering shows him at 10 for frames 40-224 and 13
from frame 319 on — i.e. he **changed it on camera mid-session**. That is the same short-term /
long-term toggle behaviour C-31 proved on soybeans, so a single session cannot establish the
default. The remaining backlog chapters include further multi-market editions; re-run
`gemini/analyze_valuation.py` once they land and only then decide. Changing `equity_indices` to 13
on one chapter's evidence would repeat exactly the mistake this audit exists to correct.

---

## C-66 — **Seasonality indicator identified and our lookbacks CONFIRMED correct.** No change needed.

RESUME section 5 records that our pack's `Seasonality_OTC.txt` is the wrong indicator, and that
his "Seasonality Index - v4" has five inputs identical to TradeStation's Campus Algo Forecast.
The transcribed chapters confirm the identity and now give the actual inputs:

```
Campus Algo Forecast ( N , 100 , False , False , False )

N=15  x191      N=10  x143      N=5  x95      N=6  x13
```

The first input is the seasonal lookback in YEARS and he cycles it across **5 / 10 / 15** — the
same toggle habit as Valuation Length (C-31, C-65). The remaining inputs are constant
(`100, False, False, False`) in all 442 sightings; the handful of 4-item and 6-item signatures are
transcription truncation of the same string, not different settings.

**Our implementation already matches**: `BP_indicators.Seasonality.DEFAULT_LOOKBACKS = (5, 10, 15)`,
with the documented rule that bias is strongest when all three agree. That is exactly the set he
runs, arrived at independently from the textbook. **Confirmed correct on 429 frame sightings —
no code change.**

Open item this does NOT close: the C-52 finding that seasonality is silently dead on ~21 forex
pairs because of an absolute price threshold. That is a separate defect in our code, not a
settings mismatch.

---

## C-67 — **After cleaning the labels, the failure mode is ONE thing: Location overrides everything.**

Running the reviewed ground truth (C-64) through the engine, both flags OFF:

| ground truth | n | MATCH | hold | OPPOSITE |
|---|---|---|---|---|
| original `lecture_verdicts_partial.csv` | 85 | 40 (47%) | 33 | 12 (**14%**) |
| **reviewed** `lecture_verdicts_reviewed.csv` | 75 | 37 (**49%**) | 32 | **6 (8%)** |

The predicted ~7-8% true wrong-direction rate is confirmed at **8%**. Match rate is essentially
unchanged (47% -> 49%), as expected — the review only reclassified failures, it did not flatter
the hit rate.

**All 6 survivors share one signature:**

```
date        sym      his      ours     | location  trend      cot      val       seas
2023-04-16  BABA     bearish  bullish  | bullish   sideways   neutral  bullish   bearish
2023-05-13  BTC-USD  bullish  bearish  | neutral   downtrend  bearish  bearish   bearish
2024-02-11  NG=F     bearish  bullish  | bullish   downtrend  bearish  neutral   bullish
2024-02-19  NG=F     bearish  bullish  | bullish   downtrend  bearish  neutral   bullish
2024-02-11  ZW=F     bearish  bullish  | bullish   sideways   neutral  bullish   bullish
2024-03-09  ZW=F     bearish  bullish  | bullish   sideways   neutral  bullish   bullish
```

**`location = bullish` in 5 of 6, and it wins every time.** The NG pair is the clearest possible
statement of the defect: our own **trend reads `downtrend`** and our own **COT reads `bearish`** —
both agreeing with him — and the Phase-39 zone-arrival rule fires **bullish** over the top of both.
That is C-58's asymmetric rule, and it is now the single largest identified failure mode in the
system, not "the consensus layer" generally.

**Split of the remaining 6 by root cause:**

1. **Zone-arrival overrides an opposing COT — 2 rows (NG=F x2).** Fixed by
   `cot_blocks_zone_arrival` (C-58). Measured: passes the goldtest OOS regression with 0 cases
   changed, and removes exactly these 2.
2. **Zone-arrival overrides a bearish price read our TREND detector missed — 3 rows
   (ZW=F x2, BABA).** Our trend says `sideways`; he says *"on a daily looks ugly"*, *"we are
   basically going lower"*, *"we cannot go long, we are in a downtrend"*. COT is `neutral` on all
   three, so the COT guard cannot help. **This is a TREND-DETECTION gap, newly isolated** — our
   detector calls sideways where he calls a downtrend. Next investigation.
3. **Crypto has no COT — 1 row (BTC-USD).** Falls through to a Commercials default that appears
   nowhere in his methodology (C-52). Known cause, unfixed.

**Consequence for the flag decision:** `cot_blocks_zone_arrival` addresses category 1 only, and
that is 2 of 6. It is still worth enabling (positive on Bernd data, zero goldtest regression), but
it is not the fix for the system — **category 2 is now the highest-value open lead**, and it is a
trend-detection problem, not a COT or consensus problem.

---

## C-68 — Trend timeframe tested (daily vs weekly). **Result INCONCLUSIVE — do not act on it yet.**

C-67 category 2 isolated three wrong-direction rows where our trend says `sideways` and he says
the market is going lower, and his own words name a timeframe: *"on a **daily** looks ugly"*
(ZW=F 2024-02-11). Our scanner runs `_determine_trend` on the **weekly** HTF. Same suspected root
cause as C-53.

**Failure-only test (the misleading one, run first to show the trap):** on the 6 genuine failures,
daily agrees with him 4/6 vs weekly 2/6 — ZW=F 2024-03-09 and BABA 2023-04-16 both flip to correct.
Selection bias again: those rows were chosen for the engine being wrong.

**Unbiased test over the whole reviewed ground truth (n=75):**

| bars | agree | disagree | sideways | agree % of decided |
|---|---|---|---|---|
| WEEKLY | 25 | 19 | 31 | 57% (of 44) |
| DAILY | 23 | 14 | 38 | 62% (of 37) |

Daily is modestly more accurate when it commits (62% vs 57%) but commits less often (37 vs 44
decided). Net agree-minus-disagree: weekly +6, daily +9. **That difference is well inside noise at
this sample size. It does NOT justify changing the trend timeframe.** Re-measure after the C-62
backlog adds Bernd calls.

**The larger finding is in the same table and is not about timeframe at all:** the trend detector
returns `sideways` on **31 of 75 rows on weekly (41%) and 38 of 75 on daily (51%)**. It abstains
about half the time. That lines up with the scoreboard's **39% "hold"** rate — most of the gap
between us and Bernd is the system declining to call, not calling wrong. Making the detector
commit more often is a larger available gain than moving it to a different timeframe, and the
ZigZag pivot thresholds (`_zigzag_pivots`, ~6% weekly) are the obvious lever.

**No code changed.**

---

## C-69 — `cot_blocks_zone_arrival` APPLIED and verified through the config path.

`BP_config.yaml` gained a `rules:` block (the file had none; both flags were reading their
code-level `False` default). Backup `BP_config.yaml.bak-2026-08-21`.

```yaml
rules:
  cot_blocks_zone_arrival: true
  xcat_skip_equity_indices: false
```

**Verified end to end with NO environment variables set**, so the config path is confirmed live and
not just the env override that was used for the A/B:

| run | n | MATCH | hold | OPPOSITE |
|---|---|---|---|---|
| flags-off baseline | 75 | 37 | 32 | 6 (8%) |
| env `BP_COT_BLOCKS_ZONE=1` | 75 | 37 | 34 | 4 (5%) |
| **config `cot_blocks_zone_arrival: true`** | 75 | **37** | **34** | **4 (5%)** |

**0 rows differ between the config run and the env run.**

Remaining 4 wrong-direction rows, all outside this flag's reach:
```
2023-04-16  BABA     he=bearish  we=bullish     trend says 'sideways', he says downtrend
2023-05-13  BTC-USD  he=bullish  we=bearish     crypto has no COT (C-52 commercials default)
2024-02-11  ZW=F     he=bearish  we=bullish     trend says 'sideways', he says "looks ugly"
2024-03-09  ZW=F     he=bearish  we=bullish     trend says 'sideways', he says "going lower"
```
Three of four are the C-68 trend-abstention problem, not a COT or consensus problem.

---

## C-70 — **CRITICAL: the system is structurally LONG-ONLY. It matches 64% of his longs and 5% of his shorts.**

This is the largest finding in the audit and it supersedes the flag debate entirely.

### Measured, reviewed ground truth, flag applied (n=75)

```
he said  : bullish 56   bearish 19
we said  : bullish 39   bearish  2   hold 34
```

| his call | n | we MATCH | we hold | we OPPOSITE | match rate |
|---|---|---|---|---|---|
| **bullish** | 56 | 36 | 19 | 1 | **64%** |
| **bearish** | 19 | **1** | 15 | 3 | **5%** |

**We emit a bearish call on 2 of 75 rows (3%). He is bearish on 25% of his calls.** On the 19
occasions he said "short this", the system produced his direction **once**. Fifteen became "hold"
and three came out bullish.

The headline 49% match rate is therefore almost entirely a long-only score: it is 64% on the
bullish half and near-zero on the bearish half. A prop account running this takes longs and sits
out (or fades) every short he takes.

### Root cause is in the decision function, not the indicators

`BP_rules_engine._bias_consensus` (727 lines):

```
return 'bullish'  x17
return 'bearish'  x4
return 'neutral'  x0
```

**Seventeen ways to conclude buy, four ways to conclude sell.** The bearish branches additionally
carry guards the bullish ones do not — the surviving asymmetry after C-58:

```python
if loc_n == 'bullish' and val != 'bearish' and _ng_seas_ok and _cot_long_ok:
    return 'bullish'
if (loc_n == 'bearish' and val != 'bullish' and _ng_seas_ok
        and _forex_cot_short_ok and _cot_short_ok_sym):     # two EXTRA conditions
    return 'bearish'
```

C-58 fixed one half of one rule (adding `_cot_long_ok` so the bullish branch is also COT-guarded).
It did not touch the 17-vs-4 imbalance across the whole function.

### Corroborating signature in the component readings

Profile of the 37 MATCH rows: `location bullish 59%`, `valuation bullish 57%`,
`seasonality bullish 70%`, and **`cot bearish 3%`, `valuation bearish 3%`**. The system reaches a
confident verdict essentially only when every input is bullish. The 34 HOLD rows are the mirror:
`location bearish/neutral 88%`, `valuation neutral 68%`.

Note the HOLD rows are NOT explained by trend abstention — only 35% of them have `trend=sideways`,
and 41% actually read `uptrend`. So C-68's "make the trend detector commit" lead is **not** the fix
either; the abstention happens downstream, in consensus.

### The ZigZag threshold is already optimal — that knob is not the lever

Sweep of the weekly ZigZag reversal pct against his calls (n=75):

| zz pct | agree | disagree | sideways | commit rate | accuracy when committed |
|---|---|---|---|---|---|
| 0.02 | 20 | 23 | 32 | 57% | 47% |
| 0.03 | 16 | 22 | 37 | 51% | 42% |
| 0.04 | 22 | 20 | 33 | 56% | 52% |
| **0.05** | **28** | 18 | 29 | **61%** | **61%** |
| **0.06 (current)** | **28** | 18 | 29 | **61%** | **61%** |
| 0.08 | 14 | 21 | 40 | 47% | 40% |
| 0.10 | 16 | 21 | 38 | 49% | 43% |

The shipped 0.06 sits exactly at the optimum on both commit rate and accuracy. Loosening it to
manufacture more calls makes the detector *less* accurate. **No change.**

### What to do next — and what NOT to do

**Do not** patch individual bearish branches to fire more easily. That is curve-fitting toward a
target and is how this system got here.

**Do** treat the 17-vs-4 imbalance as the design question: enumerate every `return 'bullish'` path,
ask for each whether a mirror-image bearish path exists, and where it does not, establish from the
corpus whether Bernd genuinely has an asymmetric rule there or whether the bearish twin was simply
never written. Several bullish paths (zone-arrival, seasonality-plus-valuation, cycle overrides)
have no bearish counterpart at all.

**Measure any candidate change against all four harnesses** — reviewed lecture set, original
lecture set, goldtest OOS, goldtest lectures — and report the bullish/bearish split separately
every time. A change that lifts the overall number while leaving the short side at 5% has fixed
nothing.

**Sample-size caveat:** 19 bearish calls is a small base. The direction of the finding is not in
doubt (2 bearish outputs in 75 rows is a structural fact about the code, independent of the ground
truth), but the exact 5% figure will move as the C-62 backlog adds Bernd calls. Re-measure then.

---

## C-71 — Goldtest A/B complete (8 runs). Flags settled; C-70 independently corroborated.

Both goldtest suites x both flags x on/off, run to completion:

| suite | config | n | bias_match | bias_only |
|---|---|---|---|---|
| OOS | off | 71 | 40 | 41 |
| OOS | xcat | 71 | 40 | 41 |
| OOS | cotzone | 71 | 40 | 41 |
| OOS | both | 71 | 40 | 41 |
| lectures | off | 32 | 9 | **21** |
| lectures | xcat | 32 | 9 | **20** |
| lectures | cotzone | 32 | 9 | **21** |
| lectures | both | 32 | 9 | **20** |

### Flag verdicts, now measured on every harness we have

| harness | `xcat_skip_equity_indices` | `cot_blocks_zone_arrival` |
|---|---|---|
| Bernd reviewed labels (n=75) | −1 correct call | **−2 opposite, 0 cost** |
| Bernd original labels (n=85) | −1 unique call | −2 opposite, 0 cost |
| goldtest OOS (n=71) | 0 change | 0 change |
| goldtest lectures (n=32) | **−1 bias_only** | 0 change |
| non-Bernd signals (n=23) | −3 opposite | 0 change |

`xcat` is **negative or neutral on every Bernd harness** and positive only on the non-Bernd rows
C-60 disqualified. **DROPPED — confirmed on five measurements.**
`cot_blocks_zone_arrival` is positive on one and neutral on four, with zero regressions anywhere.
**ENABLED — confirmed (C-69).**

### The goldtest lectures suite corroborates C-70 from a completely separate harness

Directional breakdown of that suite (Bernd's own published calls, different extraction, different
code path from `validate_against_lectures.py`):

```
he = long     we = long        1
he = long     we = neutral    23
he = neutral  we = neutral     8
```

**Of his 24 directional calls the system produced his direction once — 23 came out neutral.**
Stage-2 full-signal is 9/32 (28%). There is not a single short in the suite, so this measures the
abstention half of C-70 rather than the long/short split, and it is worse here than on the
reviewed lecture set: **96% neutral on his longs.**

Two independent harnesses, built at different times from different ground truth, both say the
system's dominant behaviour is **declining to call**. C-70's 17-vs-4 imbalance in
`_bias_consensus` is the common explanation, and neither flag moves it — every config above scores
identically on `bias_match`.

---

## C-72 — **The pre-election equity-index SHORT BLOCK rests on a premise that is false.** Natural experiment attached.

### The block

`BP_rules_engine._bias_consensus`, Phase 42 Fix-2:

```python
# When pres+sann cycles are both bullish (e.g. year-3 pre-election = 2023),
# Bernd NEVER takes equity-index short positions -- 0 such calls in 160 goldtest.
# The flag ... blocks any bearish return for equity indices during pre-election cycles.
if _pres42 > 0 and _sann42 > 0:
    _equity_idx_no_short = True
```

Verified active state: **every month of 2023 is blocked** (cycle year 3, pres=1, sann=1); 2024 is
not (cycle year 0, pres=0, sann=0).

### The premise is contradicted by his own Weekly Outlook

Three 2023 equity-index bearish calls, extracted this session from chapters that had never been
mined (C-62), each read in full transcript context per C-64:

- **YM=F 2023-09-16** — *"we are moving from that supply area where price was at least
  overvalued … we had this head and shoulders that we discussed … And this is really falling apart.
  And I think it will fall apart just before."* Four stacked reasons. The cleanest bearish call in
  the batch.
- **YM=F 2023-09-23** — *"expect some follow through to the downside, especially after bearish
  candle like this … I don't see any buying"*
- **NQ=F 2023-09-16** — *"And on the nasdaq. Similar scenario here also we have a daily bearish
  engulfing"*

"0 such calls in 160 goldtest" was **absence of evidence** from a corpus that had not been mined
for 2023 index shorts. Fourteen Weekly Outlook chapters were never read at all (C-62), and the
first four of them yielded three.

### Natural experiment — the block is the whole explanation

The five new equity-index bearish calls split cleanly by year, and nothing else differs:

| call | year | blocked? | our output | outcome |
|---|---|---|---|---|
| YM=F 2023-09-16 bearish | 2023 | **YES** | bullish | OPPOSITE |
| YM=F 2023-09-23 bearish | 2023 | **YES** | bullish | OPPOSITE |
| NQ=F 2023-09-16 bearish | 2023 | **YES** | hold | miss |
| NQ=F 2024-03-10 bearish | 2024 | no | **bearish** | **MATCH** |
| RTY=F 2024-03-10 bearish | 2024 | no | **bearish** | **MATCH** |

Same asset class, same detector, same trader, six months apart. **Blocked → 0/3. Unblocked → 2/2.**

This also explains the C-67 anomaly that had no explanation: `YM=F` rows where
`location = bearish` and every other component is neutral, yet the engine returns **bullish**. The
bearish return is simply unavailable, so a weaker bullish path wins by default.

### Enlarged-ground-truth measurement (C-70 re-confirmed)

Merged set, 85 rows (75 reviewed + 10 newly extracted, bearish sample 19 -> 25, +32%):

| his call | n | MATCH | hold | OPPOSITE | match rate |
|---|---|---|---|---|---|
| bullish | 60 | 38 | 21 | 1 | **63%** |
| bearish | 25 | 3 | 17 | 5 | **12%** |

We emit bearish on 4 of 85 (5%); he is bearish on 29%. **C-70 holds on the larger sample.**

### Flag added, DEFAULT OFF

`rules.allow_prelection_index_shorts` / env `BP_ALLOW_PREELECTION_INDEX_SHORTS=1`.
Backup: `BP_rules_engine.py.bak-2026-08-21`. A/B in progress; do not enable until it is measured on
the merged set AND both goldtest suites — the goldtest is where this block was originally tuned, so
it is the run most likely to show a cost.

### Note on the second structural long bias

`_bias_consensus` also carries, by design and separately from this block:

```
# STOCKS: Valuation-driven, long-only (Phase 6 audit validated)
```

The `equities` class is **deliberately long-only**. Combined with the index block, two of the
largest asset classes in the watchlist are structurally incapable of producing a short. That is
most of C-70's mechanism, and unlike the 17-vs-4 branch imbalance it is explicit and intentional —
so it needs the same treatment: find whether the corpus actually supports it, or whether it is
another absence-of-evidence rule.

---

## C-73 — Ground truth grown 75 -> 95 rows from the newly transcribed chapters. Bearish sample +42%.

C-70's long-only finding rested on 19 bearish calls. The 11 chapters transcribed under C-62 were
mined for Bernd's own directional calls, using `gemini/build_call_candidates.py` (Gemini supplies
the symbol on screen per frame; the spoken line comes from `transcript.json`; the CALL judgement is
made by reading the block in context, never from an isolated cue line).

```
session start :  75 rows   56 bullish   19 bearish
after batch 1 :  85 rows   60 bullish   25 bearish
after batch 2 :  95 rows   68 bullish   27 bearish     (bearish +42%)
```

Files: `validation/lecture_verdicts_new_2026-08-21.csv`, `..._new_batch2.csv`, merged into
`validation/lecture_verdicts_merged.csv`. Every row carries its verbatim quote and a note on why it
was judged that way.

### C-64 discipline applied — these were NOT counted as calls

- `AAPL` CW36 — *"we don't want to short now … we don't want to go long right now"* (explicit no-trade)
- `ES=F` CW36 — *"once we are overvalued I'm the first one who going to scream let's look to short"* (waiting)
- `YM=F` CW11-2024 — *"I need all stars aligned … here it's not even close"* (explicit no-trade)
- `SI=F` CW10-2024 — *"silver we would not trade yet"*
- `GC=F` CW10-2024 — *"we wait for another dip … wait to retrace back into that weekly"* recorded as
  **bullish**, because a pullback into a buy zone is entry timing, not a bearish call.

Two genuine two-week direction flips were preserved rather than smoothed: `SI=F` bullish (CW37) ->
bearish (CW39), and `RACE` bearish (CW07) -> bullish (CW09).

### Anti-bias check on my own extraction

If the rows I wrote scored BETTER than the pre-existing ones, that would suggest I had selected
calls the engine already agrees with. Measured on the 95-row set, shipped config:

| row source | n | MATCH | hold | OPPOSITE |
|---|---|---|---|---|
| original | 75 | 37 (**49%**) | 34 | 4 |
| new batch 1 (mine) | 10 | 4 (**40%**) | 4 | 2 |
| new batch 2 (mine) | 10 | 3 (**30%**) | 6 | 1 |

They score **lower**, which is the safe direction. The overall match rate consequently fell 49% ->
46% as the set grew — the honest consequence of adding harder, previously unmined calls, and worth
stating rather than quoting the old 49%.

### C-72 flag re-measured on the 95-row set

| config | MATCH | hold | OPP | his-bullish | his-bearish | we output bearish |
|---|---|---|---|---|---|---|
| pre-election block ON (shipped) | 44 (46%) | 44 | 7 | 41/68 (60%) | **3/27 (11%)** | 5 |
| block OFF | **46 (48%)** | 42 | 7 | 41/68 (60%) | **5/27 (19%)** | 7 |

Same +2 / 0-cost result as on the 85-row set — it replicates as the sample grows. Both converted
rows are `hold -> bearish MATCH`, and one of them (**ES=F 2023-04-16**) is an ORIGINAL row, not one
extracted this session, so the gain is not an artefact of my own labelling.

### CLEAN goldtest verdict (back-to-back, noise floor 0 per C-74)

The first goldtest attempt was time-separated and unusable. Re-run back-to-back from one fetch
window:

| config | bias_match | bias_only |
|---|---|---|
| block ON (shipped) | 40 | 41 |
| block OFF | **40** | **40** |

`bias_match` cases changed: **0**. `bias_only` cases changed: **1**, and it IS equity_indices, so
unlike the earlier NG=F noise it is genuinely attributable to the flag:

```
ES=F 2023-04-24   Bernd = neutral
  block ON  : direction=neutral  bias_only=neutral  -> match
  block OFF : direction=neutral  bias_only=short    -> miss
  components: location bearish | cot bearish STRONG | seasonality bearish
              | valuation neutral | trend sideways | constituent bullish
```

Note `direction` is `neutral` under BOTH settings — **no trade fires either way**. The cost is a
Stage-1 directional *view* on a date Bernd stayed silent, not a spurious position. And the view is
defensible on its own components: four of them read bearish.

### Full ledger

| harness | effect of lifting the block |
|---|---|
| Bernd 85-row | **+2 MATCH**, 0 new opposites |
| Bernd 95-row | **+2 MATCH**, 0 new opposites, his-bearish 11% -> 19% |
| goldtest OOS, trade level (`bias_match`) | **0 change** |
| goldtest OOS, view level (`bias_only`) | **-1** (ES=F, he was neutral, no trade fired) |
| goldtest lectures | 0 change |

Two correct directional calls gained against one directional view added where he was silent, and
zero trade-level changes. Favourable, and not free.

**STILL DEFAULT OFF — deliberately, and this is a judgement call not a measurement gap.** Lifting
it re-enables an entire class of trade (equity-index shorts in pre-election years) on a funded
account. The two flags the session was mandated to decide (C-58, C-61) are settled; this is a third
that was discovered, not commissioned. It needs an explicit human decision.

Also note this is a PARTIAL fix: the two `YM=F` OPPOSITE rows do NOT flip when the block is lifted,
so some other bullish path still wins there. Lifting the block does not by itself resolve C-70.

---

## C-74 — **METHODOLOGY DEFECT: goldtest A/B runs made at different times are not comparable.**

This affects how every goldtest-based conclusion in this project should be read, including
historical ones.

### The observation

Four OOS goldtest runs (`off` / `xcat` / `cotzone` / `both`) produced **identical totals** —
bias_match 40, bias_only 41 in all four — yet disagreed on **individual cases**:

```
bias_only cases differing vs the 'off' run:   xcat 2    cotzone 4    both 6
```

Breakdown of every case that flips across those configs:

| symbol | flips | asset class |
|---|---|---|
| **NG=F** | **12** | energies |
| NQ=F | 2 | equity_indices |
| YM=F | 2 | equity_indices |
| ES=F | 1 | equity_indices |

**Neither flag can touch `energies`.** `xcat_skip_equity_indices` only adds to a skip-set for
equity_indices/equities; `cot_blocks_zone_arrival` guards the zone-arrival branch. Twelve NG=F
flips are therefore, by construction, not caused by the configs.

### The engine is NOT the cause — it is deterministic

Case `NG=F 2023-01-22` was re-run in isolation:
- **4 iterations inside one process** -> `bias_only='short'` every time, one distinct
  `bias_components` set.
- **5 separate processes**, including two with `PYTHONHASHSEED=0` -> `'short'` every time.

So it is not set/dict iteration order, not leaked state, not randomness. Given the same inputs the
engine returns the same answer.

### The cause is live data re-fetched per run

Each goldtest run re-fetches price and COT from the network. The runs above were made 44+ minutes
apart. `bias_components` looked identical between the two NG=F runs, but the components dict does
NOT capture everything the consensus consumes (`at_zone`, `zone_composite`, the cycle scores), and
those derive from price data fetched at run time. C-52 already records the related defect that a
**data outage reads as 'neutral' (= "does not oppose") rather than "unknown"**, which converts a
transient fetch problem into a silent directional change.

### Consequences — corrections to earlier conclusions in this file

1. **C-72's "-1 bias_only on OOS" is NOT a regression.** It sits inside a noise band of at least
   2-6 cases. The pre-election flag's goldtest result should be read as **no detectable change**.
2. **C-71's "xcat costs -1 bias_only on goldtest lectures" cannot be attributed to the flag either.**
   The verdict on `xcat` does not change — it was negative on the *deterministic* Bernd lecture
   harness (-1 unique correct call) and had zero Bernd-side support — but that one line of its
   evidence was noise and is withdrawn.
3. **The historical claim that justified keeping COT-is-king narrow** — "Phase 37/40 previously
   tried widening COT-is-king and LOST goldtest cases" (quoted in the C-58 code comment) — was
   measured the same way and may equally have been data drift. It should not be treated as settled
   evidence against widening COT authority.

### REFINEMENT (measured after the above): the noise is TIME-dependent, not per-run

Two runs of the **identical** config, executed back-to-back:

```
run 1: bias_match 40   bias_only 41
run 2: bias_match 40   bias_only 41
cases differing on bias_match : 0
cases differing on bias_only  : 0
```

**Noise floor for back-to-back runs is ZERO on both metrics.** The harness is perfectly
reproducible when two runs share a data-fetch window. The 2-6 case disagreements above came from
runs separated by 44+ minutes, i.e. genuine drift in the live data between fetches, not from any
per-run randomness.

This sharpens the rule rather than condemning the harness:

- **Back-to-back A/B runs ARE valid and exact.**
- **Runs separated by tens of minutes are NOT comparable.** The 8-run matrix in C-71 was executed
  sequentially over roughly two hours, so its per-case deltas are contaminated; its *totals* were
  stable (bias_match 40 in all four OOS configs), which is why the flag verdicts survive.
- Corrections 1-3 above stand: those deltas were measured across time-separated runs and cannot be
  attributed to the configs.

### Required fix before the goldtest is used for A/B again

Pin the data. The harness should fetch once, cache to disk keyed by (symbol, interval, as-of date),
and have every configuration replay from that cache. Until then:

- **Only compare goldtest runs executed back-to-back from the same data snapshot.**
- **Treat any delta of fewer than ~6 cases on `bias_only` as noise.**
- `bias_match` totals were stable at 40 across all four configs, so that metric appears far less
  sensitive — prefer it.
- The Bernd lecture harness (`validate_against_lectures.py`) has not shown this behaviour: the
  C-72 flag produced exactly the same 2-row change on both the 85-row and 95-row sets, and the
  changed rows were named and identical. Prefer it as the primary measurement.

---

## C-75 — Verification layer: Gemini spot-checked on the Weekly Outlook corpus. Two applied fixes independently confirmed.

The mandated pipeline requires Claude vision to check 100% of any number we act on plus a 10%
random sample. **A note on that rule as implemented:** `read_frames.is_actionable()` flags any frame
carrying a COT/Valuation/Seasonality legend, which is ~1250 of the transcribed frames (186 in
CW10-2024 alone). Verifying all of them with Claude vision would spend exactly the tokens the
Gemini pipeline exists to save, and it is the wrong unit anyway — 92 frames all reading `13` do not
need 92 verifications, the distinct VALUE does. Recommended refinement: verify each distinct
actionable value 2-3 times, not every frame that carries one.

### Verifications performed (all Claude vision, full resolution)

| what | frame | Gemini said | verdict |
|---|---|---|---|
| Valuation Length, index | CW11-2024 `frame_000213` | `True,True,True,10` on `@YM(D) Daily` | **exact** |
| Valuation Length, index | CW11-2024 `frame_000360` | `True,True,True,13` on `@YM(D)` | **exact** |
| COT nets, 3 groups | CW11-2024 `frame_000213` | comm -17331 / fund 14586 / retail 2745 | **exact** (and reproduced by our CFTC pipeline to the contract) |
| Presenter card | Signals `03.01.2024` / `14.02.2024` | "Clemens Winkler" | **exact** |
| Presenter label | CW10-2024 `frame_003120` | "Bernd Skorupinski" | **exact** |
| RANDOM sample | CW09-2023 `frame_001925` | `Campus Valuation Index 3383376 ( @US ,13, 3, 100, -100, 100, 75 ,...) @US 0.83` | **exact** (only `"@US"` vs `@US*` quote rendering) |
| RANDOM sample | CW38-2023 `frame_000312` | `Campus Algo Forecast (15,100,False,False,False) 2124.82`, `@GC=120XN+GJMQZ Daily`, crosshair `09/21/23` | **exact** — symbol, timeframe, crosshair date, all 5 inputs, value |

**7 of 7 exact.** Sample is small and partly targeted rather than purely random, so this is a
consistency check, not a precision estimate — the measured precision figure remains the OTC-lesson
benchmark (30/30 on high-confidence rows, 41/44 windowed).

### The PFE frame independently confirms two APPLIED fixes

`CW09-2023 frame_001925` shows **PFE (an individual stock), Feb 2023**, running
**`Campus Valuation Index`** — the SINGLE-reference tool — with `@US` (bonds) as its only reference
and **Length 13**.

That corroborates, from a frame nobody had looked at:
1. **C-38's era distinction** — 2023 uses the single-ref `Campus Valuation Index`, not the 3-ref
   `_CampusValuationTool_V2`.
2. **Applied fix #3** — `equities` valuation references narrowed to **bonds only**.
3. **Applied fix #2 / C-14** — `equities` valuation Length **30 -> 13**.

Three of the audit's applied changes, confirmed by a randomly drawn frame from unaudited material.

---

## C-76 — **TARGET CHANGED to "match all three OTC traders". `xcat_skip_equity_indices` REVERSED and ENABLED.**

User directive 2026-08-21: *"our system should match with them whether its 2 guy trading or bernd."*
Jan Skorupinski and Clemens Winkler run Bernd's method with his indicator pack (Campus Valuation
V2.2, Campus True Seasonality, Campus GRID), so a correct implementation should agree with all
three. C-60 disqualified their rows as *Bernd* evidence; it does not disqualify them as *OTC-method*
evidence, and the goal is now the latter.

### Combined ground truth: `validation/all_traders_ground_truth.csv`, 118 rows

| trader | rows | source |
|---|---|---|
| Bernd Skorupinski | 95 | Weekly Outlook directional calls |
| Jan Skorupinski | 16 | Funded Trader Signals |
| Clemens Winkler | 7 | Funded Trader Signals |

Every row keeps a `presenter` and `source` column so it can always be split back apart.

### Four-config measurement

| config | MATCH | hold | OPP | longs | shorts | Bernd | Jan | Clemens |
|---|---|---|---|---|---|---|---|---|
| shipped (both off) | 58 (49%) | 48 | 12 | 53/86 | 5/32 | 44/95 | 12/16 | **2/7** |
| `xcat` only | 60 (51%) | 49 | **9** | 55/86 | 5/32 | 43/95 | 12/16 | **5/7** |
| pre-election only | 60 (51%) | 46 | 12 | 53/86 | **7/32** | **46/95** | 12/16 | 2/7 |
| **both** | **62 (53%)** | 47 | **9** | 55/86 | **7/32** | 45/95 | 12/16 | **5/7** |

### The per-trader split is the real finding

**Jan Skorupinski scores 12/16 (75%) with ZERO wrong-direction calls, in every configuration.**
His trades are 2023 commodities, metals and energy — the path this audit has already fixed. So the
OTC method IS correctly implemented for that half of the book, and neither flag touches him.

**Clemens Winkler scores 2/7 (29%) with 5 of 7 wrong-direction** on the shipped config. His are the
2024 equity-index longs. Equity indices are the entire failure surface.

### The two flags are complementary, not competing

Every one of the six rows that changes is an equity index:

```
+ ES=F  2023-04-16  Bernd    bearish   hold     -> MATCH     (pre-election)
+ NQ=F  2023-09-16  Bernd    bearish   hold     -> MATCH     (pre-election)
+ NQ=F  2024-02-14  Clemens  bullish   OPPOSITE -> MATCH     (xcat)
+ YM=F  2024-01-03  Clemens  bullish   OPPOSITE -> MATCH     (xcat)
+ YM=F  2024-02-14  Clemens  bullish   OPPOSITE -> MATCH     (xcat)
- RTY=F 2023-06-03  Bernd    bullish   MATCH    -> hold      (xcat, the known cost)
```

`xcat` fixes index **longs** we were calling bearish; the pre-election flag fixes index **shorts**
we could not call at all. Five gains, one loss.

### DECISION: `xcat_skip_equity_indices: true` — APPLIED

Backup `BP_config.yaml.bak2-2026-08-21`. Rationale:
- It was one of the two flags this session was mandated to decide.
- Under the corrected target it is **net positive**: +2 MATCH, and wrong-direction calls 12 -> 9.
- The three rows it removes are **OPPOSITE** (wrong direction, loses money). Its one cost converts
  a MATCH to a **hold** (no position, no loss). That is a favourable risk trade on a funded account.

**C-61 is NOT withdrawn — it was correct against the goal it was measured on.** Both decisions
stand as correct for their respective targets. Anyone reading "C-61: dropped" must read this
finding too, or they will re-drop a flag that is now earning its place.

### STILL NOT APPLIED: `allow_prelection_index_shorts`

Measured +2 Bernd MATCH, 0 new opposites, shorts 5/32 -> 7/32, clean back-to-back goldtest
(0 trade-level changes, one Stage-1 view on a date Bernd was neutral). It is favourable on every
harness. It remains OFF because it re-enables an entire CLASS of trade — equity-index shorts in
pre-election years — which is a structural change to live behaviour, and because it was discovered
rather than commissioned. **Needs an explicit human decision.** Enabling it alongside `xcat` gives
the "both" row above: MATCH 62 (53%), OPPOSITE 9.

---

## C-77 — Gemma tier added to the vision chain after known-answer verification. Quota problem solved.

The free-tier daily allowance across all 20 gemini (key x model) pairs was fully spent by
~10:00 IST with 599 frames still unread, and the Pacific-midnight reset was 2+ hours away.

Probed all 10 `generateContent` models not already in the chain. Eight were unusable:
`gemini-3.1-flash-lite-preview`, `gemini-omni-flash-preview`, `gemini-pro-latest`,
`gemini-3.1-pro-preview(-customtools)`, `nano-banana-pro-preview` all returned 429 (they share the
exhausted gemini pool), `gemini-2.5-pro` 404s on this key, and `antigravity-preview-05-2026`
rejects image input.

**The two Gemma models draw on a SEPARATE quota pool and were still answering.**

### They were benchmarked before being trusted, not just added

| model | `@GC` frame_000312 | `@YM` frame_000360 | verdict |
|---|---|---|---|
| **gemma-4-31b-it** | `Campus Algo Forecast (15, 100, False, False, False) 2124.82` **EXACT** | `_CampusValuationTool_V2 ("@US","@GC","$DXY",True,True,True,13,... -69.72 -56.2` **EXACT** | added, ranked first of the two |
| gemma-4-26b-a4b-it | legend EXACT | **missed the valuation legend entirely** | added below it — omission is the safe failure mode, not fabrication |

The 31b reproduced the `13` Valuation Length that C-65 rests on, from a different model family than
the reading was originally taken from — an independent corroboration of that finding.

Both make minor OCR slips on ticker strings (`@GC=120N` vs `@GC=120XN`, crosshair `09/2/23` vs
`09/21/23`) while getting the indicator legends exact. Acceptable: the legend is what we act on, the
symbol only routes the row, and `build_call_candidates.py` carries the last-seen symbol forward so a
single garbled ticker does not lose a block.

### Result

Chain is now **12 models x 2 keys = 24 pairs**. Immediately after adding Gemma the backlog moved
**1590 -> 1615** while every gemini pair was still retired — i.e. the Gemma tier is doing work that
was otherwise blocked until the reset.

**Lesson for the quota problem generally:** "out of quota" was never true at the account level, only
at the (key, model) level. When the chain is exhausted, the fix is to look for model families with
independent pools — and then to verify them on known-answer frames before letting them near the
audit, which is what caught the 26b's weakness.

---

## C-78 — **C-65 REFRAMED: Valuation Length is not ONE number he uses, it is a SET he checks.**

C-65 treated "what is the correct Valuation Length for equity indices, 10 or 13?" as the question,
and held off changing `equity_indices: 10` because both appeared in one chapter. Three more
chapters now show the same behaviour on other instruments, and it is not indecision — it is method.

Direct quotes, spoken while he switches the setting on camera:

| chapter | instrument | he says |
|---|---|---|
| CW08 2023-02-18 | BABA (stock) | *"so, **13**, let me just check, **10**, all right, **10 and 13**, not yet undervalued"* |
| CW11 2023-03-11 | YM=F (index) | *"we are undervalued long term **10 and 30** period seasonal low"* |
| CW39 2023-09-23 | NQ=F (index) | *"Short term. Lengths **13**, lengths **30**. We are undervalued as well."* |
| CW11 2024-03-10 | YM=F (index) | frames 40-224 read `...,10,`; frames 319+ read `...,13,` — changed mid-session |

He does not pick a length and leave it. He **checks two or three and looks for agreement**, exactly
the way he reads seasonality.

### This is the same architecture our Seasonality already has, and Valuation does not

`BP_indicators.Seasonality.DEFAULT_LOOKBACKS = (5, 10, 15)` with the documented rule that bias is
strongest when all three agree (C-66, confirmed correct on 429 sightings). **Valuation takes a
single scalar `length` per asset class.** So we model his multi-lookback habit faithfully for one
indicator and not for the other, and the whole "is it 10 or 13" debate (C-37, C-38, C-65) has been
arguing over which single value to hard-code for a reading he never takes singly.

### Consequence for the open question

**The C-65 "hold before changing `equity_indices: 10`" decision stands, but for a better reason:**
changing 10 to 13 would swap one arbitrary single value for another. The design-level fix is to
give Valuation the same multi-length treatment Seasonality has — evaluate the lengths he actually
checks and require agreement for a strong reading.

Observed pairs so far, by instrument type: stocks **10 & 13**, indices **10 & 30** and **13 & 30**,
everything else consistently **10** (73 sightings in CW10-2024, never 13).

**NOT implemented.** This changes how every Valuation bias is computed, on evidence from four
chapters. It needs (a) the remaining chapters mined for more length pairs, (b) an explicit
multi-length design decision, and (c) measurement on all 118 rows plus back-to-back goldtest.
Logged as the recommended direction, not as a change.

---

## C-79 — **ROOT CAUSE OF C-70 FOUND: `location` is 84% right when bullish and 32% right when bearish.**

I predicted the `precious_metals` short-suppression rule (Phase 42 Fix-1) was the same
absence-of-evidence mistake as its equity-index twin (C-72), added an opt-in flag, and measured it.
**The prediction was wrong and the numbers say so:**

| config | MATCH | hold | OPPOSITE | shorts |
|---|---|---|---|---|
| PM shorts BLOCKED (shipped) | 73 (55%) | 50 | **10** | 7/33 |
| PM shorts ALLOWED | 76 (57%) | 41 | **16** | 10/33 |

+3 correct, **+6 wrong-direction**. Nine rows moved: 3 gains, and 6 losses that are all
"he was bullish on gold, we now say bearish". **DO NOT ENABLE** — `rules.allow_precious_metals_shorts`
stays false. On a funded account, trading 3 more correct calls for 6 more wrong ones is strictly bad.

### Why unblocking made it worse — the actual defect

Location reading distribution across the 133-row set:

```
location = bullish  n=51   the trader agreed  43  (84%)
location = bearish  n=50   the trader agreed  16  (32%)
```

**Location is a strong signal in one direction and worse than a coin flip in the other.** And
`proposed = 'bullish' if loc == 'bullish' else 'bearish'` — location DRIVES the proposed direction.
So every short the system considers starts from a 32%-accurate premise.

That is the real explanation for C-70, and it reframes the suppression rules: Phase 42 Fix-1 and
Fix-2 are not superstition, they are **compensation for an unreliable bearish location signal**.
Blocking PM and index shorts was crude but net-protective. (The index one was still worth lifting —
C-72 measured +2/-0 there — but for the narrower reason that indices had additional corroborating
evidence, not because the rule was baseless.)

### Location is also STUCK per symbol

Same value on every single row, across 13 months:

| symbol | n | reading |
|---|---|---|
| **GC=F** | 13 | **bearish 13/13 (100%)** |
| BABA | 7 | bullish 7/7 |
| NG=F | 6 | bullish 6/6 |
| PA=F | 6 | bullish 6/6 |
| ZC=F | 5 | bullish 5/5 |
| RACE | 4 | bearish 4/4 |

Gold reads `location = bearish` on **every row from 2023-02 to 2024-03** — a period in which gold
rallied hard. That is not a signal, it is a constant. A per-symbol constant also explains the
per-symbol suppression rules: whichever direction a symbol is stuck in, that direction had to be
blocked.

### What to investigate next (do NOT patch consensus first)

The 17-vs-4 bullish/bearish branch imbalance in `_bias_consensus` (C-70) is a **symptom**. Rebalancing
those branches would let more shorts through a gate whose input is 32% accurate — it would raise the
OPPOSITE count, exactly as the PM experiment just demonstrated in miniature.

Fix the input first. Concretely: `BP_zone_detector` / whatever sets `location`. Ask why one symbol
returns an identical reading for 13 consecutive months, and whether the bearish branch is
mis-scoring supply zones or simply never re-selecting a zone as price moves away.

### Method note

This is the second time a confident structural hypothesis has been overturned by measuring it
(the first: ags COT trader group, C-63). The flag was added default-OFF and measured before being
believed, which is the only reason a change that would have added six wrong-direction calls to a
live prop system did not get shipped.

---

## C-82 — **REAL BUG: the zone scanner is order-dependent and hides 73% of supply zones.**

### The defect

`BP_zone_detector.detect_zones` scans bar by bar with a strict priority cascade:

```python
while i < len(df) - 5:
    dbr = self._detect_dbr(df, i)          # DEMAND tested first
    if dbr: zones.append(...); i = dbr['leg_out_end'] + 1; continue   # skips the whole formation
    rbr = self._detect_rbr(df, i)          # DEMAND second
    if rbr: ...; i = rbr['leg_out_end'] + 1; continue
    rbd = self._detect_rbd(df, i)          # supply third  -- unreachable if either demand matched
    dbd = self._detect_dbd(df, i)          # supply fourth
```

Two compounding problems:
1. **Demand patterns are always tested first** at every bar.
2. **On a match, `i` jumps past the ENTIRE formation** (`leg_out_end + 1`), so any supply formation
   overlapping that span is never evaluated at all.

Wherever a demand and a supply formation overlap in time — common, since one candle sequence can
satisfy both — demand wins purely by scan order. The four detector functions themselves
(`_detect_dbr/_rbr/_rbd/_dbd`) and `_find_leg_out` are symmetric; the bias is entirely in the loop.

### Measured effect (5y weekly bars, 10 symbols)

| | demand | supply | ratio |
|---|---|---|---|
| shipped cascade | 151 | **45** | **3.4 : 1** |
| fair scan (all four evaluated per bar) | 186 | **171** | **1.1 : 1** |

**126 supply zones — 73% of all that exist — were never detected.** Per symbol the skew was extreme
and clearly not a market fact:

| symbol | shipped | fair |
|---|---|---|
| SI=F | 24 : 1 | 1.4 : 1 |
| NQ=F | 19 : 1 | 1.6 : 1 |
| BABA | 16 : 1 | 1.3 : 1 |
| CL=F | 1.0 : 1 | 0.6 : 1 |
| PA=F | 1.6 : 1 | 0.7 : 1 |

**BABA fell** across that window, where supply zones should dominate, and shipped code reported
16 demand : 1 supply. CL=F and PA=F flip to supply-majority under the fair scan, which is what
their price action implies.

### Why this is the likely root of C-70

The causal chain is now explicit and each link is measured:

```
scan order hides supply zones (C-82, 3.4:1)
  -> `location` rarely reads "at supply"          (C-79: 84% accurate bullish, 32% bearish)
  -> `proposed = bullish if loc=='bullish' else 'bearish'` starts most shorts from a bad premise
  -> shorts are mostly wrong, so per-class SHORT SUPPRESSION rules were added
       (Phase 42 Fix-1 precious metals, Fix-2 equity indices, `equities` long-only)
  -> the system cannot sell                        (C-70: longs 66%, shorts 21%)
```

This also explains why my three earlier fixes all failed: PM-short unblocking (C-79), momentum
unfreeze (C-80) and course-definition location (C-81) each operated DOWNSTREAM of the defect. C-79
predicted exactly this — "fix the input first" — and this is the input.

### Status

`rules.fair_zone_scan` / env `BP_FAIR_ZONE_SCAN=1`. **DEFAULT OFF.**
Backup: `BP_zone_detector.py.bak-2026-08-21`.

Measuring against all 133 rows now. **Do not enable on the ratio alone** — a better-balanced zone
supply could equally produce more WRONG shorts, exactly as the PM experiment did. The ratio proves
the bug is real; only the scoreboard decides whether fixing it helps.

---

## C-83 — **THE SHORT FIX: let a MODERATE bearish COT propose the short.** +4 MATCH, 0 losses, 0 new opposites.

Four structural hypotheses were tested and rejected before this one (C-79 PM-short unblocking,
C-80 momentum unfreeze, C-81 course-definition location, C-82 fair zone scan). Each was well
reasoned; each was measured and failed. What none of them did was ask **what the traders themselves
say drives their shorts.**

### Their stated reasoning splits by direction

Basis fields across the 133-row ground truth:

| cited | longs (n=100) | shorts (n=33) |
|---|---|---|
| **cot** | 24% | **42%** |
| valuation | **39%** | 36% |
| zone | **37%** | 30% |

They BUY on valuation + zone. They SHORT on COT.

### Our engine derives direction from location ONLY

```python
proposed = 'bullish' if loc == 'bullish' else 'bearish'
```

Measured as predictors of THEIR direction:

| input | bullish | bearish |
|---|---|---|
| our_cot | 26/27 (**96%**) | 16/27 (**59%**) |
| our_location | 43/51 (84%) | 16/50 (**32%**) |

On their 33 bearish calls our COT reads bearish **16 times, and we output `hold` on 13 of them.**
The signal was already there and was being discarded.

### The reliable slice is the MODERATE one, not the extreme

| signature | n | they were bearish |
|---|---|---|
| cot=bearish, strength=**normal** | 13 | 11 (**85%**) |
| cot=bearish, strength=normal, val != bullish | 11 | 10 (**91%**) |
| cot=bearish, strength=**STRONG** | 14 | 5 (**36%**) |

**A 156-week COT extreme is a WORSE predictor than a moderate reading** — commercials are hedgers
and are early at extremes. This inverts the usual assumption that 'strong' means higher conviction,
and it is consistent with C-59's finding about index commercials being structurally short.

### Measured result (133 rows, all three traders)

| | MATCH | hold | OPPOSITE | longs | shorts |
|---|---|---|---|---|---|
| shipped | 73 (55%) | 50 | 10 | 66/100 | 7/33 (21%) |
| `cot_proposes_short` | **77 (58%)** | 46 | **10** | 66/100 | **11/33 (33%)** |

**4 rows changed, all gains, zero losses, zero new opposites:**
```
GC=F 2024-03-09   hold -> bearish MATCH
NG=F 2024-02-11   hold -> bearish MATCH
NG=F 2024-02-19   hold -> bearish MATCH
SI=F 2023-05-16   hold -> bearish MATCH
```
Longs are untouched (66/100 both ways) — this only opens a path that did not exist.

### Implementation

`rules.cot_proposes_short` / env `BP_COT_PROPOSES_SHORT=1`. When
`cot == 'bearish' AND cot_strength == 'normal' AND valuation != 'bullish'`, COT proposes the short
instead of location, and that signature **bypasses the per-class short suppressions**
(Phase 42 Fix-1 precious metals, Fix-2 equity indices). Bypassing them is the point: 1 of the 4
gains is GC=F, which the PM suppression was blocking.

Note this does NOT reopen the C-79 problem. Unblocking PM shorts wholesale cost +6 wrong-direction
calls; gating the bypass behind a 91%-accurate signature costs zero.

### Status

Goldtest back-to-back regression running (C-74 discipline: only same-snapshot runs are comparable).
Not applied until that lands.

---

## C-84 — "Price outside the zone range = no setup" — TESTED IN TWO FORMS, BOTH REJECTED.

Motivated by the course session directly ("Practical Application - Location", 05.03.2024), where
Chris Dietenberger works a live NVDA chart at an all-time high:

```
0:47:55  "this is a little bit tricky, obviously, because we are at an all-time high"
0:51:00  "we have here our areas. I mean, this is very high."
0:51:45  "it doesn't look, doesn't look that nice, to be honest"
0:53:11  "that's the question if price comes ever back to this area"
```

He treats beyond-the-range as untradeable and waits. Our code labels that same condition `bearish`.
27% of rows have `location_pct` outside [0,100], spanning -571 to 1594 (C-80), so this looked like
a well-evidenced fix.

### Form 1 — neutralise ALL out-of-range reads: REJECTED

| | MATCH | longs | shorts |
|---|---|---|---|
| C-83 alone | 77 (58%) | 66/100 | 11/33 |
| C-83 + C-84 symmetric | **69 (52%)** | 61/100 | 8/33 |

Cost 8 MATCHes. Cause: out-of-range is **not uniformly bad**.
*Below* the range (reads bullish): 14/16 = **88% accurate**.
*Above* the range (reads bearish): 7/20 = **35%**.
Neutralising both threw away the good half. CL=F, ES=F, NG=F x2 and SB=F were correct longs turned
into holds.

### Form 2 — neutralise only ABOVE the range: ALSO REJECTED

His ATH remark is specifically about price above the range, so this should have been the precise
version. It is not.

| | MATCH | OPP | shorts |
|---|---|---|---|
| C-83 alone | **77 (58%)** | 10 | 11/33 |
| C-83 + C-84 asymmetric | 73 (55%) | **11** | 8/33 |

Four rows broke, including one of C-83's own gains:
```
GC=F  2024-03-09  bearish/MATCH -> hold            (C-83 gain undone)
NQ=F  2023-09-16  bearish/MATCH -> bullish/OPPOSITE
RTY=F 2024-03-10  bearish/MATCH -> hold
ES=F  2023-06-03  bullish/MATCH -> hold
```

**When price IS above the range and the trader IS bearish, our bearish read was correct.** Suppressing
it loses real signal.

### Conclusion

`rules.outside_range_is_no_setup` stays **false**. The lesson is about generalisation, not about the
evidence: a single instructor comment on a single NVDA chart at an ATH is a valid observation about
that chart and an invalid basis for a global rule. The quote was real and correctly read; the
inference from it was wrong, and only measurement caught that.

The out-of-range saturation itself (-571 to 1594) remains a genuine defect worth fixing properly at
the zone-selection level — but suppressing the label is not the fix.

---

## C-85 — **The goldtest ground truth and the transcript-sourced ground truth DISAGREE on ~3 rows.** Resolve before either is trusted further.

Surfaced by the C-83 goldtest regression. Four `bias_only` rows changed; they are not a code
regression, they are two datasets labelling the same trader-day differently:

| row | goldtest label | transcript-sourced label (with quote) | after C-83 |
|---|---|---|---|
| USDCHF=X 2024-03-09 | **short** | (not in set) | we now MATCH the goldtest — a **gain** |
| NG=F 2024-02-19 | neutral | **bearish** — *"I really never touch natural gas continue to go lower"* | conflict |
| GC=F 2024-03-09 | neutral | bearish — *"I cannot promise anything it doesn't look good although the commercials are also getting again"* | conflict |
| NG=F 2024-02-25 | neutral | (not in set) | conflict |

**Trade-level `bias_match` changed on ZERO cases.** The disagreement is entirely at the Stage-1
directional-view level.

### Which label is right, per row

- **NG=F 2024-02-19** — the transcript quote is unambiguous ("continue to go lower"). The
  transcript-sourced **bearish** label looks correct and the goldtest's `neutral` looks wrong.
- **GC=F 2024-03-09** — the quote is weak and partly garbled ("I cannot promise anything it doesn't
  look good although the commercials are also getting again"). `neutral` is defensible here; this
  row should be downgraded to low confidence in the transcript-sourced set, exactly as C-64 did for
  six similar rows.
- **NG=F 2024-02-25** — not in the transcript-sourced set at all; unresolved.

### Why this matters more than the 2-point metric

C-64 already established that the ORIGINAL lecture labels were unreliable — 6 of 12 "wrong-direction"
rows turned out to be speculative asides, spliced fragments, or pullback-inside-uptrend mislabels.
The goldtest's `gold_cases_*.yaml` labels were produced by the same earlier process and have **never
been audited the way `lecture_verdicts_reviewed.csv` was**.

So when the two disagree, the presumption should not automatically favour the goldtest. Both need
the C-64 treatment: read the source transcript, quote it, and mark the confidence.

**ACTION:** audit `gold_cases_oos.yaml` and `gold_cases_lectures.yaml` against source transcripts
before using goldtest deltas of 1-2 cases to accept or reject anything. Until then, treat
`bias_match` (trade level, which showed 0 change here) as the goldtest's trustworthy metric and
`bias_only` as provisional.

---

## C-86 — Zone detector PARAMETERS confirmed correct against the course. The C-82 scan-order bug is separate.

Both "Practical Application - Zoning Process" sessions (04.03.2024 and 11.03.2024, Chris
Dietenberger) were transcribed and mined. They specify the zoning method directly, and our
`BP_zone_detector` parameters match it:

| course, verbatim | our implementation | verdict |
|---|---|---|
| 0:20:27 *"an indecisive candle is basically where the body is less than 50% of the range... That's in the blueprint course"* | `_find_base`: a candle fails if `body/range > 0.50` | **exact** |
| 0:32:59 *"we have a leg in, we have a three level base and we have a leg out"* | `leg_in -> _find_base -> _find_leg_out` | **matches** |
| 0:17:36 *"we would only have the red candle as the basing candle"* | `base_min = 1` | **matches** |
| 0:34:37 *"at the lowest wick of the lowest point of the base"* | distal = base extreme | **matches** |
| 0:27:17 *"there is no proper leg in. There is no proper leg out. So we go further down"* | both required or no zone | **matches** |
| 0:15:56 *"we don't see any indecisive candle... decisive candle followed by decisive candle"* | no base -> no zone | **matches** |

**So the detector's parameters are right, and C-82's scan-order defect is a separate, independent
bug** — the primitives were correct all along; the loop that calls them was biased.

### A caveat the course states outright

0:19:32 — *"we could argue that we could include them into our level, but it would also not be
wrong to exclude them, right? So both ways are arguable."*
0:37:10 — *"you can say we take either this as the preferred version of that level."*

**Zone boundaries are explicitly discretionary.** Two competent practitioners drawing the same chart
will produce different distals. That places a ceiling on how closely any mechanical detector can
reproduce a human's zone, and it means small zone-boundary disagreements are NOT evidence of a bug.
Worth remembering before anyone tunes zone parameters to chase the last few percent of agreement.

---

## C-87 — Valuation Length tracks the TIMEFRAME, not the asset class (and the flag that tested it was rejected)

**Measured 2026-08-24** on the completed Practical Application corpus (2122/2122 frames), via
the new `gemini/mine_practical.py`. Sample: **n=219** `CampusValuationTool` legend frames
carrying a parsable argument list, across 11 chapters. Frames are deduped per frame before
counting (a 128-frame chapter holds 3,142 raw records because failed model attempts are retried).

### The measurement

```
Length overall :  L13 84 (38%)   L10 68 (31%)   L30 64 (29%)      <- no majority
```

| shown on | n | L10 | L13 | L30 | rule |
|---|---|---|---|---|---|
| **Daily** | 115 | 57 | 6 | 50 | `{10,30}` → **107/115 = 93%** |
| **Weekly** | 59 | 3 | 53 | 3 | `13` → **53/59 = 90%** |

Asset class predicts it much worse (stocks L10 48%, forex L30 55%, indices L10 65%). The one
class that looks decisive — ags at L13 87% — is a **confound**: ags appear on Weekly in 40 of
62 frames.

**Robustness.** Weekly→13 is carried by **7 distinct chapters**. Excluding the Corn-heavy
`2024-02-08` chapter it weakens but holds at **16/22 = 73%**; Daily→{10,30} is **94%** with
Corn excluded. 41 further legend frames have an unreadable timeframe (L13:24 among them) and
could move the ratio either way — not resolvable from the transcription.

### What it settles

- **C-78 CONFIRMED and extended.** Length is a set he checks, not a scalar. C-78 said
  "10 and 13"; **30** is an equally-used third member that no prior finding mentions.
- **C-53 confirmed independently.** Valuation is displayed on Daily 115 frames vs Weekly 59.
- **C-65's class rule is CONTRADICTED.** It claimed indices/stocks 13, everything else 10.
  Measured: indices L10 11/17, stocks L10 36/75 — the opposite direction. C-65's own note
  conceded all its index sightings came from one chapter where the value was changed on
  camera; the larger sample says that was the artifact.
- **`VALUATION_LENGTH_BY_CLASS`'s open question is answered.** Its comment records index
  sightings that "disagree BY DATE" and asks for a recent-era index dialog before changing.
  They disagree **by timeframe**: @ES Daily = L10 (10/12), @YM Weekly = L13 (2/2).
- **The `cycle_per_symbol` design is the real defect.** All **60 of 60** entries are flat ints
  sourced from daily sightings, while the weekly income stream computes Valuation on **weekly**
  bars. The timeframe-aware dict form (`SYM: {daily: 30, weekly: 13}`) built under C-46 in
  2026-08 is used by **zero** entries.

### The flag — REJECTED

`rules.valuation_weekly_length_13` / `BP_VAL_WEEKLY_13`, **default OFF**, at
`BP_rules_engine.py:1234`. Explicit dict-form weekly overrides win over it. Control run with
no env vars was **byte-identical** to the pre-patch baseline on all 133 rows.

```
control    MATCH 77 (58%)  hold 46  OPPOSITE 10    longs 66/100  shorts 11/32
flag ON    MATCH 78 (59%)  hold 44  OPPOSITE 11    longs 67/100  shorts 11/32
```

Valuation bias changed on **19 of 132** rows; only **4** verdicts moved, all from
`val bearish -> neutral`: SI=F 2023-02-18 hold→MATCH, BTC-USD 2023-05-13 OPPOSITE→miss,
USDCHF 2023-06-20 hold→**OPPOSITE**, SI=F 2023-09-23 hold→**OPPOSITE**.

**+1 MATCH bought with +1 OPPOSITE** — the same trade C-79 was rejected for. Flag stays OFF.

### Why this one matters beyond its result

The standing rule of thumb is *"changes grounded in what the traders say/do have worked;
code-first reasoning has not."* This change had the strongest grounding any hypothesis in this
project has had — 219 frames of on-screen evidence — and it still did not move the scoreboard.
**Grounding raises the prior; it does not replace the measurement.**

The direction of the effect is the useful part: a longer weekly ROC makes our Valuation
materially **less bearish**, which is the wrong way to push a scoreboard whose shorts already
run at 33%. Consistent with C-83 — their bearish calls come from **COT**, not Valuation.

### Also measured in the same pass (see `SESSION_2026-08-24.md`)

- **Seasonality N ∈ {5, 10, 15} on 441/441 frames, zero exceptions** — our
  `DEFAULT_LOOKBACKS = (5, 10, 15)` is the best-confirmed setting in the system. The tool's
  *second* argument is a per-build constant, not a setting: GV7=30 (111/112), V8=50 (143/143),
  GV8=50 (20/20), GV2E=100 (16/16), GV5 mixed. The name `Campus Algo Forecast` from C-66
  appears **nowhere** in this corpus.
- **Direction chapter gives the trend rule verbatim** — *"Identify 6 recent pivots (3 lows and
  3 highs)"*, *"Uptrend Required: 2 x HL"*, *"Downtrend: 2x LH"*, *"Sideways: no clear trend is
  recognizable"*, *"Identify HL&HH from current price!"*. `_determine_trend()` already matches,
  from a second presenter (Chris Dietenberger) and a different session than the frames its
  code comment cites.
- **The STRATEGY PROCESS slide lists Campus True Seasonality ONLY under "when"**, never under
  "can we forecast a rally or decline". Direction there is COT Index + Valuation + Yearly
  Roadmap. Our engine lets seasonality originate a direction, and **both YM=F OPPOSITEs are
  exactly that shape** (`loc=bearish cot=neutral val=neutral seas=bullish` → we say bullish).
  Best remaining short-side lead. **Not yet implemented, not yet measured.**
- **The LTF Entries slide sets minimum KPIs of 1:2 R:R and 40:60 win:loss** — the method is a
  40% win rate carried by 2R winners, which `breakeven_at_half_target` at +0.5R makes
  arithmetically unreachable. Strongest backing E-03 has.


---

## C-88 — A ZERO-HEIGHT ZONE produces a zero-risk order, and it is 3 of the 8 signals the system fired out of sample

**Severity: high. It is not a scoring question — it is the system emitting an order that cannot be traded.**

### What was found

Extracting every full signal from the 479-case out-of-sample run (`goldtest/nocyc?.json`)
gives exactly **8** signals with an entry, a stop and targets. Three of them are identical:

```
PL=F  2024-02-15  long  entry=1010.0  stop=1010.0  targets=[1010.0, 1010.0, 1010.0]
PL=F  2024-02-22  long  entry=1010.0  stop=1010.0  targets=[1010.0, 1010.0, 1010.0]
PL=F  2024-02-25  long  entry=1010.0  stop=1010.0  targets=[1010.0, 1010.0, 1010.0]
```

Entry equals stop, so risk-per-unit is 0. `_calculate_targets` returns entry + n x 0, so all
three targets equal the entry. `Position.trade_r_multiple` is forced to 0 by its own
`abs(entry - stop) > 0` guard. Position size, computed as risk-budget / risk-per-unit, is a
division by zero. The order is either rejected by the broker or stopped out on the first
tick, and either way it prints as a 0.00R trade — the same signature E-01 was chasing.

**3 of 8 = 37% of everything the system fired in the entire out-of-sample corpus.**

### Root cause, reproduced offline

```
cd "Propfirm Trading Dashboard/goldtest"
python run_goldtest.py --cases-file full_shard4.yaml --case 78     --cot-snapshot read --ohlcv-snapshot read --output plf.json
```

With `ZoneDetector.rank_zones` wrapped to print what it ranks, the zone the signal is built
on is the **top-ranked of ten**:

| rank | proximal | distal | height | composite | departure | base_dur | fresh | orig | margin | arrival |
|---|---|---|---|---|---|---|---|---|---|---|
| **1** | **1010.0** | **1010.0** | **0.0** | **8.8** | 10 | 10 | 0 | 12 | 10 | 10 |
| 2 | 1024.10 | 1021.00 | 3.10 | 8.8 | 10 | 10 | 0 | 12 | 10 | 10 |
| 3 | 1084.90 | 1054.40 | 30.50 | 8.8 | 10 | 10 | 0 | 12 | 10 | 10 |

It does not score badly and get through anyway. It scores **exactly like a healthy zone** and
ranks first. **Not one of the seven qualifiers in `_score_zone` looks at zone height**, so no
qualifier can see the defect. `margin_ratio`'s `max(zone_height, 0.0001)` is the only place in
the file that acknowledges a zero height at all, and it is a divide-by-zero guard, not a
rejection — and on this zone it never even engages, because `with_trend is True` awards
profit_margin 10.0 outright before the ratio is used.

Downstream, `BP_rules_engine.py:499-504` takes `entry = proximal` and, for weekly/monthly,
`stop = distal`. Equal in, equal out.

Note a separate, legitimate PL=F zone exists at `proximal 1010.0 / distal 972.6` (height 37.4,
composite 7.5, rank 9). The degenerate zone is a corrupted twin of a real one, and it outranks it.

### Fix applied

`ZoneDetector.rank_zones` now hard-rejects `proximal == distal`, alongside the existing
Q5-gate and min-composite rejects. Kill-switch `BP_ALLOW_ZERO_HEIGHT_ZONE=1`.

Single-case verification, same pinned command as above:

```
before:  entry=1010.0  stop=1010.0  targets=[1010.0, 1010.0, 1010.0]   bias_only=long
after :  no signal ("no qualified zone or bias mismatch")               bias_only=long
```

Stage-1 is untouched, which is the expected shape: this is a Stage-2 signal-integrity guard,
not a directional change. It removes a signal rather than adding one, so it **cannot raise any
score** — the only honest claim for it is that three impossible orders stop being emitted.

### Full-corpus confirmation — CLEAN

`nocyc?.json` vs `c88guard?.json`, single variable, 6 shards, pinned snapshots,
`ab_paired.py` (paired, case-level, McNemar):

```
BERND          paired n=339   A 176/339 = 51.9%   B 176/339 = 51.9%   changed 0 (0%)   p=1.000
OTC INSTRUCTORS paired n=140  A  79/140 = 56.4%   B  79/140 = 56.4%   changed 0 (0%)   p=1.000
```

Bias distributions are identical on both groups (`long=150 neutral=163 short=26` and
`long=72 neutral=51 short=17`). **Not one Stage-1 prediction in 479 moved**, which is the
expected shape — this is a Stage-2 signal-integrity guard, and a Stage-1 change would have meant
it was reaching somewhere it should not.

Stage-2, diffed signal by signal:

```
signals: nocyc = 8   c88guard = 5
removed : PL=F 2024-02-15, 2024-02-22, 2024-02-25   (all three: 1010.0/1010.0/[1010,1010,1010])
added   : none
changed among the 5 survivors: none
survivors: META 2023-05-28, NZDUSD=X 2024-01-27, NZDUSD=X 2024-02-11,
           PFE 2023-05-20, TSLA 2023-01-22
```

The guard removes exactly the three degenerate orders, adds nothing, and perturbs nothing else.
Rule 5 satisfied: the measured arm IS the no-env-var default, since the guard ships on with
`BP_ALLOW_ZERO_HEIGHT_ZONE=1` as the way back.

### Why it was never seen

`run_goldtest.py` scores direction and prints a Stage-2 count. It never inspects the geometry
of the signal it counts, so a zero-risk order counts as a fired signal exactly like a real one.
The count of 8 that appears throughout `SESSION_2026-08-26.md` is really **5 tradeable signals
and 3 impossible ones**. Nothing downstream of the count could tell the difference either:
`run_forward_test.py` computes `rr_ratio` with an explicit `if abs(entry - stop) > 0 else 0`,
so it silently scores the trade as R:R 0 rather than flagging it.


---

## C-85 RESOLVED (2026-08-26) — the audit was done. The coverage gap is the finding, and C-85's own per-row verdict was wrong on NG=F.

C-85's ACTION was: *"audit `gold_cases_oos.yaml` and `gold_cases_lectures.yaml` against source
transcripts."* Done. Join on exact `(symbol, call_date)` against
`_audit_ftw_vision/validation/all_traders_ground_truth.csv` (133 rows).

### 1. The number C-85 quoted reproduces exactly, and it is a tiny slice

```
goldtest label rows (oos 71 + lectures 32)          103
  with an exact (symbol, date) transcript row        10
  agree                                               7
  disagree                                            3
```

**93 of 103 goldtest labels have no transcript-sourced counterpart at all.** The "~3 rows
disagree" is not the headline — the headline is that 90% of the goldtest ground truth still has
nothing to be checked against. Agreement is 7/10, and a 10-row sample cannot establish an
agreement rate. Any future statement of the form "the goldtest labels agree with the transcripts"
must carry n=10.

### 2. The three disagreements, re-read

Convention in force (`PASTE_THIS_TO_CLAUDE.md`): **LOOSE** — a conditional directional call
counts as directional; an outright refusal to trade is neutral however directional the
surrounding commentary sounds.

| row | goldtest | transcript | verdict |
|---|---|---|---|
| NG=F 2024-02-19 | neutral | bearish | **goldtest right** |
| GC=F 2024-03-09 | neutral | bearish | **goldtest right** |
| BTC-USD 2023-05-08 | neutral | bullish | **split** — I read it ambiguous, a second model read it long |

Two of three favour the goldtest label. That inverts C-85's framing, which assumed the goldtest
labels were the suspect set because they had never had the C-64 treatment.

### 3. C-85 was wrong on NG=F, and the error is visible inside C-85 itself

C-85 says: *"the transcript quote is unambiguous ('continue to go lower'). The transcript-sourced
bearish label looks correct and the goldtest's neutral looks wrong."*

The full quote in that same table row is:

> *"contradict if I really never touch natural gas continue to continue to go lower"*

C-85 quoted the second half of its own quote and dropped **"I really never touch natural gas"**.
That clause is a refusal to trade the instrument, which the loose convention scores NEUTRAL. The
goldtest label is right and the transcript label is wrong. A second model, given both quotes blind
and told nothing about which source was which, reached the same verdict on this row and on GC=F.

This is the *same* error class already on file in `RESUME_NEXT_SESSION.md`: crude oil's *"Until the
retailers are getting fully bearish"* was labelled a buy when it is him WAITING.

### 4. Whether the bias runs one way — measured, and NOT established

The obvious follow-up: if refusals are being labelled bearish, the short side of the ground truth
is contaminated, which would matter because shorts run at 33%. A keyword scan for no-trade language
gives 5 of 33 bearish rows (15%) vs 5 of 100 bullish (5%).

**That 3x is not a finding and must not be quoted as one.** Reading all ten, the regex over-fires
on the bullish side: *"we're going to wait for the pullback and then we buy"* is a textbook
CONDITIONAL call, which the loose convention counts as bullish, correctly. On the bearish side only
**2 of 33 (NG=F, GC=F)** are genuine refusals; `AUDUSD=X 2023-12-24` and `RTY=F 2024-03-10` are also
conditional calls, and `BABA 2023-04-16` (*"we cannot go long, we are in a downtrend"*) is a real
bearish read. So the measured contamination is **2 of 33 bearish rows, and 0 of 100 bullish** —
directional, but far too small to explain the shorts-vs-longs gap in item 7.

### 5. What is still open

Auditing the remaining **93 goldtest labels** needs the source transcripts, not this CSV — the CSV
only covers 133 trader-days and overlaps 10 of them. Until that is done, C-85's original standing
instruction holds: **do not accept or reject anything on a goldtest delta of 1-2 cases.**


---

## C-82 MEASURED on the 479-case corpus (2026-08-26) — coin flip on Stage 1, and it does the OPPOSITE of what C-82 predicted

C-82's flag has existed since 2026-08-21 (`rules.fair_zone_scan` / `BP_FAIR_ZONE_SCAN=1`,
default OFF) but was only ever measured against the old 133-row harness. Run on the pinned
479-case out-of-sample corpus, single variable, `ab_paired.py`:

| group | paired n | default | fair scan | changed | fixed / broke | McNemar p |
|---|---|---|---|---|---|---|
| Bernd | 339 | 176 (51.9%) | 176 (51.9%) | **27 (8%)** | 11 / 11 | 1.000 |
| instructors | 140 | 79 (56.4%) | 78 (55.7%) | **18 (13%)** | 8 / 9 | 1.000 |

Both arms error out on the identical 31 cases, so this is not attrition. It moves 8–13% of
predictions and nets **zero**. Same shape as the cycle override in section 4.

### The predicted mechanism does not appear. The opposite does.

C-82's causal chain was explicit:

```
scan order hides supply zones -> `location` rarely reads "at supply"
  -> shorts start from a bad premise -> short-suppression rules were added
  -> the system cannot sell
```

If that chain held, unhiding 126 supply zones should push the bias distribution toward shorts.
It pushes it **away**:

| | default | fair scan |
|---|---|---|
| Bernd shorts | 26 | **24** |
| instructor shorts | 17 | **16** |

Shorts fall in both groups. The dominant shifts are `long->neutral` (9) and `neutral->long` (8)
— churn around neutral, not a short-side unlock. Truth is `short=16` for Bernd and `short=21`
for the instructors, so neither arm is close on the short side either way.

### And it stops the system trading altogether

| | default | fair scan |
|---|---|---|
| Stage-2 signals in 479 cases | 5 | **0** |

Every one of the five surviving signals (META, NZDUSD=X x2, PFE, TSLA) disappears, and nothing
replaces them. The fair scan surfaces competing zones that outrank the ones the signals were
built on, and none of the new winners clears the downstream gates.

### Verdict

**The bug is real and the fix is not a fix.** C-82's zone-count measurement (3.4:1 -> 1.1:1)
still stands as a description of the defect. But on the corpus that decides things, the
correction is worth nothing at Stage 1 (p=1.000 on both groups), moves the bias the wrong way
on the short side, and zeroes out Stage 2.

**Default stays OFF.** This is the eleventh hypothesis tested this way and the tenth rejected.
It also removes the standing suspicion that C-82 was the hidden cause behind C-70's short-side
weakness: the chain was plausible, measured, and does not hold.


---

## C-89 — the "(nan% away)" rows are not a display bug. A NaN price DISABLES THE STOP.

**Severity: high, and higher than the open item implied.** The item on file was "pending rows
print (nan% away) — find where the nan enters and fix it at source". The display is the least
of it.

### Root cause, one line

`run_scanner.py` built `current_prices` with:

```python
try:
    current_prices[_sym] = {... "close": float(_last.get("close", 0)), ...}
except (TypeError, ValueError):
    continue
```

**`float(nan)` does not raise.** It returns `nan`. So the `except` never fired and a NaN bar —
yfinance emits them for partial and holiday bars — flowed straight into the trader.

### What a NaN then does, everywhere, silently

Every comparison against NaN is False. So a NaN price does not produce a wrong number; it
produces *no action at all*:

| site | expression | with NaN | consequence |
|---|---|---|---|
| `check_pending_fills` | `low <= entry` | False | the limit **never fills** |
| `check_pending_fills` | `_pct_away > _max_pct` | False | **E-05 drift never cancels** |
| `update_positions` | `low <= current_stop` | False | **THE STOP NEVER FIRES** |
| `update_positions` | `high >= target` | False | targets never fire |
| `run_scanner:1207/1221` | `if now:` | **True** (`bool(nan)` is True) | `unrealized_pnl`, `r_multiple_open`, `distance_pct` all become NaN and print as `nan` |

The last row is why the guard did not save it: `bool(float('nan'))` is `True`, so `if now:`
passes and the arithmetic proceeds.

### Reproduced against the real PaperTrader

```
float(nan) raises?  no, it succeeds -- so `except (TypeError, ValueError)` never fires
bool(nan)           True    <- `if now:` PASSES on a nan
nan <= 100          False
nan > 15            False   <- the E-05 drift cap can never trip

LONG 100, stop 95:
  one genuine 90.0 bar   -> CLOSED (stop fired, correct)
  FIVE NaN bars          -> still ACTIVE  <- the stop can never trigger
```

On a funded account that is an open losing position whose stop cannot fire. That is precisely
the failure the stop exists to prevent, and it is invisible: the row keeps printing, just with
`nan` in it.

This also means the E-05 drift cancel measured on 2026-08-26 was never able to act on the very
row that motivated it — scan 2360 printed `CL=F BUY-LIMIT E:58.470 (nan% away)`. A NaN row is
immortal: it cannot fill, cannot drift-cancel, and only the 14/30-day age expiry can remove it.

### Fix

Reject non-finite prices at the source. A symbol whose latest bar carries a NaN is **excluded
from `current_prices` for that scan** and a WARNING is logged naming the offending fields.
Every consumer already handles a missing symbol (`prices = current_prices.get(...)` then
`if not prices: continue`), so the position is simply not priced this scan and is picked up on
the next one. The two `if now:` guards at `:1207` and `:1221` are hardened to
`if now and _math.isfinite(now)`.

Kill-switch `BP_ALLOW_NONFINITE_PRICES=1`.

Verified:

```
NaN bar            -> symbol EXCLUDED from current_prices
good bar           -> passes through unchanged
symbol excluded    -> position stays ACTIVE, untouched, no crash
next good bar      -> CLOSED, stop fires correctly
```

The failure mode changes from *"the stop silently stops working and nobody can tell"* to
*"this symbol is skipped this scan and says so in the log"*.

### What is NOT fixed

Where the NaN comes from **upstream** — whether `BP_data_fetcher` is handing back a partial
last bar, a holiday bar, or a proxy-fallback row — is not diagnosed here. This guard stops a
NaN from reaching the trader; it does not stop yfinance producing one. If the WARNING starts
firing often on the same symbol, that is the next thread to pull.


---

## C-90 — the event calendar now extends itself for the two categories that CAN be derived, and refuses to invent the four that cannot

`BP_calendar.py`'s tables stop at the end of 2026. The existing safeguard only *logged* that:
once the clock rolls into 2027 every blackout silently becomes a no-op and the system trades
straight through NFP. The warning fires on every run today, including in this session's
forward-test output.

### The split — and why it is not "just refresh the tables"

| category | derivable? | action |
|---|---|---|
| NYSE holidays | **yes**, by statute + NYSE convention | generated |
| NFP | **yes**, by BLS scheduling convention | generated |
| CPI, GDP | no — the BLS picks the day | **not generated** |
| FOMC, ECB, BoE | no — announced by the banks ~1 year ahead | **not generated** |

Inventing a plausible-looking 2027 FOMC date would be worse than having none: it would black
out the wrong day AND leave the real one unguarded. When central-bank coverage lapses the
loader escalates to ERROR instead.

### Both generators were validated against the hand-curated tables BEFORE being used

```
NYSE holidays   2025: 10/10 dates    2026: 10/10 dates
NFP             2025: 12/12          2026: 12/12         -> 24/24
```

Reaching 24/24 needed two conventions, and both were **derived from the curated data, not
assumed**. A naive "first Friday of the month" scores only 20/24:

1. **January lands on the SECOND Friday**, not the first — the December report needs the extra
   week. `2025-01-03 -> 2025-01-10` and `2026-01-02 -> 2026-01-09`, both off by exactly 7 days.
2. **If the target Friday is a FEDERAL holiday the release moves one day earlier** — seen at
   July 4 in both years. **Good Friday does NOT move it.** The BLS is a government agency and
   is open even though the NYSE is shut, which is why the curated 2026 table legitimately has
   NFP on Good Friday, `2026-04-03`. A "skip market holidays" rule gets that one wrong, and
   that single row is what separated an 11/12 rule from a 12/12 one.

That second point is the sort of thing that only shows up if you check the generator against
data somebody else curated by hand, which is the whole reason to do it that way round.

### Verified after the change

```
generated years          [2027]
2027 NFP                 12 dates, first 2027-01-08, all flagged
                         description="RULE-DERIVED, not confirmed against the official BLS schedule"
2027 NYSE holidays       10 dates, 2027-01-01 .. 2027-12-24
2027 FOMC/ECB/BoE        none -- correctly NOT invented
blackout 2027-03-05 13:30 UTC (generated NFP)  -> True
blackout 2027-03-04 03:00 UTC (quiet)          -> False
2026-03-06 NFP (curated, unchanged)            -> True, risk_multiplier 0.5
BP_CALENDAR_NO_AUTOEXTEND=1                    -> 147 events / 20 holidays = the exact
                                                  pre-change baseline
```

Curated years are untouched: only years past the curated maximum are generated, and holidays
are merged with `setdefault`, so a curated date always wins. All modules import clean.

The staleness warning is now per-category, because a single "last event year" over all events
would read 2027 and hide the fact that the bank dates still stop at 2026:

```
EconomicCalendar: central-bank + CPI dates end in 2026 (current year). Refresh
BP_calendar.py from the published FOMC/ECB/BoE schedules before year-end. NFP and
NYSE holidays extend automatically and need no action.
```

### Still needs a human

The 2027 FOMC, ECB and BoE schedules have to be copied from the banks' own published
calendars. That is the one part of this item that cannot be automated and must not be guessed.


---

## C-91 — `GeminiFrameBacklog` fires every 30 minutes on work that finished five days ago, and it is why interactive Gemini calls are slow

Section 11 flagged this task only for its principal (`Interactive`, so it does not run when
nobody is logged in). That is the smaller half of the problem.

### What it is actually doing

```
Task            GeminiFrameBacklog
Action          cmd.exe /c "...\gemini\run_backlog_task.bat"
Trigger         2026-08-21T00:05, RepeatEvery PT30M, RepeatFor P3650D   <- every 30 min for 10 YEARS
Principal       Interactive / Dhiraj / Limited
LastRunTime     2026-08-26 21:35:01
LastTaskResult  3221225786  = 0xC000013A  STATUS_CONTROL_C_EXIT  (forcibly terminated)
NextRunTime     2026-08-26 22:05:00
```

**Both backlogs it runs are complete:**

```
run_weekly_backlog.py    --status   TOTAL 2189 / 2189   (100% transcribed)
run_practical_backlog.py --status   TOTAL 2122 / 2122   (100% transcribed)
```

So 48 runs a day, ~240 runs since 2026-08-21, on a queue with nothing left to transcribe. It
is not idling either — `out/task.log` was being written at 21:35 today, mid-chapter
(`[3/14] 2023/03.09.2023 CW36`), producing spotcheck and summary files for chapters already
marked DONE. `out/task.log` has reached 2.0 MB.

### Why it matters beyond wasted cycles

It spends the **same two free-tier API keys** everything else in this project uses, and the
free tier is small: the runner's own status line reports the ceiling as

```
best-case reads left today if all pairs were fresh: 400  (2 keys x 10 models x 20/day)
```

20 requests per model per key per day. A job taking 48 bites a day out of that is why an
interactive call in this session took **196 seconds for a one-word reply**, why the pro models
answer 429, and why the flash models kept returning 503. It is a self-inflicted rate limit,
and it was invisible because the task is owned by Windows, not by any session.

`LastTaskResult = 0xC000013A` says the last run did not finish on its own — Windows killed it,
which is what happens when a run overruns the task's execution time limit and the next
30-minute trigger comes round.

### Not changed here

Modifying a scheduled task is a system settings change and is the operator's call, not mine.
The choice is between disabling it outright and dropping it to something like daily. Either
way, run from an ELEVATED PowerShell:

```powershell
# option A -- stop it entirely; both backlogs are 100% done
Disable-ScheduledTask -TaskName "GeminiFrameBacklog"

# option B -- keep it as a safety net but stop the 30-minute repetition
$t = Get-ScheduledTask -TaskName "GeminiFrameBacklog"
$t.Triggers[0].Repetition.Interval = "P1D"
Set-ScheduledTask -TaskName "GeminiFrameBacklog" -Trigger $t.Triggers[0]
```

The `Interactive` principal noted in section 11 becomes moot under option A. Under option B it
still wants changing to `S4U` so the task runs when nobody is logged in — but that is a second
decision, and with both backlogs complete there is currently nothing for it to run.

**Check this before trusting any timing measurement of Gemini in this project.** A slow or
429-ing call may be this task, not the API.


---

## C-85 — the full 103-label transcript audit, and why its headline number is NOT 6%

`gemini/audit_goldtest_labels.py`. Every goldtest label joined to its exact-date Weekly Outlook
chapter, the chapter transcript sent to a second model with the LOOSE convention spelled out,
and a per-label verdict required to carry a verbatim quote or be marked INSUFFICIENT.

```
labels requested        103   (18 chapters, every one with an exact-date transcript)
verdicts returned        94   (91%)
  SUPPORTS               58   (62%)
  INSUFFICIENT           30   (32%)
  CONTRADICTS             6   (6%)
still uncovered           9   -- the model omitted them despite being told to say INSUFFICIENT
```

### The 32% is the real finding, not the 6%

Nearly a third of the goldtest labels **cannot be sourced from the transcript at all**. The
transcripts are sampled roughly one frame per minute, so an instrument discussed for ninety
seconds can survive as a single fragment or as nothing. Those labels are not wrong — they are
*unfalsifiable from this source*. Any future claim about goldtest label quality has to carry
that: 62% confirmed, 32% unconfirmable, on n=94.

### All six "contradictions" dissolve on inspection

Reading each against the goldtest's OWN note rather than accepting the verdict:

| row | goldtest note | quote the audit used | verdict |
|---|---|---|---|
| GC=F 2023-01-01 | "expecting a monster rally soon **but I can just NOT take it now**" | "Yes Gold and silver expecting a monster really soon" | **goldtest right** — quote truncated before the refusal |
| SI=F 2024-02-19 | "we are close to overvaluation... **move on**" | "we are close to over valuation" | **goldtest right** — same truncation |
| TSLA 2023-01-01 | "already gone, wait for it to come back down" | "I tried to go long here... I was not filled" | **goldtest right** — past-tense narration of an UNFILLED order read as a call |
| BABA 2023-01-01 | "wait for short-term undervalued to buy Baba" | "Is the low short term undervalued to buy Baba." | **convention difference** — same words, and a conditional call does count as directional under LOOSE |
| NQ=F 2023-04-24 | "drift down early week, topping Thursday then Friday retracement. *'the question is now from where this could bounce'*" | the same sentence | **convention difference** — the goldtest note already contains the quote and reached neutral on fuller context |
| NFLX 2023-04-02 | "reading out of all zones" | "amazing these setups we are all valued maybe we get a pullback" | **genuinely ambiguous** — the goldtest note is too thin to defend, the quote is garbled |

**Not one of the six is a clear goldtest mislabel.** Three are the second reader quoting half a
sentence and missing the refusal in the other half. Two are the loose-vs-strict convention
applied to identical words. One is a coin toss.

### The error that keeps repeating is TRUNCATED QUOTING

Three of six here, and C-85's own NG=F verdict, are the same failure: read a fragment, miss the
clause that reverses it. C-85 called *"continue to go lower"* unambiguous while dropping *"I
really never touch natural gas"* from the front of its own quote. A second model, given a
sparse transcript, reproduces that error at roughly the same rate.

**This is a property of the sparse transcripts, not of any particular reader.** Which means:
never label or re-label from a single sampled line. Pull the surrounding frames first.

### Where this leaves C-85

The audit C-85 asked for is done, and its conclusion is the opposite of C-85's premise. The
goldtest labels were suspected because they had never had the C-64 treatment. Given it, they
hold: 58 confirmed, 0 demonstrably wrong, 30 unconfirmable, 6 disputed and all 6 explained.

C-85's standing instruction — *"do not accept or reject anything on a goldtest delta of 1-2
cases"* — still holds, but now for a different reason. Not because the labels are suspect, but
because a third of them cannot be checked against anything, so a 1-2 case delta can easily sit
entirely inside the unverifiable third.

### Method notes for whoever reruns this

- **Chunk the requests.** Asked for 16 verdicts in one call the flash models drift into prose,
  and a repair pass can only rescue what the prose contained — on 2023-01-01 that was 1 of 16,
  and the other 15 were dropped SILENTLY. `LABELS_PER_CALL = 6` fixed it.
- **Reconcile what came back against what was asked for.** The report counts verdicts, and a
  model that quietly omits a symbol looks identical to one that never had it. That check is
  what surfaced the 15 dropped labels and the 9 still outstanding.
- 9 labels remain uncovered: `NQ=F`/`ES=F` on 2023-01-01, `ES=F` on 2023-01-22, and six of the
  nine on 2024-02-25. They need a rerun with a smaller chunk size.


---

## C-92 — a SECOND, INDEPENDENT ground truth: the trade decisions visible in the frames

Everything the system is scored on today comes from TRANSCRIPT quotes — what the
presenter said. Every label dispute settled this week (`C-85 RESOLVED`, C-64, and
C-85's own NG=F error) turned on the same failure: a sparse transcript quoted half a
sentence and the refusal in the other half was lost. A frame showing a drawn zone and
a marked entry does not have that failure mode.

It turns out the data was already on disk and had never been joined up. The vision
pass wrote a `trade_signal_direction` on every chart frame across all three Funded
Traders corpora.

```
2,903  _gemini_analysis_output/*_analysis.json files
1,618  carry a trade_signal_direction
  246  are DIRECTIONAL           (216 buy / 30 sell -- 88% long)
  244  map to a tradeable symbol
   71  distinct (symbol, date)
   70  CASES                     (1 excluded, see below)
```

`gemini/build_frame_cases.py` builds it; `goldtest/frame_cases.yaml` is the corpus and
`frame_cases_provenance.json` keeps the source frame, folder, price and drawn levels
for every row so any disputed case can be re-read.

**Independence from the corpus already in use:** 25 of the 70 (symbol, date) pairs do
not appear in the scored 479-case shards at all.

### The one exclusion, and why it is not resolved

`NQ=F 2023-05-16` shows **4 long frames and 4 short frames in the same session**. It is
excluded rather than resolved. A session showing a long setup on one timeframe and a
short on another is a real thing; picking one would be inventing ground truth, which is
exactly what made the old in-sample score meaningless.

### Cross-checking the two ground truths found a REAL BUG — mine

Where both sources label the same (symbol, date): **39 of 45 agree, 87%.**

It was 37/45 before this. The CME currency futures are quoted as USD per unit of the
foreign currency. For EUR, GBP, AUD and NZD that matches the spot pair, so `@EC ->
EURUSD=X` carries direction through. For JPY, CHF and CAD the spot convention is the
RECIPROCAL, so **a LONG on @JY is a SHORT on USDJPY**. Verified against pinned closes
on 2023-04-18:

```
@SF frame value 1.12155   1/1.12155   = 0.89162    USDCHF=X actual 0.89851
@JY frame value 0.75125   100/0.75125 = 133.111    USDJPY=X actual 134.425
```

The symbol map this was inherited from — `gemini/analyze_valuation.py`, and the
identical one in `gemini/analyze_cot_groups.py` — does **not** invert. Any finding
derived from those two scripts for USDJPY / USDCHF / USDCAD needs re-checking.

**The trading system itself is NOT affected.** `BP_rules_engine.py:791` has
`is_usd_base_forex` and `:1729` logs *"Phase 21: USD-base pair {symbol} — COT inverted"*.
The defect is confined to the two analysis scripts in `gemini/`.

### The six rows where the two sources still disagree

```
GC=F     2024-02-14  transcript=neutral  frame=long   10 frames  "testing a daily demand zone 1823-1830"
GC=F     2024-03-07  transcript=neutral  frame=long    1 frame
NQ=F     2023-02-21  transcript=short    frame=long    5 frames  "near highlighted demand zones"
NQ=F     2024-01-03  transcript=short    frame=long    1 frame
NQ=F     2024-02-21  transcript=short    frame=long    3 frames  "180-min support zone highlighted"
USDJPY=X 2023-04-04  transcript=short    frame=long    1 frame
```

**The three NQ=F rows matter more than the count suggests.** They are instructor
equity-index shorts, and section 9 of this note declared exactly those rows an
irreducible accuracy ceiling — *"no deterministic rule set can match both sides"*. The
frames say long. If the frame evidence is right, part of that ceiling is a transcript
LABELLING error rather than a genuine disagreement between presenters, which would
RAISE the achievable score rather than cap it.

Two of the three carry multiple frames. **This is a lead, not a conclusion** — rule 9
says a single read is not evidence, and the multi-frame rows here are 3 and 5 reads of
the same session, not independent reads of the same image. Settling it means going back
to the frames themselves.

### A trap found in the first scoring run, worth knowing about

The first attempt errored on **33 of 70** cases, all with `strategy: daily`. The chart
timeframe the presenter had open is NOT the income strategy: `daily` loads `htf 1d /
ltf 60m`, and yfinance only has 60-minute bars for the last ~730 days, so every
2023-2024 daily case fails before the engine runs. A daily chart is the LTF of the
weekly strategy, so those decisions are scored in the weekly frame instead, with the
original chart timeframe preserved as `_chart_tf`.

**The scored 479-case corpus has the same latent problem** — 16 `daily` and 15
`intraday` cases, against 31 errors per run. That is very likely most of its standing
error count, and it means those 31 have never actually been scored.

### The score: does the system's decision match the frame's?

`goldtest/frame_cases.yaml` scored with pinned data. 70 cases, 1 error, 69 scoreable.

```
n = 69   -- every row is a DIRECTIONAL frame decision; there is no neutral ground truth
  system match          35/69 = 50.7%
  always-long           60/69 = 87.0%    <- the baseline
  system SILENT (neutral where a decision was made)   25/69 = 36%
  system OPPOSITE                                      9/69 = 13%
  on the 60 LONG frame decisions   33 matched
  on the  9 SHORT frame decisions   2 matched
```

**A constant "always long" beats the engine by 36 percentage points on this corpus.**
The caveat that must travel with that number: this corpus contains only frames marked
buy or sell, so there are no neutral rows and always-long is inflated relative to a
corpus that has them. The 36% silence and 13% opposites are absolute failures either way
-- the presenter drew a zone and took a side, and the engine either had nothing to say
or said the reverse.

**The two independent ground truths corroborate each other.** Transcript corpus 51.9%,
frame corpus 50.7%, built from different sources by different methods, landing 1.2
points apart. The ~51% is not an artefact of how the transcripts were labelled.

The dominant failure is not being wrong. It is saying nothing: 25 silent against 9
opposite. See C-93 for what causes that, measured.

### The 31 never-scored cases, rescued

`rescued_cases.yaml` -- the same 31 cases remapped from `daily`/`intraday` to `weekly`:

```
cases 31   errors 0   NOW SCOREABLE 31   match 14/31 = 45.2%
truth: neutral 17, long 8, short 6      system: long 18, neutral 11, short 2
```

**Zero errors.** They score. The corpus is 510, not 479, and it always could have been.
Note the system answers `long` on 18 of 31 where the truth is `long` on only 8 -- the
same long-bias the frame corpus shows.


---

## C-93 — the indicator silence is STRUCTURAL, not a threshold. Do not tune it.

The standing brief asked for this before any threshold was touched: *"Valuation reads
neutral on 64% of cases and COT on 73%, and both on 45%. Establish WHY -- is it
genuinely neutral data, a threshold that is too wide, a missing CFTC code, or a data
gap? Break the silence rate down by asset class and by year."*

Current measured rates on the 479 scored cases (they have moved slightly since that
brief was written, after the cycle-override flip and C-88):

```
Valuation neutral   285/479 = 59%
COT       neutral   324/479 = 68%
BOTH      neutral   195/479 = 41%
```

### COT silence, by asset class -- one cause dominates

```
asset_class          n   cot neutral   rate   symbols WITH a CFTC code
equities           206           206   100%   0 of 13      <-- 
equity_indices      90            42    47%   4 of 4
precious_metals     76            34    45%   4 of 4
energies            37            16    43%   2 of 2
forex               34            13    38%   6 of 8
commodities         26            10    38%   7 of 7
soft_commodities     6             0     0%   4 of 4
```

**Individual stocks have no COT report. There is no CFTC code for AAPL.** All thirteen
stock symbols in the corpus -- AAPL, AMZN, BA, BABA, GOOGL, META, MSFT, NFLX, NVDA,
PFE, RACE, TSLA, WMT -- return nothing from `get_cftc_code`, so COT is neutral 206 times
out of 206. That is **206 of the 324 silent cases, 64% of all COT silence**, and it is
not silence at all: the indicator is being asked a question that does not exist for that
instrument.

Every futures class sits at 38-47%, which is what a genuine 20/80 extreme band produces.
Nothing there suggests a threshold problem.

### Valuation silence -- two DELIBERATE code-level skips, not data

```
asset_class          n   val neutral   rate
equity_indices      90            90   100%   <-- switched OFF in code
equities           206           118    57%   <-- proxy, not real Valuation
forex               34            26    76%
energies            37            19    51%
precious_metals     76            25    33%
commodities         26             5    19%
```

`BP_rules_engine.py:1885`:

```python
if asset_class == 'equity_indices':
    _skip_val = True
```

Phase 15, with its reasoning on the line above it: *"The standard DXY/ZN/ZB comparison
reads equity indices as 'bearish' whenever they outperform bonds (i.e. in every bull
market), producing false Valuation vetoes on correct long signals."* So 90/90 is a
decision, not a failure.

Individual stocks take the `_stock_valuation_proxy` branch -- price vs a 3-year SMA --
because CampusValuationTool_V2 is not available. That proxy is neutral 57% of the time.

`VALUATION_SKIP_SYMBOLS = {'NG=F', 'QN=F', 'NFLX'}` removes three more by name.

Checked and ruled out: the indicator itself is fine. Called directly on pinned weekly
bars with the same references the engine uses, it returns real readings for every class
-- `NQ=F -40.99 bullish`, `YM=F +29.28 bearish`, `GC=F +46.42 bearish`,
`CL=F -45.42 bullish`, `AAPL -77.29 bullish`. It is the engine path that suppresses it,
not the maths.

### Data gap -- ruled out by measurement

All three valuation references return a full history at weekly resolution for every
asset class tested, in offline pinned mode:

```
DX-Y.NYB 522 bars   ZB=F 522 bars   GC=F 522 bars
```

No class is short of reference data. This hypothesis is dead.

### Verdict on the four candidates in the brief

| candidate | verdict |
|---|---|
| genuinely neutral data | **partly** -- explains the 38-47% on futures classes, which is normal for a 20/80 band |
| threshold too wide | **NO** -- not dominant anywhere; no class shows a pile-up just outside its band |
| missing CFTC code | **YES, and it dominates COT** -- 206 of 324 silent cases, 64% |
| data gap | **NO** -- 522 reference bars available for every class |

And a fifth cause the brief did not list, which dominates Valuation:
**deliberate code-level skips** (equity_indices by class, three symbols by name).

### The consequence, which is the point

**On 206 of 479 cases -- 43% of the corpus -- NEITHER decisive indicator can speak, by
construction.** Stocks have no COT at all, and their Valuation is a 3-year-SMA proxy
standing in for a tool the user does not have. On those rows Location alone decides the
direction, and Location read bearish on 45% of the corpus because almost everything sat
near an all-time high.

That is a complete mechanical explanation for the flat ~51% Stage-1 result, and it says
plainly: **no threshold change can fix it.** Widening the COT band cannot conjure a COT
report for AAPL. The three things that would actually move it are, in order of size:

1. **Obtain CampusValuationTool_V2.** It is the missing piece for both equities and
   equity indices -- 296 of 479 cases, 62% of the corpus. Everything else is downstream
   of not having it.
2. **Re-examine the Phase 15 equity-index skip.** Its reasoning is sound as far as it
   goes, but it was a decision taken to avoid a false veto, and it has never been A/B'd
   on the out-of-sample corpus. It is a flag-shaped change and should be measured.
3. **Accept that on stocks the method is running on one leg** and consider whether they
   belong in the tradeable universe at all, rather than tuning around them.

Measured 2026-08-26 on `c88guard?.json`, n=479, and reproducible from it.


---

## C-94 — 31 cases have NEVER been scored, in any run, ever. The corpus is 510, not 479.

Every goldtest run reports "Errors: 31". They are not random attrition:

```
corpus strategies   weekly 448   monthly 31   daily 16   intraday 15
errors by strategy                            daily 16   intraday 15   = 31   EXACT MATCH
error kind          "insufficient OHLCV"
```

`daily` loads `htf 1d / ltf 60m`; `intraday` loads `htf 60m / ltf 15m`. **yfinance keeps
60-minute bars for roughly 730 days**, so every 2023-2024 case on those two strategies
fails before the engine runs. The gap is SYSTEMATIC -- it removes exactly the
short-timeframe cases -- and among them:

```
bias mix of the never-scored 31:   neutral 17   long 8   short 6
```

**Six shorts**, in a corpus where Bernd has only 16 across all 479 scored cases. Every
short-side conclusion on file, including item 7, has been drawn from a sample missing 27%
of the available shorts.

**Fix and verification.** Remapped to `weekly` (htf 1wk / ltf 1d, which keeps the same
daily bars in view as the LTF), with `_original_strategy` recorded on each case rather
than hidden:

```
rescued_cases.yaml:   31 cases   errors 0   NOW SCOREABLE 31   match 14/31 = 45.2%
truth: neutral 17, long 8, short 6      system: long 18, neutral 11, short 2
```

Zero errors. They score, and always could have. `full510_shard{0..5}.yaml` is the whole
corpus with the remap applied -- use it for future A/Bs instead of silently discarding 6%.

Note the system answers `long` 18 times out of 31 where the truth is `long` only 8 -- the
same long-bias the frame corpus shows independently.

The same trap cost 33 of 70 cases on the first run of the frame corpus. The chart
timeframe a presenter has open is NOT the income strategy; conflating them loses the case.


---

## C-95 — "THE INDICATORS ARE NOT THE PROBLEM" is FALSE for equity-index Valuation. Our tool reads bearish 59% where his reads bearish 0%.

The load-bearing claim in `PASTE_THIS_TO_CLAUDE.md` is: *"THE INDICATORS ARE NOT THE
PROBLEM. They reproduce Bernd's lecture frames exactly (COT 85.10 / 18.10 / 74.56). What
has no measured out-of-sample skill is the bias-consensus rule layer built on top."*

That claim rests on **three** COT values. Measured against the frame corpus it does not
survive for Valuation on equity indices.

### What HIS tool prints, n=400 across 16 chapters

Every on-screen Valuation reading mined from the frame corpus (1,400 observations,
1,399 parse cleanly; the one reject is the tool's own `-100000000` no-data sentinel):

| chart class | n | min | max | bullish <=-75 | neutral | **bearish >=+75** |
|---|---|---|---|---|---|---|
| equities | 722 | -100.0 | 100.0 | 48 (7%) | 648 | 26 (4%) |
| **equity_indices** | **400** | -100.0 | **+66.1** | **34 (8%)** | 366 | **0 (0%)** |
| futures | 186 | -100.0 | 83.6 | 3 (2%) | 182 | 1 (1%) |
| forex | 91 | -100.0 | 38.6 | 1 (1%) | 90 | 0 (0%) |

**On equity indices his tool never once reached the +75 overvalued threshold.** Highest
reading anywhere in the corpus: **+66.08**. And it is not mute either — 34 of 400 read
bullish.

The reference configuration is not the explanation. The legend also prints which
references are switched on, and those are SETTINGS, so they join without a date:

```
equity_indices   333 of 334 (100%)  True, True, True   -> bonds + gold + DXY, the standard set
futures          152 of 153  (99%)  True, True, True
forex             38 of  38 (100%)  True, True, True
equities         435 of 441  (99%)  True, False, ...   -> bonds ON, GOLD OFF
```

He runs the ordinary three-reference config on indices, exactly as on futures.

### What OUR engine prints on the same instruments

`BP_INDEX_VALUATION=1` removes the Phase 15 skip. A/B on the 101 equity-index cases in
the corpus, 90 paired, pinned snapshots, single variable:

```
valuation component   flag OFF : neutral 90                          (the skip)
valuation component   flag ON  : bearish 53 (59%)   neutral 32   bullish 5 (6%)

MATCH  OFF  31/90 = 34.4%
MATCH  ON   19/90 = 21.1%      delta -12      changed 35, fixed 3 / broke 15
```

Side by side:

| | bearish | bullish | neutral |
|---|---|---|---|
| **his tool** (n=400 frames) | **0%** | 8% | 92% |
| **our engine** (n=90 cases) | **59%** | 6% | 36% |

### The conclusion, which is not the one either side predicted

Phase 15's *observed symptom* is real and its instinct was right: turning the skip off
does read bearish through a bull market and does break correct longs, 15 against 3.
**But his tool does not do that.** The skip is therefore **a workaround for a defect in
our own Valuation implementation, not a property of the method.**

Both of the obvious readings were wrong:
- *"The skip is unjustified, remove it"* -- no. Removing it costs 12 cases.
- *"The skip is vindicated"* -- no. It is vindicated as damage control over a bug that
  should be fixed instead.

**Default stays OFF.** Removing the skip while the underlying divergence exists would be
strictly worse. The flag stays in the tree because it is the measuring instrument for
whoever fixes the divergence: when our reading matches his, `BP_INDEX_VALUATION=1`
should stop costing 12 cases, and that is the test that the fix worked.

### Where the divergence is likely to be -- NOT YET DIAGNOSED

The reference SET is confirmed identical (all three, 333/334), so it is not which
symbols. What is left:

1. **Reference ordering.** `_audit_ftw_vision/tv_fixtures/CampusValuationTool_CORRECTED.pine`
   documents that `Valuation_OTC.txt` had the order REVERSED -- ours declared
   Symbol1=DXY / Symbol2=GC / Symbol3=ZB, his dialog reads Ref1=ZB (bonds), Ref3=DXY.
2. **Timeframe.** His `request.security(..., timeframe.period, ...)` makes every
   reference follow the CHART timeframe, and the corpus shows him on DAILY ~95 times
   against weekly ~6 (audit C-53). Our engine computes Valuation on the HTF.
3. **Rescale window.** `rescale_length=100` bars, and a rescale over a different window
   moves every reading.

A second, separate discrepancy falls out of the same table: **`VALUATION_REFS['equities']
= ["ZB=F", "GC=F"]` is contradicted 435 to 1** -- gold is switched OFF on stock charts.
The code comment claims *"Phase 36 multi-agent consensus: Ch173 + Phase 32 rulebooks
agree stocks use Bonds + Gold"*. The frames disagree. It does not currently change any
output, because equities take the `_stock_valuation_proxy` branch and never reach
`VALUATION_REFS` at all -- but it would the moment the proxy is replaced.

**Caveat on the stock rows:** 436 of 441 stock legends truncate after ref2, so gold being
OFF is established and DXY's state is not.

### What this does to the project's headline framing

"The indicators are fine, only the rule layer is broken" now needs qualifying. It holds
for COT (85.10 / 18.10 / 74.56, n=3). It is **false** for Valuation on equity indices at
n=400 vs n=90. Since equity indices are 90 of 479 cases and are exactly where the engine
is weakest, that is not a footnote.


---

## C-96 — REJECTED. Matching his indicator's thresholds makes the SCORE WORSE, significantly.

C-95 established that our `Valuation.get_bias` votes a line bearish at **+10**, a band that
is not in the indicator: the settings dialog exposes Upper 75 / Lower -75 and
`CampusValuationTool_CORRECTED.pine` draws hlines at 75 / -75 and nothing else. Applied to
his own 1,399 on-screen readings the band reclassifies most of the corpus -- equity indices
go from 92% neutral under his thresholds to 15% neutral under ours; futures 98% -> 16%.

So: use his thresholds. `BP_VAL_STRICT_THRESHOLDS=1`, measured on the full 510-case corpus,
paired, single variable, pinned snapshots.

### It converges on his distribution and loses cases doing it

Neutral rate, ours vs his:

| class | ours default (+/-10) | ours strict (+/-75) | his tool |
|---|---|---|---|
| forex | 76% | **100%** | 99% |
| energies | 51% | **95%** | 98% (futures) |
| precious_metals | 33% | **89%** | 98% (futures) |
| commodities | 19% | 58% | 98% (futures) |
| equities | 57% | 57% (unchanged) | 90% |
| equity_indices | 100% | 100% (unchanged) | 92% |

Forex, energies and precious metals move most of the way to his numbers. The two unchanged
rows are unchanged for known reasons -- equities never reach Valuation at all (SMA proxy),
equity indices are still skipped by Phase 15 -- and commodities are explained by C-97.

And the score:

```
BERND        n=339   176 -> 172   -4    changed  7   fixed 1 / broke  5   p=0.219
INSTRUCTORS  n=171    93 ->  85   -8    changed 13   fixed 2 / broke 10   p=0.039  SIGNIFICANT
```

**-12 pooled, and significant against on the instructor group.** Default stays OFF.

### The reason this matters more than the -12

This is the first change measured that moves the engine TOWARD his indicator and AWAY from
the scoreboard. Both cannot be right at once, and the disagreement is not marginal: the
+/-10 band is a setting his indicator does not have, and removing it costs 12 cases.

Two readings, and they are not equivalent:

1. The band is an accidental compensator -- wrong against his tool, but it happens to supply
   signal the rest of the engine has come to rely on.
2. The rest of the engine is fitted around the band, so pulling one leg out of a jointly
   tuned system hurts regardless of whether that leg was correct.

Either way the conclusion is the same and it is uncomfortable: **the engine's score depends
on an indicator setting that his indicator does not have.** That is direct evidence the
engine is fitted to its own quirks rather than to his method -- the same class of problem as
the ~20 phases of `_bias_consensus` tuning, but at the indicator layer, which is the layer
this project has always treated as sound.

Do not "fix" this by putting the band back with a justification. It is already the default.
What it means is that the score cannot be used to validate the indicator layer, because the
score rewards the divergence.

### Note on the corpus

This is the first A/B run on all **510** cases (C-94). The instructor group is n=171 here
against n=140 on the old 479-case shards, because the 31 rescued cases are now scored.
Baseline instructor accuracy on the fuller corpus is 93/171 = 54.4%.

---

## C-97 — the ROC-length override is CONTRADICTED by the frames and INERT on the corpus. Both halves matter.

`BP_config.yaml`'s `cycle_per_symbol` sets ROC Length 30 for six ags/softs symbols. The
Valuation legend prints the Length actually running, and for three of them it says 10:

```
ZS=F   observed 10 x6    config 30   CONTRADICTED
ZC=F   observed 10 x2    config 30   CONTRADICTED
KC=F   observed 10 x5    config 30   CONTRADICTED
CT=F   observed 30 x3    config 30   supported
ZW=F   no observations
CC=F   no observations
HG=F   observed 10 x1    config 10   supported (never overridden)
```

13 observations against, 3 for. Pooled across the corpus the Length he runs is
`{10: 77, 13: 59, 30: 3}` (n=146, counting only legends where all three reference booleans
are visible so the Length's position in the argument list is unambiguous). **30 is 2% of
sightings and the config applies it to six symbols.**

This is also the answer to "why did commodities not converge when the thresholds did": we
run a 30-bar ROC on WEEKLY bars where the legend shows 10.

### Measured: `BP_VAL_FRAME_LENGTH=1`, 510 cases, paired

```
BERND        n=339   176 -> 176   0 changed   p=1.000
INSTRUCTORS  n=171    93 ->  93   0 changed   p=1.000
```

**0 of 510 predictions move.** Rule 5 -- verified ACTIVE, not merely applied. On the 16
corpus cases for the three symbols the Valuation component does change:

```
KC=F 2023-12-31   val bullish -> bearish    bias neutral -> neutral
KC=F 2024-03-09   val bearish -> neutral    bias short   -> short
(the other 14 read identically at length 10 and length 30)
```

So the flag fires, changes the component on 2 of 16, and changes the final direction on none.

### Why both halves matter

The config is **wrong** against the frame evidence, and fixing it **buys nothing measurable**.
Recording only the first half would imply a lever exists here; recording only the second would
lose a real documentation defect. `ZC=F` and `ZS=F` read `bullish` on all 11 of their cases in
BOTH arms -- the ROC window is not what decides them.

**Default OFF.** Not because the config is right, but because changing it is inert and every
change to this system should be measured before it ships. Whoever repairs `cycle_per_symbol`
from frame evidence should expect the score not to move.

### Method correction to C-87, which shares this data

C-87 extracted Length as *the first integer anywhere in the parameter list*. That is
contaminated:

```
C-87 first-int      n=275   {3383376: 126, 10: 61, 13: 58, 30: 11, 75: 3, ...}
positional          n=146   {10: 77, 13: 59, 30: 3, 33: 3, ...}
```

**`3383376` is the indicator's ID number** -- `Campus True Seasonality 3383376` -- counted 126
times as a "Length", making it the single most common value in C-87's distribution. `75` is a
threshold. C-87's conclusion that Length tracks the TIMEFRAME is not overturned (both methods
agree 30 is rare), but its counts should not be quoted as they stand.


---

## C-99 — the Valuation MATHS is faithful. The divergence is entirely in how we READ it. And equities never run it at all.

This corrects my own earlier conclusion in this session, which was that the leverage lay in
"obtaining CampusValuationTool_V2 for 296 of 510 cases". That was too broad, and half of it
was wrong.

### The maths matches the Pine, checked line by line

`CampusValuationTool_CORRECTED.pine` (frame-verified from the settings dialog) against
`BP_indicators.Valuation.calculate`:

| | Pine | ours |
|---|---|---|
| ROC | `(src - src[Length]) / src[Length] * 100` | identical |
| difference | `SymPerc - CompPerc` per reference | identical |
| rescale | `RescaleMin + (RescaleMax-RescaleMin)*(v-mn)/(mx-mn)` | `(v-mn)/denom*200-100` -- algebraically the same at Min=-100 / Max=100 |
| window | `ta.highest(v, RescaleLength)` trailing | `rolling(window=length)` trailing |
| zero guard | `mx == mn ? na` | `denom != 0` else NaN |

Two immaterial differences: our `min_periods` is adaptive so early bars produce values Pine
would leave blank (the LAST bar, which is the only one `get_bias` reads, has a full window on
every series here -- 120 to 522 bars against a 100-bar window), and Pine additionally guards
`prev == 0`, which cannot arise on a price series.

**There is no reconstruction to do. The indicator is right.**

### The equity-index divergence was 100% the +/-10 band

Our index line values at the real case dates, scored under HIS thresholds:

| | ours (n=177) | his (n=400 frames) |
|---|---|---|
| bearish >= +75 | 8.5% | 0% |
| bullish <= -75 | 4.5% | 8.5% |
| **neutral** | **87.0%** | **91.5%** |

Close. Score the SAME values under our `get_bias` band and 57.1% land >= +10 -- which
reproduces the engine's measured 59% bearish almost exactly.

So the 59%-vs-0% gap reported in C-95 is not a broken indicator. It is `get_bias`. C-96 already
measured removing the band: **-12 cases, p=0.039 against.**

**Consequence: there is no leverage on equity indices.** The values already match his; the
issues are the Phase 15 skip and the band; and correcting the band costs score. Anyone
returning to this should not spend time "fixing the index indicator".

### Equities are the real substitution, and 224 cases

Individual stocks never reach `Valuation` at all -- they take `_stock_valuation_proxy`, price
against a 3-year SMA, because "CampusValuationTool_V2 is NOT available (user confirmed)".

Measured against his own on-screen readings, that premise does not hold. Raw line values at
the 224 corpus equities case dates, classified under his +/-75:

```
config                              n     bearish   bullish   neutral
bonds only  (frames say 435/441)  224        8.9%      8.0%     83.0%
bonds + gold (shipped config)     448       10.0%      6.7%     83.3%
HIS TOOL, 722 frame readings      722        3.6%      6.6%     90.0%
```

**Our own Valuation, run on stocks with bonds refs at +/-75, reproduces his distribution to
within 7 points of neutral and 1.4 points of bullish.** The tool we were told we do not have is
substantially the tool we already have, pointed at the wrong thing and read through the wrong
band.

Two config details fall out, both frame-derived rather than argued:

- **gold OFF.** The legend reads `True, False` on **435 of 441** stock charts (99%).
  `VALUATION_REFS['equities'] = ["ZB=F", "GC=F"]` includes gold and is contradicted 435 to 1.
  The code comment cites a "Phase 36 multi-agent consensus" for including it.
- **length 13.** The on-camera edit *"I'm going to change the ROC from 10 to 13"* is performed
  on AAPL, and stock legends read 13 on 4 of 6 observations.

### Measured: `BP_STOCK_REAL_VALUATION=1`

Replaces the SMA proxy with real Valuation (bonds only, L13, +/-75) for `asset_class ==
'equities'`. Default OFF. 510 cases, paired.

**Prior stated before the run: expect it to cost cases.** C-96 measured the same trade --
closer to his instrument, further from the scoreboard -- at -12, p=0.039, on the classes that
already run Valuation. This applies it where the substitution is real rather than cosmetic.

**RESULT: pending -- see the session note.**

### Why this matters even if it loses

If a change that demonstrably moves the indicator TOWARD his own readings loses cases for the
third time, the conclusion is no longer about Valuation. It is that **the 510-case scoreboard
cannot be used to steer the system toward his method**, because the engine has been fitted to
its own divergences and the score rewards them. At that point the correct move is to stop
optimising the score and start scoring against the frame corpus instead -- which is
independent, was built today, and agrees with the transcript corpus to within 1.2 points.

---

## C-100 — I concluded the Signals sessions draw no position tools. That was wrong, and the error was SAMPLING, not vision.

Recording this because a false NEGATIVE is the expensive kind: it closes a line of enquiry
that was actually open, and nobody re-opens it.

### The claim, and why it looked solid

After reading 105 Signals frames for drawn entry/stop position tools:

```
with a chart symbol   :  92  (88%)     <- real charts, not slides
with drawn LEVELS     :  26  (25%)
with a POSITION TOOL  :   0  ( 0%)
```

I concluded the live Signals sessions never draw entry/stop/target boxes, that the
entry discipline is only recorded where it is taught, and that R-multiple expectancy is
therefore unrecoverable from the corpus. I stopped the run to save quota.

### What was actually wrong

The reader walked folders DEPTH-FIRST. 68 of those 105 frames came from a single folder,
`01.02.2024`, which `RESUME_NEXT_SESSION.md` already records as containing **zero**
signals ("they are market overviews, not entries"). The remaining 37 came from one other
folder. So a CORPUS-level conclusion rested on 37 frames from one session.

Depth-first answers "does THIS session draw position tools". Round-robin answers "does
this CORPUS draw them". I asserted the second from evidence for the first.

### The corrected measurement

Same prompt, same models, same quota -- only the traversal changed (round-robin across
folders, 4 parallel workers, folders with no recorded decision skipped):

```
217 frames   9 position tools   9 complete (entry+stop) setups   across 23 folders
example:  @NQ  short  entry=12341.0  stop=12500.0
```

**Roughly 1 usable setup per 24 frames.** The trades are there; they are spread thinly
across many sessions instead of concentrated in any one, which is exactly the pattern
depth-first sampling is blind to.

### The rule this should leave behind

When the question is about a CORPUS, sample across it. n frames of budget become n/22
frames from each of 22 folders, and the cost is identical. Depth-first is only correct
when the unit of the claim is the folder.

Corollary for any negative result in this project: state the traversal alongside the n.
"0 of 105" is not a corpus rate if 65% of those 105 came from one folder that was already
documented as empty.

---

## C-101 — THE EDGE IS THE ENTRY PRICE, NOT THE DIRECTION. Controlled, and it inverts the project's premise.

Every phase of this project has optimised **direction agreement** -- does our arrow point the
same way as his arrow. This measures what that arrow is worth on its own, and the answer is:
less than nothing.

### The control

54 drawn position tools mined from the Funded Trader Signals frames (2,162 of 2,509 frames
read). 51 geometry-valid, 45 after dedupe, 39 surviving a price-scale check that catches
`@JY`-type futures/spot inversions.

Then the same trade measured two ways -- SAME symbol, SAME date, SAME direction, SAME risk
size in R. Only the entry price differs. Exit is mechanical both ways: 2R target, 1R stop.

```
THEIR drawn entry (wait for the level)   win 13/25 = 52.0%   expectancy +0.56R
CONTROL: entry at market on day 1        win  8/36 = 22.2%   expectancy -0.33R

random walk, no drift, by theory         win       = 33.3%   expectancy +0.00R
their published KPI slide                win       = 40.0%   expectancy +0.20R
```

**Same call, same risk, same period. Waiting for the drawn level is worth +0.89R per trade.**

Two things fall out, and the second is the one that matters:

1. **Their directions entered at market are WORSE THAN RANDOM** -- 22.2% against a 33.3%
   theoretical baseline. This is the same result as the earlier horizon test, where their
   calls held blindly for 60 bars returned -3.91% against always-long, now reproduced under
   a defined-risk rule.
2. **Their directions entered at the drawn level BEAT their own published KPI** -- 52.0%
   against the 40% the LTF Entries slide asks for.

The 33.3% baseline is exact, not estimated: on a driftless series the probability of touching
+2R before -1R is 1/3, so a random entry has zero expectancy by construction.

### Per opportunity, not per trade

13 of 38 setups never filled -- price never reached the level. Those earn 0R rather than
+0.56R, and the honest comparison against a market entry (which always fills) counts them:

```
per TRADE TAKEN      +0.56R   (n=25 decided)
per OPPORTUNITY      +0.37R   (n=38, unfilled counted as 0R)
market entry         -0.33R   (n=36, always fills)
```

Positive on either accounting, and the gap to market entry survives both.

### What this means for the system

**The engine has been built to replicate the half of the method that carries no edge.**

Stage 1 -- direction -- is what ~20 phases of `_bias_consensus` tuning optimised, what the
479/510-case corpus scores, and what every A/B in this project has moved. Measured here, that
signal is worth less than a coin flip when acted on at market.

Stage 2 -- the zone entry that decides WHERE to buy -- is the part that carries the edge, and
it is the part that fires on 1.7% of cases and has produced 5 tradeable signals out of 479.

That reframes every previous finding rather than contradicting them. Stage-1 accuracy of 52.7%
against an always-long 50.4% is not a disappointing edge; it is a measurement of something that
was never the edge. C-93's indicator silence, C-96's threshold trade-off, C-98's dead basket
rule -- all of them are refinements to the wrong stage.

### Caveats, stated with the number

- **n=25 decided.** A 52% win rate at that size has a 95% interval of roughly 31-72%, which
  still overlaps both the random baseline and their KPI. The direction of the control gap is
  strong; the magnitude is not settled.
- **The exit rule is mine.** Flat 2R/1R with no breakeven, partials or trailing. E-03 showed
  breakeven-at-half converts winners into scratches, so their real management would score
  differently -- probably worse, on the E-03 evidence.
- **Selection.** These are the setups legible to a vision model. If position tools are drawn
  more carefully on higher-conviction trades, the sample skews to his better ideas.
- **Small-sample optimism is already visible in this very measurement**: at n=7 it read
  +1.14R, at n=25 it reads +0.56R. Expect further regression as n grows.

### What follows

Do not tune Stage 1 further. The measurable next question is whether OUR zone entries carry
the same property their drawn entries do -- which is a Stage-2 question, answerable with
`goldtest/replay_trades.py`, and blocked only by the engine firing 5 signals in 479 cases.

---

## C-103 — OUR ZONE ENTRY IS A MEDIAN 0.89R AWAY FROM THEIRS. That is the defect, and it is now measurable.

C-101 established that the entry price is the entire edge: their calls entered at market
return -0.33R, the same calls entered at their drawn level return +0.56R. C-102 then showed
our engine's own entries do the OPPOSITE -- they LOSE to a market entry.

This measures why, directly. For every drawn setup mined from the Signals frames, the zone
detector was run on the same symbol, the same date, the same weekly bars, and asked for its
nearest same-side zone.

### The measurement

```
their typical risk (stop distance):   median 3.87% of price

OUR entry error, in THEIR R units        n=38
   median   0.89 R
   min      0.02 R        max 103.56 R

   within 0.25 R    13/38   34%
   within 0.50 R    16/38   42%
   within 1.00 R    20/38   53%
   within 2.00 R    26/38   68%

   MORE THAN 1R AWAY:  18/38  (47%)
```

**The detector is not broken -- it is imprecise.** A third of the time it lands within a
quarter of the risk distance, which is the same trade. Nearly half the time it is more than a
full R away, which is a DIFFERENT trade: where they take profit we are still underwater, and
where their stop sits we were stopped out long ago.

Expressed in percent the gap looks small (median 4.1% of price) and that is exactly why it was
never caught. It only becomes visible against the risk: their median stop is 3.87% of price,
so a 4.1% entry error is slightly MORE than the whole trade.

### Why this explains everything measured today

| | |
|---|---|
| their entries | +0.56R |
| our entries | -1.00R (n=2) |
| our direction accuracy | 52.7%, +2.4pp over always-long |

The direction can be right and the trade still lose, because the trade being taken is not the
same trade. Twenty phases of `_bias_consensus` tuning optimised the label on the trade while
the price of the trade was off by more than its own risk.

### What this gives the project that it did not have

A better objective function. Every A/B in this project has been scored on DIRECTION AGREEMENT,
a metric C-101 showed carries no edge. **Entry error in R is a strictly better target**: it is
continuous rather than three-valued, it is measured against what the traders actually drew, and
it maps directly onto money -- an entry within 0.25R is the same trade, an entry beyond 1R is
not.

n=38 is small, and it grows every time the Signals frame pass finds another position tool.

### The next question, now well-posed

WHICH zone is wrong -- is the detector finding the right zone and mis-placing its proximal
edge, or finding a different zone entirely? Those have different fixes:
  * right zone, wrong edge  -> the proximal/distal derivation (`_score_zone` lines 377-381)
  * wrong zone entirely     -> ranking, or the 300-bar lookback window used here
The 13 cases inside 0.25R and the 18 beyond 1R should be compared directly to tell them apart.

---

## C-104 — MIDPOINT ENTRY. The fix existed, was unreachable, and is now wired. Entry error 0.89R -> 0.31R; expectancy inconclusive.

### What was wrong

`BP_rules_engine.run_seven_step_process(prefer_midpoint_entry: bool = False)` has existed
since the E2 entry type was written. Every signal entered at the zone PROXIMAL EDGE because:

  * no caller ever passed it -- `run_goldtest.py`, `run_scanner.py`, `run_forward_test.py`
    and `run_realworld.py` all omit the argument;
  * `BP_config.yaml` had no key for it, so it could not be enabled at all.

The E2 branch was unreachable code.

### Measured against what the traders actually drew

38 position tools mined from the Funded Trader Signals frames, evaluated on the same symbol,
same date, same weekly bars. Error expressed in units of THEIR risk:

```
proximal / body-top of base  (SHIPPED)   median 0.89R    >1R off: 18/38
base OPEN extreme                        median 0.84R    >1R off: 17/38
base HIGH/LOW extreme                    median 0.57R    >1R off: 17/38
ZONE MIDPOINT                            median 0.31R    >1R off: 11/38
```

It corrects a second defect at the same time. The stop stays at the distal, so moving the
entry to the midpoint halves the risk distance:

```
THEIR risk (entry->stop)     median  3.87% of price
OURS, entry at EDGE          median 11.37%   = 2.71x theirs
OURS, entry at MIDPOINT      median  6.03%   = 1.38x theirs
```

Risking 2.71x what they risk on the same setup distorts position sizing and pushes the entry
far enough from price that the E-05 distance cap (measured in R) cancels the order.

### Now wired

Resolution order: explicit argument > `BP_MIDPOINT_ENTRY` env > `entry.prefer_midpoint_entry`
in `BP_config.yaml` > False. **Default stays false.**

### The A/B, and why it settles nothing

510 cases, paired, pinned:

```
EDGE (shipped)   5 signals    1 decided   0/1 win   -1.00R
MIDPOINT        11 signals    9 decided   1/9 win   -0.67R
Stage-1 direction: 0 of 510 changed  (correct -- entry price cannot move the bias)
```

Expectancy improves but stays negative. **It cannot be believed, because the 11 signals are
only 4 DISTINCT trades** -- see C-105. Eight of the nine decided trades are one BABA setup
re-emitted on eight dates, so -0.67R is essentially one losing trade counted eight times.

**Default stays false**: not because midpoint is disproven, but because an n=4 A/B cannot
disprove or confirm it. The entry-error result (n=38, measured against ground truth rather
than against outcomes) is an order of magnitude stronger evidence and points the other way.

Re-run this once the frame corpus has grown the setup sample past ~60.

---

## C-105 — the engine re-emits the SAME trade across consecutive scans, inflating every signal count in this project.

Found while reading the C-104 A/B output:

```
DISTINCT (symbol, entry) among the 11 midpoint signals: 4
   BABA      89.16   x8     <- one zone, identical entry AND stop, on 8 separate dates
   META     205.97   x1
   PFE       35.945  x1
   EURUSD=X   1.1124 x1
```

`BABA` produces byte-identical entry 89.16 / stop 86.01 on 2023-04-16, 04-18, 05-09, 05-13,
05-20, 05-23, 06-03 and 06-06. It is one setup, re-signalled every scan while the zone stays
unconsumed.

`BP_paper_trader.submit_signal` DOES guard against this -- `zone_memory` plus a duplicate
check on (zone_id, symbol+direction+entry within 1bp). But `run_goldtest.py` evaluates each
case in isolation with a fresh engine and no trader state, so nothing dedupes.

**Consequence: every Stage-2 signal count reported in this project is an upper bound, not a
trade count.** "8 firings in 479 cases" and "5 after C-88" are counts of signal EMISSIONS.
The number of distinct trades is lower and has never been measured.

This does not change the direction of any earlier finding -- 5 emissions was already
desperately few -- but it makes the scarcity worse than recorded, and it means any expectancy
computed from goldtest output must dedupe on (symbol, entry, stop) first or a single trade
dominates the average.

---

## C-106 — THE 6-QUALIFIER ZONE SCORE IS SATURATED. It cannot rank, and that is why zone selection fails.

### Measured across 248 ranked zones, 12 symbols, weekly bars

```
qualifier                distinct values   modal value   % of zones at the mode
level_on_top_score                     1          0.00        100%   <- NEVER FIRES
departure_score                        4         10.00         92%
base_duration_score                    4         10.00         82%
freshness_score                        4          0.00         81%
arrival_score                          4         10.00         70%
profit_margin_score                    4         10.00         61%
originality_score                      3         10.00         45%
```

Five of seven qualifiers hand the same score to 60-100% of zones. `level_on_top_score` is
**0.00 on all 248** -- a seventh qualifier that has never once contributed. The composite
therefore separates the zone the trader picks from the ones he ignores by 7.20 vs 7.10
(separation 0.13 pooled-sd), i.e. not at all.

**A ranking function whose inputs are constant cannot rank.** This is the root cause beneath
C-103: rank-1 is effectively an arbitrary pick from the candidate set, the correct zone sits
4th of 8 on average, and the engine's real entry error is 3.15R (proximal) / 1.93R (midpoint),
not the 0.89R first reported from the NEAREST zone.

### What DOES discriminate

From 20 labelled setups (the chosen zone vs 231 rejected ones in the same scans):

```
feature                CHOSEN med   OTHERS med   separation
retest_count                20.00         7.00         0.72   <- the only strong signal
dist_to_price_pct            5.49        23.77         0.42
composite_score              7.20         7.10         0.13
departure / base_dur / originality / profit_margin / arrival / freshness   0.00
```

He picks **heavily retested** zones near price. Note this runs OPPOSITE to the freshness
qualifier the methodology emphasises -- `freshness_score` is 0 on 81% of zones and does not
separate at all, while retests, which nothing in the ranking uses, is the strongest feature
available.

### Selection rules tested, all measured against 38 drawn setups

```
composite rank-1  [SHIPPED]         median 1.93R   <=0.25R  9/38   >1R 24/38
nearest to price                    median 1.78R   <=0.25R  8/38   >1R 21/38
MOST RETESTED                       median 1.33R   <=0.25R  4/38   >1R 22/38
retests*0.72 - proximity*0.42       median 1.27R   <=0.25R  6/38   >1R 19/38
ORACLE (best zone available)        median 0.31R   <=0.25R 14/38   >1R 11/38
```

**Best implementable rule reaches 1.27R against an oracle of 0.31R.** Median error improves
34% over shipped, and the >1R disasters fall 24 -> 19, but the count of "same trade" (<=0.25R)
gets WORSE, 9 -> 6. It trades precision for fewer catastrophes.

**This is NOT a validated improvement and must not be shipped as one.** The 0.72/0.42 weights
were derived from the same 38 samples they are scored on -- textbook in-sample fitting, the
exact error that produced "74/160" and "zero false positives". It needs an out-of-sample test
on setups the weights were not fitted to.

### The honest state of zone selection

Four approaches tried, all measured: hand rules (1.68R), feature analysis, retest-weighted
ranking (1.27R), oracle (0.31R). **The gap does not close.** A trade needs to be inside about
0.5R to be the same trade; the best rule sits at 1.27R.

The next legitimate step is NOT another ranking heuristic on saturated inputs. It is to fix the
qualifiers so they discriminate at all -- starting with `level_on_top_score`, which is dead
across every zone measured, and `freshness_score`, which is 0 on 81%. Until the inputs vary,
nothing downstream of them can select.

## C-107 — C-106 sampled a diagnostic path; the LOL finding is withdrawn

**Status:** correction, measured
**Tool:** `Propfirm Trading Dashboard/goldtest/zone_qualifier_stats.py` (new, durable)

C-106 reported `level_on_top_score` as 0.00 on 100% of 248 zones and concluded the
qualifier was dead code. That was a sampling artifact and the conclusion is wrong.

`ZoneDetector.rank_zones` is called from three sites. Probing all three across 60
cases and 13,482 zones on the real engine:

| call site | what it ranks | n | LOL mean | LOL sd |
|---|---|---:|---:|---:|
| `BP_rules_engine.py:366` | LTF zones, post-align — **the trading path** | 9,929 | 4.28 | 3.22 |
| `run_goldtest.py:565` | HTF zones, Stage-1 diagnostic fallback | 2,081 | 0.00 | 0.00 |
| `BP_rules_engine.py:1654` | HTF zones | 1,472 | 0.00 | 0.00 |

`align_multi_timeframe` writes LOL onto **LTF** zones using HTF zones as parents. On
any path that ranks HTF zones directly it is 0.00 by construction. C-106's sample came
from those paths, so it measured a tautology and said nothing about live behaviour.
61.8% of zones reaching ranking carry `htf_aligned=True`.

**The real finding is the inverse.** On the trading path LOL is the *least* saturated
qualifier — 26.4% at its modal value — while the four that carry most of the composite
weight are pinned:

    departure_score       72.4% at 10.0
    base_duration_score   77.8% at 10.0
    profit_margin_score   82.4% at 10.0
    arrival_score         80.4% at 10.0
    freshness_score       91.6% at 0.0
    originality_score     37.4% at 5.0
    level_on_top_score    26.4% at 2.0   <- the only one that varies freely

Composite sd is 1.46 on a 0-10 scale. Ranking is near-constant across candidates not
because a qualifier is missing, but because five of seven are effectively constants.

**Consequence for C-106.** Its headline number — composite separating chosen from
unchosen zones by 0.13 pooled-sd — was computed on the same mis-sampled population and
must be re-measured at `BP_rules_engine.py:366` before anything is built on it. Do not
cite the 0.13 figure until that is done.

**Consequence for the fix queue.** "Implement level_on_top" is removed; it is
implemented and working. The open question is whether the four pinned qualifiers can be
made to discriminate, which is a threshold-calibration problem, not a missing-feature one.

## C-108 — Four of seven qualifiers are constants on the zones we actually trade

**Status:** root cause, measured
**Files:** `BP_zone_detector.py` `_score_zone` (Q1 line ~387, Q5 ~458, Q6 ~483), detection gate line 352

C-107 established that five of seven qualifiers are saturated on the trading path. This
is why. It is not threshold calibration -- three of them are constant *by construction*.

**Q1 Departure repeats the detection gate verbatim.** A candle is only accepted as a
leg-out if `body_pct >= 0.70` (line 352). Q1 then scores `10.0` if `body_pct >= 0.70`
(line 387) -- the same test on the same quantity. Q1 carries **weight 0.30, the largest
of the seven**, so roughly 3.0 of a ~6.9 composite is a fixed offset.

CORRECTION to the first draft of this finding, from the branch histogram: the lower
branches are NOT unreachable. Measured across 9,559 zones they fire on 23% of them --

    departure_score branches ->  10.0: 77%   7.0: 5%   5.0: 4%   0.0: 14%

They fire because the gate is evaluated on the leg-out START candle while scoring reads
`df.iloc[zone['leg_out_end']]`, which on a multi-candle leg is a DIFFERENT candle. So
Q1's variance is real but it is an artifact of the candle mismatch, not a measurement of
departure quality -- the AAPL sample shows zones scoring a full 10.0 at a departure
strength of 1.278 and 1.224, both below the 2.0 multiple detection required. A qualifier
whose only variation comes from reading the wrong bar is worse than a constant one.

**Q5 Profit Margin and Q6 Arrival are hardcoded to 10.0 on trend-aligned zones**
(`if with_trend is True: profit_score = 10.0` / `arrival_score = 10.0`). The
methodology says to skip these qualifiers on trend trades, and skipping the GATE is
correct -- but the code also destroys the MEASUREMENT, which is a different thing.
"Do not reject a zone for this" is not "every zone scores full marks on this."

**Q3 Freshness is 0 on 91.6%,** which is not a bug: most zones in a long history have
been retested. But it means it contributes nothing to ordering either.

**Net effect.** On a trend-aligned zone -- the majority -- Q1, Q5, Q6 are pinned at 10
and Q3 at 0. Ranking reduces to originality (3 distinct values) + LOL + a rare freshness
bump. Composite sd is 1.46 on a 0-10 scale, and candidates tie constantly. That is the
mechanism behind the entry-selection failure in C-101: the engine is not choosing the
wrong zone by a bad rule, it is very nearly not choosing at all.

**What was changed here.** Nothing behavioural. `_score_zone` now also emits
`departure_strength` (leg-out body as a multiple of `avg_body_20` -- detection only
lower-bounds this at `leg_out_body_multiplier`, so it stays informative *above* the
gate) and `bars_to_return` (Q6's raw input before the override). `margin_ratio` and
`with_trend` were already persisted. Nothing consumes these fields, so the admissible
zone set and the ordering are byte-identical.

**Deliberately not done yet.** Rescaling Q1/Q5/Q6 in the engine would lower composites
and push zones under the `min_score=4.0` cut, changing which zones QUALIFY and not just
how they are ORDERED -- confounding a ranking experiment with an admission experiment.
The ordering question is being settled offline first, against the drawn setups, and only
a rule that demonstrably ranks their zone higher will be built as a flag and A/B'd.

## C-109 — Q5 Profit Margin measures zone age, not profit margin

**Status:** defect, measured
**File:** `BP_zone_detector.py` `_score_zone`, Q5 block (lines ~449-456)

    max_move = df.iloc[zone['leg_out_end']:]['high'].max()     # demand
    margin_distance = max_move - proximal
    margin_ratio = margin_distance / max(zone_height, 0.0001)

The slice runs from zone formation to **the end of the loaded dataframe**, so
`margin_distance` is the largest excursion price has made since the zone formed, across
however much history was loaded. An older zone mechanically accumulates a larger
maximum. The ratio is therefore a proxy for zone age and lookback length.

Measured on AAPL 1d (219 zones), the first eight `margin_ratio` values are

    874.02  181.27  479.42  241.80  589.79  384.63  221.01  749.41

against a Q5 threshold of `>= 5` for full marks.

The branch histogram over 9,559 zones shows the lower branches DO fire --

    profit_margin_score branches ->  10.0: 79%   7.0: 7%   5.0: 3%   0.0: 11%

-- and that turns out to be the more damaging fact, not a softening of the finding.
`margin_distance` grows with the amount of history after the zone, so a LARGE ratio
means an OLD zone and a small one means a RECENTLY FORMED zone. The 11% scoring 0 are
therefore the youngest zones in the pool. Those are exactly the zones sitting nearest
current price -- the ones a trader would actually be filled at. **Q5 as written
systematically penalises fresh, nearby zones and rewards ancient ones**, which is the
opposite of what the qualifier is for, and it points the same direction as the
observed failure: rank-1 is repeatedly a zone from years before the call date.

Not a lookahead bug -- the frame is truncated at the call date in both live scanning
and the goldtest harness, so no future data leaks. But `margin_ratio` changes when the
lookback changes, which makes it a determinism hazard across timeframes and snapshot
lengths.

The methodology's profit margin is room from the zone to the opposing structure -- the
next opposing zone, or the target -- assessed at trade time and bounded. Maximum of all
subsequent history is not that quantity.

**Consequence.** Of the three C-108 repairs, only the Q1 one has a usable measurement
behind it. `departure_strength` shows real spread (1.22-2.81 on the AAPL sample where
`departure_score` was a flat 10.0). Q5 needs a bounded horizon defined before it can be
scored at all, and Q6 `bars_to_return` is 1 for a large share of zones, so its 10.0
branch is near-universal too. Do not expect the "real Q5/Q6" arm in `rank_rules.py` to
improve anything; it is included to demonstrate this, not because it is promising.

## C-110 — Ranking has no term for where price is, and picks zones price left years ago

**Status:** root cause, measured; fix implemented behind `BP_ZONE_REACHABLE`, default OFF
**Tools:** `goldtest/zone_choice_separation.py`, `goldtest/rank_rules.py`, `gemini/build_setups.py` (all new)

C-107/C-108/C-109 established that the qualifiers barely discriminate. Repairing them
does not help, and measuring why exposed a larger defect they were masking.

`rank_zones` sorts `valid` -- every same-type zone in the loaded history -- by composite
alone. Composite contains no term for the current price or for when the zone formed. So
a high-scoring zone from 2015 outranks a mediocre one price is sitting on today.

**Measured over 65 drawn setups** (their own position tools, read from the frames,
symbol- and scale-validated; `--strategy weekly`, median 93 same-type candidates each):

    engine rank-1 zone      median 6.29R from their drawn entry
    best candidate in pool  median 0.11R
    rank-1 IS their zone    0 of 65   (0%)
    their zone's rank       median 60 of 93 candidates
    rank-1 zone age         median 904 bars      their zone: 467 bars

Their zone is in the pool nearly every time, 0.11R away. We rank it 60th.

**Ordering rules compared** (fit-free, no coefficients estimated on this sample; full
table in `rank_rules.py` output, split first-half/second-half):

    rule                        hit@1   median entry error
    current composite              0%          4.74R
    null: pseudo-random            0%          5.91R
    control: nearest to price     20%          2.64R
    reachable 10% + composite     11%          2.02R

The seven-qualifier composite does not beat a pseudo-random ordering of the same pool.
Ranking reachable zones first cuts the median error from 4.74R to 2.02R, and the effect
held at **every** band tried (2/5/10/20%) and on **both** halves -- twelve of twelve
cells improved -- so it comes from the filter, not from a tuned width.

**Confound, stated plainly.** Their drawn entries are limit orders near price, so a
proximity rule is partly tautological with the label and the 20% hit@1 is flattered by
it. The practical point survives -- a zone price cannot reach cannot fill -- but do not
read hit@1 as a clean skill measure.

**What did NOT work,** measured on the same pools, all discarded:
  - Q1 scored on `departure_strength` instead of the flat 10: **worse**, +0.47R
  - Q5/Q6 scored on their real measurements instead of the `with_trend` override:
    **identical**, +0.00R -- exactly as C-109 predicted
  - dropping Q5 entirely: -0.98R overall but -1.12R / +0.00R across halves, i.e. noise
  - fewest retests (the earlier C-106 candidate): **worse**, +3.36R
  - LOL alone: **worse**, +2.59R

**Implementation.** `rank_zones` gained an optional `current_price`; with
`BP_ZONE_REACHABLE` set it sorts on `(reachable, composite)` instead of `composite`.
Reachability is an ORDERING, never a rejection -- an unreachable zone still ranks, below
every reachable one -- so the admissible set is unchanged and the flag cannot empty the
candidate list on a symbol where nothing is close. Verified: flag OFF with a price passed
produces a byte-identical order; flag ON reorders the same set. Band defaults to 0.10,
overridable by setting the variable to a float.

**Not yet established:** whether this improves the 510-case corpus or expectancy. A
2.02R median entry error is much better than 4.74R and still far too large to trade.
This is a real defect fixed, not a solved problem.

## C-111 — The driftless 33.3% null understated the bar all session; against a drift-matched null nothing here is significant

**Status:** methodological correction, measured
**File:** `goldtest/expectancy.py` -- `drift_null()` and `--drift-null N` added

`expectancy.py` compared every signal population against P(+2R before -1R) = 1/3, which
is EXACT -- on a driftless series. The samples it was applied to are not driftless. The
C-110 reachability arm is **33 of 34 signals long and 28 of 34 dated 2023**, a strongly
rising year. "Long these instruments at a random date" is not a 33.3% proposition.

Measured directly: same symbols, same directions, same R fractions, 40 random entry
dates each, identical mechanical rule (n=1355 resolved trades):

    drift-matched null      41.0% win   +0.23R
    driftless theory null   33.3% win   +0.00R      <- what was quoted all session

The real bar is 7.7 points higher than the one used. Re-testing the C-110 arm against it:

    at the zone entry   5/22  = 22.7%   -0.32R   one-sided p=0.061   not significant
    at market          16/30  = 53.3%   +0.60R   one-sided p=0.117   not significant
                                                 95% CI 35%-71%, contains the null

**Neither arm demonstrably beats a drift-matched random baseline.** The zone entry looks
harmful and the direction looks helpful, and at n=22 and n=30 the sample supports
neither claim. The earlier reading of the same numbers -- "+0.60R at market proves the
direction has value" -- was drift, and is withdrawn.

**A consequence worth stating plainly.** Their published KPI slide is 40.0% win / +0.20R
at 2R. The drift-matched null on this symbol set and era is 41.0% / +0.23R. On this
sample those are indistinguishable. That is NOT a claim about their actual trading --
different instruments, different era, discretionary sizing and management, and a slide
is not a track record. It does mean the published KPI cannot be used as evidence of edge
over "long these markets in 2023", and it should not be cited as a target the system has
reached.

**Standing rule from here.** Any expectancy claim on a directionally lopsided sample must
quote `--drift-null`. The 1/(1+rr) null stays valid only for direction-balanced samples,
and the tool now says so where it prints.

**Re-examine under this null:** C-101's +0.56R for their drawn setups was computed with
the driftless null in view. Its direction split has not yet been checked. Until it is,
treat the "+0.56R at their entry vs -0.33R at market" spread as unverified.

## C-101 AMENDED — the entry-price effect is real in direction, not established in strength

Re-measured under C-111's drift-matched null, on the corrected 65-setup ground truth
(`gemini/build_setups.py`, which fixed the inverted-contract price bug that had five
USDJPY setups on the reciprocal scale). This sample is direction-balanced -- 38 long /
27 short, 38 in 2023 and 27 in 2024 -- so it does not carry the lopsidedness that
invalidated the C-110 arm's control.

    at their drawn entry   14/30 = 46.7%   +0.40R
    same calls at market   10/41 = 24.4%   -0.27R
    drift-matched null     957/2572 = 37.2%   +0.12R

Against the null: their entry is NOT significant (p~0.14); their calls taken at market
are significantly WORSE than the null (p~0.045).

The claim C-101 actually makes is paired -- same symbol, same date, same direction, only
the entry price differs -- so the paired test is the right one. On the 26 setups decided
both ways:

    agree                          19
    entry wins where market loses   6
    market wins where entry loses   1
    McNemar exact two-sided         p = 0.125   NOT significant

**Restated headline.** The original "+0.56R at their entry vs -0.33R at market" becomes
**+0.40R vs -0.27R, discordant 6:1 in the entry's favour, p=0.125.** The effect points
the same way under every accounting tried and is not established at this sample size.
Seven discordant pairs cannot reach significance at 6:1 (7:0 would give p=0.016).

**This is a power problem, not a dead end,** and the fix is already running: the Signals
corpus is at 2162/2509 frames with 347 unread, currently blocked on the free-tier daily
quota and resuming on its own backoff. Every new drawn setup adds a paired observation.
Re-run `gemini/build_setups.py` then this test when the corpus completes.

Note 18 of 65 setups resolve to "no data" -- no pinned daily series for that symbol.
Pinning those would add ~28% more paired observations for no new frame reading at all,
and is the cheapest available power increase.

## C-101 AMENDED AGAIN — with the missing 18 setups recovered, the effect shrinks

`goldtest/extend_pins.py` (new) fetched forward history for the four symbols whose pins
ended before their March-2024 call dates (NZDUSD, USDJPY, USDCAD, ZC), into a quarantined
`ohlcv_extended/` that `expectancy.py --pin-dir` searches ahead of the reproducible
snapshot. All 65 setups now resolve; "no data" is 0.

Adding those 18 setups made the result WORSE, not better:

                            before (47 usable)      after (65 usable)
    at their drawn entry    46.7%   +0.40R          39.5%   +0.18R
    same calls at market    24.4%   -0.27R          25.4%   -0.24R
    drift-matched null      37.2%   +0.12R          36.5%   +0.09R

    paired discordant       6:1  p=0.125            7:2  p=0.180

Their entry now sits 3.0 points above a drift-matched null instead of 9.5. The paired
comparison stays lopsided in the entry's favour and stays insignificant.

**Status of C-101: NOT ESTABLISHED.** Every cut points the same direction -- entering at
a drawn zone beats entering at market on the same call -- and the magnitude has fallen
each time the sample grew or a measurement error was fixed (+0.56R -> +0.40R -> +0.18R).
A finding that shrinks as data improves is usually a finding that was mostly noise.

It should not be used to justify a configuration change, and it must not be cited as
evidence the system has an edge. The remaining 347 unread Signals frames are the only
clean way to settle it; the supervisor is on them and blocked on daily quota.

**Process note.** The three numbers above moved because of, in order: a stale setups
file (13 of 54 setups), an inverted-contract price bug (5 setups on the reciprocal
scale), and 18 setups silently dropped as "no data". Each was found only by looking at
the per-case detail rather than the summary. The summary looked reasonable every time.

## C-112 — Entry depth explains nothing; the zone does. Controlled sweep.

**Status:** measured; one hypothesis refuted, one quantified
**Tool:** `goldtest/entry_depth.py` (new)

Three arms had lined up monotonically against their own drift-matched nulls -- proximal
-18.3 points, midpoint -8.3, market +4.3 to +12.3 -- which looked like adverse selection
on entry depth. It is not. Those were three goldtest runs over three DIFFERENT signal
populations (34 vs 28 distinct trades), so the comparison confounded depth with which
trades each arm emitted.

Re-run properly: ONE signal set, entries re-priced across a depth sweep, symbol, date,
direction and STOP held fixed. Same trades throughout, so any trend is the depth itself.

**Our zones** (C-110 reachability arm, n=34):

    depth   win%    perTrade   null%   vs null
    0.00    22.7%   -0.32R     42.3%   -19.6
    0.25    27.3%   -0.18R     40.6%   -13.4
    0.50    23.8%   -0.29R     39.6%   -15.8
    0.75     5.6%   -0.83R     34.2%   -28.7

Flat from 0 to 0.5, collapsing at 0.75. **No depth beats the null.** The midpoint arm's
better headline (-0.05R vs -0.32R) was therefore NOT caused by the midpoint -- it came
from emitting a smaller, different set of trades. Withdraw any reading of it as an
entry-placement effect.

**Their drawn zones, same sweep, same tool** (n=65, direction-balanced):

    depth   win%    perTrade   null%   vs null
    0.00    39.5%   +0.18R     35.1%    +4.4
    0.25    34.2%   +0.03R     34.5%    -0.3
    0.50    27.0%   -0.19R     33.6%    -6.6
    0.75    27.8%   -0.17R     30.3%    -2.5

Their entries are BEST at depth 0 and degrade with depth -- what you would expect if the
drawn level is chosen deliberately rather than being an arbitrary point in a band.

**The comparison that matters.** At the same depth, on the same metric, against each
sample's own null: **their zones +4.4 points, our zones -19.6 points.** A ~24-point gap
that is entirely about WHICH ZONE is selected, not where in it the order sits. Two-
proportion test z=1.33, p=0.18 -- consistent in direction, underpowered, like everything
else at these sample sizes.

**Consequence for the fix queue.** Entry-placement work is finished: midpoint entry,
depth tuning and C-104 are all measured and none of them is the lever. The lever is zone
SELECTION, where C-110 established the engine ranks its candidate pool no better than
pseudo-random and reachability recovers only part of it (4.74R -> 2.02R median error,
still far too coarse to trade).

## C-110 ADDENDUM — what reachability can and cannot buy, and the qualifiers' final verdict

Two follow-up measurements on the same 65-setup pools, both bounding the C-110 fix.

**1. The qualifiers add nothing once the pool is sane.** Composite vs a deterministic
pseudo-random pick, WITHIN the reachable subset only:

    band   reachable pool   composite            pseudo-random
     5%     8 zones         8% hit  2.66R err    5% hit  2.56R err
    10%    16 zones        11% hit  2.02R err    9% hit  2.57R err
    20%    30 zones         5% hit  2.19R err    5% hit  3.09R err

At a tight band the composite is WORSE than random on error. Its advantage at wider
bands is largely that it correlates weakly with proximity -- the quantity already being
filtered on. Combined with C-110's finding that composite loses to pseudo-random over the
full pool, the verdict on the seven-qualifier machinery as a SELECTOR is that it does not
work, at any pool width. It may still be doing its documented job of rejecting malformed
zones; it is not choosing between well-formed ones.

**2. Reachability has a hard recall ceiling.** How often the zone they drew is inside the
band at all:

    within  5% of price   24/65 = 37%
    within 10% of price   35/65 = 54%
    within 20% of price   55/65 = 85%
    within 50% of price   64/65 = 98%

    their zone's distance from price:  median 8.3%,  p75 14.1%,  max 168%
    their drawn ENTRY from price:      median 6.7%,  p75 14.6%

**A 10% band excludes the right answer 46% of the time**, capping hit@1 at 54% no matter
how good the ranking inside it becomes. This is why both rules above score BELOW the
~12.5% you would expect by chance among 8 candidates: often neither can hit, because the
target is not in the set.

The 10% default still wins the measured comparison (2.02R vs 2.19R, 11% vs 5% hit) since
unreachable zones are ordered last rather than dropped, so wide-band recall does not
convert into accuracy. But the ceiling is real and should be quoted whenever this flag is
discussed. It also says something about the method: they place orders a median 6.7% away
from spot, so "near price" is not the same as "at price", and any future filter built on
distance must respect that.

## C-113 — The Stage-1 components carry no out-of-sample signal. Rule tuning cannot work.

**Status:** measured, decisive
**Tools:** `goldtest/bias_ceiling.py`, `goldtest/bias_features.json` (new)

Twenty phases of `_bias_consensus` tuning produced a 74/160 score that turned out to be
memorisation. Nobody had asked the prior question: how much information do the seven
components actually carry? Measured now, three ways, all pointing the same direction.

**1. Marginals.** Each component's IN-SAMPLE upper bound (majority label per value):

    valuation 53.3%   location 52.5%   trend 51.6%   seasonality 51.6%
    cot 51.0%   cot_strength 50.4%   constituent 50.4%

against an always-long baseline of **50.39%**. `cot_strength` and `constituent` score
exactly the baseline: zero information. The engine's live 52.75% sits inside this range.

**2. The overfitting ceiling.** A lookup table memorising the best answer for every
distinct combination of all seven components:

    1 feature   53.3%      5 features  68.6%
    2 features  56.1%      6 features  70.6%
    3 features  58.2%      7 features  71.4%   <- 158 cells, 70 seen exactly once
    4 features  64.9%

**71.4% is the hard ceiling for ANY rule over these features**, and ~14% of it is single-
case cells, i.e. pure memorisation. **80% is unreachable by rule tuning. Not difficult --
arithmetically unavailable.**

**3. Out-of-sample.** Forward splits by date (train past, test future; a random split
leaks, because the corpus holds the same symbol days apart with near-identical
components):

    in-sample ceiling      71.37%
    mean out-of-sample     48.71%      <- BELOW the 50.39% always-long baseline
    memorisation gap       22.67 points

An exhaustive search of all 127 feature subsets found the best out-of-sample result to be
**+0.00 points** over the per-fold majority baseline -- achieved by degenerating to
predicting the majority class. Every other subset was negative, to -11.5.

A naive-Bayes additive vote -- the engine's OWN model class -- scores **-8.47 points**
versus baseline out-of-sample.

**Conclusion.** No rule over location / trend / cot / cot_strength / valuation /
seasonality / constituent can beat a constant out of sample, because those inputs contain
no generalisable information about the label. Every past and future attempt to raise
Stage-1 accuracy by adjusting consensus logic is fitting noise. This retroactively
explains the whole tuning history, the 74/160, and today's 52.75%.

**The bottleneck is the FEATURES, not the rules.** The most conspicuous gap: Stage-1 bias
is computed with no knowledge of zones, because zones are Stage 2 -- yet their calls are
routinely justified by zone context ("nice new demand sitting here"). The thing the label
most depends on is absent from the vector used to predict it. `goldtest/zone_features.py`
(new) adds zone-derived features -- reachable-zone counts, distance to nearest demand and
supply, best composite among reachable, inside-zone, HTF alignment -- computed strictly
from data up to the call date, and re-runs this identical ceiling test on them.

**Standing rule.** Before tuning any rule layer, run `bias_ceiling.py` on its inputs. If
the out-of-sample number does not beat the baseline, the rule layer cannot be fixed and
the work belongs in the features.

## C-114 — Nothing available at the call date predicts the label. The 80% target is degenerate either way.

**Status:** measured, decisive
**Tools:** `goldtest/bias_ceiling.py`, `price_features.json`, `zone_features.py` (new)

C-113 showed the seven bias components carry no out-of-sample signal. The obvious reply
is "then build better features". This tests that reply directly, on three independent
feature families, with the same forward-by-date validation.

**Every feature family fails, and combining them fails hardest:**

    feature set              in-sample   out-of-sample   vs baseline
    symbol identity alone       61.6%        52.00%        -1.65
    market state (returns,
      52w range position, vol)  68.4%        48.24%        -5.41
    engine indicators           68.6%        49.65%        -4.00
    symbol + market state       74.7%        49.88%        -3.76
    symbol + indicators         72.4%        48.00%        -5.65
    ALL ELEVEN FEATURES         96.1%        50.59%        -3.06

**96.1% in-sample against 50.59% out-of-sample** is the signature of fitting noise: with
enough features the corpus can be memorised almost perfectly while learning nothing. Not
one feature set beats the per-fold majority baseline of 53.65%.

Standard price features (5/20/60-bar returns, position in the 52-week range, realised
vol) were included precisely so this could not be blamed on the project's own indicators.
They score 49.18% out-of-sample with a 26.7-point memorisation gap. The label is not a
function of market state at the call date.

**On directional cases only** -- dropping `neutral`, which is 41% of the corpus and
carries the content-selection noise -- the picture becomes degenerate in the other
direction:

    300 directional cases, 257 long / 43 short
    always-long baseline                       85.67%
    best feature subset out-of-sample          +0.80 points  (inside noise)
    SHORT RECALL, every feature set            0% - 12%

**So the answer to "can we reach 80%" depends entirely on which metric is meant, and
both readings are degenerate:**

  - On the full 510-case metric including neutral, **80% is arithmetically unreachable**.
    Total memorisation of every component combination caps at 71.4%, and honest
    validation puts every model at or below a constant.
  - On directional cases only, **85.7% is already available today by answering "long"
    every time** -- above the 80% target, with 0% short recall and zero information.

**Why.** The label encodes three things: a genuine market read, a discretionary judgment
about whether a setup is worth trading, and which symbols he chose to cover that day.
The last two are not market variables. C-112 showed the same corpus contains explicit
directional statements labelled `neutral` (PFE: "we're gonna go lower lower ... I don't
think anybody's desperate to trade Pfizer"), so a correct market read is scored wrong there.

**What this closes.** Stage-1 accuracy work is finished. Not "hard" -- finished. Any
future change that reports a Stage-1 improvement on this corpus is reporting noise or
in-sample fit unless it clears `bias_ceiling.py` out-of-sample first, which nothing has.

## C-114 COMPLETED — zone features tested; 575 subsets searched; nothing beats a constant

The zone-feature family from `goldtest/zone_features.py` is now measured, completing the
test C-114 left running. It was the most plausible remaining family: their calls are
routinely justified by zone context, and Stage-1 bias is computed without any knowledge
of zones. It is the WORST performer of the three.

    feature family        in-sample ceiling   out-of-sample   vs baseline
    zone-derived                62.4%            44.24%         -9.41
    market state                68.4%            48.24%         -5.41
    engine indicators           68.6%            49.65%         -4.00
    ALL 15 FEATURES             96.5%            50.12%         -3.53

**Exhaustive search over 575 subsets spanning all three families: the best result
anywhere is -0.47 points versus the 53.65% per-fold majority baseline.** Nothing beats a
constant. Not one subset.

**Why the zone features fail is itself informative.** They are near-constants, for the
same reason C-108's qualifiers were:

    dist_dem = "at" (within 2% of a demand zone)   444/510 = 87%
    inside_zone = yes                              472/510 = 93%
    htf_aligned = "most"                           507/510 = 99%

With a median 93 candidate zones per case (C-110), price is ALWAYS sitting on a demand
zone, so "is there a zone here" cannot discriminate anything. The zone detector emits so
many zones that zone presence carries no information. This is the same defect as C-108
appearing in a second place: the system's own outputs are saturated, and saturated inputs
cannot support any decision downstream of them.

**STAGE-1 ACCURACY IS CLOSED.** Three independent feature families, two model classes
(lookup table and naive-Bayes additive vote, the engine's own architecture), forward-by-
date validation, 575 subsets. Every result is at or below a constant. Combined with
C-113, the conclusion is not "we have not found the right rule yet" -- it is that no rule
over any information available at the call date predicts this label out of sample.

Do not spend further effort raising the 52.75%. Any reported improvement is noise or
in-sample fit; require `bias_ceiling.py` out-of-sample evidence before believing otherwise.

## C-115 — A drawn zone is not a trade. The two must never be pooled.

**Status:** measured
**Tool:** `gemini/build_setups.py` (`zone_rows`), `goldtest/expectancy.py`

The C-101 paired test has been stuck at 7:2 discordant, p=0.18 -- underpowered, waiting on
347 unread frames behind a daily quota wall. But the frame reads already held far more
evidence than was being used: 83 frames carry a position tool with a readable entry and
stop, while **265 more carry a readable zone proximal and distal with no position tool**.
In this methodology those edges ARE the trade -- entry at proximal, stop at distal, which
is exactly what `BP_rules_engine` does with its own zones -- so they looked like a free
2.8x increase in sample.

They are not the same population. Measured separately, same tool, same nulls:

    class            n     at their entry        drift-matched null    delta
    position_tool    65    39.5%   +0.18R        34.6%   +0.04R        +4.9 pts
    zone_edges      119    16.1%   -0.52R        34.3%   +0.03R       -18.2 pts

**Zones they merely drew perform 18 points BELOW random.** Only the ones they committed a
position tool to beat the null. Pooling the two -- the obvious move to raise sample size,
and the one that was one line away from happening -- would have dragged the combined
result far below the null and produced a confident false negative on C-101.

**Interpretation.** They draw many zones while talking through a chart and trade very few
of them. A drawn zone is a level worth marking; it is not a decision. The distinction is
the entire content of their skill, and it is invisible in the geometry -- both classes are
just a proximal and a distal on a chart.

**Consequence for C-110.** `zone_choice_separation.py` reads `drawn_setups.json`, which
now contains both classes, so it silently began aiming at the wrong target. It now filters
on `--source position_tool` by default. The C-110 numbers already recorded were taken when
that file held position-tool rows only and are unaffected.

**Consequence for the engine.** This is the clearest statement yet of what Stage-2 is
missing. The engine treats every detected zone as tradeable and emits a median 93
candidates per case. They also see many zones -- and reject nearly all of them. Neither
our qualifiers (C-108, composite loses to pseudo-random) nor zone geometry (C-114, zone
features are the worst-performing family) captures whatever separates the 65 from the 119.

**Standing rule.** Never pool `position_tool` and `zone_edges`. When a sample-size problem
tempts a merge, measure the classes separately first -- here the merge would have inverted
the finding.

## C-116 — A 6,094-frame corpus was invisible: frame discovery only looked one directory deep

**Status:** defect, fixed
**Files:** `gemini/read_practical_trades.py` (`session_dirs`, `session_frames`),
`gemini/supervise_frames.py` (`corpus_total`)

Both the reader and the supervisor enumerated frames as

    for d in root.iterdir():
        if d.is_dir():
            n += len(list(d.glob("frame_*.jpg")))

-- exactly one directory below the corpus root. Signals and Practical are shaped that
way, so it worked and nobody looked further. **Funded Trader Weekly Outlook nests a year
level** (`root/2023/<session>/frame_*.jpg`), so it returned zero, and every progress
readout in this project has reported that corpus as "0/0 frames" while it held 6,094.

Full inventory of `D:/Trading/Output` after the fix:

    corpus       frames    read   setups   REMAINING
    practical      2122    2122       29           0
    signals        2509    2162       54         347
    weekly         6094       0        0        6094   <- reported as 0/0 all along
    hybrid         7316       0        0        7316   <- never wired up
    otc            2023       0        0        2023   <- never wired up
    TOTAL         20064                            15780

**15,780 unread frames, 3.4x everything read so far.** `weekly` is the same genre as
`signals` -- live weekly calls with drawn charts -- so it is the largest available source
of the drawn setups that C-101 and the traded-vs-passed test are starved for.

**A trap in the fix.** Naively switching to `rglob("frame_*.jpg")` is WRONG. The Signals
and Practical session folders contain `_python_vision_output/` holding
`frame_000001_overlay.jpg` -- ANNOTATED copies produced by earlier tooling, which match
that glob. A deep glob would have fed the vision model its own previous overlays and
counted them as new evidence. Discovery now skips any path with a `_`-prefixed component
and any file whose stem ends `_overlay`.

Folder identity is still the LEAF directory name, so the 4,284 frames already read keep
matching `already_done()` and are not re-read.

`hybrid` and `otc` are course material and are registered with the same caveat as
`practical`: worked examples demonstrate both sides of a trade on one instrument, so they
are evidence about HOW setups are drawn and must never enter an expectancy population
(C-115).

## C-117 — C-101 CONFIRMED on the signals corpus alone, p=0.0156. It was being diluted by course material.

**Status:** measured, first significant result in the project. Fragile; see robustness.

C-101 has been stuck at "consistent direction, never significant" through three
re-measurements. The reason was a pooling error of exactly the kind C-115 warned about.

`drawn_setups.json` pooled every position-tool setup regardless of which corpus it came
from. Measured separately, the three corpora are not the same population -- two of them
run in OPPOSITE directions:

    corpus      n    at their entry      drift null    delta      at market
    signals    30    50.0%  +0.50R       36.9%         +13.1 pts  22.0%  -0.34R
    weekly     13    23.1%  -0.31R       35.2%         -12.1 pts  61.1%  +0.83R
    practical   8     0.0%  -1.00R       33.7%         -33.7 pts  33.3%  +0.00R

Pooling live trade signals with course worked examples dragged the signals effect from
+0.50R to +0.18R and buried it.

**Excluding `practical` is not post-hoc subsetting.** `read_practical_trades.py`
CORPUS_CHOICES has documented it since it was written: "Teaching sessions... NOT for
expectancy: they demonstrate both a long and a short on the same instrument on the same
day, because they are worked examples, not calls." Pooling it was the error; removing it
restores the pre-registered design.

**`weekly` is a third class, discovered by checking before pooling.** A Weekly Outlook
position tool is a trade being ANTICIPATED; a Signals position tool is one being ISSUED.
Their entries measure 12 points BELOW null while the same calls at market measure +0.83R
-- the inverse of signals. C-115 one level up. Never merge weekly into signals.

**The paired test on signals alone** (same symbol, date, direction and R; only the entry
price differs -- 26 setups decided both ways):

    entry wins / market loses    7
    market wins / entry loses    0
    McNemar exact two-sided      p = 0.0156   SIGNIFICANT

**What this does and does not establish.**
  - ESTABLISHED: holding the call fixed, entering at their drawn entry beats taking the
    same call at market. That is C-101's actual claim.
  - NOT ESTABLISHED: that following their signals beats a random baseline. Against the
    drift-matched null the same 15/30 is z=1.49, one-sided **p=0.068**. Not significant.

**Robustness -- read before citing this.** The 7 discordant pairs span 5 symbols and 7
dates, 4 shorts and 3 longs, so it is not a long-drift artefact. But NG=F supplies 3 of
the 7, all longs. Drop NG=F and it is 4:0, **p=0.125, not significant**. The result rests
on three NG=F trades and must be re-tested as the corpus grows -- 347 signals frames are
still unread, and every new signals setup is another paired observation.

Treat this as the first real lead, not a settled finding.

## C-118 — The reader DROPPED deprioritised folders instead of deferring them, so a corpus could never finish

**Status:** defect, fixed
**Files:** `gemini/read_practical_trades.py` (`--include-unranked`),
`gemini/supervise_frames.py` (`eligible_zero`)

`folder_rank` returns 10_000 for a Signals folder with no recorded decision, and
`targets()` did `continue` on it. That is a DROP, not a deprioritisation. Consequence:

    frames counted by corpus_total   2509
    frames the reader would admit    2094
    frames actually read             2162

The reader ran out of admissible work at 2,094 while the supervisor was measuring against
2,509, so it reported "347 remaining" forever and slept on 40/80/120-minute backoffs
diagnosing a **quota wall that did not exist**. Four supervisor cycles and roughly five
hours were spent sleeping on a corpus with nothing it was permitted to touch, while the
weekly corpus was reading normally on the same KeyPool -- which is what exposed it: two
corpora sharing one quota cannot be quota-blocked and healthy at the same time.

This also blocked C-117 directly. That finding rests on 7 discordant pairs, 3 of them
NG=F, and needs more signals setups to survive. The ~415 unread frames that would supply
them were sitting in folders the reader refused to look at.

**Fixed two ways.** `--include-unranked` reads those folders LAST rather than never, so a
corpus can reach 100%. And the supervisor now runs a dry-run eligibility probe before
concluding "quota wall": if the reader admits zero frames it stops and says so, instead
of sleeping indefinitely.

**General lesson.** Two different denominators for "how much is left" -- one counting
files on disk, one counting what the tool will actually process -- guarantee a phantom
remainder. Any progress readout must count what the CONSUMER admits, not what the
directory holds.

## C-117 UPDATED — survives the full signals corpus at p=0.039, still fails the NG=F check

Signals corpus completed after the C-118 fix: 2,508/2,509 frames, position-tool setups
54 -> 87 (73 with resolvable dates). Paired sample 26 -> 35.

                        26 paired (partial)     35 paired (complete)
    entry wins/mkt loses         7                      8
    mkt wins/entry loses         0                      1
    McNemar two-sided       p = 0.0156             p = 0.0391
    per trade at entry        +0.50R                 +0.28R
    win rate                50.0% (15/30)          42.6% (20/47)
    drift-matched null      36.9%                  34.2%

**Survived a 35% sample increase and stayed significant** -- the first finding in this
project to do so. Discordant pairs span 5 symbols, 5 short / 4 long, so not a drift
artefact.

**Three limits, all still binding:**
  1. It WEAKENED with more data (p 0.0156 -> 0.0391, +0.50R -> +0.28R), the same pattern
     that preceded every earlier collapse of C-101.
  2. Drop NG=F and it is 5:1, **p=0.219, not significant**. Three NG=F trades still
     carry it.
  3. It does NOT beat the drift-matched null: 42.6% vs 34.2%, z=1.21, **p=0.114**.

**Precise claim.** "Entering at their drawn entry beats taking the SAME call at market"
is supported (p=0.039). "Their calls have an edge" is NOT (p=0.114). Only the first is
established, and part of it is mechanical: a resting limit either fills at a better price
or does not fill at all, and 20 of 73 never filled. The per-trade figure conditions on
filling; the per-opportunity figure is the honest one for a funded account.

**Do not configure the engine on this yet.** What would settle it is more SIGNALS-class
data, and that corpus is now exhausted at 2,509 frames. `weekly` is the wrong class
(-12.1 points vs null, C-117) and `hybrid`/`otc` are course material (C-115). So the
sample cannot grow from `D:/Trading/Output` -- it can only grow from new signals sessions.

## C-119 — The entry-price edge belongs to the ZONE, not the technique. Ours is inverted.

**Status:** measured, significant. The most actionable finding in the project.

C-117 established that entering at THEIR drawn entry beats taking the same call at market
(8:1 discordant, p=0.039). The obvious next question is whether the engine can exploit
that by doing the same thing: resting a limit at the zone proximal instead of buying at
market. It cannot. It gets the opposite sign.

Identical paired test, identical tool, identical pinned data -- same symbol, date,
direction and R, only the entry price differs:

    population                        zone-entry wins   market wins   McNemar p
    our engine, reachability arm            2                5          0.453
    our engine, reachable + midpoint        4                5          1.000
    THEIR signals corpus                    8                1          0.039

Both of ours favour the MARKET entry; theirs favours the zone entry. Neither of ours is
individually significant, but they agree with each other and disagree with theirs.

**The difference between the two is itself significant.** Fisher exact on the discordant
splits (2:5 ours vs 8:1 theirs): **two-sided p = 0.035**.

**What this settles.** The advantage is NOT a property of the technique -- resting a limit
at a zone edge is exactly what the engine already does. It is a property of WHICH ZONE is
chosen. Run the same mechanic on their zones and it wins; run it on ours and it loses.
Our zone selection is not merely worse than theirs, it is inverted relative to it: our
zone entries systematically select the trades that were going to fail, which is the
textbook signature of adverse selection on a badly-chosen level.

**What it closes.** Entry mechanics are finished as a line of work, now for the second
time and by a stronger argument than C-112's. Midpoint entry, depth sweeps, C-104 and the
reachability band all move the entry PRICE; none of them changes which zone the price is
attached to, and this shows the price is not where the edge lives.

**What it points at.** Everything now converges on one defect. C-110: composite ranking
loses to a pseudo-random ordering of its own pool. C-108/C-109: five of seven qualifiers
are near-constants and Q5 scores zone age. C-114: zone-derived features are the WORST
predictor family tested, because with a median 93 candidates price is always "at" a zone.
C-115: a drawn zone is not a trade. And now C-119: the same entry mechanic wins on their
zones and loses on ours.

The engine detects zones adequately and cannot choose between them. That single defect
accounts for every failure measured in this project, and no amount of work on direction,
qualifier weights, entry placement or ranking heuristics has moved it.

**Caveat.** 7 and 9 discordant pairs. Fisher exact is valid at this size, but the whole
comparison rests on 16 discordant observations and should be re-tested if the signals
class ever grows.

## C-120 — `goldtest/verdict.py`: the four gates every future change must clear

**Status:** tooling, in place

Every false positive in this project passed at least one honest-looking test:

    "74/160 on the goldtest"     in-sample, ~20 phases tuned against those very cases
    "+0.60R at market"           sample was 33 of 34 LONG in 2023 -- drift, not edge
    "midpoint entry helps"       a different trade population, not a different entry
    "their entries beat market"  true, but only after NOT pooling course material
    "level_on_top is dead"       measured on a call site that never trades

No single check catches all of those, so they are now run together and the WEAKEST result
decides:

    GATE 1  accuracy, paired McNemar on cases scored in BOTH arms
    GATE 2  did the emitted trade population change? (informational, but it invalidates
            any outcome comparison between the arms -- this is what made midpoint look
            like an improvement)
    GATE 3  expectancy vs a DRIFT-MATCHED null, never the driftless 1/3
    GATE 4  does the zone entry beat the same call at market, paired on the same trades

Gate 4 is the one that matters. Their signals corpus passes it 8:1, p=0.039. Both of our
arms LOSE it. A change that does not move gate 4 has not touched the defect.

Run against every arm tested to date -- reach, rmid, both, zf, mid -- **all five return
NOT supported**, which is the correct answer and matches every individual measurement.
Exit code is 0/1 so it can gate a commit.

Two bugs found while building it, both the kind it exists to prevent: cases with
`verdict=None` (errored during a run) crashed gate 1, and would otherwise have counted as
misses -- exactly the attrition bias that makes unpaired percentages unsafe. Only cases
scored in BOTH arms are compared.

## C-121 — The supervised attack on zone selection also fails. Everything measurable is now tested.

**Status:** measured; negative, and underpowered enough to say so carefully

C-119 located the defect: our zone entries lose to market while theirs win, significantly
(p=0.035). The direct attack is supervised -- learn what separates a zone they TRADED
(position tool) from one they only DREW (zone edges).

Best-posed version yet: restricted to the SIGNALS corpus alone (C-117 showed the corpora
are different populations, so pooling them was the earlier error), giving **73 traded vs
67 passed** -- near-balanced, baseline 52.1%, against the earlier pooled 65/119 at 64.7%.

In-sample separation is visibly present for the first time in this project:

    rangepos   low 59%  midlo 68%  midhi 50%  high 33%      (35-point spread)
    ret20      up 77%   fdn 65%    fup 41%    dn 35%        (42-point spread)
    height     wide 58% med 58%    small 47%  tight 33%

It does not survive validation:

    in-sample ceiling (memorise everything)   93.57%
    mean out-of-sample, 4 forward date folds  50.00%
    memorisation gap                          43.57 points
    best of 63 feature subsets                -4.46 points

**Caveat, stated because it changes the strength of the claim.** Test folds are 28 cases
with 24-27 of 28 combinations unseen, and the class balance swings 57% / 71% / 86% / 54%
across the four folds. This is "no signal found at n=140", NOT "no signal exists". The
in-sample spreads above are larger than anything seen in C-113/C-114 and could be real.

**Where this leaves the project.** Tested and closed: Stage-1 direction (571 subsets, C-113/
C-114), zone-derived features for direction (C-114), entry mechanics (C-112, C-119), zone
ranking rules (C-110, composite loses to pseudo-random), and now zone selection as
supervised classification. Nothing available at the call date predicts anything, at any
sample size this project can reach.

**The binding constraint is sample size, and it cannot be relieved from `D:/Trading/Output`.**
The signals corpus is exhausted at 2,509 frames. `weekly` is a different population
(-12.1 points vs null) and `hybrid`/`otc` are course material. More signals-class data
means NEW sessions, which do not exist yet, or forward time.

## C-122 — The anticipated/issued split holds at 3x the sample. It measures HIS selection skill.

**Status:** measured, robust

C-117 separated the corpora on 13-30 decided trades and warned the split might be noise.
The weekly corpus is now complete (6,094 frames, 64 position-tool setups, 42 decided) and
the pattern held:

    corpus                     n    W/dec    win%    R/trade   drift null   delta
    signals   (issued)        73    20/47    42.6%    +0.28R     34.1%      +8.5 pts
    weekly    (anticipated)   64    11/42    26.2%    -0.21R     36.8%     -10.6 pts
    practical (course)        21     0/8      0.0%    -1.00R     29.6%     -29.6 pts

Weekly went from 13 to 42 decided trades and stayed ~10 points BELOW its own null. The
class distinction is durable, not a small-sample artefact.

**What it measures.** These are the same trader, the same method, the same instruments,
weeks apart. The only difference is commitment: a Weekly Outlook position tool is a setup
being ANTICIPATED, a Signals position tool is one being ISSUED. The 19-point gap between
them is his selection skill, isolated. (Direct comparison z=1.62, p=0.11 -- suggestive,
not significant, so quote the two-vs-null deltas rather than the gap.)

**Why it matters for the engine.** C-119 showed the same entry mechanic wins on his zones
and loses on ours. C-122 shows that even HIS OWN drawn zones lose when he has not
committed to them. So the thing being replicated is not "where to draw a zone" -- he
draws plenty of losing ones -- it is the decision to act on one. C-121 tried to learn
exactly that decision, supervised, and found nothing out of sample at n=140.

**Operational rule, now load-bearing.** Never pool corpora. Merging weekly into signals is
the obvious move for sample size and it would have destroyed the only positive result in
the project: pooled, the +8.5 and -10.6 cancel to roughly nothing.

## C-123 — The course names the bound Q5 is missing. The qualifiers are right; our implementations are not.

**Status:** measured from course material; fix identified, not yet built
**Tool:** `gemini/read_course_rules.py` (new)

C-113 concluded the bottleneck is the FEATURES, not the rules, so the course corpora were
read for STATED SELECTION CRITERIA rather than for trade setups. 203 frames in, 24 state a
rule (12%). The measurable quantities they name:

    higher timeframe zone overlap  5      departure           2
    freshness                      3      base                2
    percentage penetration         3      profit margin       2
    distance to opposing zone      2      times zone tested   2

**Almost all of it is already implemented.** One frame transcribes the checklist verbatim
-- "Rule 1: Departure: Yes  Rule 2: Base: Yes  Rule 3: Freshness: Yes  Rule 4:
Originality: No  Flip: No  Rule 5: LOL" -- which is the engine's seven qualifiers. Another
states the zone construction we use: "Proximal line is drawn at the highest candle body in
the base, distal at the lowest price."

So the methodology was identified correctly. What fails is the IMPLEMENTATION, which is
exactly C-108: Q1 repeats the detection gate verbatim, Q5/Q6 are hardcoded to 10.0 on
trend-aligned zones, and five of seven qualifiers are near-constants on the trading path.

**The one actionable gap: "distance to opposing zone".** C-109 established that Q5
computes `max(all subsequent history) - proximal) / zone_height`, unbounded in time, which
makes it a proxy for zone AGE -- measured values of 181 to 874 against a threshold of 5,
and the youngest zones (the ones nearest price, the tradeable ones) scoring worst. C-109
could not fix it because no bounded horizon was defined. **The course defines it: the
opposing zone.**

`ZoneDetector.detect_speed_bumps` already finds opposing zones between price and a target,
so the machinery exists. A bounded Q5 would be
`distance from proximal to the nearest opposing zone / zone_height`, which is finite,
independent of lookback length, and does not grow with age.

**Not yet built, deliberately.** The holdout forward test is using the CPU, and any change
must be measured through `goldtest/verdict.py` on a full corpus run before it means
anything. Course material is evidence about CRITERIA, never about outcomes (C-115), so
this raises the prior on the fix -- it does not validate it. C-87 had 219 frames behind it
and still failed the measurement.

### C-123 addendum — bounded Q5 implemented behind `BP_Q5_BOUNDED`, default OFF

`margin_ratio_bounded` now measures the excursion within a bounded window
(`profit_margin_lookahead_bars`, default 60) instead of to the end of loaded history. It
is ALWAYS emitted as a diagnostic; the scored `margin_ratio` only changes when
`BP_Q5_BOUNDED=1`, so every recorded result stays byte-identical with the flag off.

Measured on AAPL 1d, 219 zones:

                        median   scoring 10   branch distribution
    unbounded (current)   42.7        85%     10:186   7:11   5:6   0:16
    bounded (60 bars)      3.7        41%     10:89    7:35   5:23  0:72

**This is the first change in the session that un-saturates a qualifier.** C-108 found
five of seven behaving as constants; Q5's branches are now populated rather than 85%
piled on a single value. The bound came from the course material naming it, not from
picking a number that looked good.

**It is NOT validated.** Distribution shape is not performance. A qualifier that varies
can still rank badly, and C-110 showed the composite loses to a pseudo-random ordering of
its own pool, so a better-distributed input may change nothing. Required before any
default flips:

    python goldtest/verdict.py --arm 'q5b?.json'          (510-case corpus, all 4 gates)
    plus a holdout forward arm, since the 510 corpus is in-sample by now

Queued behind the running holdout rather than run concurrently -- two engine runs halved
each other's speed earlier today and made a healthy run look hung.

## C-124 — The course's stated step 1 is what C-110 found empirically, and the engine does neither

**Status:** implemented behind `BP_NEAREST_FRESH`, default OFF. Not yet measured.

273 rules extracted from the course corpora, ranked by how often each criterion appears:

    freshness       81  (30%)      <- the single most-repeated criterion
    HTF coverage    46  (17%)      <- his "Rule 6"
    nearest         25   (9%)
    "first fresh"   22   (8%)
    trap            15   (5%)

His step 1 is stated literally: **"Find nearest Supply Zone (First fresh)"**, and his
checklist runs Departure / Base / Freshness / Originality+Flip / LOL / HTF Coverage.

**Two gaps this exposes, both in the engine, both already corroborated by measurement:**

1. **Freshness is his #1 criterion and a near-constant in ours.** C-108 measured
   `freshness_score` at 0 on **91.6%** of zones on the trading path. He reads the current
   chart and takes the first untested zone; we score every zone in the loaded history,
   where almost everything has been retested. The most important qualifier in the method
   carries no information in the implementation.

2. **HTF Coverage is his Rule 6 and is DISABLED by default.**
   `require_big_brother` defaults to False in `BP_rules_engine.py:362` and does not
   appear in `BP_config.yaml` at all.

**And "nearest, first fresh" is exactly what C-110 found without knowing the rule.** That
measurement put "nearest to price" at 2.64R median entry error against 4.74R for the
composite, and the composite behind a pseudo-random ordering of its own pool. The stated
method and the empirical result agree with each other and disagree with the engine.

**Implementation.** `BP_NEAREST_FRESH=1` sorts on `(not fresh, distance to price)` instead
of composite -- a filter-then-sort, not another score, because scoring is what saturates.
Fresh zones order ahead of stale ones and never exclude them, so the candidate list cannot
empty. Verified: flag off is byte-identical and reproducible; flag on moves AAPL rank-1
from 152.87 to 157.40 against a price of 169.12, same candidate set, 23 of 201 zones fresh.

**Nothing is validated.** Course material raises the prior; it does not substitute for the
measurement (C-87 had 219 frames behind it and still failed). Three flags now await a run:
`BP_Q5_BOUNDED`, `BP_NEAREST_FRESH`, `require_big_brother`. All must clear
`goldtest/verdict.py`, and the 510 corpus is in-sample by now, so the holdout arm is the
one that counts.

## C-125 — The full checklist is NINE rules. Exactly one is structurally missing from the engine.

**Status:** measured from course material (292 rules over 2,163 frames)

Recovered verbatim and repeatedly from the Hybrid AI corpus:

    Rule 1  Departure          Rule 6  HTF Coverage
    Rule 2  Base               Rule 7  Profit margin        <- listed under "Additional Rules"
    Rule 3  Freshness          Rule 8  Arrival              <- listed under "Additional Rules"
    Rule 4  Originality/Flip   Rule 9  Asset-specific / commercial coverage
    Rule 5  LOL                        ("NET commercial net long buy")

He calls rules 1-6 "90% of the job".

**CORRECTION to a claim made earlier this session.** From the first six rules alone it
looked as though `profit_margin` and `arrival` were our own additions, absent from his
method -- and suspiciously, they are the two hardcoded to 10.0 on trend-aligned zones.
That was wrong. They are his Rules 7 and 8, filed under "Additional Rules", which is why
they did not appear until frames mentioning "Additional Rules" were searched
specifically. The qualifier set is not padded; it matches.

**Mapping against the engine:**

    1-5  departure / base_duration / freshness / originality / level_on_top   implemented
    6    HTF Coverage -> filter_by_big_brother          DISABLED BY DEFAULT
    7    Profit margin -> Q5                            implemented, measures zone AGE (C-109)
    8    Arrival -> Q6                                  implemented, hardcoded to 10.0 on trend
    9    asset-specific / commercial -> COT engine      implemented, carries no signal (C-113)

**Rule 6 is the only structurally missing piece.** `require_big_brother` defaults to False
in `BP_rules_engine.py` and does not appear in `BP_config.yaml` at all. Everything else he
teaches is present and either working or broken in a way already diagnosed here.

That is a narrower and more useful result than "we implement everything": there is no
hidden concept, one disabled filter, and two known-defective implementations. Requiring
HTF coverage removes 26% of candidates on AAPL (219 -> 163), so it is a real constraint,
not a formality.

Rule 6 also carries nuance the binary flag does not capture -- "HTF Coverage: Yes, no trap
coverage" and "Yes but only the lower level" recur -- so a pass/fail implementation is an
approximation of what he actually evaluates.

## C-126 — The calendar evaluates the WALL CLOCK, not the scan date. Every backtest ran with it inert.

**Status:** defect, confirmed. Backtest/live divergence.
**File:** `BP_rules_engine.py:767`

    blackout = calendar.check_blackout()          # no argument

`EconomicCalendar.check_blackout(when=None)` documents "Defaults to now" and does
`when = datetime.utcnow()`. The engine never passes the date being simulated, so in every
historical run -- the 510-case goldtest, the walk-forward, and the holdout currently
running -- the calendar asks **"is TODAY a blackout?"** rather than "was the CASE DATE a
blackout?".

Confirmed empirically:

    check_blackout()                -> in_blackout=False   (today, 2026-08-31)
    check_blackout(2025-12-25)      -> in_blackout=True, risk_multiplier=0.0, Christmas
    check_blackout(2024-07-04)      -> in_blackout=False   (2024 has no curated dates)

`BP_calendar.py` itself passes a date at all three of its own call sites (lines 22, 1023,
1074). Only the engine omits it.

**Consequences.**

1. **Every measured result in this project was produced with calendar gating effectively
   disabled** -- uniformly, since the wall clock barely moves across a run. Not a source
   of error in the comparisons (it is constant across arms), but it means the calendar
   contributes nothing to any number recorded here.

2. **Live trading would behave differently from every backtest.** Live, the wall clock IS
   the scan date, so `risk_multiplier == 0.0` would start returning None and suppressing
   signals near holidays and high-impact events -- behaviour no backtest has ever
   exercised. For a system about to be run on a funded account, that is a divergence
   between what was measured and what would execute.

3. A second, smaller gap: the curated tables cover 2025-2026, so **the first nine months
   of the holdout (Apr-Dec 2024) have zero events per quarter** (measured: 2024 Q2/Q3/Q4
   = 0, 2025 = 23-24, 2026 = 13). Even with the date passed correctly, 2024-07-04 does not
   register as a holiday. This is the already-known "2027 dates need a human" item
   extending backwards as well as forwards.

**Not fixed here, deliberately.** Passing the scan date would change signal counts on
every historical run and invalidate today's in-flight holdout mid-flight. It must be a
flag, measured through `goldtest/verdict.py` like everything else, and run against a
baseline taken with the same code. Logged as the highest-priority correctness item behind
the running test.

### C-126 addendum — fix implemented behind `BP_CALENDAR_ASOF`, default OFF

The as-of date is taken from the last LTF bar, which the harness has already truncated to
the call date. Falls back to the old behaviour on any parse failure rather than crashing.
Verified: `pd` and `os` are in scope, the engine imports cleanly, and with the flag unset
the call is still `calendar.check_blackout()` -- byte-identical default path.

What the flag would change, by scan date:

    2025-12-25   in_blackout=True   risk_mult=0.0   Christmas         -> signal SUPPRESSED
    2025-07-04   in_blackout=True   risk_mult=0.0   Independence Day  -> signal SUPPRESSED
    2025-01-29   in_blackout=False  risk_mult=1.0
    2024-12-25   in_blackout=False  risk_mult=1.0   <- 2024 has no curated dates
    (no argument, i.e. every backtest to date)      -> never suppressed

**A caveat that matters more than the fix.** Because the curated tables only cover
2025-2026, turning this on makes the engine behave DIFFERENTLY IN DIFFERENT YEARS: 2025+
scans get gated at holidays, 2024 scans do not, since 2024-12-25 does not register. On the
holdout window (Apr 2024 - Aug 2026) that would mean the first nine months run ungated and
the rest gated -- a period-dependent bias introduced by the fix itself.

So the correct order is: extend the curated tables backwards through 2024 and forwards
through 2027 FIRST (needs published FOMC/ECB/BoE/CPI schedules -- a human, must not be
guessed), and only then A/B the flag. Enabling it before the tables are complete would
trade a known-inert calendar for a silently inconsistent one, which is worse.

## C-127 — C-117 does not survive de-duplication. WITHDRAWN as a significant result.

**Status:** measured. Found by reading frames directly rather than trusting the extraction.

Reading the source frames with vision instead of consuming Gemini's extracted numbers
exposed two defects in the ground truth that no aggregate check had caught.

**1. Contradictory same-day directions.** 8 of 46 symbol/date pairs carry BOTH a long and
a short, and **26 of 73 setups (36%) sit in a contradiction**. PA=F 2023-03-21 appears as
a long (entry 1385.0, stop 1331.37, frame 934) AND a short (entry 1385.0, stop 1405.5,
frame 962) -- identical entry, opposite direction. The chart settles it: the drawn zone is
1,331.37-1,385.00 with price at 1,405.50, i.e. a demand zone below price, so the LONG is
correct and the short is a misread of the daily chart's 1,395.00 / 1,342.80 lines. One of
my "winners" and one of my "losers" were the same setup.

**2. The same position tool counted many times.** NQ=F 2023-02-14 yields seven setups --
entries 12545.25 / 12130.0 / 12285.5 / 12553.5 / 11800.0 / 11800.0 / 12560.5, mostly
against a 12000 stop. That is one tool being dragged across the screen and re-read, not
seven trades. The dedupe key was (symbol, date, direction, entry, stop), so 12545 and
12553 registered as distinct. This is C-105's re-emission problem one layer up, in the
frame data rather than the goldtest harness.

**Effect on the finding:**

    dedup rule                                  n   paired   entry/market      p
    as measured (every extracted setup)        73     35        8 / 1        0.0391  SIG
    one per symbol/date/direction (median)     54     35        7 / 1        0.0703  ns
    ...and drop contradictory symbol/dates     38     23        5 / 0        0.0625  ns

**C-117 is withdrawn as a significant result.** Its p=0.039 rested on duplicate readings of
the same position tool. The DIRECTION is consistent under every rule -- entering at his
drawn entry beats the same call at market, 8:1, 7:1, 5:0, never once reversing -- but the
sample cannot support significance. At 5:0 discordant, p=0.0625 is the minimum achievable,
so this is not a threshold that more careful analysis can cross; it needs more setups.

**C-119 is affected too.** Its Fisher test (our 2:5 versus their 8:1, p=0.035) used the
un-deduplicated 8:1. Recomputed against 5:0 the comparison weakens correspondingly. The
qualitative claim -- the same mechanic wins on their zones and loses on ours -- still holds
in direction across every cut, but "significantly different" no longer stands unqualified.

**Process lesson.** Every aggregate check passed: dedupe was in place, scale validation was
in place, classes were separated. The contradiction was only visible in the IMAGE. When a
result matters, look at the raw evidence, not the extraction of it.


## C-128 — "Valuation is trend-following only" is what Bernd teaches, not what he calls. Encoding it costs 6 of 479.

**Status:** measured (2026-09-05). Flag `BP_VAL_TREND_ONLY`, default OFF. Full detail
`SESSION_2026-09-05.md` §2 D1.

Three Hybrid AI lessons (A017, A018, A019 1:53:38) state on camera that Valuation is used
"only for trend following ... very low accuracy" against the trend, with end-of-trend
reserved for the weekly 13-period reading. The engine's Step-3 long-in-downtrend path
(Phase 10/11 relaxed) fires on `val==bullish and loc==bullish and bearish_excl_trend<=1`,
i.e. exactly the setup his backtest rejects.

Mode 1 removes the counter-trend Valuation vote from the Step-3 tallies only; with-trend
and sideways consensus are byte-identical. Six-shard paired run, n=479:

    group        n    base   arm   changed  fixed/broke   p
    Bernd       339   176    174      2        0 / 2     0.500
    instructors 140    79     75      4        0 / 4     0.125
    pooled      479   255    249      6        0 / 6     0.031

All six are long→neutral and all six carry truth=long (PL=F 2023-11-05, 2023-11-18;
PA=F 2024-01-04, 2024-02-22; CL=F 2023-05-02; ZS=F 2024-02-01). The counter-trend
valuation path was right every time it fired. The stated rule and the observed calls
disagree; the goldtest scores the calls. **Not a candidate.**

Mode 2 (strict: the counter-trend vote is neutralised before the base tally, so it
touches every consensus path): 16 changed, 4 fixed / 11 broke, pooled p=0.118 (Bernd
3/6, p=0.508). The seven D1 longs all break (two flip to SHORT once the bullish vote is
gone), and nine stock/silver/USDCHF cases go neutral→long because the removed bearish
vote had been holding the engine neutral: 4 right, 5 wrong. With index valuation on top
(`strictboth0905_?.json`): 48 changed, 7/23, p=0.005. Neither mode is a candidate.

## C-129 — Index Valuation, switched on as the courses say, is significantly worse. Phase 15 is now measured.

**Status:** measured (2026-09-05). Flag `BP_INDEX_VALUATION` (C-93), default OFF.

B074 24:11 calls valuation "the primary tool" for equities and indices; A017/A019/A023 run
it on YM/NQ/ES throughout. Phase 15 forced index Valuation to neutral without an OOS
measurement. Six-shard paired run, n=479, single variable:

    group        n    base   arm   changed  fixed/broke   p
    Bernd       339   176    166     30        3 / 13    0.021  SIG
    instructors 140    79     77      5        0 / 2     0.500
    pooled      479   255    243     35        3 / 15    0.008  SIG

All 35 changes are `equity_indices` (31/90 → 19/90 correct). Shifts: neutral→short 14,
long→short 13, long→neutral 2, short→neutral 1. The index valuation reads overvalued
through the 2023–24 advance and turns the engine short into a bull market; the three fixes
are the Sep-2023 and Feb-2024 pullbacks. Combined with C-128's flag the losses are additive
(pooled −18, p<0.001; `both` vs `idxval` changes exactly C-128's six cases). **Stays OFF.**

## C-130 — Natural Gas primary tool: the course, the docs and the code give three different answers.

**Status:** open, needs a decision. 20 NG cases OOS (13 long / 7 neutral).

- A018 1:14:35 (Bernd): "the COT doesn't work, the valuation doesn't work → true
  seasonality [is] the primary tool".
- A025 28:27 (Bernd): "a technical blind demand game in combination with the true
  seasonals ... and then yes, there is the non commercials with breakouts".
- A015 1:21: retailer 5-yr extremes — the Phase 12/33 source; `methodology/07` encodes
  Retailers ① contrarian 260w.
- `BP_rules_engine.py:38`: `'nat_gas': 26  # Phase 41 S-01: non-commercials are primary`.

Not changed. Whichever teaching is chosen becomes a flag and a paired run; the seasonality
reading is already available to the engine, so the seasonality-primary variant is cheap.

## C-131 — Q5 documentation said "<1× zone height"; the code scores 0 below 2× and never reads its own 3.0 config.

**Status:** docs synced (2026-09-05); code unchanged.

`methodology/02` and the CLAUDE.md Q5 row described the profit-margin qualifier as "score 0
only <1× zone height, counter-trend only". The code (`_score_profit_margin`) awards
10/7/5 at 5×/3×/2× and 0 below 2×, counter-trend only, and `profit_margin_min_ratio: 3.0`
in config is read but never used by the scorer. Bernd's own words are the honest source:
A022 0:40:45 "minimum of 1 to 3 ... regardless of trend" (conservative) and 0:46 "bigger
than 1 to 2" (the floor). Both docs now state what the code does and cite the lesson.
Still stale and NOT changed: `methodology/03` dual-ROC "13 + 30" (measured in C-87: daily
10 + 30, weekly 13) and `methodology/07` NG group (waits on C-130).
