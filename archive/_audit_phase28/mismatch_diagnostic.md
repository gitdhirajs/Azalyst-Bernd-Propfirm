# Phase 28 Goldtest Mismatch Diagnostic

Source: `D:\Azalyst Bernd Skorupinski\Propfirm Trading Dashboard\goldtest\gold_results.json`
Generated at (goldtest run): 2026-05-10T14:44:05.979941
Total cases: 160

## Outcome distribution

| Outcome | Count | Pct |
|---|---|---|
| STAGE1_MATCH | 93 | 58.1% |
| STAGE1_NEUTRAL | 31 | 19.4% |
| STAGE1_OPPOSITE | 20 | 12.5% |
| BERND_NEUTRAL | 12 | 7.5% |
| ERROR | 4 | 2.5% |

## Per asset class

| Asset Class | STAGE1_MATCH | STAGE1_NEUTRAL | STAGE1_OPPOSITE | BERND_NEUTRAL | ERROR |
|---|---|---|---|---|---|
| equities (47) | 29 (66%) | 13 | 2 | 1 | 2 |
| equity_indices (44) | 20 (57%) | 8 | 7 | 7 | 2 |
| precious_metals (41) | 29 (78%) | 4 | 4 | 4 | 0 |
| commodities (14) | 10 (71%) | 0 | 4 | 0 | 0 |
| forex (9) | 2 (22%) | 4 | 3 | 0 | 0 |
| energies (4) | 3 (75%) | 1 | 0 | 0 | 0 |
| interest_rates (1) | 0 (0%) | 1 | 0 | 0 | 0 |

## Failed indicator tallies

For STAGE1_NEUTRAL cases (Bernd had a direction; system said hold), counts how many cases had each indicator opposing or neutral relative to Bernd's direction.

| Indicator | Opposing | Neutral | Total disagree |
|---|---|---|---|
| cot_strength | 0 | 31 | 31 |
| constituent | 1 | 29 | 30 |
| seasonality | 16 | 13 | 29 |
| cot | 4 | 23 | 27 |
| valuation | 6 | 20 | 26 |
| location | 11 | 10 | 21 |
| trend | 9 | 12 | 21 |

## Failed indicator by asset class

### energies
- trend:opposing: 1
- cot:neutral: 1
- cot_strength:neutral: 1
- valuation:neutral: 1
- seasonality:opposing: 1
- constituent:neutral: 1

### equities
- cot:neutral: 13
- cot_strength:neutral: 13
- constituent:neutral: 13
- seasonality:opposing: 10
- location:opposing: 6
- valuation:neutral: 5
- valuation:opposing: 4
- trend:opposing: 4
- trend:neutral: 4
- seasonality:neutral: 3
- location:neutral: 2

### equity_indices
- cot_strength:neutral: 8
- valuation:neutral: 8
- location:neutral: 6
- constituent:neutral: 6
- seasonality:opposing: 5
- trend:neutral: 4
- cot:neutral: 3
- cot:opposing: 2
- trend:opposing: 2
- location:opposing: 2
- constituent:opposing: 1
- seasonality:neutral: 1

### forex
- cot_strength:neutral: 4
- seasonality:neutral: 4
- constituent:neutral: 4
- valuation:neutral: 3
- trend:neutral: 3
- cot:neutral: 2
- trend:opposing: 1
- valuation:opposing: 1
- cot:opposing: 1
- location:opposing: 1

### interest_rates
- trend:neutral: 1
- cot:neutral: 1
- cot_strength:neutral: 1
- valuation:neutral: 1
- seasonality:neutral: 1
- constituent:neutral: 1

### precious_metals
- cot_strength:neutral: 4
- seasonality:neutral: 4
- constituent:neutral: 4
- cot:neutral: 3
- location:neutral: 2
- location:opposing: 2
- valuation:neutral: 2
- trend:opposing: 1
- cot:opposing: 1
- valuation:opposing: 1

## STAGE1_OPPOSITE detail (system said opposite direction)

Total: 20

### equity_indices (7)
- Case  14 YM=F     2024-03-03 [monthly] Bernd=bullish Sys=bearish | location=bearish, trend=sideways, cot=bearish, cot_strength=strong, valuation=neutral, seasonality=bullish, constituent=bearish
   Reasoning: New demand created on Dow; retailers getting bullish, retracement is for buying.
