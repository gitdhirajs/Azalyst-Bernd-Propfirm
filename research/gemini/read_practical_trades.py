#!/usr/bin/env python3
"""Mine DRAWN TRADE LEVELS from the Practical Application frames with Gemini vision.

WHY
The corpus can measure whether our DIRECTION matches theirs. It cannot measure whether
either makes money, and direction is demonstrably the wrong axis:

  * their own KPI slide sets 1:2 R:R and a 40:60 win:loss -- a 40% win rate carried by
    2R winners, not a high hit rate;
  * measured on 72 of their frame calls, holding their direction blindly for 60 bars won
    75.0% -- but ALWAYS-LONG on the same symbols and dates won 80.8%. Their directional
    selection did not beat buying everything, at any horizon tested.

That test threw away the part they would say is the edge: WHERE they enter and where the
stop goes. `support_resistance_levels` in the existing Signals/Weekly analysis is a flat
unlabelled list -- it cannot say which number is the entry and which is the stop, so no
R-multiple can be computed from it.

This asks for the labelled levels directly, so each call becomes
(entry, stop, target) and can be run through goldtest/replay_trades.py for expectancy
in R -- the number that actually decides whether this is tradeable.

The Practical Application corpus is the right place to look: 2,176 frames, 18 folders,
and NONE of them have ever been analysed for trade decisions (`_gemini_analysis_output`
does not exist for any of them). The teaching sessions in it -- LTF Entries, Zoning
Process, Location, Direction -- are where trades are actually drawn on screen.

    python gemini/read_practical_trades.py --dry-run
    python gemini/read_practical_trades.py --limit 60

Output: gemini/out/practical_trades.jsonl, resumable (a frame already present is skipped).

QUOTA. Both keys are free-tier; the runner's own status line puts the ceiling near 400
reads/day across all (key, model) pairs. 2,176 frames is several days at that rate, so
frames are PRIORITISED, not swept -- the trade-teaching folders first, and within a folder
the frames the existing legend pass already saw chart content on. Check C-91 before
blaming the API for being slow.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from gemini_vision import KeyPool, load_keys, read_image        # noqa: E402

CORPUS_CHOICES = {
    # Teaching sessions. Useful for confirming HOW setups are drawn -- the 27
    # valid ones read here have a median R:R of 2.0, matching the 1:2 KPI slide --
    # but NOT for expectancy: they demonstrate both a long and a short on the same
    # instrument on the same day, because they are worked examples, not calls.
    "practical": (Path(r"D:/Trading/Output/Funded Traders/Practical Application"),
                  "practical_trades.jsonl"),
    # The live weekly trade calls. This is the population expectancy has to come
    # from. Its `support_resistance_levels` are an unlabelled list, which is what
    # broke the earlier reconstruction -- the position-tool prompt does not need
    # labels, it reads entry and stop off the drawn tool.
    "signals":   (Path(r"D:/Trading/Output/Funded Traders/Funded Trader Signals"),
                  "signals_trades.jsonl"),
    # 6,283 frames that were reported as ZERO for the whole project, because this
    # corpus nests a year level (root/2023/<session>/) and frame discovery only
    # looked one directory down. Same genre as Signals -- live weekly calls with
    # drawn charts -- so it is the largest untapped source of drawn setups.
    "weekly":    (Path(r"D:/Trading/Output/Funded Traders/Funded Trader Weekly Outlook"),
                  "weekly_trades.jsonl"),
    # Course material, not live calls. Worked examples demonstrate both sides of a
    # trade on the same instrument, so these are evidence about HOW a setup is drawn
    # and must never be pooled into an expectancy population (same caveat as
    # `practical`, and see C-115 on drawn zones not being trades).
    "hybrid":    (Path(r"D:/Trading/Output/Bernd Skorupinski  Hybrid AI Trading"),
                  "hybrid_trades.jsonl"),
    "otc":       (Path(r"D:/Trading/Output/Bernd_Skorupinski Campus Blueprint OTC"),
                  "otc_trades.jsonl"),
    "weekly":    (Path(r"D:/Trading/Output/Funded Traders/Funded Trader Weekly Outlook"),
                  "weekly_trades.jsonl"),
}
CORPUS = CORPUS_CHOICES["practical"][0]
OUT = HERE / "out" / "practical_trades.jsonl"

# Sessions where a trade is most likely to be drawn, best first.
PRIORITY = ["LTF Entries", "Zoning Process", "Location", "Direction",
            "Valuation", "Seasonality", "Beginner Breakout Room"]

PROMPT = """You are reading ONE screenshot from a trading education session. Report only
what is actually drawn or written on the chart. Never infer a number that is not visible.

