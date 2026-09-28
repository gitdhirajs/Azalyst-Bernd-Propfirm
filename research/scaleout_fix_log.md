# Scale-out review fixes — 2026-09-28

Branch `feat/scale-out-runner` (worktree `D:\Trading\azb-scaleout`), on top of acc941f.
Eleven reviewer findings (all tagged major). Each one was reproduced first, with the reviewer's
script in `research/review_tmp/` (not committed) or an equivalent test. **All eleven reproduced.**
Ten are fixed. Finding 3 is a policy choice, so it now has a config flag that keeps the current
behaviour, plus logging, and waits for the user's decision.

Regression tests: `Propfirm Trading Dashboard/tests/test_scale_out_review_fixes.py` (28 tests).
26 of them fail on acc941f. The other 2 guard behaviour that must not change: a real gap still
gets gap credit, and a position with no partial is never treated as a runner.
Full suite: 212 passed + 2 xfailed before → **240 passed + 2 xfailed**.

| # | Finding | Reproduced | Fix |
|---|---|---|---|
| 1, 7, 10 | Partial P&L is not booked to balance / equity / daily P&L until the runner closes | yes | fixed |
| 2 | Fill bar trades through +1R, and the partial is booked at the next open | yes | fixed |
| 3 | A de-risked runner still blocks correlated entries / counts toward max positions | yes | flag + log, **user decision** |
| 4 | Late (backstop) partial is printed after the lock, which reads as "loosen the stop" | yes | fixed |
| 5 | First run after deploy reports ladder T2 partials as +1R scale-out partials | yes | fixed |
| 6 | Partial and runner close in the same run: "runner 50% open" next to CLOSED | yes | fixed |
| 8 | Alerts never tell a manual mirror how to take the 50%; NZDCHF was announced under `fixed` | yes | fixed |
| 9 | Result chart is drawn in the configured mode, not the trade's mode | yes | fixed |
| 11 | A gapped stop entry measures L1 from the planned entry, so the "partial" books a loss | yes | fixed |

## 1 / 7 / 10 — partial not credited to the account (three reports of one defect)

**Repro** (`misc_review.py`, `synth3.py`, `scenA.py`). After a +1R partial the bot showed
`balance 5000, daily_pnl 0, prop current_equity 5000, Realised +$0.00`, while the partial block
said `+$25.00 booked`. When the runner closed at breakeven three days later, that day's
`daily_pnl` became +25. With a gapped runner the bot showed −$5 on the close day. The broker shows
−$30 that day, because it credited the +$25 on the partial's day.

**Fix** (`BP_paper_trader.py`):
- New `Position.booked_pnl`: the part of `realized_pnl` already credited to the account.
- `_scale_out_manage` credits the partial the moment it happens, through `_book_to_account(pnl)`.
  That updates `closed_pnl_total`, `balance`, `daily_pnl`, `peak_balance` and `max_drawdown_pct`.
- `_close_position` books only `realized_pnl - booked_pnl`.
- Win / loss / scratch counting, R and the closed event still use the full `realized_pnl`.
- `get_open_positions()` `unrealized_pnl` no longer includes the booked half.
- Fixed and ladder never pre-book: `booked_pnl` stays 0, so they behave exactly as before. The
  ladder's T2 partial is still booked at close. That is pre-existing behaviour and was left
  unchanged, as the spec requires.

**Result**: after the partial, balance, equity and prop `current_equity` are 5025,
Realised is +$25.00, and Unrealised is the runner only. The runner's close day carries only the
runner's P&L. Samples section 2b shows it: `Account Equity $5,025.00`, `Progress 8.3%`.

**Tests**: booked on its own day with nothing double-counted; gapped runner −$30 on its own day;
account summary; legacy path books too; ladder does not pre-book; the booking survives a
save/load and a close after the reload.

## 2 — fill bar traded through +1R, partial credited at the next open

**Repro** (`misc_review.py` "fill-bar"). Setup: a long limit at 100 with the stop at 90.
- The fill bar is (101, 126, 99.5, 125). The next bar opens at 125.
- The partial was booked at **125.0**, which is +2.5R and +$62.50. It should be 110.0 (+1R).

**Fix**:
- New `Position.fill_bar_extreme`: the favourable extreme of the fill bar, set on both the replay
  and the legacy fill paths.