- Case  26 NQ=F     2023-01-29 [weekly] Bernd=bullish Sys=bearish | location=bearish, trend=sideways, cot=bearish, cot_strength=strong, valuation=neutral, seasonality=bearish, constituent=neutral
   Reasoning: Bull market resumed; Nasdaq strongest with weekly demand at 11759.
- Case  78 NQ=F     2023-10-29 [weekly] Bernd=bullish Sys=bearish | location=bearish, trend=downtrend, cot=neutral, cot_strength=none, valuation=neutral, seasonality=bearish, constituent=neutral
   Reasoning: Nasdaq undervalued; constituents undervalued, supporting upside.
- Case 122 NQ=F     2023-05-16 [weekly] Bernd=bearish Sys=bullish | location=bearish, trend=sideways, cot=bullish, cot_strength=strong, valuation=neutral, seasonality=bullish, constituent=neutral
   Reasoning: quite came into this and for last week we also had a shorting opportunity on the S&P and price quite came into this and for last week we also had a shorting opportunity on the S&P and price never q...
- Case 151 NQ=F     2023-02-18 [weekly] Bernd=bullish Sys=bearish | location=bearish, trend=sideways, cot=bullish, cot_strength=strong, valuation=neutral, seasonality=bearish, constituent=neutral
   Reasoning: it makes more sense. Now, we haven't got now here as well, just of all, held again, but I'm still like very stubborn here, and but I think it's being stubborn in a good way and wait for the demand ...
- Case 152 NQ=F     2023-02-18 [weekly] Bernd=bullish Sys=bearish | location=bearish, trend=sideways, cot=bullish, cot_strength=strong, valuation=neutral, seasonality=bearish, constituent=neutral
   Reasoning: you see also when we just look pure seasonality, when we look pure seasonality, I would like to buy again, same strategy as last week, we discussed everything last week very refined, 140 minute ent...
- Case 153 NQ=F     2023-02-18 [weekly] Bernd=bullish Sys=bearish | location=bearish, trend=sideways, cot=bullish, cot_strength=strong, valuation=neutral, seasonality=bearish, constituent=neutral
   Reasoning: I would like to buy again, same strategy as last week, we discussed everything last week very refined, 140 minute entry, it's basically the same, nothing really changed here, but look at the refine...

### precious_metals (4)
- Case  19 GC=F     2023-01-01 [weekly] Bernd=bullish Sys=bearish | location=bearish, trend=downtrend, cot=bearish, cot_strength=strong, valuation=bearish, seasonality=neutral, constituent=neutral
   Reasoning: Expecting a monster rally soon from this demand cluster area.
- Case  56 GC=F     2023-09-09 [weekly] Bernd=bullish Sys=bearish | location=bearish, trend=sideways, cot=neutral, cot_strength=none, valuation=neutral, seasonality=bearish, constituent=neutral
   Reasoning: Nice area to go long on adjusted chart; gold long but not a forever long.
- Case  90 GC=F     2023-11-25 [weekly] Bernd=bullish Sys=bearish | location=bearish, trend=uptrend, cot=bearish, cot_strength=normal, valuation=neutral, seasonality=neutral, constituent=neutral
   Reasoning: End-of-year rally — wait for retracement back into demand to go long.
- Case 127 GC=F     2023-04-18 [weekly] Bernd=bullish Sys=bearish | location=bearish, trend=sideways, cot=bearish, cot_strength=strong, valuation=bearish, seasonality=neutral, constituent=neutral
   Reasoning: Well let's talk about precious metals first before we move into equity indices and then we talk about stocks we've got lots to cover still so precious metals we stayed on the sidelines we said well...

### commodities (4)
- Case 106 CT=F     2023-12-16 [weekly] Bernd=bearish Sys=bullish | location=bullish, trend=sideways, cot=bullish, cot_strength=strong, valuation=neutral, seasonality=bullish, constituent=neutral
   Reasoning: Cotton may come down — bearish trade idea in agricultural markets.
- Case 125 ZC=F     2024-01-18 [weekly] Bernd=bearish Sys=bullish | location=bullish, trend=sideways, cot=bullish, cot_strength=strong, valuation=bullish, seasonality=bullish, constituent=neutral
   Reasoning: So palladium our dear friend palladium while we did stop out I cannot I will not come and say okay you know even if it's few ticks yet we got stopped out I think fundamentally both burn down I were...
