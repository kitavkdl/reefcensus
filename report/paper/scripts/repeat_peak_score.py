"""Tally Table 4b from report/paper/data/repeat_peak_f35.json: Spark's verdict on the faint fish (tile D7) per layout,
original call + repeats. kept = is_target true; "not a fish" = is_target false with a non-animal answer (seagrass, water, "no fish");
"other fish" = is_target false otherwise (a fish other than the label).
Fisher exact test (two-sided) on not-a-fish, edge (V4) vs middle (V5), with and without the original calls.
  python3 report/paper/scripts/repeat_peak_score.py"""
import json, os, re
from math import comb
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
D = json.load(open(os.path.join(ROOT, "report/paper/data/repeat_peak_f35.json")))


def verdict(text):
    m = re.search(r"\[.*\]", text, re.S)
    tiles = json.loads(m.group(0)) if m else []
    t = next((x for x in tiles if x.get("tile") == "D7"), None)
    if t is None:
        return "no answer"
    if t.get("is_target"):
        return "kept"
    w = str(t.get("what_it_is", "")).lower()
    if re.search(r"seagrass|water|weed|no fish|sand|empty|nothing", w):
        return "not a fish"
    return "other fish"


def fisher(a, n1, b, n2):          # two-sided, by summing tables no more likely than the observed one
    k, n = a + b, n1 + n2
    p = lambda x: comb(n1, x) * comb(n2, k - x) / comb(n, k)
    po = p(a)
    return sum(p(x) for x in range(max(0, k - n2), min(k, n1) + 1) if p(x) <= po * (1 + 1e-9))


rows = {}
for v in ("V4", "V5", "V5-category"):
    allv = [verdict(D[v]["original"])] + [verdict(r) for r in D[v]["repeats"]]
    rows[v] = allv
    c = {k: allv.count(k) for k in ("not a fish", "other fish", "kept", "no answer")}
    print(f"{v:12s} n={len(allv):3d}  " + "  ".join(f"{k} {n}" for k, n in c.items()))
FX = os.path.join(ROOT, "report/paper/data/repeat_peak_f35_fixexample.json")
if os.path.exists(FX):
    fx = [verdict(r) for r in json.load(open(FX))["repeats"]]
    c = {k: fx.count(k) for k in ("not a fish", "other fish", "kept", "no answer")}
    print(f"{'V6, example without fish':12s} n={len(fx):3d}  " + "  ".join(f"{k} {n}" for k, n in c.items()))
    rows["V6fx"] = ["x"] + fx      # placeholder for the original call, so slice(1, None) drops nothing real
    o = rows["V5-category"]
    print(f"other fish, V6 vs V6 with the example fixed: {o.count('other fish')}/{len(o)} vs {fx.count('other fish')}/{len(fx)}, "
          f"p = {fisher(o.count('other fish'), len(o), fx.count('other fish'), len(fx)):.3g}")
for label, sl in (("all calls", slice(0, None)), ("repeats only", slice(1, None))):
    e, m = rows["V4"][sl], rows["V5"][sl]
    print(f"not a fish, edge vs middle ({label}): {e.count('not a fish')}/{len(e)} vs {m.count('not a fish')}/{len(m)}, "
          f"p = {fisher(e.count('not a fish'), len(e), m.count('not a fish'), len(m)):.3g}")
    rk = lambda xs: sum(x != "kept" for x in xs)
    print(f"track removed, edge vs middle ({label}): {rk(e)}/{len(e)} vs {rk(m)}/{len(m)}, p = {fisher(rk(e), len(e), rk(m), len(m)):.3g}")
