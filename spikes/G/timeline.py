"""Spike G: draw a contact timeline (rows = object pairs, bars = frames in contact) from maskcontact.py output.
usage: python3 timeline.py <contacts.txt> <n_frames> <out.png> [--skip board]"""
import os, sys
sys.path.insert(0, os.path.expanduser("~/meta-smoke/pylib"))
import cv2
import numpy as np

a = sys.argv[1:]
src, n, out = a[0], int(a[1]), a[2]
skip = a[a.index("--skip") + 1] if "--skip" in a else None
spans, open_ = {}, {}
for line in open(src):
    f, kind, rest = line.split(" ", 2)
    p = tuple(x.strip(" '()\n") for x in rest.split(","))
    if skip and any(x.startswith(skip) for x in p):
        continue
    if kind == "touch":
        open_[p] = int(f)
    elif p in open_:
        spans.setdefault(p, []).append((open_.pop(p), int(f)))
for p, s in open_.items():
    spans.setdefault(p, []).append((s, n))
rows = sorted(spans)
L, cw, rh = 230, 16, 34
img = np.full((40 + rh * len(rows), L + cw * n + 20, 3), 250, np.uint8)
for f in range(0, n + 1, 10):
    x = L + f * cw
    cv2.line(img, (x, 30), (x, img.shape[0]), (215, 215, 215), 1)
    cv2.putText(img, str(f), (x - 6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (90, 90, 90), 1)
for r, p in enumerate(rows):
    y = 40 + r * rh
    cv2.putText(img, f"{p[0]} - {p[1]}", (8, y + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (30, 30, 30), 1)
    for s, e in spans[p]:
        cv2.rectangle(img, (L + s * cw, y + 6), (L + e * cw, y + rh - 6), (60, 60, 210), -1)
cv2.imwrite(out, img)
print(out, len(rows), "pairs")