- Case 126 ZC=F     2024-01-18 [weekly] Bernd=bearish Sys=bullish | location=bullish, trend=sideways, cot=bullish, cot_strength=strong, valuation=bullish, seasonality=bullish, constituent=neutral
   Reasoning: okay it one more minutes moving into the agricultural which used to be my favorites I mean there's still but I now trade I'm getting trade ideas on other products products of course if I get a setu...
- Case 154 CT=F     2023-11-18 [weekly] Bernd=bearish Sys=bullish | location=bullish, trend=sideways, cot=bullish, cot_strength=strong, valuation=neutral, seasonality=neutral, constituent=neutral
   Reasoning: week before because the retailers are getting super bullish and this is where you saw that big drop when you think it cannot get even lower well and this copper anything has changed it seems like t...

### forex (3)
- Case  43 6E=F     2023-04-30 [weekly] Bernd=bullish Sys=bearish | location=bearish, trend=sideways, cot=bullish, cot_strength=strong, valuation=bearish, seasonality=neutral, constituent=neutral
   Reasoning: EURUSD long is the only currency trade Bernd is in.
- Case 114 USDCHF=X 2024-03-02 [weekly] Bernd=bearish Sys=bullish | location=bullish, trend=sideways, cot=bullish, cot_strength=normal, valuation=bearish, seasonality=neutral, constituent=neutral
   Reasoning: Weekly + daily supply level-on-top-of-level; price overvalued; retailers bearish.
- Case 143 6S=F     2023-05-13 [weekly] Bernd=bullish Sys=bearish | location=bearish, trend=downtrend, cot=bullish, cot_strength=strong, valuation=bearish, seasonality=neutral, constituent=neutral
   Reasoning: a setup for you guys so as i said i was trading this with frang and this basically was i was you're interested you can watch them to the end if not them basically it for the session but you're inte...

### equities (2)
- Case  53 AAPL     2023-09-03 [weekly] Bernd=bearish Sys=bullish | location=bearish, trend=sideways, cot=neutral, cot_strength=none, valuation=bullish, seasonality=bearish, constituent=neutral
   Reasoning: Apple is overvalued (only mega-cap that is), an alarm bell signaling weakness.
- Case 131 AAPL     2023-01-01 [weekly] Bernd=bearish Sys=bullish | location=bullish, trend=downtrend, cot=neutral, cot_strength=none, valuation=bullish, seasonality=neutral, constituent=neutral
   Reasoning: I position myself now for this being the law of the law and is to go higher, right? year long term, we are short term overvalued anyway, but also now long term overvalued and it's just as you saw t...

## STAGE1_NEUTRAL detail (sample first 5 per asset class)

### equities (13 total)
- Case   3 AMZN     2024-01-02 [monthly] Bernd=bullish Sys=neutral
   Components: location=bearish, trend=uptrend, cot=neutral, cot_strength=none, valuation=neutral, seasonality=neutral, constituent=neutral
   Disagreeing with Bernd (bullish): location(opposing), cot(neutral), cot_strength(neutral), valuation(neutral), seasonality(neutral), constituent(neutral)
   Reasoning: Amazon close to undervalued long-term and short-term.
- Case   5 NFLX     2024-01-02 [monthly] Bernd=bullish Sys=neutral
   Components: location=bearish, trend=uptrend, cot=neutral, cot_strength=none, valuation=bearish, seasonality=bearish, constituent=neutral
   Disagreeing with Bernd (bullish): location(opposing), cot(neutral), cot_strength(neutral), valuation(opposing), seasonality(opposing), constituent(neutral)
   Reasoning: Netflix coming from undervalued, going long-term undervalued.
- Case  10 MSFT     2024-02-03 [monthly] Bernd=bullish Sys=neutral
   Components: location=bearish, trend=uptrend, cot=neutral, cot_strength=none, valuation=neutral, seasonality=neutral, constituent=neutral
   Disagreeing with Bernd (bullish): location(opposing), cot(neutral), cot_strength(neutral), valuation(neutral), seasonality(neutral), constituent(neutral)
   Reasoning: Microsoft coming from overvalued, now at mean — still room to run.
