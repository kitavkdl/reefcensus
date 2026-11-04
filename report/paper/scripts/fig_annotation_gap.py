"""Figure 3: the last frame of held-out clip 20190709_17. Cyan = boxes of tracks the pipeline counts (run cr7,
bundled in data/heldout/runs), orange = the dataset's human reference boxes (data/heldout/gt). Needs the clip itself
(~/meta-smoke, not bundled: the dataset's videos are not redistributed here).
  PYTHONPATH=~/meta-smoke/pylib:. python3 report/paper/scripts/fig_annotation_gap.py"""
import json, os, sys
import cv2, numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
from fishcount import video  # noqa: E402
B, CID, F = os.path.join(ROOT, "report/paper/data/heldout"), "fish_20190709_17", 29
clip = os.path.expanduser(f"~/meta-smoke/{json.load(open(f'{B}/manifest.json'))['clips'][CID]['path']}")
res = json.load(open(f"{B}/runs/cr7_{CID}/result.json"))
lab = lambda t: res["auto_labels"].get(t, res["tracks"].get(t, {}).get("label"))   # as rescore_heldout.boxes
pipe = [k["box"] for k in res["frames"][str(F)] if lab(k["track"])]
gt = json.load(open(f"{B}/gt/{CID}.json"))["frames"][str(F)]
img = np.array(video.frames(clip, [F])[F]).copy()
for x0, y0, x1, y1 in pipe:
    cv2.rectangle(img, (int(x0), int(y0)), (int(x1), int(y1)), (255, 210, 0), 5)
for x, y, w, h, *_ in gt:
    cv2.rectangle(img, (int(x), int(y)), (int(x + w), int(y + h)), (0, 140, 255), 5)
img = cv2.resize(img, (1600, 900))
out = os.path.join(ROOT, sys.argv[1] if len(sys.argv) > 1 else "report/paper/figures/annotation_gap.jpg")
cv2.imwrite(out, img, [cv2.IMWRITE_JPEG_QUALITY, 85])
print(out, f"pipeline {len(pipe)}, human {len(gt)}")
