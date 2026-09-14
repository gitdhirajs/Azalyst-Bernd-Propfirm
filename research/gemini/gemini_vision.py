"""Gemini vision client for the Bernd frame audit.

WHY THIS EXISTS
---------------
Frame reading was burning 200-350k Claude tokens per chapter. Frame reading is
mechanical transcription; it does not need Opus. So: Gemini transcribes, Claude
Opus does all judgement and code work.

WHAT THIS MODULE GIVES YOU
--------------------------
1. A (key x model) rotating pool. The free tier bills 20 requests PER DAY PER
   MODEL PER KEY -- measured, see KeyPool -- so a key is not a budget, a
   (key, model) pair is. Two keys across ten models is the throughput, not two
   keys. Pairs are retired as they exhaust and the pool degrades down the chain.
2. A model fallback chain. `gemini-2.0-flash` (what the 2026-08-19 note used) has
   been RETIRED from the API and no longer exists; `gemini-2.5-flash` still answers
   on the older key but 404s on the newer one. MODEL_CHAIN below is what actually
   worked on 2026-08-20.
3. The strict TRANSCRIBE-don't-DESCRIBE prompt. This is the whole reason the older
   `_gemini_analysis_output\\` run was fabricated garbage; do not soften it.
4. Sanity filters, so an invented number gets flagged before a human ever sees it.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
It does not decide anything. Its output is a candidate transcription that still has
to pass the spot-check layer in read_frames.py before Opus is allowed to use it.
"""
from __future__ import annotations

import base64
import json
import os
import random
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"

# Measured on the known-answer frame (frame_002093, OTC M3 L2) on 2026-08-20.
# All four reproduced "34.43%" and "Mon 07 Aug '23" exactly. Ordered by latency:
#   gemini-3.7-flash       3.2s   294 thinking tokens   read the OHLC legend too
#   gemini-3.5-flash       9.6s  1209 thinking tokens
#   gemini-3.1-flash-lite 21.4s     0 thinking tokens
#   gemini-2.5-flash      22.3s  3020 thinking tokens   image downsampled (258 img
#                                                       tokens vs 1100 on the 3.x models)
# gemini-3-flash-preview returned HTTP 503 (capacity) and is not in the chain.
# Ordered best-first. EVERY model carries its OWN free-tier daily budget per key,
# so a long chain is not redundancy -- it is throughput. See KeyPool below.
MODEL_CHAIN = (
    # REORDERED 2026-08-21 on measured throughput, not on assumed model quality.
    # Observed over 1590 successful reads of this corpus:
    #     gemini-3.1-flash-lite      851
    #     gemini-3.5-flash-lite      369
    #     gemini-flash-lite-latest   359
    #     ALL full-flash models       11
    # The free-tier "20 requests/day/model/key" cap bites the PREMIUM flash models
    # hard; the -lite tier has a far larger allowance and did 99% of the work. Putting
    # the premium models first just burned their 20 on bulk frames and then fell
    # through anyway, wasting a round-trip per frame.
    # Accuracy is not being traded away: every Claude-vision-verified read on this
    # corpus came from a LITE model and was exact, including the two Valuation Length
    # readings (10 on frame_000213, 13 on frame_000360) that C-65 rests on.
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite",
    "gemini-flash-lite-latest",
    "gemini-2.5-flash-lite",
    # ADDED 2026-09-12. ListModels on both keys returns six `*-lite` models that
    # serve generateContent; this was the one missing from the chain. A (key,
    # model) pair is its own 20/day budget, so a fifth usable model is +25%
    # throughput for free. `gemini-3.1-flash-lite-image` is the sixth and is
    # deliberately NOT here -- it is an image-GENERATION model.
    "gemini-3.1-flash-lite-preview",
    # GEMMA tier TRIED AND WITHDRAWN 2026-08-21 (C-77). gemma-4-31b-it and
    # gemma-4-26b-a4b-it draw on a separate quota pool and DO work, which unblocked the
    # backlog while every gemini pair was spent. They are out of the chain anyway:
    # a 2-frame spot check is not a quality bar, gemma-4-26b already MISSED a valuation
    # legend on one of those two frames, and a silently missing legend is the failure
    # mode that makes a chapter look thinner than it is. Re-add only if
    # `/tmp/gbench.py <model>` scores them on the same 44-assertion fixture set Gemini
    # was measured on (Gemini: 33/44 exact, 41/44 windowed, 0 fabrications).
    # Premium tier last: small daily quota, reserved for frames the lite tier fails.
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-flash-latest",
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
)

