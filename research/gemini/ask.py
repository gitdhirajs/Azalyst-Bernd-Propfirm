#!/usr/bin/env python3
"""Ask Gemini a question about this project, with whole files attached.

Why this exists: the Gemini CLI needs interactive trust + an auth method, and the
pro models return 429 on both of our free-tier keys. This goes straight at the
REST API, rotates key/model on 429/503, and writes the answer to a file so a long
answer is not lost to a terminal scrollback.

Usage
  python gemini/ask.py -q "question" [-f FILE ...] [-o OUT.md] [-m MODEL] [--numbered]
  python gemini/ask.py -Q prompt.txt -f a.md -f b.py -o gemini/out/answer.md

  --numbered  prefixes every attached line with [Lnnnn] so the answer can cite
              line numbers you can actually jump to.

Models that work on our keys (checked 2026-08-26): the flash tier only.
Pro (gemini-3.1-pro-preview, gemini-pro-latest, gemini-2.5-pro) is 429 -- no free
quota. See GEMINI.md.
"""
import argparse, json, os, sys, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
KEYFILE = os.path.join(HERE, 'keys.local.json')

# (key index, model) tried in order. acct-A first: it is the one already used by
# the frame pipeline, and acct-B 404s on 2.5-flash.
ATTEMPTS = [(0, 'gemini-3.7-flash'), (1, 'gemini-3.5-flash'), (0, 'gemini-3.5-flash'),
            (1, 'gemini-3-flash-preview'), (0, 'gemini-2.5-flash'),
            (0, 'gemini-3.7-flash'), (1, 'gemini-3.5-flash')]

PREAMBLE = """You are the second reader on an audit of a live prop-firm trading system.
The user lost two funded challenges trusting claims that were never verified out of
sample. Never say something is correct. Say what was measured, on how many samples,
and what it got wrong. Every claim carries its sample size; a claim without one is not
a claim. If the attached files do not settle the question, say so -- do not fill the
gap with a plausible answer. Full context is in GEMINI.md in the project root."""


def numbered(txt):
    return '\n'.join(f'[L{i+1}] {l}' for i, l in enumerate(txt.split('\n')))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('-q', '--question')
    ap.add_argument('-Q', '--question-file')
    ap.add_argument('-f', '--file', action='append', default=[])
    ap.add_argument('-o', '--out')
    ap.add_argument('-m', '--model', help='force one model instead of the fallback chain')
    ap.add_argument('--numbered', action='store_true')
    ap.add_argument('--temperature', type=float, default=0.1)
    ap.add_argument('--max-output-tokens', type=int, default=16000)
    ap.add_argument('--no-preamble', action='store_true')
    a = ap.parse_args()

    q = a.question or (open(a.question_file, encoding='utf-8').read() if a.question_file else None)
    if not q:
        ap.error('need -q or -Q')

    keys = json.load(open(KEYFILE, encoding='utf-8'))['keys']
    parts = []
    if not a.no_preamble:
        parts.append({'text': PREAMBLE})
    parts.append({'text': q})
    for path in a.file:
        body = open(path, encoding='utf-8', errors='replace').read()
        parts.append({'text': f'=== FILE: {path} ===\n' + (numbered(body) if a.numbered else body)})

    payload = {'contents': [{'parts': parts}],
               'generationConfig': {'temperature': a.temperature,
                                    'maxOutputTokens': a.max_output_tokens}}
    blob = json.dumps(payload).encode()
    attempts = [(0, a.model), (1, a.model)] if a.model else ATTEMPTS

    r = None
    for ki, model in attempts:
        url = (f'https://generativelanguage.googleapis.com/v1beta/models/'
               f'{model}:generateContent?key={keys[ki]["key"]}')
        req = urllib.request.Request(url, data=blob, headers={'Content-Type': 'application/json'})
        try:
            r = json.load(urllib.request.urlopen(req, timeout=900))
            print(f'[ask.py] served by {keys[ki]["id"]} / {model}', file=sys.stderr)
            break
        except urllib.error.HTTPError as e:
            print(f'[ask.py] HTTP {e.code} {keys[ki]["id"]} {model}: '
                  f'{e.read().decode()[:140]!r}', file=sys.stderr)
            time.sleep(20)
        except Exception as e:                                   # timeouts, resets
            print(f'[ask.py] ERR {keys[ki]["id"]} {model}: {e}', file=sys.stderr)
            time.sleep(20)
    if r is None:
        sys.exit('[ask.py] every key/model attempt failed')

    cand = r['candidates'][0]
    txt = ''.join(p.get('text', '') for p in cand['content'].get('parts', []))
    if cand.get('finishReason') not in (None, 'STOP'):
        txt += f"\n\n<!-- TRUNCATED: finishReason={cand.get('finishReason')} -->\n"
        print(f'[ask.py] WARNING finishReason={cand.get("finishReason")}', file=sys.stderr)
    print(f'[ask.py] usage {r.get("usageMetadata")}', file=sys.stderr)

    if a.out:
        os.makedirs(os.path.dirname(a.out) or '.', exist_ok=True)
        open(a.out, 'w', encoding='utf-8').write(txt)
        print(f'[ask.py] wrote {a.out}', file=sys.stderr)
    print(txt)


if __name__ == '__main__':
    main()