- The first managed bar after the fill reads it and clears it.
- If the fill bar already reached a level (L1 or the runner target), that level fills AT the
  level. A take-profit resting from the fill would have filled there.
- Gap credit stays for levels the fill bar never reached, i.e. a real gap.
- The fill bar itself still gets no partial credit (spec rule 1 is unchanged).

**Not applied to fixed mode's `tp_px`**: the spec says fixed must keep working exactly as
before. Fixed mode has the same pre-existing quirk: T2 after a fill bar that ran through T2 is
priced at the next open.

**Tests**: fill bar through +1R books at 1.1050 (+$25); a real gap after a quiet fill bar still
fills at the gapped open.

## 3 — de-risked runner still blocks new entries (user decision)

**Repro** (`corr_review.py`). A EURUSD runner at breakeven makes
`_check_activation_gates('GBPUSD=X', 50)` return
`(False, "correlated with open position(s): ['EURUSD=X']")`.

**Why it is not simply "fixed"**: whether a zero-risk runner should still block a correlated
entry, or count toward `max_open_positions`, is a risk-policy choice. Rule 12 ("uncorrelated
positions, max 2-3") is about risk. The daily-loss gate already counts a breakeven position as
zero risk. But a gap can still hit a runner. The user has not decided, so the default keeps
today's behaviour.

**What was added**:
- `stop_loss.runner_blocks_new_entries` in `BP_config.yaml`, read by `BP_management`. The default
  is `true`, which is unchanged behaviour. `false` excludes de-risked runners from the
  correlation peers and from the `max_open_positions` count.
- A runner is a de-risked runner when `partial_taken` is set and its stop is at or beyond the fill.
- When runners alone cause the block, it is logged: "blocked only by de-risked runner(s) …; set
  stop_loss.runner_blocks_new_entries: false to allow". The same log applies to max_positions.

**Tests**: blocked by default and logged; `false` allows the correlated entry and frees the
position slot; a position with no partial is never a runner; the reader parses the flag.

## 4 — backstop partial ordered after the lock ("stop to breakeven" read last)

**Repro** (`scenB.py`). The partial run's post fails, and the next run reaches +2.2R. The block
printed `runner stop -> 1.10500 (+1R locked)` and then `stop to breakeven 1.10000`.

**Fix** (`send_discord._partial_events`):
- Events are sorted by (`at`, partial before a stop move). Backstop stop moves have no `at` and
  sort last.
- Every event is enriched with the position's live `current_stop` and `current_price`.
- When the current stop is already tighter than breakeven, the partial line reads
  `stop since moved to 1.10500 (+1R locked), runner 50% open`. It never says "stop to breakeven",
  and its broker instruction uses the current stop.

**Test**: `test_backstop_partial_is_ordered_before_the_lock_and_does_not_loosen_the_stop`.

## 5 — the first run after deploy reports ladder-era partials

**Repro** (`scenAllcoins.py`). `paper_trader_state_allcoins.json` has NVO and UPS positions whose
partials were taken under the ladder. The previous state has no `runner_stops_seen`. The block
said `NVO LONG +2R reached … stop to breakeven 43.940`, but the real stop is 45.8286.

**Fix**:
- A backstop `partial_close` is emitted only for a scale-out partial. The new
  `BP_management.trade_mode()` decides this from `management_mode`, then `partial_time`, then
  `runner_peak_r`. Ladder partials have none of these.
- On the first run after the upgrade (`runner_stops_seen` absent), a partial is reported only if
  its `partial_time` is later than the last successful post (`last_sent_at`). Earlier partials
  count as already reported, and the run only seeds `runner_stops_seen`.

**Tests**: ladder partial ignored with and without the key; the upgrade run skips a partial
covered by the last post and reports a later one; the real allcoins state posts no partial.

## 6 — partial and runner close in one run

**Repro** (`scenC.py`). The message said `stop to breakeven 1.10000, runner 50% open` next to
`CLOSED … +0.50R breakeven`.

**Fix**: `compute_events` sets `runner_closed` on a partial or stop event when the position is in
this post's CLOSED list, or is in history and no longer open. `partials_block` then prints
`runner 50% closed since (see CLOSED)` and `>> Broker: whole position is closed now`.
It prints no stop instruction.

**Test**: `test_partial_and_close_in_one_run_does_not_say_move_the_stop`.

## 8 — no instruction for a manual mirror; NZDCHF announced under `fixed`

**Repro**:
- `scenSig.py`: the signal gave one lot and one stop.
- `scenA.py`: the partial block was in the past tense, and the header only said "move the stop".
- The live `discord_state.json` lists the NZDCHF id in `order_ids_seen`, so it would never be
  announced again.

**Fix** (`send_discord.py`):
- **Signal block (scale_out only)**: `>> PLACE AS 2 ORDERS (same entry + stop):`, then
  `A 0.06 lots, TP +1R 2.34538` and `B 0.06 lots, no take-profit (runner)`.
  - When `runner_target_r` is set, order B gets `TP +3R …`.
  - When the lot cannot be split in 0.01 steps: `Lot too small to split: place ONE order with no
    TP; close 50% by hand at +1R`.
  - The fixed/ladder text is unchanged.
- **Partial block**: the header is now `(repeat at the broker)`. Each partial adds
  `>> Broker: close 50% unless order A's TP filled; move the runner's stop to <px>`.
- **Stop already past the price**: when the live price is already beyond the stop being set, the
  block adds `[!] price … is already past it: close the runner at market`. A broker rejects such
  a stop, and the bot exits at the next open. This also covers the reversal case left open by
  finding 11.
- **One-time notice**: `MANAGEMENT CHANGED: earlier alerts -> scale-out`, posted as news.
  - It fires when the scan carries `results['management']` and its mode differs from
    `management_mode` in the last saved Discord state. A state with no `management_mode` was
    written by the fixed bot.
  - It fires only when there are pending orders or open positions to act on.
  - It lists each one. An order not yet partialled gets `remove its old take-profit; at +1R <px>
    close 50% + stop to breakeven`. A position already partialled gets "runner, stop X".
  - `build_state` saves `management_mode` only after a successful post, so a failed post
    retries the notice.
  - An older scan file without `management` never triggers it.
  - On the live files, the first run after deploy gives `reason=news`, no partials, and a notice
    for `NZDCHF=X BUY-LIMIT E:0.46562 … at +1R 0.46724` (samples section 4).

**Tests**: the lot split, including too-small lots and a runner target; the broker instruction
line; the notice with a synthetic prev and with the committed live `discord_state.json`, fired
once only; a failed post keeps the old mode; a scan without `management` gives no notice.

## 9 — result chart drawn in the configured mode

**Repro** (`charts.py` → `png/res_trail_fixed.png`). A scale-out trail trade drawn with
`management={'mode':'fixed'}` showed "Target / Exit / Trail stop" with no partial marker.

**Fix**:
- New helpers `BP_management.trade_mode()` and `trade_management(trade, *fallbacks)`. They return
  the configured settings with the mode replaced by the one the trade ran under.
- `Position.management_mode` is stamped at fill (replay, legacy, legacy immediate fill) and set
  to `scale_out` by a partial.
- `draw_chart.generate_trade_result_chart` and `send_discord.build_result_images` use it.

The chart `research/scaleout_charts/closed_gbpnzd_short_trail_config_fixed.png` is drawn with the
config set to `fixed` and still shows "50% off +1R" and the runner exit.

`build_result_images` is not called from `send_discord.main()` on this branch, so the defect was
latent in the live post. It is fixed at the function anyway.

**Tests**: mode inference; result images pass the trade's mode, not the config's; a fixed-config
chart still marks the partial.

## 11 — gapped stop entry: the "partial" books a loss

**Repro** (`synth2.py`).
- Buy-stop at 1.000 with the stop at 0.990. It gap-fills at 1.015.
- The next bar has high 1.0145, which is above the planned L1 of 1.010.
- A partial was booked at 1.014: −$2.50, −0.05R. The stop moved to 1.015, above the market.
- The next bar closed the trade as `breakeven` at −0.15R.

**Fix**: L1 is measured from the worse of the planned entry and the fill:
`base = max(entry, fill)` for a long, `min(...)` for a short.
- The partial is therefore always at least +1R of risk from the fill.
- A better fill (a limit that gapped through) keeps the planned level.
- The runner locks and the runner target stay measured from the planned entry, per the spec.
  "Never loosen" still applies, so a lock below a gapped fill is simply not applied.

"Never set a stop on the wrong side of the close" is handled as follows. Suppose the bar that
reached L1 reverses and closes below the fill:
- The breakeven stop takes effect from the next bar. That bar opens beyond it, so the runner exits
  at the open (spec rule 1). This is the same outcome as closing at market.
- The Discord block warns `close the runner at market` (see finding 8).

**Tests**: gapped buy-stop and gapped sell-stop both book +$25 at fill ± 1R, with breakeven at the
fill.

## Samples

`research/make_scaleout_samples.py` now uses the real `PaperTrader` with the live `BP_config.yaml`
to produce sections 2a–3. The trader replays the GBPNZD fixture's daily bars: fill, +1R partial,
then runner at breakeven. Account figures are no longer typed by hand.

Section 4 is the first-run notice for the live NZDCHF order. Charts are regenerated in
`research/scaleout_charts/` and were checked visually:
- signal, scale_out
- signal, fixed
- closed breakeven, from the real trader
- closed breakeven and closed trail, from the fixture
- closed trail with the config set to fixed

## Open

- **Finding 3 needs the user's decision**: `stop_loss.runner_blocks_new_entries` is true (current
  behaviour) or false (runners stop blocking correlated entries and position slots).