- Case  13 NVDA     2024-02-03 [monthly] Bernd=bullish Sys=neutral
   Components: location=bearish, trend=uptrend, cot=neutral, cot_strength=none, valuation=bearish, seasonality=neutral, constituent=neutral
   Disagreeing with Bernd (bullish): location(opposing), cot(neutral), cot_strength(neutral), valuation(opposing), seasonality(neutral), constituent(neutral)
   Reasoning: Nvidia not overvalued long-term.
- Case  23 GOOG     2023-01-08 [weekly] Bernd=bullish Sys=neutral
   Components: location=bullish, trend=downtrend, cot=neutral, cot_strength=none, valuation=bullish, seasonality=bearish, constituent=neutral
   Disagreeing with Bernd (bullish): trend(opposing), cot(neutral), cot_strength(neutral), seasonality(opposing), constituent(neutral)
   Reasoning: Long above with stop below the level, nice risk reward.
   ... and 8 more

### equity_indices (8 total)
- Case   1 NQ=F     2024-01-02 [monthly] Bernd=bullish Sys=neutral
   Components: location=neutral, trend=uptrend, cot=bearish, cot_strength=strong, valuation=neutral, seasonality=bearish, constituent=bearish
   Disagreeing with Bernd (bullish): location(neutral), cot(opposing), cot_strength(neutral), valuation(neutral), seasonality(opposing), constituent(opposing)
   Reasoning: NASDAQ rally with mega-cap tech undervalued long-term.
- Case  21 YM=F     2023-01-08 [weekly] Bernd=bullish Sys=neutral
   Components: location=neutral, trend=uptrend, cot=neutral, cot_strength=none, valuation=neutral, seasonality=bearish, constituent=bullish
   Disagreeing with Bernd (bullish): location(neutral), cot(neutral), cot_strength(neutral), valuation(neutral), seasonality(opposing)
   Reasoning: Weekly bullish engulfing, undervalued long-term and short-term, strong January.
- Case  34 RTY=F    2023-03-18 [monthly] Bernd=bullish Sys=neutral
   Components: location=neutral, trend=sideways, cot=bullish, cot_strength=normal, valuation=neutral, seasonality=bearish, constituent=neutral
   Disagreeing with Bernd (bullish): location(neutral), trend(neutral), cot_strength(neutral), valuation(neutral), seasonality(opposing), constituent(neutral)
   Reasoning: High-quality monthly demand and undervalued — picture-perfect level into a strong April.
- Case  49 RTY=F    2023-06-03 [weekly] Bernd=bullish Sys=neutral
   Components: location=neutral, trend=downtrend, cot=bullish, cot_strength=strong, valuation=neutral, seasonality=neutral, constituent=neutral
   Disagreeing with Bernd (bullish): location(neutral), trend(opposing), cot_strength(neutral), valuation(neutral), seasonality(neutral), constituent(neutral)
   Reasoning: Russell super strong; potential to run all the way up to dot D level.
- Case  51 YM=F     2023-08-26 [weekly] Bernd=bullish Sys=neutral
   Components: location=bearish, trend=sideways, cot=neutral, cot_strength=none, valuation=neutral, seasonality=bullish, constituent=neutral
   Disagreeing with Bernd (bullish): location(opposing), trend(neutral), cot(neutral), cot_strength(neutral), valuation(neutral), constituent(neutral)
   Reasoning: Already long from weekly demand; valuation great, expecting price higher.
   ... and 3 more

### forex (4 total)
- Case  46 USDCHF=X 2023-05-13 [weekly] Bernd=bullish Sys=neutral
   Components: location=bullish, trend=downtrend, cot=neutral, cot_strength=none, valuation=neutral, seasonality=neutral, constituent=neutral
   Disagreeing with Bernd (bullish): trend(opposing), cot(neutral), cot_strength(neutral), valuation(neutral), seasonality(neutral), constituent(neutral)
   Reasoning: 240-minute supply zone target on shorts of CHF (long USD/CHF setup).
- Case 113 USDCAD=X 2024-03-02 [weekly] Bernd=bearish Sys=neutral
   Components: location=bearish, trend=sideways, cot=neutral, cot_strength=none, valuation=bullish, seasonality=neutral, constituent=neutral
   Disagreeing with Bernd (bearish): trend(neutral), cot(neutral), cot_strength(neutral), valuation(opposing), seasonality(neutral), constituent(neutral)
   Reasoning: Reacting from weekly demand; retailers bullish, getting undervalued — expecting downside.