# ---------------------------------------------------------------------------
# THE PROMPT.  Transcribe, never describe.  Do not "improve" this wording.
# ---------------------------------------------------------------------------
STRICT_PROMPT = """You are reading a screenshot of a trading platform (TradingView or
TradeStation). Transcribe ONLY what is literally visible. This feeds a live trading
system, so a missing value is cheap and a wrong value is expensive.

RULES - follow exactly:
- If a character is not clearly legible, write "?" for that character.
- If you cannot read a value at all, use null. NEVER estimate, infer, round, or
  complete a number from context.
- Do not describe what you think a trading platform usually shows. Only what is
  actually on this screen, verbatim, including punctuation and separators.
- Copy indicator legends character for character, including every input number in
  the legend row, in the order they appear.
- If a settings / "Format Study" / "Inputs" dialog is open, transcribe every visible
  field label and its value exactly, and set "truncated" to true if the dialog is
  scrolled so that fields are cut off.

Return STRICT JSON with this shape:
{
  "platform": "TradingView" | "TradeStation" | "other" | null,
  "chart_symbol_text": string|null,
  "timeframe": string|null,
  "indicator_legends": [ {"raw_text": string, "values": [string]} ],
  "settings_dialog": {"title": string|null,
                      "fields": [{"label": string, "value": string}],
                      "truncated": boolean} | null,
  "crosshair_date": string|null,
  "visible_dates": [string],
  "slide_text": string|null,
  "unreadable_notes": string|null
}"""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "platform": {"type": "string", "nullable": True},
        "chart_symbol_text": {"type": "string", "nullable": True},
        "timeframe": {"type": "string", "nullable": True},
        "indicator_legends": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "raw_text": {"type": "string"},
                    "values": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["raw_text"],
            },
        },
        "settings_dialog": {
            "type": "object",
            "nullable": True,
            "properties": {
                "title": {"type": "string", "nullable": True},
                "fields": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"label": {"type": "string"},
                                       "value": {"type": "string"}},
                        "required": ["label", "value"],
                    },
                },
                "truncated": {"type": "boolean"},
            },
        },
        "crosshair_date": {"type": "string", "nullable": True},
        "visible_dates": {"type": "array", "items": {"type": "string"}},
        "slide_text": {"type": "string", "nullable": True},
        "unreadable_notes": {"type": "string", "nullable": True},
    },
    "required": ["platform", "indicator_legends", "visible_dates"],
}


FREE_TIER_PER_DAY_PER_PAIR = 20   # measured from the 429 body, see KeyPool below


def load_keys():
    """Keys come from, in order: GEMINI_API_KEYS env, keys.local.json, GEMINI_API_KEY env."""
    env = os.environ.get("GEMINI_API_KEYS", "").strip()
    if env:
        return [{"id": "env%d" % i, "key": k.strip()}
                for i, k in enumerate(env.split(",")) if k.strip()]
    f = HERE / "keys.local.json"
    if f.exists():
        blob = json.loads(f.read_text(encoding="utf-8"))
        return [k for k in blob.get("keys", []) if k.get("key")]
    one = os.environ.get("GEMINI_API_KEY", "").strip()
    return [{"id": "env", "key": one}] if one else []


# ---------------------------------------------------------------------------
# Key x model pool
# ---------------------------------------------------------------------------
# MEASURED 2026-08-20, and this is the binding constraint on the whole plan:
#
#   quotaId    GenerateRequestsPerDayPerProjectPerModel-FreeTier
#   quotaValue 20            <- twenty requests PER DAY, PER MODEL, PER KEY
#
# So a key is not a budget -- a (key, model) PAIR is a budget. Two keys and one
# model is 40 frames a day, and one OTC lesson is ~234 frames. The only way to get
# usable throughput on the free tier is to rotate across BOTH keys AND every model
# that will serve the request, because each pair carries its own 20.
#
# Consequences the old single-key-cooldown design got wrong:
#   * a 429 does not mean "this key is busy", it means "this key is finished with
#     THIS model until the quota resets" -- other models on the same key still work.
#   * the server's retryDelay ("5s") is meaningless for a per-DAY quota. Sleeping and
#     retrying just burns wall-clock. A PerDay 429 must retire that pair for the run.
#
# Model availability also differs BY KEY: gemini-2.5-flash answers on acct-A but
# returns 404 "no longer available to new users" on acct-B. Dead pairs are retired
# the same way, so the pool self-heals around it without any hand-maintained list.