- The same fill-bar quirk remains in fixed mode's T2 (left unchanged by the spec).
- The ladder's T2 partial is still credited to the account only at close (left unchanged by the
  spec).

---

# Round 2 — 2026-09-28 (second review)

Nine major findings (two pairs were duplicates: 4 = 8, 5 = 9) and the listed minor ones. Every
one was reproduced first with the reviewer's script in `research/review_tmp/` (not committed).
Decisions were given with the task (gapped entries, unsplittable lots, rollback, mode notice,
backstop). Regression tests: `tests/test_scale_out_review_round2.py` (32 tests, 29 fail on
bb9ce54) and the rewritten gapped-entry tests in `tests/test_scale_out_review_fixes.py`.
Full suite: 240 passed + 2 xfailed → **274 passed + 2 xfailed**. `fixed_text_parity.py`: the
fixed-mode signal and status text is still byte-identical to gitdhirajs/main.

| # | Finding | Reproduced | Fix |
|---|---|---|---|
| M1 | Gapped stop entry: L1 from the worse of entry/fill, but order A's TP rests at the planned L1 | yes (`stopgap.py`: paper −$60, broker −$10) | fixed |
| M2 | Ladder revert: backstop posts every trailing move (hourly `news`) | yes (`rv_ladder.py`) | fixed |
| M3 | Partial first reported with the runner's close: "whole position is closed now" although order B is still open at the broker | yes (`rv_cases.py` be / lock2) | fixed |
| M4 = M8 | Mode-change notice lists orders announced in the same post; fires after every reset | yes (`rv_mode.py`) | fixed |
| M5 = M9 | Pending / filled / open blocks print T1/T2/T3 and "place as shown" in scale_out | yes (`flow_default.txt`, `discord_e2e.py`) | fixed |
| M6 | 0.01 lot: "close 50% by hand" is impossible, paper still books 50% | yes (`rv_signal.py`) | fixed |
| M7 | Code rollback double-books a partial | yes (`code_rollback.py`: 5046.94 vs 5035.20) | documented + migration script |

