"""Video asset for the 0:20 scene: the same deep-sea frame asked two ways. Left: SAM 3.1 prompt "animal" (0
detections, response status completed). Right: prompt "fish" with every mask and box. Uses the saved SAM outputs
in spikes/L1/out (no API calls). Writes demo/out/compare_<clip>.jpg, one per IMAS clip, at the frame with the
most fish.

compare3(): the same frame a third way, the full reefcensus run (runs/imas_TF_52, scout + zoom tiles). Every SAM
"fish" detection stays, and a faint fish that SAM missed on the full frame was found in a zoomed tile (zoom-left).
Writes demo/out/compare3_<clip>.jpg (three panels side by side) and panel_<clip>_{animal,fish,pipeline}.jpg (each
full size, for the video editor).

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
ASKED = (200, 99, 29)       # BGR bait-pipe blue, same as render.ASKED
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


def paint(img, dets, col, alpha=0.5, thick=3):
    over = img.copy()
    for box, m in dets:
        x0, y0 = int(round(box[0])), int(round(box[1]))
        mm = m[: img.shape[0] - y0, : img.shape[1] - x0]
        over[y0:y0 + mm.shape[0], x0:x0 + mm.shape[1]][mm] = col
    out = cv2.addWeighted(over, alpha, img, 1 - alpha, 0)
    for box, _ in dets:
        x0, y0, x1, y1 = map(int, box)
        cv2.rectangle(out, (x0, y0), (x1, y1), col, thick)
    return out


def inset(img, box, at, scale=4, col=FOUND, src=None):
    """Magnified copy of `box` (with some context) pasted with its top-left at `at`, joined to the box by a line."""
    x0, y0, x1, y1 = map(int, box)
    cx, cy, w, h = (x0 + x1) // 2, (y0 + y1) // 2, (x1 - x0) * 2, (y1 - y0) * 2
    a, b = max(0, cx - w // 2), max(0, cy - h // 2)
    patch = (img if src is None else src)[b:b + h, a:a + w].copy()
    big = cv2.resize(patch, (patch.shape[1] * scale, patch.shape[0] * scale), interpolation=cv2.INTER_CUBIC)
    bx0, by0, bx1, by1 = [(v - o) * scale for v, o in ((x0, a), (y0, b), (x1, a), (y1, b))]
    cv2.rectangle(big, (bx0 - 8, by0 - 8), (bx1 + 8, by1 + 8), col, 3)
    X, Y = at
    H, W = big.shape[:2]
    cv2.line(img, (x0 - 6, (y0 + y1) // 2), (X + W, Y + H // 2), col, 3, cv2.LINE_AA)
    img[Y:Y + H, X:X + W] = big
    cv2.rectangle(img, (X, Y), (X + W, Y + H), col, 6)
    cv2.putText(img, f"x{scale}", (X + 12, Y + 44), FONT, 1.3, col, 3, cv2.LINE_AA)


def compare3(clip="imas_TF_52", run="imas_TF_52"):
    import json
    raw = lambda word: open(os.path.join(ROOT, "spikes/L1/out", f"{clip}__{word}.txt")).read()
    assert not list(maskcodec.records(raw("animal"))), "expected zero detections for 'animal'"
    per = maskcodec.masks(raw("fish"))
    f = max(per, key=lambda k: len(per[k]))
    res = json.load(open(os.path.join(ROOT, "runs", run, "result.json")))
    assert video.info(os.path.join(ROOT, "runs", run, "clip.mp4"))["n_frames"] == \
        video.info(os.path.join(ROOT, "spikes/L1/clips", f"{clip}.mp4"))["n_frames"]
    hits = res["frames"][str(f)]
    extra = [h for h in hits if h["track"].startswith("zoom-")]
    img = video.frames(os.path.join(ROOT, "spikes/L1/clips", f"{clip}.mp4"), [f])[f]
    left = img.copy()
    mid = paint(img, per[f], ASKED)
    right = paint(img, per[f], ASKED)
    for h in extra:
        x0, y0, x1, y1 = map(int, h["box"])
        cv2.rectangle(right, (x0 - 6, y0 - 6), (x1 + 6, y1 + 6), FOUND, 6)
    if extra:
        inset(right, extra[0]["box"], at=(40, 150), src=img)
    banner(left, 'SAM 3.1   prompt: "animal"', "0 detections", (160, 160, 160))
    banner(mid, 'SAM 3.1   prompt: "fish"', f"{len(per[f])} detections", ASKED)
    banner(right, "reefcensus   SAM 3.1 + Muse Spark",
           f"{len(hits)} detections  (+{len(extra)} faint fish found in a zoomed tile)", FOUND)
    os.makedirs(OUT, exist_ok=True)
    for name, im in (("animal", left), ("fish", mid), ("pipeline", right)):
        cv2.imwrite(os.path.join(OUT, f"panel_{clip}_{name}.jpg"), im, [cv2.IMWRITE_JPEG_QUALITY, 90])
    gap = np.full((img.shape[0], 16, 3), 255, np.uint8)
    path = os.path.join(OUT, f"compare3_{clip}.jpg")
    cv2.imwrite(path, np.hstack([left, gap, mid, gap, right]), [cv2.IMWRITE_JPEG_QUALITY, 90])
    return path, f, len(per[f]), len(hits), [h["track"] for h in extra]


LABEL_COL = {"striped seabream": FOUND, "fish (unidentified)": (60, 200, 250)}   # BGR orange, amber


def compare_luderick(run="eval6_fish_20190618_9", frame=35):
    """Video asset for the 0:16 scene, CC BY 4.0 footage (luderick archive, PANGAEA 926930, clip 20190618_9).
    Same frame three ways: SAM 3.1 "animal" (0 detections in all 107 frames), SAM 3.1 "fish", and the audited run
    (Spark's names on SAM's tracks). Cached replies only, no API calls. Writes panel_luderick_{animal,fish,pipeline}.jpg
    and compare3_luderick.jpg."""
    import json
    from fishcount import api
    clip = os.path.join(ROOT, "runs", run, "clip.mp4")
    n = video.info(clip)["n_frames"]
    animal = api.sam_video(clip, "animal", n, offline=True)
    assert not list(maskcodec.records(animal)), "expected zero detections for 'animal' on this clip"
    per = maskcodec.masks(api.sam_video(clip, "fish", n, offline=True))
    res = json.load(open(os.path.join(ROOT, "runs", run, "result.json")))
    labels = res["auto_labels"]
    img = video.frames(clip, [frame])[frame]
    left = img.copy()
    mid = paint(img, per[frame], ASKED)
    right = img.copy()
    hits = res["frames"][str(frame)]
    tally = {}
    for h in hits:
        lab = labels.get(h["track"], "fish (unidentified)")
        tally[lab] = tally.get(lab, 0) + 1
        x0, y0, x1, y1 = map(int, h["box"])
        cv2.rectangle(right, (x0, y0), (x1, y1), LABEL_COL.get(lab, FOUND), 4)
    sub = "  +  ".join(f"{v} {k}" for k, v in sorted(tally.items(), key=lambda kv: -kv[1]))
    banner(left, 'SAM 3.1   prompt: "animal"', "0 detections", (160, 160, 160))
    banner(mid, 'SAM 3.1   prompt: "fish"', f"{len(per[frame])} detections", ASKED)
    banner(right, "reefcensus   SAM 3.1 + Muse Spark", sub, FOUND)
    os.makedirs(OUT, exist_ok=True)
    for name, im in (("animal", left), ("fish", mid), ("pipeline", right)):
        cv2.imwrite(os.path.join(OUT, f"panel_luderick_{name}.jpg"), im, [cv2.IMWRITE_JPEG_QUALITY, 90])
    gap = np.full((img.shape[0], 16, 3), 255, np.uint8)
    path = os.path.join(OUT, "compare3_luderick.jpg")
    cv2.imwrite(path, np.hstack([left, gap, mid, gap, right]), [cv2.IMWRITE_JPEG_QUALITY, 90])
    return path, frame, len(per[frame]), tally


if __name__ == "__main__":
    for c in ("imas_TF_52", "imas_TF_63", "imas_TF_81"):
        print(*compare(c))
    print(*compare3())
    print(*compare_luderick())