@dataclass
class _Slot:
    """One (key, model) budget."""
    key_id: str
    key: str
    model: str
    cool_until: float = 0.0     # short-term backoff (per-minute limits, 503s)
    retired: str = ""           # non-empty => unusable for the rest of this run
    calls: int = 0
    ok: int = 0


class KeyPool:
    """Round-robin over every (key, model) pair, retiring pairs as they exhaust.

    Preference order follows MODEL_CHAIN, so the fastest/most accurate model is
    tried first and the pool degrades gracefully down the chain as quotas burn out.
    """

    def __init__(self, keys=None, models=None):
        if keys is None:
            keys = load_keys()
        if not keys:
            raise SystemExit(
                "No Gemini keys. Put them in gemini/keys.local.json or set "
                "GEMINI_API_KEYS='key1,key2'.")
        models = list(models or MODEL_CHAIN)
        # Ordered model-major so the whole fleet of keys is used on the best model
        # before dropping to the next one.
        self._slots = [_Slot(key_id=k.get("id", "k%d" % i), key=k["key"], model=m)
                       for m in models
                       for i, k in enumerate(keys)]
        self._i = 0
        self._lock = threading.Lock()
        self.n_keys = len(keys)
        self.n_models = len(models)

    def __len__(self):
        return len(self._slots)

    def budget_hint(self):
        """Best-case reads left, if every live pair still had its full free-tier 20."""
        live = sum(1 for s in self._slots if not s.retired)
        return live * FREE_TIER_PER_DAY_PER_PAIR

    def acquire(self, timeout=180.0):
        """Next usable (key, model) slot. Raises QuotaExhausted when all are retired."""
        deadline = time.time() + timeout
        while True:
            with self._lock:
                live = [s for s in self._slots if not s.retired]
                if not live:
                    raise QuotaExhausted(self._exhaustion_report())
                n = len(self._slots)
                soonest = None
                for _ in range(n):
                    s = self._slots[self._i % n]
                    self._i += 1
                    if s.retired:
                        continue
                    if s.cool_until <= time.time():
                        s.calls += 1
                        return s
                    soonest = (s.cool_until if soonest is None
                               else min(soonest, s.cool_until))
            if time.time() > deadline:
                raise QuotaExhausted("every live (key, model) pair is backing off; "
                                     "waited %.0fs" % timeout)
            time.sleep(max(1.0, min(20.0, (soonest or 0) - time.time())))

    def retire(self, slot, why):
        with self._lock:
            if not slot.retired:
                slot.retired = why
                remaining = sum(1 for s in self._slots if not s.retired)
                print("  [pool] retiring %s/%s (%s) -- %d pairs left"
                      % (slot.key_id, slot.model, why, remaining))

    def backoff(self, slot, seconds):
        with self._lock:
            slot.cool_until = max(slot.cool_until, time.time() + seconds)

    def note_ok(self, slot):
        with self._lock:
            slot.ok += 1

    def _exhaustion_report(self):
        by = {}
        for s in self._slots:
            by.setdefault(s.retired or "live", []).append("%s/%s" % (s.key_id, s.model))
        return ("all (key, model) pairs are exhausted:\n" +
                "\n".join("  %-22s %s" % (k, ", ".join(v)) for k, v in sorted(by.items())) +
                "\nFree tier is %d requests per day per model per key. Either wait for "
                "the daily reset, add another key, or enable billing on a project."
                % FREE_TIER_PER_DAY_PER_PAIR)

    def stats(self):
        with self._lock:
            return [{"key": s.key_id, "model": s.model, "calls": s.calls,
                     "ok": s.ok, "retired": s.retired or None}
                    for s in self._slots if s.calls or s.retired]

    def summary(self):
        st = self.stats()
        done = sum(r["ok"] for r in st)
        live = sum(1 for s in self._slots if not s.retired)
        return ("%d successful reads | %d of %d (key, model) pairs still live"
                % (done, live, len(self._slots)))