## M1 — gapped stop entry

`_scale_out_manage` measures L1 from the **planned** entry again (`entry ± at_r × risk`), which is
where order A's take-profit rests. A fill short of L1 (a 0.2R gap) books the partial at L1 from the
worse fill: +$20 in the repro, and the stop goes to breakeven = the fill, as order A does at the
broker. A fill already at/through the planned L1 is handled on the fill bar by the new
`_scale_out_gap_fill`: order A's TP is instantly marketable, so the partial is booked **at the fill**
($0), before the fill bar's stop check (the runner keeps the original stop for the rest of that
bar), and breakeven applies from the next bar. The fill event carries `gapped_past_l1` / `l1`, the
partial event `gap_fill`; the FILLED block prints `[!] stop order filled past +1R <L1>: ... the bot
closed 50% at the fill <px>` and `>> Broker: if order A's TP did not fill, close A at market; set the
runner's stop to breakeven <px>`. The partial booking moved to `_take_partial` (one code path for
both cases). Tests: small gap, gap past L1 (long and short), gap past L1 then stop on the fill bar,
the FILLED text; the round-1 "L1 from the fill" tests were replaced.

## M2 — backstop stop moves only for scale-out runners

`_partial_events` reports a backstop `stop_moved` only when `trade_mode(p) == 'scale_out'` and the
new stop is a whole-R lock (+1R, +2R, … within 0.02R). `build_state` stores `runner_stops_seen`
only for scale-out positions. Repro after the fix: run1..run5 give `reason=None` in ladder mode.
Tests: ladder cadence (trail-only runs never post, nothing stored), whole-R filter, ladder position
ignored.

