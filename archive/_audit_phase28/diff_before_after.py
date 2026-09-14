"""Compare two goldtest result JSONs and produce a before-after diff report.

Usage:
    python diff_before_after.py BEFORE.json AFTER.json --output BEFORE_AFTER.md
"""
import json
import sys
import argparse
from collections import Counter, defaultdict


NEUTRAL = {"neutral", "hold", None, ""}
LONG = {"long", "bullish"}
SHORT = {"short", "bearish"}
UPTREND = {"uptrend"}
DOWNTREND = {"downtrend"}


def norm(x):
    if x is None:
        return "neutral"
    s = str(x).lower().strip()
    if s in NEUTRAL or s == "sideways":
        return "neutral"
    if s in LONG or s in UPTREND:
        return "bullish"
    if s in SHORT or s in DOWNTREND:
        return "bearish"
    return "neutral"


def classify(case):
    bernd = norm((case.get("bernd") or {}).get("bias"))
    sys_only = norm((case.get("system") or {}).get("bias_only"))
    sys_dir = norm((case.get("system") or {}).get("direction"))
    err = case.get("error")
    if err:
        return "ERROR"
    if bernd == "neutral":
        return "BERND_NEUTRAL"
    if sys_only == bernd:
        return "MATCH"
    if sys_only == "neutral":
        return "NEUTRAL"
    return "OPPOSITE"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("before")
    ap.add_argument("after")
    ap.add_argument("--output", default=r"D:\Azalyst Bernd Skorupinski\BEFORE_AFTER.md")
    args = ap.parse_args()

    with open(args.before) as f:
        before = {r["case_index"]: r for r in json.load(f)["results"]}
    with open(args.after) as f:
        after = {r["case_index"]: r for r in json.load(f)["results"]}

    common = sorted(set(before) & set(after))

    before_outcomes = Counter()
    after_outcomes = Counter()
    transitions = Counter()
    by_class_before = defaultdict(Counter)
    by_class_after = defaultdict(Counter)
    gained = []      # NEUTRAL/OPPOSITE/ERROR -> MATCH
    lost = []        # MATCH -> NEUTRAL/OPPOSITE/ERROR
    same_match = 0
    same_other = 0

    for i in common:
        b = before[i]
        a = after[i]
        bc = classify(b)
        ac = classify(a)
        before_outcomes[bc] += 1
        after_outcomes[ac] += 1
        transitions[(bc, ac)] += 1
        cls = b.get("asset_class", "?")
        by_class_before[cls][bc] += 1
        by_class_after[cls][ac] += 1
        if bc == "MATCH" and ac == "MATCH":
            same_match += 1
        elif bc != "MATCH" and ac == "MATCH":
            gained.append({
                "case_index": i, "symbol": b["symbol"], "call_date": b["call_date"],
                "bernd": (b.get("bernd") or {}).get("bias"),
                "before_sys": (b.get("system") or {}).get("bias_only"),
                "after_sys": (a.get("system") or {}).get("bias_only"),
                "before_class": bc, "after_class": ac,
                "before_components": (b.get("system") or {}).get("bias_components"),
                "after_components": (a.get("system") or {}).get("bias_components"),
            })
        elif bc == "MATCH" and ac != "MATCH":
            lost.append({
                "case_index": i, "symbol": b["symbol"], "call_date": b["call_date"],
                "bernd": (b.get("bernd") or {}).get("bias"),
                "before_sys": (b.get("system") or {}).get("bias_only"),
                "after_sys": (a.get("system") or {}).get("bias_only"),
                "before_class": bc, "after_class": ac,
                "before_components": (b.get("system") or {}).get("bias_components"),
                "after_components": (a.get("system") or {}).get("bias_components"),
            })
        else:
            same_other += 1

    lines = []
    lines.append("# Phase 28 Goldtest BEFORE vs AFTER\n")
    lines.append(f"Before: `{args.before}`")
    lines.append(f"After:  `{args.after}`")
    lines.append(f"Common cases compared: **{len(common)}**\n")
    lines.append("## Overall outcome distribution\n")
    lines.append("| Outcome | Before | After | Delta |")
    lines.append("|---|---|---|---|")
    keys = sorted(set(before_outcomes) | set(after_outcomes))
    for k in ["MATCH", "NEUTRAL", "OPPOSITE", "BERND_NEUTRAL", "ERROR"]:
        b = before_outcomes.get(k, 0)
        a = after_outcomes.get(k, 0)
        d = a - b
        sign = "+" if d > 0 else ""
        lines.append(f"| {k} | {b} | {a} | {sign}{d} |")
    lines.append("")
    n = len(common)
    m_b = before_outcomes.get("MATCH", 0)
    m_a = after_outcomes.get("MATCH", 0)
    lines.append(f"**Stage 1 match rate**: {m_b}/{n} = {100*m_b/n:.1f}% (before) -> {m_a}/{n} = {100*m_a/n:.1f}% (after). Delta: {m_a-m_b:+d} cases ({(m_a-m_b)/n*100:+.1f}pp).\n")
    o_b = before_outcomes.get("OPPOSITE", 0)
    o_a = after_outcomes.get("OPPOSITE", 0)
    lines.append(f"**Stage 1 opposites** (filtered at Stage 2): {o_b} (before) -> {o_a} (after). Delta: {o_a-o_b:+d}.\n")

    lines.append("## Per asset class\n")
    lines.append("| Asset Class | Before MATCH | After MATCH | Delta |")
    lines.append("|---|---|---|---|")
    all_classes = sorted(set(by_class_before) | set(by_class_after))
    for cls in all_classes:
        bm = by_class_before[cls].get("MATCH", 0)
        am = by_class_after[cls].get("MATCH", 0)
        total = sum(by_class_before[cls].values())
        d = am - bm
        sign = "+" if d > 0 else ""
        lines.append(f"| {cls} ({total}) | {bm} | {am} | {sign}{d} |")
    lines.append("")

    lines.append("## Transitions\n")
    lines.append("| Before | After | Count |")
    lines.append("|---|---|---|")
    for (bc, ac), cnt in sorted(transitions.items(), key=lambda x: -x[1]):
        lines.append(f"| {bc} | {ac} | {cnt} |")
    lines.append("")

    lines.append(f"## Cases GAINED (was non-match, now MATCH) — {len(gained)}\n")
    if not gained:
        lines.append("None.\n")
    for g in gained:
        lines.append(f"### Case {g['case_index']} {g['symbol']} {g['call_date']}")
        lines.append(f"- Bernd: {g['bernd']}")
        lines.append(f"- Before: {g['before_class']} (sys={g['before_sys']})")
        lines.append(f"- After:  {g['after_class']} (sys={g['after_sys']})")
        lines.append(f"- Before components: {g['before_components']}")
        lines.append(f"- After components:  {g['after_components']}")
        lines.append("")

    lines.append(f"## Cases LOST (was MATCH, now non-match) — {len(lost)}\n")
    if not lost:
        lines.append("None.\n")
    for l in lost:
        lines.append(f"### Case {l['case_index']} {l['symbol']} {l['call_date']}")
        lines.append(f"- Bernd: {l['bernd']}")
        lines.append(f"- Before: {l['before_class']} (sys={l['before_sys']})")
        lines.append(f"- After:  {l['after_class']} (sys={l['after_sys']})")
        lines.append(f"- Before components: {l['before_components']}")
        lines.append(f"- After components:  {l['after_components']}")
        lines.append("")

    lines.append(f"## Same MATCH: {same_match} cases. Same non-MATCH: {same_other} cases.\n")

    with open(args.output, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Wrote {args.output}")
    print(f"Before MATCH: {m_b}/{n} = {100*m_b/n:.1f}%")
    print(f"After  MATCH: {m_a}/{n} = {100*m_a/n:.1f}%")
    print(f"Delta: {m_a-m_b:+d} cases ({(m_a-m_b)/n*100:+.1f}pp)")
    print(f"Gained: {len(gained)} | Lost: {len(lost)}")


if __name__ == "__main__":
    main()
