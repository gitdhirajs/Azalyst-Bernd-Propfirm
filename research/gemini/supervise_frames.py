#!/usr/bin/env python3
"""Keep reading frames until the corpus is finished. Survive quota exhaustion.

WHY A SUPERVISOR
`read_practical_trades.py` stops when the KeyPool is spent -- correctly, there is
nothing else it can do. But the corpus needs several daily quota windows to finish,
and a run that dies at the first 429 makes no progress overnight.

This wraps it in a loop: read until the pool is spent, sleep until quota has had a
chance to reset, resume. The reader is idempotent (a frame already in the .jsonl is
skipped), so resuming costs nothing and cannot double-read.

    python gemini/supervise_frames.py --corpus practical
    python gemini/supervise_frames.py --corpus signals --sleep-min 45

It stops for exactly two reasons: the corpus is complete, or --max-hours elapses.
Everything else -- 429, 503, timeouts, a model retiring, the whole pool retiring --
is treated as "wait and continue".

Progress is printed each cycle so the log shows whether it is still advancing or
merely spinning against a hard quota wall.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
READER = HERE / "read_practical_trades.py"

CORPORA = {
    "practical": (Path(r"D:/Trading/Output/Funded Traders/Practical Application"),
                  HERE / "out" / "practical_trades.jsonl"),
    "signals":   (Path(r"D:/Trading/Output/Funded Traders/Funded Trader Signals"),
                  HERE / "out" / "signals_trades.jsonl"),
    "weekly":    (Path(r"D:/Trading/Output/Funded Traders/Funded Trader Weekly Outlook"),
                  HERE / "out" / "weekly_trades.jsonl"),
    "hybrid":    (Path(r"D:/Trading/Output/Bernd Skorupinski  Hybrid AI Trading"),
                  HERE / "out" / "hybrid_trades.jsonl"),
    "otc":       (Path(r"D:/Trading/Output/Bernd_Skorupinski Campus Blueprint OTC"),
                  HERE / "out" / "otc_trades.jsonl"),
}


def corpus_total(root: Path) -> int:
    """Source frames at ANY depth, excluding derived artefacts.

    The one-level version of this reported Weekly Outlook as 0/0 -- it nests a
    year directory -- so 6,283 frames were invisible to every progress readout in
    the project. It must also skip `_`-prefixed directories: `_python_vision_output`
    holds `frame_*_overlay.jpg`, annotated copies that match a naive glob.
    """
    n = 0
    for f in root.rglob("frame_*.jpg"):
        if any(part.startswith("_") for part in f.relative_to(root).parts):
            continue
        if f.stem.endswith("_overlay"):
            continue
        n += 1
    return n


def eligible_zero(corpus: str, include_unranked: bool) -> bool:
    """True when the reader has no unread frames it is permitted to read."""
    import subprocess as _sp
    cmd = [sys.executable, str(READER), "--corpus", corpus, "--limit", "1", "--dry-run"]
    if include_unranked:
        cmd.append("--include-unranked")
    r = _sp.run(cmd, capture_output=True, text=True)
    for line in (r.stdout or "").splitlines():
        if "this run:" in line:
            try:
                return int(line.rsplit("this run:", 1)[1].strip().split()[0]) == 0
            except (ValueError, IndexError):
                return False
    return False


def progress(out_file: Path):
    """(frames read, complete setups) so far."""
    if not out_file.exists():
        return 0, 0
    read = setups = 0
    for line in open(out_file, encoding="utf-8"):
        try:
            d = json.loads(line).get("data") or {}
        except Exception:
            continue
        read += 1
        if d.get("has_position_tool") and d.get("entry") and d.get("stop"):
            setups += 1
    return read, setups


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", choices=sorted(CORPORA), default="practical")
    ap.add_argument("--batch", type=int, default=600, help="frames requested per cycle")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--sleep-min", type=int, default=40,
                    help="minutes to wait after a cycle makes no progress")
    ap.add_argument("--max-hours", type=float, default=48.0)
    ap.add_argument("--include-unranked", action="store_true",
                    help="pass through to the reader; needed to finish a corpus")
    a = ap.parse_args()

    root, out_file = CORPORA[a.corpus]
    total = corpus_total(root)
    deadline = datetime.now() + timedelta(hours=a.max_hours)
    cycle = 0
    stalls = 0

    print(f"supervising '{a.corpus}': {total} frames in corpus")
    print(f"deadline {deadline:%Y-%m-%d %H:%M}   batch {a.batch}   workers {a.workers}\n",
          flush=True)

    while datetime.now() < deadline:
        cycle += 1
        before, setups_before = progress(out_file)
        if before >= total:
            print(f"[cycle {cycle}] CORPUS COMPLETE: {before}/{total} frames, "
                  f"{setups_before} setups", flush=True)
            return
        print(f"[cycle {cycle}] {datetime.now():%H:%M}  at {before}/{total} frames, "
              f"{setups_before} setups -- starting batch", flush=True)

        subprocess.run(
            [sys.executable, "-u", str(READER), "--corpus", a.corpus,
             "--limit", str(a.batch), "--workers", str(a.workers)]
            + (["--include-unranked"] if a.include_unranked else []),
            capture_output=True, text=True,
        )

        after, setups_after = progress(out_file)
        gained = after - before
        print(f"[cycle {cycle}] {datetime.now():%H:%M}  +{gained} frames, "
              f"+{setups_after - setups_before} setups  -> {after}/{total}", flush=True)

        if after >= total:
            print(f"CORPUS COMPLETE: {after}/{total} frames, {setups_after} setups",
                  flush=True)
            return

        if gained == 0 and eligible_zero(a.corpus, a.include_unranked):
            # Not a quota wall: the reader has nothing left it is ALLOWED to read.
            # Sleeping here waits forever. This masked a finished signals corpus as
            # "347 frames remaining, quota-blocked" for hours.
            print(f"[cycle {cycle}] no ELIGIBLE frames left "
                  f"(corpus counts {total}, reader admits fewer). "
                  f"Re-run with --include-unranked to read the deprioritised folders.",
                  flush=True)
            return
        if gained == 0:
            stalls += 1
            # Back off further the longer the wall persists, but never give up:
            # a daily quota window can be hours away.
            wait = min(a.sleep_min * min(stalls, 3), 120)
            print(f"[cycle {cycle}] no progress (stall {stalls}) -- quota wall. "
                  f"sleeping {wait} min", flush=True)
            time.sleep(wait * 60)
        else:
            stalls = 0
            time.sleep(60)

    read, setups = progress(out_file)
    print(f"deadline reached: {read}/{total} frames, {setups} setups", flush=True)


if __name__ == "__main__":
    main()
