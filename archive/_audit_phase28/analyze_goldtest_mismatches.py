"""Phase 28 diagnostic: bucket goldtest mismatches by which indicator disagreed with Bernd.

For each of the 160 cases:
  - classify the outcome (MATCH, NEUTRAL, OPPOSITE, BERND_NEUTRAL)
  - for non-matches, identify which bias_components disagreed with Bernd's stated direction
  - tally root cause buckets

Cross-references each bucket to Phase 28 findings where applicable.

Usage:
    python analyze_goldtest_mismatches.py [--input PATH] [--output PATH]
"""
import json
import argparse
import os
from collections import Counter, defaultdict

NEUTRAL_VOCAB = {"neutral", "hold", None, ""}
LONG_VOCAB = {"long", "bullish"}
SHORT_VOCAB = {"short", "bearish"}
SIDEWAYS_VOCAB = {"sideways"}
UPTREND_VOCAB = {"uptrend"}
DOWNTREND_VOCAB = {"downtrend"}


def norm_bias(x):
    if x is None:
        return "neutral"
    s = str(x).lower().strip()
    if s in NEUTRAL_VOCAB or s in SIDEWAYS_VOCAB:
        return "neutral"
    if s in LONG_VOCAB or s in UPTREND_VOCAB:
        return "bullish"
    if s in SHORT_VOCAB or s in DOWNTREND_VOCAB:
        return "bearish"
    return "neutral"


def classify_case(case):
    bernd = norm_bias((case.get("bernd") or {}).get("bias"))
    sys_only = norm_bias((case.get("system") or {}).get("bias_only"))
    sys_dir = norm_bias((case.get("system") or {}).get("direction"))
    err = case.get("error")
    if err:
        return "ERROR", bernd, sys_only, sys_dir
    if bernd == "neutral":
        return "BERND_NEUTRAL", bernd, sys_only, sys_dir
    if sys_only == bernd:
        return "STAGE1_MATCH", bernd, sys_only, sys_dir
    if sys_only == "neutral":
        return "STAGE1_NEUTRAL", bernd, sys_only, sys_dir
    return "STAGE1_OPPOSITE", bernd, sys_only, sys_dir