class QuotaExhausted(RuntimeError):
    """Every (key, model) pair is out of free-tier budget."""


# ---------------------------------------------------------------------------
# The call
# ---------------------------------------------------------------------------
def _retry_delay_from(body, default=20.0):
    m = re.search(r'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"', body)
    return float(m.group(1)) if m else default


def _is_per_day_quota(body):
    """True when the 429 is the daily budget, not a per-minute burst limit.

    A per-day 429 can never be waited out inside a run, so the pair is retired.
    A per-minute one is worth a short backoff.
    """
    return "PerDay" in body or "per day" in body.lower()


def read_image(path, pool, prompt=STRICT_PROMPT, max_attempts=8,
               timeout=180, schema=None):
    """Transcribe one frame at FULL resolution. Returns a result envelope.

    The model is chosen by the pool, not by the caller -- the pool owns which
    (key, model) budgets still have room. The image is sent as-is, no downscaling:
    the old fabricated run downscaled frames and asked the model to DESCRIBE a
    table, and that combination is what produced `bid: 12.0` for ES at 4300.
    """
    path = Path(path)
    raw = path.read_bytes()
    b64 = base64.b64encode(raw).decode()
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"

    last_err = None
    for attempt in range(max_attempts):
        try:
            slot = pool.acquire()
        except QuotaExhausted as exc:
            return {"ok": False, "frame": path.name, "path": str(path),
                    "error": "QUOTA EXHAUSTED: %s" % exc, "quota_exhausted": True,
                    "data": None, "warnings": []}

        url = "%s/%s:generateContent?key=%s" % (API_ROOT, slot.model, slot.key)
        body = {
            "contents": [{"parts": [{"text": prompt},
                                    {"inline_data": {"mime_type": mime, "data": b64}}]}],
            "generationConfig": {
                "temperature": 0,
                "response_mime_type": "application/json",
                "response_schema": schema or RESPONSE_SCHEMA,
            },
        }
        try:
            r = requests.post(url, json=body, timeout=timeout)
        except Exception as exc:                       # network flake
            last_err = "%s/%s: %s" % (slot.model, slot.key_id, exc)
            pool.backoff(slot, 2.0 * (attempt + 1))
            continue

        if r.status_code == 200:
            try:
                payload = r.json()
                parts = payload["candidates"][0]["content"]["parts"]
                txt = next(p["text"] for p in reversed(parts) if "text" in p)
                data = json.loads(txt)
            except Exception as exc:
                last_err = "%s/%s: unparseable response (%s)" % (slot.model, slot.key_id, exc)
                continue
            pool.note_ok(slot)
            usage = payload.get("usageMetadata", {})
            return {"ok": True, "frame": path.name, "path": str(path),
                    "model": slot.model, "key_id": slot.key_id, "data": data,
                    "tokens": usage.get("totalTokenCount"),
                    "warnings": sanity_check(data)}

        if r.status_code == 429:
            if _is_per_day_quota(r.text):
                pool.retire(slot, "daily quota spent")
            else:
                pool.backoff(slot, _retry_delay_from(r.text, 20.0))
            last_err = "%s/%s: 429" % (slot.model, slot.key_id)
            continue
        if r.status_code == 404:                       # model not available on THIS key
            pool.retire(slot, "404 not available for this key")
            last_err = "%s/%s: 404" % (slot.model, slot.key_id)
            continue
        if r.status_code in (500, 503, 504):           # transient capacity
            pool.backoff(slot, 5.0 + 3 * attempt)
            last_err = "%s/%s: %d" % (slot.model, slot.key_id, r.status_code)
            continue
        if r.status_code == 403:                       # bad/blocked key: whole key is dead
            pool.retire(slot, "403 forbidden")
            last_err = "%s/%s: 403 %s" % (slot.model, slot.key_id, r.text[:150])
            continue
        last_err = "%s/%s: HTTP %d %s" % (slot.model, slot.key_id,
                                          r.status_code, r.text[:200])
        if r.status_code == 400:                       # our request is wrong: stop
            break

    return {"ok": False, "frame": path.name, "path": str(path),
            "error": last_err, "data": None, "warnings": []}


