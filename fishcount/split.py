"""One SAM mask over two animals apart (D-SPLIT, 11/23: one SAM box can hold two fish a body length
apart, so a frame counts one fish less). No Spark or SAM call: the masks and detections are already here.

A counted box whose mask falls into two or more separate blobs (dilated DILATE px, each >= MIN_SHARE of the frame and
>= MIN_RATIO of the largest; a blob another counted box's mask already covers is left out) is
- split into one box per blob when another pass backs it: a detection of any pass in that frame that is not a box
  kept there (IoU >= SELF_IOU) and matches one blob (IoU >= SUPPORT_IOU), i.e. a second pass saw that blob as an
  animal on its own, and every blob is a whole body: its box's long side is at least BODY of the median long side of
  the track's boxes in its other frames, every frame where find reports nothing for it (one blob, no mask, or parts
  another counted box covers; none: no body to compare, so no split). A fish cut in
  two by something in front (11/23 review 2) has parts far shorter than its body, so a zoom/cell pass boxing one half
  does not split it, while the two fish of the case it was made for are each close to a whole body. The gap between
  the blobs is not a rule: in that case it was less than either body. The blob nearest the track's previous box keeps the track; the others go to child tracks
  "<track>~2", "~3"... with the parent's label and a copy of its verdict (name + "b", "c"...), so a child is queued
  or not exactly as its parent and no new question is asked;
- otherwise only marked: the box gets "blobs": n, which the review screen's upper end of the MaxN range counts
  (web/server.py effective); the count, the queue and the lower end stay as they are.
"""
import os
import shutil

import cv2
import numpy as np

from fishcount import maskdedupe, tracks

DILATE, MIN_SHARE, MIN_RATIO = 5, 1e-4, 0.25
SELF_IOU, SUPPORT_IOU, COVER, BODY = 0.8, 0.5, 0.5, 0.6


def family(t):
    """A split child's parent track ("p0+8:0~2" -> "p0+8:0"); any other track is its own."""
    return t.split("~")[0]


def blobs(mask, W, H):
    """The separate parts of one mask (local pixels, largest first) by the rule above; [] when it is one animal."""
    mask = mask.astype(bool)
    n, lab, st, _ = cv2.connectedComponentsWithStats(cv2.dilate(mask.astype(np.uint8), np.ones((DILATE, DILATE), np.uint8)),
                                                     connectivity=8)
    if n < 3:
        return []
    order = sorted(range(1, n), key=lambda i: -st[i, 4])
    keep = [i for i in order if st[i, 4] >= MIN_SHARE * W * H and st[i, 4] >= MIN_RATIO * st[order[0], 4]]
    return [(lab == i) & mask for i in keep] if len(keep) >= 2 else []


def _cover(gx, gy, m):
    """Share of the pixels (gx, gy) inside mask record m = (mask, x0, y0)."""
    mask, x0, y0 = m
    lx, ly = gx - x0, gy - y0
    ok = (lx >= 0) & (ly >= 0) & (lx < mask.shape[1]) & (ly < mask.shape[0])
    return mask[ly[ok], lx[ok]].sum() / len(gx)


def find(frames, labels, trk, dec, sources, W, H):
    """[{frame, track, boxes: [one box per blob], support: [[source, id]...]}] for every counted box of two blobs or
    more (support empty: mark only). dec: maskdedupe.decode_sources; sources: what tracks.merge was given."""
    lab = lambda t: labels.get(t, trk[t]["label"])
    out = []
    for f in sorted(frames):
        ks = frames[f]
        counted = [k for k in ks if lab(k["track"])]
        ms = [maskdedupe.det_mask(dec, k["track"].split(":")[0], f, k["box"]) for k in counted]
        for i, k in enumerate(counted):
            if ms[i] is None:
                continue
            mask, x0, y0 = ms[i]
            boxes = []
            for p in blobs(mask, W, H):
                ys, xs = np.nonzero(p)
                gx, gy = xs + x0, ys + y0
                if any(m is not None and j != i and _cover(gx, gy, m) >= COVER for j, m in enumerate(ms)):
                    continue        # already counted as an animal of its own
                boxes.append([int(gx.min()), int(gy.min()), int(gx.max()) + 1, int(gy.max()) + 1])
            if len(boxes) < 2:
                continue
            sup = sorted({(src, d["id"]) for src, _, dets in sources for d in dets.get(f, [])
                          if not any(tracks.iou(d["box"], o["box"]) >= SELF_IOU for o in ks)
                          and any(tracks.iou(d["box"], b) >= SUPPORT_IOU for b in boxes)})
            out.append(dict(frame=f, track=k["track"], boxes=boxes, support=[list(s) for s in sup]))
    hit = {(h["frame"], h["track"]) for h in out}
    side = lambda b: max(b[2] - b[0], b[3] - b[1])
    for h in out:
        body = [side(k["box"]) for f, ks in frames.items() for k in ks if k["track"] == h["track"] and (f, h["track"]) not in hit]
        if not body or min(map(side, h["boxes"])) < BODY * float(np.median(body)):
            h["support"] = []
    return out


def apply(frames, trk, labels, verdicts, found, thumbs=None):
    """Split the backed boxes of `found` and mark the others (mutates frames, trk, labels, verdicts). thumbs: the
    run's thumbs/ folder; a child gets copies of its parent's thumbnails under its own name. Returns the splits made
    [{frame, track, into: [track, child...], support}]."""
    hits = {(h["frame"], h["track"]): h for h in found}
    last, kids, splits = {}, {}, []
    for f in sorted(frames):
        new = []
        for k in frames[f]:
            t, h = k["track"], hits.get((f, k["track"]))
            if h is None or not h["support"]:
                new.append(dict(k, blobs=len(h["boxes"])) if h else k)
                last[t] = k["box"]
                continue
            boxes = list(h["boxes"])
            mine = max(boxes, key=lambda b: tracks.iou(b, last.get(t, k["box"])))
            boxes.remove(mine)
            new.append(dict(k, box=mine))
            last[t], into = mine, [t]
            free = list(kids.get(t, []))
            for b in boxes:
                c = max(free, key=lambda c: tracks.iou(b, last[c]), default=None)
                if c is None:
                    c = _child(t, len(kids.setdefault(t, [])) + 2, trk, labels, verdicts, h, thumbs)
                    kids[t].append(c)
                else:
                    free.remove(c)
                new.append(dict(k, track=c, box=b))
                last[c] = b
                trk[c]["frames"].append(f)
                into.append(c)
            splits.append(dict(frame=f, track=t, into=into, support=h["support"]))
        frames[f] = new
    return splits


def _child(t, n, trk, labels, verdicts, h, thumbs):
    c = f"{t}~{n}"
    trk[c] = dict(trk[t], frames=[])
    if t in labels:
        labels[c] = labels[t]
    if t in verdicts:
        v = verdicts[t]
        name = f"{v.get('name') or t}{chr(ord('a') + n - 1)}"
        verdicts[c] = dict(v, name=name, split_from=t,
                           split_reason=f"one SAM mask over {len(h['boxes'])} separate parts; another pass saw a part on its own "
                                        f"({', '.join(f'{s}:{i}' for s, i in h['support'])})")
        for suffix in (".jpg", "_trio.jpg") if thumbs else ():
            a = os.path.join(thumbs, f"{v.get('name')}{suffix}")
            if os.path.exists(a):
                shutil.copy(a, os.path.join(thumbs, f"{name}{suffix}"))
    return c
