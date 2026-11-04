"""Table 1d: held-out MaxN against the hand count of the 24 full videos, with constant baselines and per-clip
error statistics. Offline, no model calls.
  python3 report/paper/scripts/handcount_table.py [--tag held1]
Reads runs/<tag>_<clip>/result.json, else the bundle report/paper/data/heldout/runs/<tag>_<clip>/result.json.
The hand count is report/paper/data/heldout/recount/scores.json["hand"] (protocol in recount/key.json).
Constant baselines predict one value for every clip; "always 1" is also the most common hand count (12 of 24), so it
is the strongest constant a reader could pick after seeing the labels."""
import argparse, json, math, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT)
from fishcount import pipeline  # noqa: E402

B = os.path.join(ROOT, "report/paper/data/heldout")


def load_run(tag, cid):
    for d in (os.path.join(ROOT, "runs", f"{tag}_{cid}"), os.path.join(B, "runs", f"{tag}_{cid}")):
        p = os.path.join(d, "result.json")
        if os.path.exists(p):
            return json.load(open(p))
    raise FileNotFoundError(f"no result.json for {tag}_{cid}")


def maxn(res, frames=None, drop_queue=False):
    q = {t for t, v in res["verdicts"].items() if pipeline.needs_review(v)} if drop_queue else set()
    lab = lambda t: res["auto_labels"].get(t, res["tracks"].get(t, {}).get("label"))
    best = 0
    for f, ks in res["frames"].items():
        if frames is not None and int(f) not in frames:
            continue
        best = max(best, sum(1 for k in ks if lab(k["track"]) and k["track"] not in q))
    return best


def stats(pred, ref):
    e = [pred[c] - ref[c] for c in ref]
    n = len(e)
    return dict(exact=sum(x == 0 for x in e), within1=sum(abs(x) <= 1 for x in e), sum_abs=sum(abs(x) for x in e),
                mae=sum(abs(x) for x in e) / n, rmse=math.sqrt(sum(x * x for x in e) / n), bias=sum(e) / n, n=n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="held1")
    a = ap.parse_args()
    sc = json.load(open(os.path.join(B, "recount/scores.json")))
    hand, boxes = sc["hand"], sc["boxes"]
    pipe, pipe_full = {}, {}
    for cid in hand:
        gtf = {int(k) for k in json.load(open(os.path.join(B, "gt", f"{cid}.json")))["frames"]}
        r = load_run(a.tag, cid)
        pipe[cid], pipe_full[cid] = maxn(r, gtf), maxn(r)
    rows = [("human reference boxes (luderick annotation)", boxes),
            (f"pipeline ({a.tag}), queue accepted, annotated frames", pipe),
            (f"pipeline ({a.tag}), queue accepted, every frame", pipe_full),
            ("constant: always 1 (most common hand count)", {c: 1 for c in hand}),
            ("constant: always 2", {c: 2 for c in hand})]
    out = {}
    for ref_name, ref in (("hand count", hand), ("reference boxes", boxes)):
        print(f"\nagainst the {ref_name} (24 clips)")
        print(f"{'system':55s} exact  ±1  Σ|err|   MAE  RMSE   bias")
        for name, pred in rows:
            if pred is ref:
                continue
            s = stats(pred, ref)
            out.setdefault(ref_name, {})[name] = s
            print(f"{name:55s} {s['exact']:2d}/24 {s['within1']:2d}/24 {s['sum_abs']:4d}  {s['mae']:.2f}  {s['rmse']:.2f} {s['bias']:+.2f}")
    big = [c for c in hand if hand[c] >= 3]
    print(f"\nclips with hand count >= 3 ({len(big)}): " + ", ".join(
        f"{c[5:]} hand {hand[c]} pipeline {pipe[c]} boxes {boxes[c]}" for c in big))
    json.dump(dict(tag=a.tag, pipeline=pipe, pipeline_full=pipe_full, stats=out),
              open(os.path.join(B, f"recount/table1d_{a.tag}.json"), "w"), indent=1)


main()
