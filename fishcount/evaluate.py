"""Score cached SAM runs against the luderick ground truth (Ditria et al. 2021, CC BY 4.0).
Reports recall/precision on annotated frames and the MaxN absolute error, for several confidence cut-offs.
  python3 fishcount/evaluate.py [--prompt fish]"""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fishcount import api, tracks

SMOKE = os.path.expanduser("~/meta-smoke")


def score(pred, gt, thr_iou=0.3):
    tp = fn = fp = 0
    mg = mp = 0
    for i, g in gt.items():
        gb = [(x, y, x + w, y + h) for x, y, w, h, *_ in g]
        pb = [d["box"] for d in pred.get(i, [])]
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", default="fish")
    ap.add_argument("--conf", nargs="*", type=float, default=[0, 0.3, 0.5, 0.6, 0.7, 0.8])
    a = ap.parse_args()
    man = json.load(open(f"{SMOKE}/clips/manifest_fish.json"))
    rows = {c: [0, 0, 0, 0] for c in a.conf}   # tp fn fp |maxn err| sum
    per = []
    for cid, c in man["clips"].items():
        gt = {int(k): v for k, v in json.load(open(f"{SMOKE}/{c['gt']}"))["frames"].items()}
        try:
            txt = api.sam_video(f"{SMOKE}/{c['path']}", a.prompt, c["n_frames"], offline=True)
        except FileNotFoundError:
            continue
        det = tracks.parse_boxes(txt)
        for cut in a.conf:
            pred = {f: [d for d in ds if (d["conf"] or 0) >= cut] for f, ds in det.items()}
            tp, fn, fp, mg, mp = score(pred, gt)
            r = rows[cut]; r[0] += tp; r[1] += fn; r[2] += fp; r[3] += abs(mg - mp)
            if cut == 0:
                per.append((cid, len(gt), tp, fn, fp, mg, mp))
    print(f"prompt={a.prompt!r}; IoU>=0.3; GT-annotated frames only (annotators skipped some faint fish -> precision understated)")
    print("clip                 gtF  recall   precision  MaxN gt/pred")
    for cid, n, tp, fn, fp, mg, mp in per:
        print(f"{cid:20s} {n:3d}  {tp/max(1,tp+fn):5.0%}    {tp/max(1,tp+fp):5.0%}      {mg}/{mp}")
    print("\nconf>=  recall  precision  sum|MaxN err| over clips")
    for cut, (tp, fn, fp, e) in rows.items():
        print(f"{cut:5.2f}   {tp/max(1,tp+fn):5.1%}   {tp/max(1,tp+fp):5.1%}     {e}")


main()
