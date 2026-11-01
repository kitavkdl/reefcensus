"""Turn SAM 3.1 video output into detections, tracks and survey metrics (MaxN, time of first arrival).
Boxes are read with a regex (fast); masks are decoded only for frames we render (see render.py)."""
import re
from collections import defaultdict

LINE = re.compile(r"^<(\d+)f>(.*)$")
BOX = re.compile(r"(\d+)<\|box;x1=([\d.]+);y1=([\d.]+);x2=([\d.]+);y2=([\d.]+);[^|]*?(?:c=([\d.]+))?\|>")


def parse_boxes(text):
    """{frame: [dict(id, box=(x1,y1,x2,y2) half-open, conf)]}"""
    out = {}
    for ln in text.splitlines():
        m = LINE.match(ln.strip())
        if not m:
            continue
        out[int(m.group(1))] = [dict(id=int(b[0]), box=(float(b[1]), float(b[2]), float(b[3]) + 1, float(b[4]) + 1),
                                     conf=float(b[5]) if b[5] else None) for b in BOX.findall(m.group(2))]
    return out


def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ix * iy
    return ix * iy / u if u else 0.0


def overlap(a, b):
    """Max of IoU and containment (intersection / smaller box). Containment catches a tile-cut partial fish."""
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    if not inter:
        return 0.0
    sa, sb = (a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])
    return max(inter / (sa + sb - inter), inter / min(sa, sb) - 0.2)   # containment 0.7 ~ IoU 0.5


def from_tile(dets, tile, scale):
    """Map detections found in an upscaled crop back to full-frame pixels. tile=(x,y,w,h)."""
    x0, y0 = tile[0], tile[1]
    out = {}
    for f, ds in dets.items():
        out[f] = [dict(d, box=(x0 + d["box"][0] / scale, y0 + d["box"][1] / scale,
                               x0 + d["box"][2] / scale, y0 + d["box"][3] / scale)) for d in ds]
    return out


def merge(sources, thr=0.5):
    """Combine detections from several SAM runs (different prompts or tiles) into one set of global tracks.
    sources: list of (source_name, label, {frame: [det]}) in priority order (first wins on overlap).
    Track identity: (source_name, sam_id). A lower-priority detection overlapping (IoU>=thr) a kept one in the
    same frame is dropped; its track is linked to the kept track if that happens on most of its frames.
    Returns (frames {f: [dict(track, label, box, conf)]}, tracks {track: dict(label, source, frames)})."""
    kept = defaultdict(list)
    dup = defaultdict(lambda: defaultdict(int))   # lower track -> higher track -> frames overlapped
    seen = defaultdict(int)
    for src, label, dets in sources:
        for f, ds in dets.items():
            for d in ds:
                tid = f"{src}:{d['id']}"
                seen[tid] += 1
                hit = max(((overlap(d["box"], k["box"]), k) for k in kept[f] if k["src"] != src), key=lambda t: t[0], default=(0, None))
                if hit[0] >= thr:
                    dup[tid][hit[1]["track"]] += 1
                    continue
                kept[f].append(dict(track=tid, src=src, label=label, box=d["box"], conf=d["conf"]))
    # link tracks that were mostly duplicates of a higher-priority track
    alias = {}
    for tid, hits in dup.items():
        top, n = max(hits.items(), key=lambda t: t[1])
        coexist = any(any(k["track"] == tid for k in ks) and any(k["track"] == top for k in ks) for ks in kept.values())
        if n >= 0.5 * seen[tid] and not coexist:
            alias[tid] = top
    frames, tracks = {}, {}
    for f, ks in kept.items():
        for k in ks:
            k["track"] = alias.get(k["track"], k["track"])
            t = tracks.setdefault(k["track"], dict(label=k["label"], source=k["track"].split(":")[0], frames=[]))
            t["frames"].append(f)
        frames[f] = ks
    return frames, tracks


def metrics(frames, tracks, n_frames, fps, labels=None):
    """Per-label count curve, MaxN (value + first frame reaching it) and time of first arrival.
    `labels` overrides a track's label (human review); a label of None/'' removes the track."""
    labels = labels or {}
    lab = lambda tid: labels.get(tid, tracks[tid]["label"]) if tid in tracks else None
    names = sorted({l for tid in tracks if (l := lab(tid))})
    curve = {n: [0] * n_frames for n in names}
    for f, ks in frames.items():
        if f >= n_frames:
            continue
        for k in ks:
            l = lab(k["track"])
            if l:
                curve[l][f] += 1
    out = {}
    for n in names:
        c = curve[n]
        m = max(c) if c else 0
        first = next((i for i, v in enumerate(c) if v), None)
        out[n] = dict(maxn=m, maxn_frame=c.index(m) if m else None, maxn_time=round(c.index(m) / fps, 2) if m else None,
                      first_frame=first, first_time=round(first / fps, 2) if first is not None else None,
                      tracks=sum(1 for tid in tracks if lab(tid) == n), curve=c)
    return out


def stitch(frames, tracks, max_gap=10, min_iou=0.2):
    """Re-join fragmented IDs: track B is a continuation of track A if B starts within `max_gap` frames after A
    ends, they never co-occur, share a label, and A's last box overlaps / is near B's first box.
    Mutates `frames` in place; returns the new tracks dict."""
    span = {}
    for f in sorted(frames):
        for k in frames[f]:
            s = span.setdefault(k["track"], [f, f, k["box"], k["box"]])
            s[1], s[3] = f, k["box"]
    def near(a, b):
        if iou(a, b) >= min_iou:
            return True
        ca, cb = ((a[0] + a[2]) / 2, (a[1] + a[3]) / 2), ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
        size = max(a[2] - a[0], a[3] - a[1], b[2] - b[0], b[3] - b[1])
        return ((ca[0] - cb[0]) ** 2 + (ca[1] - cb[1]) ** 2) ** 0.5 < 0.6 * size
    alias = {}
    root = lambda t: root(alias[t]) if t in alias else t
    order = sorted(span, key=lambda t: span[t][0])
    for b in order:
        best = None
        for a in order:
            ra = root(a)
            if ra == b or a == b or tracks[a]["label"] != tracks[b]["label"]:
                continue
            sa = span[ra]
            gap = span[b][0] - sa[1]
            if 0 < gap <= max_gap and near(sa[3], span[b][2]) and (best is None or gap < best[0]):
                best = (gap, ra)
        if best:
            ra = best[1]
            alias[b] = ra
            span[ra][1], span[ra][3] = span[b][1], span[b][3]
    new = {}
    for f, ks in frames.items():
        for k in ks:
            k["track"] = root(k["track"])
            t = new.setdefault(k["track"], dict(label=tracks[k["track"]]["label"], source=tracks[k["track"]]["source"], frames=[]))
            t["frames"].append(f)
    return new