def read_blob(raw, mime, pool, prompt, schema=None, max_attempts=8, timeout=600,
              label=""):
    """Same contract as `read_image`, for any inline payload (used for PDF slices).

    WHY A SEPARATE FUNCTION RATHER THAN GENERALISING `read_image`
    `read_image` is the validated path behind every frame read in this project.
    Its 429/404/403 handling is subtle -- a per-DAY 429 must RETIRE the (key,
    model) pair rather than sleep on it, because the server's retryDelay is
    meaningless for a daily quota. Rewriting it to take a mime type would put
    that logic at risk for no benefit, so this duplicates the loop instead and
    leaves the frame path untouched.

    `timeout` defaults higher than read_image's: a 40-page PDF slice is ~10 MB
    of upload and ~20k image tokens, which does not answer in 180s.
    """
    b64 = base64.b64encode(raw).decode()
    last_err = None
    for attempt in range(max_attempts):
        try:
            slot = pool.acquire()
        except QuotaExhausted as exc:
            return {"ok": False, "label": label,
                    "error": "QUOTA EXHAUSTED: %s" % exc, "quota_exhausted": True,
                    "data": None, "warnings": []}

        url = "%s/%s:generateContent?key=%s" % (API_ROOT, slot.model, slot.key)
        body = {
            "contents": [{"parts": [{"text": prompt},
                                    {"inline_data": {"mime_type": mime, "data": b64}}]}],
            "generationConfig": {
                "temperature": 0,
                "response_mime_type": "application/json",
            },
        }
        if schema:
            body["generationConfig"]["response_schema"] = schema
        try:
            r = requests.post(url, json=body, timeout=timeout)
        except Exception as exc:
            last_err = "%s/%s: %s" % (slot.model, slot.key_id, exc)
            pool.backoff(slot, 2.0 * (attempt + 1))
            continue

        if r.status_code == 200:
            try:
                payload = r.json()
                parts = payload["candidates"][0]["content"]["parts"]
                txt = next(p["text"] for p in reversed(parts) if "text" in p)
                data = json.loads(txt)
            except Exception as exc:
                # A truncated answer (MAX_TOKENS on a big slice) lands here. It is
                # not a quota problem and must not retire the pair; the caller
                # retries with fewer pages.
                last_err = "%s/%s: unparseable response (%s)" % (
                    slot.model, slot.key_id, exc)
                continue
            pool.note_ok(slot)
            usage = payload.get("usageMetadata", {})
            return {"ok": True, "label": label, "model": slot.model,
                    "key_id": slot.key_id, "data": data,
                    "tokens": usage.get("totalTokenCount"), "warnings": []}

        if r.status_code == 429:
            if _is_per_day_quota(r.text):
                pool.retire(slot, "daily quota spent")
            else:
                pool.backoff(slot, _retry_delay_from(r.text, 20.0))
            last_err = "%s/%s: 429" % (slot.model, slot.key_id)
            continue
        if r.status_code == 404:
            pool.retire(slot, "404 not available for this key")
            last_err = "%s/%s: 404" % (slot.model, slot.key_id)
            continue
        if r.status_code in (500, 503, 504):
            pool.backoff(slot, 5.0 + 3 * attempt)
            last_err = "%s/%s: %d" % (slot.model, slot.key_id, r.status_code)
            continue
        if r.status_code == 403:
            pool.retire(slot, "403 forbidden")
            last_err = "%s/%s: 403 %s" % (slot.model, slot.key_id, r.text[:150])
            continue
        last_err = "%s/%s: HTTP %d %s" % (slot.model, slot.key_id,
                                          r.status_code, r.text[:200])
        if r.status_code == 400:
            break

    return {"ok": False, "label": label, "error": last_err, "data": None,
            "warnings": []}


# ---------------------------------------------------------------------------
# Sanity filters -- step 3 of the mandatory pipeline
# ---------------------------------------------------------------------------
# Plausible ranges for the instruments in this corpus. A transcription that lands
# outside its band is FLAGGED, never silently corrected.
PRICE_BANDS = {
    "ES": (1500, 9000), "NQ": (3000, 30000), "YM": (15000, 55000), "RTY": (900, 3500),
    "GC": (900, 6000), "GOLD": (900, 6000), "SI": (10, 80), "PA": (400, 4000),
    "PL": (500, 2500), "CL": (10, 200), "CRUDE": (10, 200), "NG": (1.0, 20.0),
    "ZC": (200, 900), "ZW": (300, 1400), "ZS": (700, 1900), "SB": (5, 40),
    "KC": (80, 450), "CT": (40, 250), "BTC": (100, 200000), "DXY": (70, 130),
}
COT_INDEX_BAND = (-35.0, 135.0)      # 0-100 form, plus the legacy -20..120 band, plus slack
COT_NET_K_ABS_MAX = 2000.0           # net positions are printed in thousands of contracts
CORPUS_YEAR_MAX = 2026               # nothing in this corpus can be dated later