## M3 — runner closed in the post that first reports its partial

Every event in the PARTIAL block is a first report, so when the runner has closed since, the user
never moved order B's stop there. `compute_events` copies the close price and reason onto the event,
and `partials_block` prints `runner 50% closed since: stopped at <px>` / `(breakeven; see CLOSED)` /
`>> Broker: order B's stop was never moved there -- close order B (the runner) at market now`, once
per position. A runner closed at its own take-profit says `order B's TP closed it; nothing left
open`. Tests: partial + breakeven close, stop move + trail close, runner target, line width.

## M4 / M8 — management notice

`_mode_change` lists only ids announced **before** this run (`order_ids_seen`,
`pending_orders_seen`, `open_position_ids_seen` of the saved state), minus the `paper_trade_id` of
every NEW SIGNAL in the same post. `reset_challenge.fresh_discord_state` writes `management_mode`
(the profile's mode: `_allcoins` merges its override and records `fixed`), so a reset never looks
like a change. Tests: same-post order excluded, earlier order kept, reset state gives no notice.

## M5 / M9 — mode-aware level lines

`_levels_line(p, m)` is mode-aware. fixed/ladder: unchanged. scale_out: `SL:<stop>  +1R(50%):<L1>
runner: no TP, 1R trail` (or `runner TP +3R:<px>` / `runner: no TP, stop at BE`), `SL  TP +1R (100%)`
for a single-order trade, and no level line for a partialled runner (its Booked / Runner lines
remain). PENDING ORDERS in scale_out: header `place as below` and `2 orders: A 50% TP +1R / B 50% no
TP` (or `ONE order, TP +1R`). OPEN POSITIONS header `+1R=first take`; rows use the mode stamped on
the position (`_row_mode`), so a fixed-stamped position keeps its T-levels. FILLED shows the bracket
as placed (the original stop). The status builders pass `_mgmt(scan)`. Tests: pending, open, filled,
fixed-stamped row, fixed text unchanged.

## M6 — unsplittable lot

`BP_management.split_lots` (shared by run_scanner and send_discord) and `scale_out_unsplittable`.
run_scanner sets `s["scale_out_unsplittable"] = True` right after sizing when the lot cannot be split
in 0.01 steps (or the fraction is >= 1). `submit_signal` copies it to `Position.scale_out_single`
(round-trips through the state file); `_scale_out_manage` closes 100% at +1R for such a position
(`close_reason = scale_out`). Text: `PLACE AS 1 ORDER: TP +1R <px>` / `Minimum lot: cannot split
into 2 orders: the bot closes 100% at +1R; stop never moves.`; the signal chart shows `+1R: close
100%` and no runner box, the result chart badge `+1R TP (100%)`. `scale_out_fraction >= 1` renders
the same single take-profit text (`Scale-out fraction is 100%`), no more "Runner 0%". An unflagged
minimum lot (older scan) also gets the single-order text, never an impossible split. Tests: flag,
paper close at +1R, text, fraction 1.0, round trip, unflagged lot.

## M7 — code rollback

Documented in `SESSION_2026-09-28.md` next to **Revert** and in `BP_config.yaml`: the revert is
config-only (`management: fixed`) while any open position has booked partials. New
`research/unbook_partials.py` (dry run by default, `--apply` writes with a `.bak`) implements the
migration for a code revert. Demo on the reviewer's rollback state: after the migration the old
engine closes the runner at T2 with balance **5035.20** (was 5046.94). Tests: old-code close
double counts without the migration and books once with it, idempotent, daily P&L adjusted only for
a same-day partial, CLI dry run writes nothing.

## Minor fixes

- **Gapped breakeven exit**: `_stop_close_reason(pos, exit_px)` returns `breakeven_gap` when the
  breakeven stop was gapped through by more than 0.05R (scale_out only; ladder keeps `breakeven`).
  Text: `runner gapped through breakeven, out at <px> (-0.6R)`, reason label `breakeven (gapped)`.
  A trail exit away from its lock reads `runner gapped through the +1R locked stop, out at ...`.
- **Result chart runner label**: signed R (`runner gapped lock -0.5R`); "lock" only at the lock.
  Reason labels `scale_out` → `+1R TP (100%)`, `breakeven_gap`, `runner_target`.
- **`_runner_exit_text` rounding**: `runner target +1.5R` (2 decimals, `:g`), not `+1R`.
- **Config validation**: unknown `management` value, `scale_out_at_r` / `scale_out_fraction` <= 0 or
  unparseable, fraction > 1, `runner_target_r <= scale_out_at_r` → mode `fixed`, `logger.error`,
  `errors` in the settings, `[!] CONFIG:` line in the Discord footer. A missing key still means
  scale_out (documented in the session note).
- **`_scale_out_booked`** returns None unless the trade is scale_out: ladder T2 partials get no
  blended / Booked / Runner lines again.
- **Subtitle / track record** follow `runner_trail` and `runner_target_r` (`runner trails` /
  `runner stop at BE` / `runner to +3R`); the dangling `Runner 50% trails in 1R steps:` line is gone
  when there are no locks; the `+1.5R runner TP : ` label keeps its space.
- **stop_moved line**: timestamp on its own line and `>> Broker: move the runner's stop to <px>`.
- **OPEN POSITIONS runner row**: `runner +$x` on line 1 and `Whole trade now: +1.50R (+$75.00 incl.
  booked)`.
- **Allcoins tracker** pinned to `stop_loss: {management: fixed}` in `BP_config_allcoins.yaml` and
  `_gen_allcoins_config.py`.
- **`goldtest/replay_trades.py`** prints `management mode simulated: <mode>`, notes that `be_half`
  only matters in ladder, and every summary row has a `management` column (default unchanged).
- **Ladder text**: NEW SIGNAL `>> MANAGEMENT (ladder): stop to breakeven at <half-way to T1 | T1>;
  close 50% at T2, trail the rest 1R behind price, close it at T3`; the empty TRACK RECORD and the
  mode notice say the same. The breakeven point follows `breakeven_at_half_target` (the live yaml
  has `false` = T1), carried as `ladder_be_at_half` in the settings. Fixed text is byte-identical.
- Found while regenerating samples: a gapped fill's breakeven stop printed as `+0.20R` / `+1.50R`
  (R from the planned entry); `_stop_r_label` now calls a stop at the fill `breakeven`. The
  "already past it" warning is strict (price exactly at the stop is not past it). The closed line of
  a partial taken at a gapped fill reads `50% at the fill (gapped past +1R)`.

## Left alone (as instructed)

- Fixed mode's T2 fill-bar quirk (a T2 reached on the fill bar is priced at the next open).
- Result images: `build_result_images` is still not called from `send_discord.main()` (not a
  regression; noted in the session note).
- Not in this round's list and not changed: the fill bar still gets no partial credit even if order
  A's resting TP would have filled on it (needs a user decision); the legacy path
  (`BP_BAR_REPLAY=0`) has no `open` key; overlapping captions when fill, partial and exit share one
  daily bar; `management_mode` is not re-stamped after a mode revert.

## Samples

`python research/make_scaleout_samples.py` now also writes: 4) the pending-orders block in scale_out
(first run after deploy, live NZDCHF), 5) the runner closed in the same post as its first partial
report (real PaperTrader), 6) a minimum-lot single order (signal, fill, +1R close), 7a) an E3b
buy-stop gapped past +1R and 7b) a 0.2R gap. New charts: `signal_gbpnzd_short_min_lot_single.png`,
`closed_gbpnzd_short_min_lot_single.png`, `closed_gbpnzd_short_gap_through_lock.png` (badge
`runner gapped lock -0.5R`). All regenerated charts were checked visually.