- Case 118 6E=F     2023-04-11 [weekly] Bernd=bearish Sys=neutral
   Components: location=bearish, trend=sideways, cot=bullish, cot_strength=strong, valuation=neutral, seasonality=neutral, constituent=neutral
   Disagreeing with Bernd (bearish): trend(neutral), cot(opposing), cot_strength(neutral), valuation(neutral), seasonality(neutral), constituent(neutral)
   Reasoning: upside there's always a risk of price going slightly higher before we then may turn however in my books we can now look to take a short on the lower time frame and I would here just take the first ...
- Case 119 6E=F     2023-04-11 [weekly] Bernd=bullish Sys=neutral
   Components: location=bearish, trend=sideways, cot=bullish, cot_strength=strong, valuation=neutral, seasonality=neutral, constituent=neutral
   Disagreeing with Bernd (bullish): location(opposing), trend(neutral), cot_strength(neutral), valuation(neutral), seasonality(neutral), constituent(neutral)
   Reasoning: in my books we can now look to take a short on the lower time frame and I would here just take the first level that comes to mind here or that we see and here we see a drop-based drop and if you up...

### precious_metals (4 total)
- Case  61 PL=F     2023-09-23 [weekly] Bernd=bullish Sys=neutral
   Components: location=neutral, trend=uptrend, cot=neutral, cot_strength=none, valuation=bullish, seasonality=neutral, constituent=neutral
   Disagreeing with Bernd (bullish): location(neutral), cot(neutral), cot_strength(neutral), seasonality(neutral), constituent(neutral)
   Reasoning: Pre-election cycle bullish in October, weekly chart at level on top of level.
- Case  86 GC=F     2023-11-05 [weekly] Bernd=bullish Sys=neutral
   Components: location=bearish, trend=uptrend, cot=neutral, cot_strength=none, valuation=neutral, seasonality=neutral, constituent=neutral
   Disagreeing with Bernd (bullish): location(opposing), cot(neutral), cot_strength(neutral), valuation(neutral), seasonality(neutral), constituent(neutral)
   Reasoning: Slowly getting undervalued again, perfect time to buy on pullback.
- Case 112 GC=F     2024-03-02 [weekly] Bernd=bullish Sys=neutral
   Components: location=bearish, trend=uptrend, cot=neutral, cot_strength=none, valuation=neutral, seasonality=neutral, constituent=neutral
   Disagreeing with Bernd (bullish): location(opposing), cot(neutral), cot_strength(neutral), valuation(neutral), seasonality(neutral), constituent(neutral)
   Reasoning: Bull flag setup confirmed; retailers getting bearish (contrarian bullish for PMs).
- Case 128 SI=F     2023-04-18 [weekly] Bernd=bullish Sys=neutral
   Components: location=neutral, trend=downtrend, cot=bearish, cot_strength=normal, valuation=bearish, seasonality=neutral, constituent=neutral
   Disagreeing with Bernd (bullish): location(neutral), trend(opposing), cot(opposing), cot_strength(neutral), valuation(opposing), seasonality(neutral), constituent(neutral)
   Reasoning: Well let's talk about precious metals first before we move into equity indices and then we talk about stocks we've got lots to cover still so precious metals we stayed on the sidelines we said well...

### interest_rates (1 total)
- Case  72 ZB=F     2023-10-21 [weekly] Bernd=bullish Sys=neutral
   Components: location=bullish, trend=sideways, cot=neutral, cot_strength=none, valuation=neutral, seasonality=neutral, constituent=neutral
   Disagreeing with Bernd (bullish): trend(neutral), cot(neutral), cot_strength(neutral), valuation(neutral), seasonality(neutral), constituent(neutral)
   Reasoning: Monthly + weekly drop-base-rally demand zone with strong fundamentals.

### energies (1 total)
- Case  94 NG=F     2023-12-02 [weekly] Bernd=bullish Sys=neutral
   Components: location=bullish, trend=downtrend, cot=neutral, cot_strength=none, valuation=neutral, seasonality=bearish, constituent=neutral
   Disagreeing with Bernd (bullish): trend(opposing), cot(neutral), cot_strength(neutral), valuation(neutral), seasonality(opposing), constituent(neutral)
   Reasoning: First time extreme COT plus seasonal low — slowly approaching bottom.
