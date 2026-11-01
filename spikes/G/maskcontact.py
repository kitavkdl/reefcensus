"""Spike G: mask-adjacency contacts (dilated masks overlap) between objects from several SAM concept runs.
usage: python3 maskcontact.py <clip.mp4> <name>=<sam.txt>... [--dilate 6] [--min 30]"""
import os, sys
sys.path.insert(0, os.path.expanduser("~/meta-fish"))
from fishcount import render, tracks, video
import cv2
import numpy as np


def full_masks(text, f, W, H):
    dets = tracks.parse_boxes(text).get(f, [])
    out = {}
    for box, m in render.frame_masks(text, f):
        hit = max(dets, key=lambda d: tracks.iou(d["box"], box), default=None)
        if hit is None:
            continue
        x0, y0 = int(round(box[0])), int(round(box[1]))
        x1, y1 = min(W, x0 + m.shape[1]), min(H, y0 + m.shape[0])
        fm = np.zeros((H, W), bool)
        fm[y0:y1, x0:x1] = m[: y1 - y0, : x1 - x0]
        out[hit["id"]] = fm
    return out


if __name__ == "__main__":
    a = sys.argv[1:]
    clip = a[0]
    dil = int(a[a.index("--dilate") + 1]) if "--dilate" in a else 6
    mn = int(a[a.index("--min") + 1]) if "--min" in a else 30
    runs = {kv.split("=")[0]: open(kv.split("=", 1)[1]).read() for kv in a[1:] if "=" in kv and not kv.startswith("--")}
    i = video.info(clip)
    W, H, n = i["width"], i["height"], i["n_frames"]
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * dil + 1, 2 * dil + 1))
    state = set()
    for f in range(n):
        ms = {f"{c}#{t}": cv2.dilate(m.astype(np.uint8), k) for c, txt in runs.items() for t, m in full_masks(txt, f, W, H).items()}
        names = sorted(ms)
        cur = set()
        for x in range(len(names)):
            for y in range(x + 1, len(names)):
                if names[x].split("#")[0] != names[y].split("#")[0] and int((ms[names[x]] & ms[names[y]]).sum()) >= mn:
                    cur.add((names[x], names[y]))
        for p in sorted(cur - state):
            print(f, "touch", p)
        for p in sorted(state - cur):
            print(f, "release", p)
        state = cur
