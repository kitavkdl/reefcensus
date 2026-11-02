"""How well Spark's A1 confidence separates real fish from the rest, on every luderick track it judged: the six
development clips (run eval6 = V5) and the 24 held-out clips (runs held1_*). Offline, no model calls; uses the
scoring bundles in report/paper/data/{luderick,heldout}.
A track is "a real fish" when at least half of its boxes in annotated frames match a human box (IoU >= 0.3, one box
per human box per frame); tracks with no box in an annotated frame are skipped. Because the human boxes omit some
real fish (§6.1), "not matched" is an upper bound on wrong tracks.
  python3 report/paper/scripts/calibration.py"""
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
from fishcount import tracks, pipeline  # noqa: E402
D = os.path.join(ROOT, "report/paper/data")


def per_track(res, gt):
    hit = {}
    for f, ks in res["frames"].items():
        f = int(f)
        if f not in gt:
            continue
        used = set()
        for k in ks:
            best = max(((tracks.iou(k["box"], g), j) for j, g in enumerate(gt[f]) if j not in used), default=(0, None))
            h = hit.setdefault(k["track"], [0, 0]); h[1] += 1
            if best[0] >= 0.3:
                used.add(best[1]); h[0] += 1
    return hit


def gt_of(path):
    return {int(k): [(x, y, x + w, y + h) for x, y, w, h, *_ in v] for k, v in json.load(open(path))["frames"].items()}


rows = []   # (set, clip, track, confidence, is_target, queued, real)
for name, bundle, tag in (("development", "luderick", "eval6"), ("held-out", "heldout", "held1")):
    man = json.load(open(f"{D}/{bundle}/manifest.json"))
    for cid in man["clips"]:
        res = json.load(open(f"{D}/{bundle}/runs/{tag}_{cid}/result.json"))
        hit = per_track(res, gt_of(f"{D}/{bundle}/gt/{cid}.json"))
        for t, v in res["verdicts"].items():
            if t not in hit or "confidence" not in v:
                continue
            rows.append((name, cid, t, float(v["confidence"]), bool(v.get("is_target")), pipeline.needs_review(v),
                         hit[t][0] * 2 >= hit[t][1]))

BINS = [(0.0, 0.5), (0.5, 0.7), (0.7, 0.9), (0.9, 1.01)]
for subset in ("development", "held-out", "all"):
    rs = [r for r in rows if subset == "all" or r[0] == subset]
    print(f"\n== {subset}: {len(rs)} judged tracks with boxes in annotated frames ==")
    print("A1 says fish, confidence    tracks   real fish (matched)")
    for lo, hi in BINS:
        b = [r for r in rs if r[4] and lo <= r[3] < hi]
        if b:
            print(f"  [{lo:.1f}, {min(hi, 1):.1f}{')' if hi < 1 else ']'}{'':14s} {len(b):5d}   {sum(r[6] for r in b):3d} ({sum(r[6] for r in b) / len(b):.0%})")
    no = [r for r in rs if not r[4]]
    if no:
        print(f"  A1 says not the target      {len(no):5d}   {sum(r[6] for r in no):3d} ({sum(r[6] for r in no) / len(no):.0%})")
    q = [r for r in rs if r[5]]; nq = [r for r in rs if not r[5]]
    print(f"  queued: {len(q)} tracks, {sum(r[6] for r in q)} real;  not queued: {len(nq)} tracks, {sum(r[6] for r in nq)} real")
    if rs:
        brier = sum(((r[3] if r[4] else 1 - r[3]) - r[6]) ** 2 for r in rs) / len(rs)
        print(f"  Brier score of P(fish) = conf if 'fish' else 1 - conf: {brier:.3f}")
