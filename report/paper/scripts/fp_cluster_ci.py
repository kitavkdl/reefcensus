"""Corrected held-out precision with a track-clustered bootstrap interval (§6.2, "A corrected precision").

The 40 unmatched boxes of the precision sheet come from 15 tracks, and boxes of one track are not independent, so the
interval resamples tracks, not boxes: draw 15 tracks with replacement, take all their boxes, and recompute the share
judged a fish and the corrected precision (517 + 153 * share) / 670 fixed in the sheet's protocol (key.json).
  python3 report/paper/scripts/fp_cluster_ci.py        ($0, no network; seed fixed)"""
import json, os, random
from collections import defaultdict

D = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "heldout", "fp_sheet")
key = json.load(open(os.path.join(D, "key.json")))
ans = json.load(open(os.path.join(D, "answers.json")))["answers"]
M, U = key["n_pool_matched"], key["n_pool_unmatched"]
tracks = defaultdict(list)
for it in key["items"]:
    if it["kind"] == "unmatched":
        tracks[f"{it['clip']}|{it['track']}"].append(ans[str(it["n"])])
T = list(tracks.values())


def precision(groups, ok):
    boxes = [v for g in groups for v in g]
    return (M + U * sum(v in ok for v in boxes) / len(boxes)) / (M + U)


rng = random.Random(1104)
for name, ok in (("clear fish only (O)", {"O"}), ("with part-of-a-fish boxes (O, P)", {"O", "P"})):
    point = precision(T, ok)
    reps = sorted(precision([rng.choice(T) for _ in T], ok) for _ in range(10000))
    print(f"{name}: {100 * point:.1f}%, track bootstrap 95% interval {100 * reps[249]:.1f}-{100 * reps[9749]:.1f}% "
          f"({sum(len(g) for g in T)} boxes, {len(T)} tracks, 10,000 resamples)")
print(f"unsure boxes kept apart: {sum(v == '?' for g in T for v in g)} on "
      f"{sum(any(v == '?' for v in g) for g in T)} tracks; if all are fish the sample's precision is 100%")
