"""Score full pipeline runs (merge, stitch, Spark audit, same-animal check, peak check) against the luderick
ground truth (Ditria et al. 2021, CC BY 4.0), next to raw SAM 'fish' on the same clips.
MaxN is taken over the human-annotated frames only, for both, so the two are comparable.
  python3 fishcount/evaluate_pipeline.py [--run]   (--run: make missing runs eval_<clip>; needs FISH_BUDGET)"""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fishcount import api, tracks

SMOKE = os.path.expanduser("~/meta-smoke")
RUNS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "runs")


def score(pred, gt, thr_iou=0.3):
    """pred, gt: {frame: [box]} over annotated frames. Returns tp, fn, fp, MaxN gt, MaxN pred."""
    tp = fn = fp = 0
    mg = mp = 0
    for i, gb in gt.items():
        pb = pred.get(i, [])
        used = set()
        for a in gb:
            best = max(((tracks.iou(a, b), j) for j, b in enumerate(pb) if j not in used), default=(0, None))
            if best[0] >= thr_iou:
                tp += 1; used.add(best[1])
            else:
                fn += 1
        fp += len(pb) - len(used)
        mg, mp = max(mg, len(gb)), max(mp, len(pb))
    return tp, fn, fp, mg, mp


def pipeline_boxes(res):
    lab = lambda t: res["auto_labels"].get(t, res["tracks"].get(t, {}).get("label"))
    return {int(f): [k["box"] for k in ks if lab(k["track"])] for f, ks in res["frames"].items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    a = ap.parse_args()
    man = json.load(open(f"{SMOKE}/clips/manifest_fish.json"))
    rows, tot = [], {"sam": [0, 0, 0, 0], "pipe": [0, 0, 0, 0]}
    for cid, c in man["clips"].items():
        gt = {int(k): [(x, y, x + w, y + h) for x, y, w, h, *_ in v]
              for k, v in json.load(open(f"{SMOKE}/{c['gt']}"))["frames"].items()}
        clip = f"{SMOKE}/{c['path']}"
        sam = {f: [d["box"] for d in ds] for f, ds in tracks.parse_boxes(api.sam_video(clip, "fish", c["n_frames"], offline=True)).items()}
        rp = os.path.join(RUNS, f"eval_{cid}", "result.json")
        if a.run and not os.path.exists(rp):
            from fishcount import pipeline
            pipeline.run_pipeline(clip, f"eval_{cid}", do_scout=False, prompts=["fish"], max_usd=0.2)
        res = json.load(open(rp)) if os.path.exists(rp) else None
        r = dict(clip=cid, frames=len(gt), sam=score(sam, gt))
        if res:
            r["pipe"] = score(pipeline_boxes(res), gt)
            r["queue"] = sum(1 for v in res["verdicts"].values() if not v or v.get("confidence", 0) < 0.7 or v.get("is_target") is False)
            r["tracks"] = len(res["tracks"])
            r["dups"] = sum(d["same"] for d in res.get("duplicates", []))
        rows.append(r)
        for k in ("sam", "pipe"):
            if k in r:
                tp, fn, fp, mg, mp = r[k]
                t = tot[k]; t[0] += tp; t[1] += fn; t[2] += fp; t[3] += abs(mg - mp)
    pct = lambda x, y: f"{x / max(1, y):.0%}"
    print("clip                frames | SAM 'fish' alone: recall precision MaxN gt/pred | pipeline: recall precision MaxN gt/pred  human queue")
    for r in rows:
        tp, fn, fp, mg, mp = r["sam"]
        line = f"{r['clip']:20s} {r['frames']:4d} |  {pct(tp, tp + fn):>5} {pct(tp, tp + fp):>8}   {mg}/{mp}"
        if "pipe" in r:
            tp, fn, fp, mg, mp = r["pipe"]
            line += f"         |  {pct(tp, tp + fn):>5} {pct(tp, tp + fp):>8}   {mg}/{mp}   {r['queue']}/{r['tracks']} tracks"
        print(line)
    for k, (tp, fn, fp, e) in tot.items():
        print(f"{k:5s} total: recall {tp / max(1, tp + fn):.1%}, precision {tp / max(1, tp + fp):.1%}, sum |MaxN error| {e}")


main()