def _numbers(text):
    out = []
    for tok in re.findall(r"-?\d[\d,]*\.?\d*", text or ""):
        try:
            out.append(float(tok.replace(",", "")))
        except ValueError:
            pass
    return out


def sanity_check(data):
    """Return human-readable warnings. Empty list == nothing obviously impossible.

    This is a smoke detector, not proof of correctness. It would have caught the old
    fabricated run instantly (`ES bid 12.0`), which is the bar it has to clear.
    """
    w = []
    if not isinstance(data, dict):
        return ["response was not a JSON object"]

    sym = (data.get("chart_symbol_text") or "").upper()
    for root, (lo, hi) in PRICE_BANDS.items():
        if root in sym:
            for leg in data.get("indicator_legends") or []:
                txt = leg.get("raw_text", "")
                if not re.search(r"\b[OHLC]\s*[\d-]", txt):
                    continue                       # only price OHLC rows get band-checked
                for n in _numbers(txt):
                    if abs(n) > 1 and not (lo <= abs(n) <= hi):
                        w.append("price %s outside plausible %s band %s-%s"
                                 % (n, root, lo, hi))
            break

    for leg in data.get("indicator_legends") or []:
        txt = leg.get("raw_text", "")
        low = txt.lower()
        if "pos. indices" in low or "cot index" in low:
            for m in re.findall(r"(-?\d+\.\d+)\s*%", txt):
                v = float(m)
                if not (COT_INDEX_BAND[0] <= v <= COT_INDEX_BAND[1]):
                    w.append("COT index %s%% outside %s" % (v, COT_INDEX_BAND))
        if "net futures only" in low:
            for m in re.findall(r"(-?[\d,]+\.?\d*)\s*K", txt):
                v = abs(float(m.replace(",", "")))
                if v > COT_NET_K_ABS_MAX:
                    w.append("COT net %sK exceeds %sK" % (v, COT_NET_K_ABS_MAX))

    # Only a CROSSHAIR date is a data readout. `visible_dates` are axis labels, and a
    # seasonality / forecast panel legitimately projects years past the recording date --
    # the 2024-03-02 CW10 chapter really does print "'25 '26 '27 '28" on the Campus
    # seasonality axis. Flagging those produced 90 false positives on that one chapter and
    # flooded the spot-check queue, which is the one queue that has to stay all-signal.
    cross = data.get("crosshair_date") or ""
    for y in re.findall(r"\b(19\d{2}|20\d{2})\b", cross):
        if int(y) > CORPUS_YEAR_MAX:
            w.append("crosshair date year %s is after the corpus cutoff %d"
                     % (y, CORPUS_YEAR_MAX))
    for y2 in re.findall(r"'(\d{2})\b", cross):
        if 2000 + int(y2) > CORPUS_YEAR_MAX:
            w.append("crosshair date year '%s is after the corpus cutoff %d"
                     % (y2, CORPUS_YEAR_MAX))

    if data.get("platform") and not (data.get("indicator_legends")
                                     or data.get("settings_dialog")
                                     or data.get("slide_text")
                                     or data.get("visible_dates")):
        w.append("platform claimed but nothing transcribed -- suspicious empty read")
    return w


ACTIONABLE_RE = re.compile(
    r"(cot|valuation|seasonality|zigzag|pos\. indices|net futures|look\s*back|length|"
    r"upper bound|lower bound|weeks)", re.I)


def is_actionable(data):
    """True if this frame carries a number we might act on.

    Per the mandated pipeline these need 100% Claude-vision verification, not the
    10% random sample.
    """
    if not isinstance(data, dict):
        return False
    if data.get("settings_dialog"):
        return True
    for leg in data.get("indicator_legends") or []:
        t = leg.get("raw_text", "")
        if ACTIONABLE_RE.search(t) and re.search(r"-?\d", t):
            return True
    return False
