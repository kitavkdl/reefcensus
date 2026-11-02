"""Video asset for the 0:20 scene: the same deep-sea frame asked two ways. Left: SAM 3.1 prompt "animal" (0
detections, response status completed). Right: prompt "fish" with every mask and box. Uses the saved SAM outputs
in spikes/L1/out (no API calls). Writes demo/out/compare_<clip>.jpg, one per IMAS clip, at the frame with the
most fish.

    python3 demo/prompt_compare.py
"""
import os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.expanduser("~/meta-smoke/pylib"))
import cv2
import numpy as np
from fishcount import maskcodec, video

OUT = os.path.join(ROOT, "demo", "out")
FOUND = (29, 85, 242)       # BGR survey orange, same as render.FOUND
FONT = cv2.FONT_HERSHEY_SIMPLEX


def banner(img, title, sub, col):
    H, W = img.shape[:2]
    cv2.rectangle(img, (0, 0), (W, 120), (28, 24, 20), -1)
    cv2.putText(img, title, (32, 58), FONT, 1.6, (255, 255, 255), 3, cv2.LINE_AA)
    cv2.putText(img, sub, (32, 104), FONT, 1.3, col, 3, cv2.LINE_AA)


def compare(clip):
    raw = lambda word: open(os.path.join(ROOT, "spikes/L1/out", f"{clip}__{word}.txt")).read()
    animal, fish = raw("animal"), raw("fish")
    assert not list(maskcodec.records(animal)), "expected zero detections for 'animal'"
    per = maskcodec.masks(fish)
    f = max(per, key=lambda k: len(per[k]))
    img = video.frames(os.path.join(ROOT, "spikes/L1/clips", f"{clip}.mp4"), [f])[f]
    left, right = img.copy(), img.copy()
    over = right.copy()
    for box, m in per[f]:
        x0, y0 = int(round(box[0])), int(round(box[1]))
        mm = m[: img.shape[0] - y0, : img.shape[1] - x0]
        over[y0:y0 + mm.shape[0], x0:x0 + mm.shape[1]][mm] = FOUND
    right = cv2.addWeighted(over, 0.5, right, 0.5, 0)
    for box, _ in per[f]:
        x0, y0, x1, y1 = map(int, box)
        cv2.rectangle(right, (x0, y0), (x1, y1), FOUND, 3)
    banner(left, 'SAM 3.1   prompt: "animal"', "0 detections", (160, 160, 160))
    banner(right, 'SAM 3.1   prompt: "fish"', f"{len(per[f])} detections", FOUND)
    gap = np.full((img.shape[0], 16, 3), 255, np.uint8)
    out = np.hstack([left, gap, right])
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"compare_{clip}.jpg")
    cv2.imwrite(path, out, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return path, f, len(per[f])


if __name__ == "__main__":
    for c in ("imas_TF_52", "imas_TF_63", "imas_TF_81"):
        print(*compare(c))
