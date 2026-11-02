"""Same animal, two boxes: 11/2 s004 frame 24 had shrimp boxed twice by different passes (whole body incl.
legs from one, body only from another), so MaxN counted each twice. Box overlap can't separate that from two
animals touching (11/1 s003: one nautilus partly behind another, whole and correct). Masks can: a duplicate's
mask lies inside the other's; two animals' masks barely overlap even when their boxes nest."""
from fishcount import maskcodec, render, tracks


def decode_sources(raw, W, H):
    """{src: {frame: [(box, mask, x0, y0)]}} in full-frame pixels (tile masks mapped back)."""
    out = {}
    for src, (text, tile) in raw.items():
        if not text:
            continue
        dec = maskcodec.masks(text)
        out[src] = {f: render._masks_full(text, tile, ms, W, H) for f, ms in dec.items()}
    return out


def det_mask(dec, src, f, box):
    """The mask record of `src` in frame f whose box matches a kept detection's box."""
    cands = dec.get(src, {}).get(f, [])
    best = max(cands, key=lambda c: tracks.iou(c[0], box), default=None)
    if best is None or tracks.iou(best[0], box) < 0.8:   # stitched track: this frame's piece came from another pass
        cands = [c for d in dec.values() for c in d.get(f, [])]
        best = max(cands, key=lambda c: tracks.iou(c[0], box), default=None)
    if best is None or tracks.iou(best[0], box) < 0.8:
        return None
    return best[1], best[2], best[3]


def containment(a, b):
    """|A & B| / min(|A|, |B|) for two placed masks (mask, x0, y0); None if either is missing or empty."""
    if a is None or b is None:
        return None
    (ma, ax, ay), (mb, bx, by) = a, b
    sa, sb = int(ma.sum()), int(mb.sum())
    if not sa or not sb:
        return None
    x0, y0 = max(ax, bx), max(ay, by)
    x1, y1 = min(ax + ma.shape[1], bx + mb.shape[1]), min(ay + ma.shape[0], by + mb.shape[0])
    if x1 <= x0 or y1 <= y0:
        return 0.0
    inter = int((ma[y0 - ay:y1 - ay, x0 - ax:x1 - ax] & mb[y0 - by:y1 - by, x0 - bx:x1 - bx]).sum())
    return inter / min(sa, sb)


def pairs(frames, dec, same=lambda a, b: True, min_c=0.0):
    """Yield (frame, i, j, containment) for same-frame detection pairs whose boxes touch."""
    for f, ks in frames.items():
        ms = [det_mask(dec, k.get("src", k["track"].split(":")[0]), f, k["box"]) for k in ks]
        for i in range(len(ks)):
            for j in range(i + 1, len(ks)):
                if not same(ks[i], ks[j]) or tracks.overlap(ks[i]["box"], ks[j]["box"]) <= 0:
                    continue
                c = containment(ms[i], ms[j])
                if c is not None and c >= min_c:
                    yield f, i, j, c
