"""
Generate BP_config_allcoins.yaml -- the OVERRIDE layer for the all-coins
Bernd-accuracy paper-trading profile. run_scanner.py deep-merges this over
BP_config.yaml, so this file carries ONLY the deltas + the validated
watchlist expansion (watchlist_extra). Re-run after editing the candidate
list or after a new BP_config.yaml methodology change.
"""
import json
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent

# Symbols already in the base watchlist -> never duplicate them.
with open(HERE / "BP_config.yaml", "r", encoding="utf-8") as f:
    base = yaml.safe_load(f)
base_symbols = {e["symbol"] for e in (base.get("watchlist") or [])}

with open(HERE / "_validate_expansion_result.json", "r", encoding="utf-8") as f:
    val = json.load(f)

extra = []
skipped = []
for rec in val["passed"]:
    sym = rec["symbol"]
    if sym in base_symbols:
        skipped.append(sym)
        continue
    entry = {"symbol": sym, "name": rec["name"], "asset_class": rec["asset_class"]}
    if rec.get("extra", {}).get("strategies"):
        entry["strategies"] = rec["extra"]["strategies"]
    extra.append(entry)

# Build the override document. prop_firm OFF + unlimited caps/positions so the
# tracker takes EVERY qualifying signal and measures raw directional accuracy
# (how often Bernd's method is right), not prop-firm survival.
header = """# ============================================================
# BP_config_allcoins.yaml  --  ALL-COINS profile OVERRIDE layer
# ============================================================
# Deep-merged OVER BP_config.yaml by run_scanner.py when invoked with
#   python run_scanner.py --profile allcoins
# Carries ONLY the deltas from the FundingPips base config:
#   * prop_firm.enabled: false        -> no challenge gating
#   * risk: unlimited positions/caps  -> take EVERY qualifying signal
#   * active_strategy: weekly         -> matches the TradingView Ideas default
#   * watchlist_extra: [...]          -> validated global expansion appended
#                                        to the base ~170-symbol watchlist
# All Phase 1-46 methodology settings (zones, COT, valuation, seasonality,
# entry_distance, ...) are inherited from BP_config.yaml -- DO NOT copy them
# here. Regenerate with:  python _gen_allcoins_config.py
# ============================================================

"""

doc = {
    "prop_firm": {"enabled": False},
    "risk": {
        "account_balance": 100000.0,
        "max_open_positions": 99999,    # effectively unbounded -> take every signal
        "max_daily_loss_pct": 1000000.0,
        "max_total_loss_pct": 1000000.0,
    },
    "active_strategy": "weekly",
    "watchlist_extra": extra,
}

with open(HERE / "BP_config_allcoins.yaml", "w", encoding="utf-8") as f:
    f.write(header)
    yaml.safe_dump(doc, f, sort_keys=False, default_flow_style=False, width=100)

print(f"Wrote BP_config_allcoins.yaml")
print(f"  base watchlist symbols : {len(base_symbols)}")
print(f"  expansion added        : {len(extra)}")
print(f"  skipped (already base) : {len(skipped)} -> {skipped}")
print(f"  TOTAL all-coins symbols: {len(base_symbols) + len(extra)}")
# class breakdown
from collections import Counter
c = Counter(e["asset_class"] for e in extra)
print(f"  expansion by class     : {dict(c)}")