I need the TRADE SETUP, if one is drawn:

1. chart_symbol_text -- the instrument symbol exactly as shown.
2. timeframe -- Daily / Weekly / Monthly / 240 min / 60 min / 15 min, as written.
3. has_position_tool -- true if the chart shows a long/short position tool: the paired
   coloured boxes (typically green = profit/target side, red = risk/stop side) that a
   platform draws between an entry line, a stop line and a target line. false otherwise.
4. direction -- "long" | "short" | null. For a position tool, the target box sits ABOVE
   the entry for a long and BELOW for a short.
5. entry / stop / target -- the numeric price levels of the position tool, read off the
   labels or the price axis. Return null for any you cannot read. DO NOT guess, and do
   not compute one from the others.
6. zone_proximal / zone_distal -- if a highlighted supply or demand zone (a coloured
   rectangle) is drawn, the price at its near edge and far edge. null if absent.
7. drawn_levels -- any other horizontal lines with readable prices, as numbers.
8. annotation_text -- any text the instructor typed on the chart.

If NO trade is drawn, set has_position_tool false, direction null, and the price fields
null. That is a completely valid answer and is expected on most frames -- most are
lecture slides, watchlists or bare charts.

Return STRICT JSON:
{
  "chart_symbol_text": string|null,
  "timeframe": string|null,
  "has_position_tool": boolean,
  "direction": string|null,
  "entry": number|null,
  "stop": number|null,
  "target": number|null,
  "zone_proximal": number|null,
  "zone_distal": number|null,
  "drawn_levels": [number],
  "annotation_text": string|null,
  "unreadable_notes": string|null
}"""

SCHEMA = {
    "type": "object",
    "properties": {
        "chart_symbol_text": {"type": "string", "nullable": True},
        "timeframe": {"type": "string", "nullable": True},
        "has_position_tool": {"type": "boolean"},
        "direction": {"type": "string", "nullable": True},
        "entry": {"type": "number", "nullable": True},
        "stop": {"type": "number", "nullable": True},
        "target": {"type": "number", "nullable": True},
        "zone_proximal": {"type": "number", "nullable": True},
        "zone_distal": {"type": "number", "nullable": True},
        "drawn_levels": {"type": "array", "items": {"type": "number"}},
        "annotation_text": {"type": "string", "nullable": True},
        "unreadable_notes": {"type": "string", "nullable": True},
    },
    "required": ["has_position_tool", "direction", "entry", "stop", "target"],
}


# Signals folders ranked by how many directional decisions the EXISTING
# chart_analysis pass already found in them. Quota is the binding constraint, so
# frames are spent where trades are known to exist.
#
# This is not an optimisation, it is a correction. Without it `folder_rank`
# returns the same value for every Signals folder and the ordering falls back to
# alphabetical -- which starts on `01.02.2024`, one of the two folders
# RESUME_NEXT_SESSION.md explicitly records as containing ZERO signals ("they are
# market overviews, not entries"). 60 frames were read there for 0 position tools
# before this was caught.
#
# 22 of 29 Signals folders contain at least one decision; 7 contain none and are
# skipped entirely.
_RANK_FILE = HERE / "out" / "signals_folder_rank.json"
try:
    _FOLDER_DECISIONS = json.load(open(_RANK_FILE, encoding="utf-8"))
except Exception:
    _FOLDER_DECISIONS = {}


def session_dirs(root: Path):
    """Every directory anywhere under `root` that DIRECTLY holds source frames.

    The corpora are not uniformly shaped. Signals and Practical are flat --
    root/<session>/frame_*.jpg -- but Weekly Outlook nests a year level in
    between, root/2023/<session>/frame_*.jpg. The original one-level `glob`
    silently reported that corpus as EMPTY: 6,283 frames, counted as 0, for the
    whole project. Walking to whatever depth the frames actually sit at fixes
    that without needing a per-corpus layout config.

    Directories whose path contains a `_`-prefixed component are skipped. Those
    hold DERIVED artefacts from earlier tooling -- `_python_vision_output`
    contains `frame_000001_overlay.jpg`, which matches a naive `frame_*.jpg`
    glob and is an ANNOTATED copy of a frame. Reading those back would feed the
    model its own earlier overlays and count them as new evidence.
    """
    for d in sorted(p for p in root.rglob("*") if p.is_dir()):
        rel = d.relative_to(root).parts
        if any(part.startswith("_") for part in rel):
            continue
        if any(session_frames(d)):
            yield d


def session_frames(d: Path):
    """Source frames in one directory: `frame_*.jpg`, minus derived overlays."""
    return [f for f in sorted(d.glob("frame_*.jpg"))
            if not f.stem.endswith("_overlay")]


def folder_rank(name):
    # evidence-ranked corpora first: most known decisions -> lowest rank
    if _FOLDER_DECISIONS:
        n = _FOLDER_DECISIONS.get(name)
        if n is not None:
            return -n            # 26 decisions sorts before 7
        if name in _FOLDER_DECISIONS or any(k.endswith("Funded Trader Signals")
                                            for k in _FOLDER_DECISIONS):
            # a Signals folder with no recorded decision -- push to the very back
            if name.endswith("Funded Trader Signals"):
                return 10_000
    for i, p in enumerate(PRIORITY):
        if p.lower() in name.lower():
            return i
    return len(PRIORITY)


def session_date(name):
    m = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", name)
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


INCLUDE_UNRANKED = False


def targets(breadth=True):
    """Frames worth reading.

    BREADTH-FIRST BY DEFAULT, and that is the important part. Reading one folder
    to exhaustion answers "does THIS session draw position tools"; interleaving
    across folders answers "does this CORPUS draw them", which is the actual
    question. The first Signals run went depth-first and spent 68 of its 105
    frames inside a single folder that RESUME_NEXT_SESSION.md already recorded as
    containing zero signals -- so a corpus-level conclusion got drawn from 37
    frames in one good folder. Round-robin makes that mistake impossible: n
    frames of budget become n/22 frames from each of 22 folders.
    """
    by_folder = {}
    for d in sorted(session_dirs(CORPUS), key=lambda x: folder_rank(x.name)):
        folder = d.name
        rank = folder_rank(folder)
        if rank >= 10_000 and not INCLUDE_UNRANKED:
            # A Signals folder with no recorded decision. Deprioritising these was
            # right while budget was scarce -- read the known-productive sessions
            # first. But `continue` DROPS them, it does not defer them, so the
            # corpus could never finish: 2,509 frames existed, 2,094 were ever
            # eligible, and the supervisor read 2,162 and then reported the
            # remainder as a permanent "quota wall" while sleeping on a corpus that
            # had nothing left it was allowed to touch.
            # With --include-unranked they are read LAST rather than never.
            continue
        by_folder[folder] = [
            {"folder": folder, "date": session_date(folder), "frame": f.name,
             "path": str(f), "rank": rank}
            for f in sorted(session_frames(d))
        ]
    if not breadth:
        return [t for fr in by_folder.values() for t in fr]
    out, i = [], 0
    while any(len(v) > i for v in by_folder.values()):
        for fr in by_folder.values():
            if len(fr) > i:
                out.append(fr[i])
        i += 1
    return out


def already_done():
    if not OUT.exists():
        return set()
    done = set()
    for line in open(OUT, encoding="utf-8"):
        try:
            r = json.loads(line)
            done.add((r.get("folder"), r.get("frame")))
        except Exception:
            pass
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--corpus", choices=sorted(CORPUS_CHOICES), default="practical")
    ap.add_argument("--workers", type=int, default=4,
                    help="parallel readers; KeyPool serialises quota access")
    ap.add_argument("--include-unranked", action="store_true",
                    help="also read folders with no recorded decision (ranked last). "
                         "Without this the corpus can never reach 100%.")
    ap.add_argument("--depth-first", action="store_true",
                    help="exhaust each folder in turn (default is round-robin across folders)")
    a = ap.parse_args()
    global CORPUS, OUT, INCLUDE_UNRANKED
    INCLUDE_UNRANKED = a.include_unranked
    CORPUS, _out = CORPUS_CHOICES[a.corpus]
    OUT = HERE / "out" / _out
    print(f"corpus: {a.corpus}  ->  {CORPUS}")

    tg = targets(breadth=not a.depth_first)
    done = already_done()
    todo = [t for t in tg if (t["folder"], t["frame"]) not in done][:a.limit]
    print(f"frames in corpus: {len(tg)}   already read: {len(done)}   this run: {len(todo)}")
    by = collections.Counter(t["folder"] for t in todo)
    for k, v in by.most_common(8):
        print(f"   {v:>4}  {k}")
    if a.dry_run:
        return

    pool = KeyPool(load_keys())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    hits = ok = fail = 0

    # PARALLEL WORKERS. KeyPool already hands out (key, model) slots and is the
    # thing that serialises access to the quota, so N workers simply keep more of
    # those slots busy instead of one at a time -- 2 keys x ~10 models is 20 pairs
    # and a serial loop uses one. Matches the --workers pattern the existing
    # run_weekly_backlog.py / run_practical_backlog.py already use.
    # Writes are guarded by a lock: the file is appended from every worker and a
    # torn line would corrupt the resume set.
    import threading
    from concurrent.futures import ThreadPoolExecutor
    lock = threading.Lock()

    def work(item):
        nonlocal hits, ok, fail
        i, t = item
        try:
            w = read_image(t["path"], pool, prompt=PROMPT, schema=SCHEMA)
        except SystemExit as exc:
            with lock:
                print(f"\nQUOTA EXHAUSTED after {ok} reads this run: {exc}")
            return False
        except Exception as exc:
            with lock:
                fail += 1
            return True
        data = (w or {}).get("data") or {}
        rec = {"folder": t["folder"], "date": t["date"], "frame": t["frame"],
               "path": t["path"], "model": (w or {}).get("model"), "data": data}
        with lock:
            fh.write(json.dumps(rec, default=str) + "\n")
            fh.flush()
            ok += 1
            if data.get("has_position_tool") and data.get("entry") and data.get("stop"):
                hits += 1
                print(f"[{ok}/{len(todo)}] TRADE  {data.get('chart_symbol_text')} "
                      f"{data.get('direction')} entry={data.get('entry')} "
                      f"stop={data.get('stop')} target={data.get('target')}")
            elif ok % 25 == 0:
                print(f"[{ok}/{len(todo)}] ... {hits} setups so far")
        return True

    with open(OUT, "a", encoding="utf-8") as fh:
        if a.workers > 1:
            with ThreadPoolExecutor(max_workers=a.workers) as ex:
                for alive in ex.map(work, enumerate(todo, 1)):
                    if alive is False:
                        break
            print(f"\nread {ok}, failed {fail}, COMPLETE SETUPS (entry+stop) {hits}  ->  {OUT}")
            return
        for i, t in enumerate(todo, 1):
            try:
                w = read_image(t["path"], pool, prompt=PROMPT, schema=SCHEMA)
            except SystemExit as exc:
                # gemini_vision raises SystemExit (NOT Exception) when the key pool
                # is spent -- see its `raise SystemExit(` path. A bare
                # `except Exception` does not catch it, so the run dies silently
                # mid-corpus and the log just stops. Caught here so the partial
                # result is reported instead of vanishing.
                print(f"\nQUOTA EXHAUSTED after {ok} reads this run: {exc}")
                break
            except Exception as exc:
                print(f"[{i}/{len(todo)}] {t['frame']} ERROR {type(exc).__name__}")
                fail += 1
                continue
            data = (w or {}).get("data") or {}
            rec = {"folder": t["folder"], "date": t["date"], "frame": t["frame"],
                   "path": t["path"], "model": (w or {}).get("model"), "data": data}
            fh.write(json.dumps(rec, default=str) + "\n")
            fh.flush()
            ok += 1
            if data.get("has_position_tool") and data.get("entry") and data.get("stop"):
                hits += 1
                print(f"[{i}/{len(todo)}] TRADE  {data.get('chart_symbol_text')} "
                      f"{data.get('direction')} entry={data.get('entry')} "
                      f"stop={data.get('stop')} target={data.get('target')}")
    print(f"\nread {ok}, failed {fail}, COMPLETE SETUPS (entry+stop) {hits}  ->  {OUT}")


if __name__ == "__main__":
    main()
