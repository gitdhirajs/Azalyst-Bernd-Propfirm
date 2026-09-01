#!/usr/bin/env python3
"""Extract STATED ZONE-SELECTION RULES from the course corpora.

WHY THIS EXISTS AND WHY IT IS NOT read_practical_trades.py

C-113 measured the ceiling on the engine's Stage-1 inputs and found nothing: 575 feature
subsets across three families, best result -0.47 points versus a constant. Its conclusion
was that **the bottleneck is the FEATURES, not the rules** -- no rule over
location/trend/COT/valuation/seasonality can work, because those inputs carry no
out-of-sample signal.

C-119 then located the one defect that survives: the same limit-at-zone-proximal mechanic
wins on their zones (8:1, p=0.039) and loses on ours (2:5, 4:5), Fisher p=0.035. The edge
is in WHICH ZONE is chosen. C-121 tried to learn that choice supervised and found nothing
at n=140.

So the open question is not "what rule over our features" but "what does he look at that
we do not compute at all". The Hybrid AI and Campus Blueprint corpora are 9,339 frames of
him TEACHING zone selection. That is the one place a criterion we never implemented would
be named out loud.

    python gemini/read_course_rules.py --corpus otc --limit 400
    python gemini/read_course_rules.py --corpus hybrid --limit 800

This deliberately does NOT extract position tools. Course frames are worked examples --
they demonstrate a long and a short on the same instrument on the same day -- and C-115
established that a drawn zone is not a trade and must never enter an expectancy
population. Nothing here is evidence about outcomes. It is evidence about CRITERIA, to be
turned into a computable feature and then tested like anything else, through
goldtest/verdict.py.

Output: gemini/out/course_rules.jsonl, one record per frame.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import read_practical_trades as R

PROMPT = """You are reading ONE screenshot from a trading course by Bernd Skorupinski on
supply/demand zone trading. Report ONLY what is visibly written or drawn. Never infer.

I am looking for STATED RULES ABOUT WHICH ZONES TO TRADE OR SKIP -- not for trade setups.

1. slide_text -- any instructional text, bullet points, headings or typed annotations
   visible on the frame, transcribed verbatim. This is the most important field.
2. states_a_rule -- true ONLY if the frame states a criterion, condition, filter or
   checklist item about zones, entries or trade selection. A bare chart with no text is
   false. A watchlist is false.
3. rule_kind -- one of: "zone_quality" (what makes a zone good or bad),
   "zone_reject" (when NOT to take a zone), "entry_timing", "risk", "bias_direction",
   "other". null if states_a_rule is false.
4. rule_text -- the criterion in his words, one or two sentences, quoted from the frame.
   null if states_a_rule is false.
5. mentions_measurable -- list any CONCRETE, MEASURABLE quantity the rule refers to:
   e.g. "number of candles in base", "percentage penetration into zone", "distance to
   current price", "how many times the zone was tested", "time since zone formed",
   "higher timeframe zone overlap", "distance to opposing zone". Use short phrases.
   Empty list if the rule is purely qualitative.
6. chart_symbol_text -- instrument symbol if one is shown, else null.

Most frames will have states_a_rule false. That is expected and correct."""

# NOTE the nullable convention. Gemini's response_schema is a protobuf, and a JSON-Schema
# union like {"type": ["string", "null"]} is rejected with
#   Unknown name "type" ... Proto field is not repeating, cannot start list
# The API returns HTTP 400, read_image records ok:false with data:null, and the caller
# sees an empty dict -- indistinguishable from "the model found nothing". A first run of
# 12 frames reported "0 rules found" that way. Use {"type": "...", "nullable": True},
# matching read_practical_trades.SCHEMA.
SCHEMA = {
    "type": "object",
    "properties": {
        "slide_text": {"type": "string", "nullable": True},
        "states_a_rule": {"type": "boolean"},
        "rule_kind": {"type": "string", "nullable": True},
        "rule_text": {"type": "string", "nullable": True},
        "mentions_measurable": {"type": "array", "items": {"type": "string"}},
        "chart_symbol_text": {"type": "string", "nullable": True},
    },
    "required": ["states_a_rule", "rule_kind", "rule_text", "mentions_measurable"],
}

OUT = HERE / "out" / "course_rules.jsonl"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="otc", choices=sorted(R.CORPUS_CHOICES))
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    R.CORPUS = R.CORPUS_CHOICES[a.corpus][0]
    R.INCLUDE_UNRANKED = True
    targets = R.targets(breadth=True)

    # Start each lesson from its MIDDLE, not its first frame.
    # R.targets round-robins index 0 of every folder, then index 1, and so on. On the
    # trade corpora that is right -- a position tool can appear anywhere. On course
    # material the opening frames are title cards and intros: a first run of 30 frames
    # produced 0 rules, while a hand-probe of mid-lesson frames hit 1 in 8. Free-tier
    # quota is the binding constraint, so frames are rotated within each folder to put
    # the teaching content first, then wrap to the head.
    byf = {}
    for t in targets:
        byf.setdefault(t["folder"], []).append(t)
    rotated = {}
    for f, rows in byf.items():
        rows.sort(key=lambda r: r["frame"])
        h = len(rows) // 2
        rotated[f] = rows[h:] + rows[:h]
    targets, i = [], 0
    while any(len(v) > i for v in rotated.values()):
        for rows in rotated.values():
            if len(rows) > i:
                targets.append(rows[i])
        i += 1

    done = set()
    if OUT.exists():
        for line in open(OUT, encoding="utf-8"):
            try:
                r = json.loads(line)
                done.add((r.get("corpus"), r.get("folder"), r.get("frame")))
            except Exception:
                pass
    todo = [t for t in targets if (a.corpus, t["folder"], t["frame"]) not in done][: a.limit]
    print(f"corpus {a.corpus}: {len(targets)} frames, {len(done)} already read, "
          f"{len(todo)} this run")
    if a.dry_run or not todo:
        for t in todo[:6]:
            print(f"   {t['folder'][:60]}  {t['frame']}")
        return

    pool = R.KeyPool(R.load_keys())
    import concurrent.futures as cf
    n_rule = 0
    with open(OUT, "a", encoding="utf-8") as fh:
        with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
            futs = {ex.submit(R.read_image, t["path"], pool,
                              prompt=PROMPT, schema=SCHEMA): t for t in todo}
            for i, fu in enumerate(cf.as_completed(futs), 1):
                t = futs[fu]
                try:
                    w = fu.result()
                except SystemExit:
                    print("  KeyPool exhausted -- stopping cleanly", flush=True)
                    break
                except Exception as e:
                    print(f"  {t['frame']}: {type(e).__name__}", flush=True)
                    continue
                if not (w or {}).get("ok"):
                    # A failed read must NOT be written as an empty result: it is
                    # indistinguishable from "no rule on this frame" and would be
                    # skipped forever by the resume logic.
                    print(f"  {t['frame']}: read failed -- "
                          f"{str((w or {}).get('error'))[:90]}", flush=True)
                    continue
                d = (w or {}).get("data") or {}
                if d.get("states_a_rule"):
                    n_rule += 1
                fh.write(json.dumps({"corpus": a.corpus, "folder": t["folder"],
                                     "frame": t["frame"], "path": t["path"],
                                     "data": d}, ensure_ascii=False) + "\n")
                fh.flush()
                if i % 25 == 0:
                    print(f"  {i}/{len(todo)}   rules found {n_rule}", flush=True)
    print(f"done: {n_rule} frames stated a rule -> {OUT}")


if __name__ == "__main__":
    main()
