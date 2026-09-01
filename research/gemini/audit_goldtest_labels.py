#!/usr/bin/env python3
"""Audit the goldtest bias labels against the Weekly Outlook transcripts.

C-85's standing ACTION was to audit `gold_cases_oos.yaml` and
`gold_cases_lectures.yaml` against source transcripts. The 133-row
`all_traders_ground_truth.csv` only overlaps 10 of the 103 goldtest labels; the
other 93 have never been checked against anything. All 93 do have an
exact-date chapter under
`D:/Trading/Output/Funded Traders/Funded Trader Weekly Outlook/`.

This groups the labels by chapter, sends each chapter's transcript to Gemini
once with the labels for that chapter, and asks for a per-label verdict with a
verbatim citation. One call per chapter, written to
`gemini/out/label_audit/<date>.json` so a rerun skips what is already done.

    python gemini/audit_goldtest_labels.py            # run the batch
    python gemini/audit_goldtest_labels.py --report   # aggregate what exists

READ THE VERDICTS AS EVIDENCE, NOT AS TRUTH. The transcripts are sparse --
roughly one sampled frame per minute -- so a symbol discussed for 90 seconds may
survive as a single fragment. INSUFFICIENT is the honest answer there and the
prompt says so explicitly. A label that cannot be sourced is a finding in its own
right, not a failure of the audit.
"""
import argparse
import collections
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJ = HERE.parent
CODE = Path(r"D:/Trading/Azalyst Bernd Skorupinski")
OUTDIR = HERE / "out" / "label_audit"
CORPUS = Path(r"D:/Trading/Output/Funded Traders/Funded Trader Weekly Outlook")

# Spoken aliases. The yaml carries yfinance tickers; nobody says "NQ=F" out loud.
ALIASES = {
    "NQ=F": ["nasdaq", "nq", "tech index"],
    "ES=F": ["s&p", "sp 500", "s and p", "es"],
    "YM=F": ["dow", "dow jones", "ym"],
    "RTY=F": ["russell", "rty"],
    "GC=F": ["gold", "gc", "xauusd"],
    "SI=F": ["silver", "si"],
    "PL=F": ["platinum"],
    "PA=F": ["palladium"],
    "HG=F": ["copper"],
    "CL=F": ["crude", "oil", "wti"],
    "NG=F": ["natural gas", "nat gas"],
    "ZC=F": ["corn"], "ZW=F": ["wheat"], "ZS=F": ["soybean", "soy"],
    "KC=F": ["coffee"], "SB=F": ["sugar"], "CC=F": ["cocoa"], "CT=F": ["cotton"],
    "ZB=F": ["bonds", "30 year", "treasury"],
    "EURUSD=X": ["euro", "eurusd", "eur usd"],
    "GBPUSD=X": ["pound", "cable", "gbpusd"],
    "USDJPY=X": ["yen", "usdjpy", "dollar yen"],
    "USDCHF=X": ["swiss", "franc", "usdchf"],
    "USDCAD=X": ["canadian", "loonie", "usdcad"],
    "AUDUSD=X": ["aussie", "australian", "audusd"],
    "NZDUSD=X": ["kiwi", "new zealand", "nzdusd"],
    "BTC-USD": ["bitcoin", "btc"], "ETH-USD": ["ethereum", "eth"],
    "DX-Y.NYB": ["dollar index", "dxy"],
}

PROMPT = """Below is the transcript of one trading lecture, sampled roughly one frame per
minute, so it is SPARSE and sometimes mid-sentence.

A previous labeller assigned a directional bias to each instrument listed under LABELS TO
CHECK. Your job is to say, for each one, whether the speaker's own words in this transcript
support that label.

CONVENTION IN FORCE -- apply it exactly:
  * LOOSE. A CONDITIONAL directional call counts as directional. "I'll buy the pullback once
    it reaches the demand zone" is LONG, not neutral.
  * An outright REFUSAL to trade the instrument is NEUTRAL, however directional the
    surrounding commentary sounds. "It keeps going lower but I never touch this market" is
    NEUTRAL, not short.
  * Commentary about an existing trade IDEA not working out ("it's running away from our
    idea", "I cannot promise anything") is about the idea, not a new directional call.

VERDICTS -- use exactly one per label:
  SUPPORTS       the transcript backs the label
  CONTRADICTS    the transcript backs a DIFFERENT label; name which one
  INSUFFICIENT   this instrument is not discussed, or only in passing with no directional
                 content. Say this freely. The transcript is sparse and an unsourceable
                 label is a real finding, not a failure. Do NOT reach for a verdict.

For SUPPORTS and CONTRADICTS you MUST quote a verbatim line from the transcript. If you
cannot quote one, the verdict is INSUFFICIENT.

Return ONLY a JSON array, no prose and no code fence:
[{"symbol": "...", "label": "...", "verdict": "SUPPORTS|CONTRADICTS|INSUFFICIENT",
  "should_be": "long|short|neutral or null", "quote": "verbatim or null",
  "timestamp": "h:mm:ss or null", "note": "one short sentence"}]
"""