def disagreeing_indicators(bernd, components):
    """Return list of (indicator, value) where the indicator opposes Bernd's direction."""
    if bernd not in ("bullish", "bearish"):
        return []
    opposite = "bearish" if bernd == "bullish" else "bullish"
    disagreeing = []
    for ind, val in components.items():
        v = norm_bias(val)
        if v == opposite:
            disagreeing.append((ind, "opposing"))
        elif v == "neutral":
            disagreeing.append((ind, "neutral"))
    return disagreeing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=r"D:\Azalyst Bernd Skorupinski\Propfirm Trading Dashboard\goldtest\gold_results.json")
    ap.add_argument("--output", default=r"D:\Azalyst Bernd Skorupinski\_audit_phase28\mismatch_diagnostic.md")
    args = ap.parse_args()

    with open(args.input) as f:
        data = json.load(f)
    cases = data["results"]

    # Top-level counts
    outcomes = Counter()
    by_class = defaultdict(Counter)
    # Per-class failure breakdown
    neutral_failures_by_class = defaultdict(list)
    opposite_failures_by_class = defaultdict(list)
    # Indicator failure tallies
    opposing_indicator_count = Counter()
    neutral_indicator_count = Counter()
    # Per-indicator detail (asset_class -> indicator -> count)
    indicator_by_class = defaultdict(Counter)

    for c in cases:
        outcome, bernd, sys_only, sys_dir = classify_case(c)
        ac = c.get("asset_class", "?")
        outcomes[outcome] += 1
        by_class[ac][outcome] += 1
        components = (c.get("system") or {}).get("bias_components", {}) or {}

        if outcome == "STAGE1_NEUTRAL":
            disagree = disagreeing_indicators(bernd, components)
            row = {
                "case_index": c["case_index"],
                "symbol": c["symbol"],
                "call_date": c["call_date"],
                "strategy": c["strategy"],
                "bernd": bernd,
                "sys": sys_only,
                "components": components,
                "disagreeing": disagree,
                "reasoning": c.get("bernd", {}).get("reasoning", ""),
            }
            neutral_failures_by_class[ac].append(row)
            for ind, kind in disagree:
                if kind == "opposing":
                    opposing_indicator_count[ind] += 1
                else:
                    neutral_indicator_count[ind] += 1
                indicator_by_class[ac][f"{ind}:{kind}"] += 1

        elif outcome == "STAGE1_OPPOSITE":
            row = {
                "case_index": c["case_index"],
                "symbol": c["symbol"],
                "call_date": c["call_date"],
                "strategy": c["strategy"],
                "bernd": bernd,
                "sys": sys_only,
                "components": components,
                "reasoning": c.get("bernd", {}).get("reasoning", ""),
            }
            opposite_failures_by_class[ac].append(row)

    # Write the diagnostic markdown
    lines = []
    lines.append("# Phase 28 Goldtest Mismatch Diagnostic\n")
    lines.append(f"Source: `{args.input}`")
    lines.append(f"Generated at (goldtest run): {data.get('generated_at', 'unknown')}")
    lines.append(f"Total cases: {len(cases)}\n")
    lines.append("## Outcome distribution\n")
    lines.append("| Outcome | Count | Pct |")
    lines.append("|---|---|---|")
    total = len(cases)
    for k, v in outcomes.most_common():
        lines.append(f"| {k} | {v} | {100*v/total:.1f}% |")
    lines.append("")

    lines.append("## Per asset class\n")
    lines.append("| Asset Class | STAGE1_MATCH | STAGE1_NEUTRAL | STAGE1_OPPOSITE | BERND_NEUTRAL | ERROR |")
    lines.append("|---|---|---|---|---|---|")
    for ac, c in sorted(by_class.items(), key=lambda x: -sum(x[1].values())):
        n = sum(c.values())
        match = c.get("STAGE1_MATCH", 0)
        neu = c.get("STAGE1_NEUTRAL", 0)
        opp = c.get("STAGE1_OPPOSITE", 0)
        bn = c.get("BERND_NEUTRAL", 0)
        er = c.get("ERROR", 0)
        match_rate = 100*match/(n-bn-er) if (n-bn-er) > 0 else 0
        lines.append(f"| {ac} ({n}) | {match} ({match_rate:.0f}%) | {neu} | {opp} | {bn} | {er} |")
    lines.append("")

    lines.append("## Failed indicator tallies\n")
    lines.append("For STAGE1_NEUTRAL cases (Bernd had a direction; system said hold), counts how many cases had each indicator opposing or neutral relative to Bernd's direction.\n")
    lines.append("| Indicator | Opposing | Neutral | Total disagree |")
    lines.append("|---|---|---|---|")
    all_inds = set(opposing_indicator_count) | set(neutral_indicator_count)
    for ind in sorted(all_inds, key=lambda x: -(opposing_indicator_count[x] + neutral_indicator_count[x])):
        opp = opposing_indicator_count[ind]
        neu = neutral_indicator_count[ind]
        lines.append(f"| {ind} | {opp} | {neu} | {opp+neu} |")
    lines.append("")

    lines.append("## Failed indicator by asset class\n")
    for ac in sorted(indicator_by_class):
        lines.append(f"### {ac}")
        for k, v in sorted(indicator_by_class[ac].items(), key=lambda x: -x[1]):
            lines.append(f"- {k}: {v}")
        lines.append("")

    lines.append("## STAGE1_OPPOSITE detail (system said opposite direction)\n")
    if not opposite_failures_by_class:
        lines.append("None.\n")
    else:
        total_opp = sum(len(v) for v in opposite_failures_by_class.values())
        lines.append(f"Total: {total_opp}\n")
        for ac, rows in sorted(opposite_failures_by_class.items(), key=lambda x: -len(x[1])):
            lines.append(f"### {ac} ({len(rows)})")
            for r in rows:
                comps = ", ".join(f"{k}={v}" for k, v in r["components"].items())
                lines.append(f"- Case {r['case_index']:>3} {r['symbol']:<8} {r['call_date']} [{r['strategy']}] Bernd={r['bernd']:<7} Sys={r['sys']:<7} | {comps}")
                lines.append(f"   Reasoning: {r['reasoning']}")
            lines.append("")

    lines.append("## STAGE1_NEUTRAL detail (sample first 5 per asset class)\n")
    for ac, rows in sorted(neutral_failures_by_class.items(), key=lambda x: -len(x[1])):
        lines.append(f"### {ac} ({len(rows)} total)")
        for r in rows[:5]:
            comps = ", ".join(f"{k}={v}" for k, v in r["components"].items())
            disagree = ", ".join(f"{i}({k})" for i, k in r["disagreeing"])
            lines.append(f"- Case {r['case_index']:>3} {r['symbol']:<8} {r['call_date']} [{r['strategy']}] Bernd={r['bernd']:<7} Sys=neutral")
            lines.append(f"   Components: {comps}")
            lines.append(f"   Disagreeing with Bernd ({r['bernd']}): {disagree}")
            lines.append(f"   Reasoning: {r['reasoning']}")
        if len(rows) > 5:
            lines.append(f"   ... and {len(rows)-5} more")
        lines.append("")

    out_path = args.output
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Wrote {out_path}")
    print(f"Cases: {len(cases)} | Outcomes: {dict(outcomes)}")

if __name__ == "__main__":
    main()
