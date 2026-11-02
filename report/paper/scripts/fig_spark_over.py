"""Figure: the most over-counted frame (Spark alone) on four held-out clips where SAM's MaxN is exact.
Green = dataset boxes. Dashed yellow circles = fish-like shapes without a box, marked by a non-expert (the authors)
from eye inspection; Spark's count-only reply carries no locations, so these are NOT the objects Spark counted.
  PYTHONPATH=~/meta-smoke/pylib:. python3 report/paper/scripts/fig_spark_over.py"""
import json, os, sys
import cv2, numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
from fishcount import video  # noqa: E402
S = os.path.expanduser("~/meta-smoke")
SC = json.load(open(os.path.join(ROOT, "report/paper/data/spark_count/held.json")))
PICKS = [("fish_20190710_5", 8, [(480, 130), (380, 470), (780, 80)]),
         ("fish_20190709_3", 16, [(1050, 922), (945, 117)]),
         ("fish_20190618_6", 9, [(510, 125), (595, 300)]),
         ("fish_20190710_6", 27, [(540, 615), (645, 322)])]

def dashed_circle(img, c, r, col, th):
    for a in range(0, 360, 30):
        cv2.ellipse(img, c, (r, r), 0, a, a + 18, col, th)

man = json.load(open(f"{S}/clips/manifest_heldout.json"))["clips"]
tiles = []
for cid, f, pts in PICKS:
    gt = json.load(open(f"{S}/{man[cid]['gt']}"))["frames"][str(f)]
    sp = {r["clip"]: r for r in SC}[cid]["per_frame"][str(f)]
    img = np.array(video.frames(f"{S}/{man[cid]['path']}", [f])[f]).copy()
    for x, y, w, h, _ in gt:
        cv2.rectangle(img, (int(x), int(y)), (int(x + w), int(y + h)), (0, 220, 0), 5)
    for p in pts:
        dashed_circle(img, p, 70, (0, 230, 255), 5)
    t = cv2.resize(img, (960, 540))
    cv2.rectangle(t, (0, 490), (960, 540), (0, 0, 0), -1)
    cv2.putText(t, f"{cid[5:]} frame {f}: boxes {sp[0]}, Spark {sp[1]}", (12, 527),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2, cv2.LINE_AA)
    tiles.append(t)
grid = np.vstack([np.hstack(tiles[:2]), np.hstack(tiles[2:])])
out = os.path.join(ROOT, "report/paper/figures/spark_over.jpg")
cv2.imwrite(out, grid, [cv2.IMWRITE_JPEG_QUALITY, 82])
print(out, grid.shape, os.path.getsize(out))