def load_cases():
    import yaml
    out = []
    for f in ("gold_cases_oos.yaml", "gold_cases_lectures.yaml"):
        p = CODE / "Propfirm Trading Dashboard" / "goldtest" / f
        d = yaml.safe_load(open(p, encoding="utf-8"))
        for c in (d["cases"] if isinstance(d, dict) else d):
            out.append({"file": f, "symbol": c["symbol"],
                        "display_name": c.get("display_name", c["symbol"]),
                        "call_date": str(c["call_date"])[:10], "bias": c["bias"],
                        "reasoning": c.get("reasoning", "")})
    return out


def chapter_index():
    idx = {}
    for year in sorted(os.listdir(CORPUS)):
        ydir = CORPUS / year
        if not ydir.is_dir():
            continue
        for name in sorted(os.listdir(ydir)):
            m = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", name)
            tj = ydir / name / "transcript.json"
            if m and tj.exists():
                idx.setdefault(f"{m.group(3)}-{m.group(2)}-{m.group(1)}", []).append(tj)
    return idx


def transcript_text(paths):
    lines = []
    for p in paths:
        d = json.load(open(p, encoding="utf-8"))
        for fr in d.get("frames", []):
            t = (fr.get("transcript") or "").strip()
            if t:
                lines.append(f'[{fr.get("timestamp_hms","")}] {t}')
    return "\n".join(lines)


# Labels per API call. Chapters carrying more than this are split.
#
# Measured: the two chapters that failed outright and the one that came back with
# 1 of 16 labels were the three largest (16, 9 and 9 labels). Asked for sixteen
# verdicts in one go the flash models drift into prose, and the repair pass can
# only rescue what the prose actually contained -- on 2023-01-01 that was one row,
# and the other fifteen were dropped SILENTLY. Small batches are the fix; the
# transcript is re-sent per batch, which costs tokens and buys completeness.
LABELS_PER_CALL = 6


def run_chapter(date, paths, cases, scratch):
    body = transcript_text(paths)
    if not body.strip():
        return {"date": date, "error": "transcript has no text"}

    if len(cases) > LABELS_PER_CALL:
        merged, errors = [], []
        for i in range(0, len(cases), LABELS_PER_CALL):
            chunk = cases[i:i + LABELS_PER_CALL]
            part = _ask_chapter(date + f"_p{i // LABELS_PER_CALL}", body, chunk, scratch)
            if "verdicts" in part:
                merged.extend(part["verdicts"])
            else:
                errors.append(part.get("error"))
        if merged:
            out = {"date": date, "verdicts": merged,
                   "via": f"chunked x{-(-len(cases) // LABELS_PER_CALL)}"}
            if errors:
                out["partial_errors"] = errors
            return out
        return {"date": date, "error": "; ".join(str(e) for e in errors) or "no verdicts"}
    return _ask_chapter(date, body, cases, scratch)


