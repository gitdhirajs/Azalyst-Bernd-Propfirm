r"""Paired case-level A/B between two goldtest result sets, split by presenter.

Unpaired comparison is unsafe here: runs differ in how many cases error out, so the
denominators move and a +/-2 case difference can be pure attrition. This compares only
cases scored in BOTH arms and reports McNemar on the discordant pairs.

    python ab_paired.py 'base?.json' 'nocyc?.json'
"""
from __future__ import annotations
import collections, glob, json, math, sys
from pathlib import Path
import yaml

HERE = Path(__file__).parent


def _mcnemar(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(math.comb(n, k) for k in range(min(b, c) + 1)) / 2 ** n)


def _load(pattern: str) -> dict:
    out = {}
    for f in sorted(glob.glob(pattern)):
        for r in json.load(open(f, encoding="utf-8")).get("results", []):
            if r.get("error"):
                continue
            k = (str(r["symbol"]), str(r["call_date"]), str(r["bernd"]["bias"]))
            out[k] = (r["bernd"]["bias"], (r["system"] or {}).get("bias_only"))
    if not out:
        sys.exit(f"no results matched {pattern!r}")
    return out


def main(pat_a: str, pat_b: str) -> None:
    corpus = {}
    for c in yaml.safe_load(open(HERE / "ft_oos_full.yaml", encoding="utf-8")):
        corpus.setdefault((str(c["symbol"]), str(c["call_date"]), str(c["bias"])), c)

    A, B = _load(pat_a), _load(pat_b)
    print(f"A = {pat_a}   B = {pat_b}\n")

    for label, want in (("BERND", True), ("OTC INSTRUCTORS", False)):
        keys = [k for k in A if k in B
                and corpus.get(k) is not None
                and bool(corpus[k].get("_is_bernd")) is want]
        if not keys:
            continue
        n = len(keys)
        a_ok = sum(A[k][0] == A[k][1] for k in keys)
        b_ok = sum(B[k][0] == B[k][1] for k in keys)
        changed = [k for k in keys if A[k][1] != B[k][1]]
        fixed = sum(1 for k in changed if B[k][0] == B[k][1])
        broke = sum(1 for k in changed if A[k][0] == A[k][1])
        p = _mcnemar(fixed, broke)

        print(f"===== {label}   paired n={n}")
        print(f"   A : {a_ok}/{n} = {100*a_ok/n:5.1f}%")
        print(f"   B : {b_ok}/{n} = {100*b_ok/n:5.1f}%   ({b_ok-a_ok:+d} cases)")
        print(f"   predictions changed: {len(changed)} ({100*len(changed)/n:.0f}%)   "
              f"B-fixed {fixed} / B-broke {broke}   McNemar p={p:.3f}"
              f" -> {'SIGNIFICANT' if p < 0.05 else 'not significant'}")
        if changed:
            d = collections.Counter((A[k][1], B[k][1]) for k in changed)
            print("   shifts (A->B): " + ", ".join(f"{x}->{y}:{c}" for (x, y), c in d.most_common(5)))
        for nm, src in (("A", A), ("B", B)):
            dist = collections.Counter(src[k][1] for k in keys)
            print(f"   {nm} bias dist: " + "  ".join(f"{k}={dist.get(k,0)}"
                                                    for k in ("long", "neutral", "short")))
        truth = collections.Counter(A[k][0] for k in keys)
        print("   truth       : " + "  ".join(f"{k}={truth.get(k,0)}"
                                              for k in ("long", "neutral", "short")))
        print()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