def _ask_chapter(date, body, cases, scratch):
    labels = []
    for c in cases:
        al = ", ".join(ALIASES.get(c["symbol"], []))
        labels.append(f'  {c["symbol"]} ({c["display_name"]})'
                      + (f' -- spoken as: {al}' if al else '')
                      + f'  LABEL = {c["bias"]}')

    qfile = scratch / f"q_{date}.txt"
    tfile = scratch / f"t_{date}.txt"
    qfile.write_text(PROMPT + "\nLABELS TO CHECK:\n" + "\n".join(labels) + "\n",
                     encoding="utf-8")
    tfile.write_text("=== TRANSCRIPT " + date + " ===\n" + body, encoding="utf-8")

    ofile = scratch / f"a_{date}.txt"
    cmd = [sys.executable, str(HERE / "ask.py"), "-Q", str(qfile), "-f", str(tfile),
           "-o", str(ofile), "--max-output-tokens", "8000"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    raw = ofile.read_text(encoding="utf-8") if ofile.exists() else ""
    if not raw:
        return {"date": date, "error": "no answer", "stderr": r.stderr[-400:]}

    parsed = extract_json_array(raw)
    if parsed is None:
        # Repair pass. On the longest chapters the flash models sometimes answer in
        # prose despite the instruction. Re-ask with the prose attached and nothing
        # else to do but reformat it -- cheaper and more reliable than re-reading
        # the whole transcript, and it cannot invent a verdict it did not already give.
        rfile = scratch / f"r_{date}.txt"
        rfile.write_text(raw, encoding="utf-8")
        rq = scratch / f"rq_{date}.txt"
        rq.write_text(
            "The text below is an answer that was supposed to be a JSON array and is not.\n"
            "Convert it, losing nothing and inventing nothing. If the text gives no verdict\n"
            "for a symbol, omit that symbol rather than guessing one.\n\n"
            'Return ONLY the array: [{"symbol": "...", "label": "...", '
            '"verdict": "SUPPORTS|CONTRADICTS|INSUFFICIENT", "should_be": "long|short|'
            'neutral or null", "quote": "verbatim or null", "timestamp": "h:mm:ss or null",'
            ' "note": "one short sentence"}]\n', encoding="utf-8")
        rout = scratch / f"ra_{date}.txt"
        subprocess.run([sys.executable, str(HERE / "ask.py"), "-Q", str(rq),
                        "-f", str(rfile), "-o", str(rout), "--no-preamble",
                        "--max-output-tokens", "8000"], capture_output=True, text=True)
        if rout.exists():
            parsed = extract_json_array(rout.read_text(encoding="utf-8"))
        if parsed is not None:
            return {"date": date, "verdicts": parsed, "via": "repair pass"}
        return {"date": date, "error": "unparseable answer", "raw": raw.strip()[:1500]}
    return {"date": date, "verdicts": parsed}


def extract_json_array(raw):
    """Pull the JSON array out of an answer that may be wrapped in prose.

    A naive `\\[.*\\]` is wrong here: the transcript lines are prefixed with
    `[0:39:42]` timestamps, and when the model answers in prose instead of JSON
    that regex happily matches from a timestamp bracket to another one and hands
    back garbage. Anchor on `[` followed by `{`, then walk the brackets so a
    trailing sentence after the array cannot break the match.
    """
    txt = raw.strip()
    txt = re.sub(r"^```(?:json)?\s*", "", txt)
    txt = re.sub(r"\s*```$", "", txt)
    try:
        val = json.loads(txt)
        return val if isinstance(val, list) else None
    except json.JSONDecodeError:
        pass
    for m in re.finditer(r"\[\s*\{", txt):
        depth, instr, esc = 0, False, False
        for i in range(m.start(), len(txt)):
            ch = txt[i]
            if instr:
                if esc:            esc = False
                elif ch == "\\":   esc = True
                elif ch == '"':    instr = False
                continue
            if ch == '"':          instr = True
            elif ch in "[{":       depth += 1
            elif ch in "]}":
                depth -= 1
                if depth == 0:
                    try:
                        val = json.loads(txt[m.start():i + 1])
                        if isinstance(val, list) and val and isinstance(val[0], dict):
                            return val
                    except json.JSONDecodeError:
                        pass
                    break
    return None


def report():
    rows, errs = [], []
    for p in sorted(OUTDIR.glob("*.json")):
        d = json.load(open(p, encoding="utf-8"))
        if "verdicts" in d:
            for v in d["verdicts"]:
                v["date"] = d["date"]
                rows.append(v)
        else:
            errs.append(d)
    c = collections.Counter(r.get("verdict") for r in rows)
    total = len(rows)
    print(f"labels audited: {total}   chapters with errors: {len(errs)}")
    for k, n in c.most_common():
        print(f"  {str(k):<14} {n:>3}  ({100*n/total:.0f}%)" if total else "")
    bad = [r for r in rows if r.get("verdict") == "CONTRADICTS"]
    if bad:
        print(f"\nCONTRADICTS ({len(bad)}):")
        for r in sorted(bad, key=lambda x: (x["date"], x["symbol"])):
            print(f'  {r["date"]}  {r["symbol"]:<10} label={r.get("label"):<8} '
                  f'should_be={r.get("should_be")}')
            if r.get("quote"):
                print(f'      "{str(r["quote"])[:150]}"')
    for e in errs:
        print(f'  ERROR {e["date"]}: {e.get("error")}')
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--limit", type=int, help="only run the first N chapters")
    ap.add_argument("--sleep", type=float, default=6.0, help="pause between calls")
    a = ap.parse_args()

    OUTDIR.mkdir(parents=True, exist_ok=True)
    if a.report:
        report()
        return

    scratch = OUTDIR / "_scratch"
    scratch.mkdir(exist_ok=True)
    idx = chapter_index()
    by_date = collections.defaultdict(list)
    for c in load_cases():
        if c["call_date"] in idx:
            by_date[c["call_date"]].append(c)

    dates = sorted(by_date)
    if a.limit:
        dates = dates[:a.limit]
    print(f"{sum(len(by_date[d]) for d in dates)} labels across {len(dates)} chapters")

    for i, date in enumerate(dates, 1):
        dest = OUTDIR / f"{date}.json"
        if dest.exists():
            print(f"[{i}/{len(dates)}] {date} already done")
            continue
        print(f"[{i}/{len(dates)}] {date}  {len(by_date[date])} labels ...",
              end=" ", flush=True)
        res = run_chapter(date, idx[date], by_date[date], scratch)
        json.dump(res, open(dest, "w", encoding="utf-8"), indent=1)
        print("error: " + str(res["error"]) if "error" in res
              else f'{len(res["verdicts"])} verdicts')
        time.sleep(a.sleep)

    print()
    report()


if __name__ == "__main__":
    main()
