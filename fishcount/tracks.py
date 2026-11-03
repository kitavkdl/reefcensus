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


def reverse_text(text, n):
    """Renumber a SAM output made on a reversed clip so frame indices refer to the original clip."""
    return "\n".join(LINE.sub(lambda m: f"<{n - 1 - int(m.group(1))}f>{m.group(2)}", ln.strip()) for ln in text.splitlines())


def shift_text(text, offset):
    """Renumber a SAM output made on a clip that starts `offset` frames into the original."""
    return "\n".join(LINE.sub(lambda m: f"<{int(m.group(1)) + offset}f>{m.group(2)}", ln.strip()) for ln in text.splitlines())


# SAM 3.1 (API) hands out at most 16 object ids per call, for the whole clip, not per frame: of ~250 cached outputs
# none has more than 16 distinct ids and 18 have exactly 16. 11/3 IMAS TF_52: the crowd tile r1c1 had its 16 by
# frame 22 and never added another, so a large seabream that swam over the pale sand at frame ~45 got no box at all.
SAM_MAX_OBJECTS = 16


def saturation_frame(dets, cap=SAM_MAX_OBJECTS):
    """First frame at which the call had used all `cap` ids (objects arriving after it were never looked at), or None."""
    seen = set()
    for f in sorted(dets):
        seen.update(d["id"] for d in dets[f])
        if len(seen) >= cap:
            return f
    return None


def max_per_frame(dets):
    return max((len(ds) for ds in dets.values()), default=0)


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


def from_tile(dets, tile, scale, margin=0.02):
    """Map detections found in an upscaled crop back to full-frame pixels. tile=(x,y,w,h).
    cut=True when the box touches the crop border (a partial animal), so merge() may match it by containment."""
    x0, y0, tw, th = tile
    mx, my = margin * tw * scale, margin * th * scale
    cut = lambda b: b[0] <= mx or b[1] <= my or b[2] >= tw * scale - mx or b[3] >= th * scale - my
    out = {}
    for f, ds in dets.items():
        out[f] = [dict(d, cut=cut(d["box"]), box=(x0 + d["box"][0] / scale, y0 + d["box"][1] / scale,
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
                # 11/1 s003: a whole nautilus from a zoom tile lay inside a bigger one's box and containment dropped
                # it; containment is only for tile-cut partials, an uncut tile detection must match by IoU
                sim = iou if d.get("cut") is False else overlap
                hit = max(((sim(d["box"], k["box"]), k) for k in kept[f] if k["src"] != src), key=lambda t: t[0], default=(0, None))
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
    for f in kept:
        kept[f] = drop_group_boxes(kept[f])
    frames, tracks = {}, {}
    for f, ks in kept.items():
        for k in ks:
            k["track"] = alias.get(k["track"], k["track"])
            t = tracks.setdefault(k["track"], dict(label=k["label"], source=k["track"].split(":")[0], frames=[]))
            t["frames"].append(f)
        frames[f] = ks
    return frames, tracks


def drop_group_boxes(ks, contain=0.8):
    """11/1 s004: one box was drawn around two shrimp that other passes had boxed separately, so all three were
    counted. A box that contains two or more other same-label boxes is a group box and is dropped. A box holding
    just one (s003: a nautilus partly behind a bigger one) is kept."""
    def inside(a, b):   # share of a lying inside b
        ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
        iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
        return ix * iy / max(1e-6, (a[2] - a[0]) * (a[3] - a[1]))
    group = {i for i, g in enumerate(ks)
             if sum(1 for j, k in enumerate(ks) if j != i and k["label"] == g["label"] and inside(k["box"], g["box"]) >= contain) >= 2}
    return [k for i, k in enumerate(ks) if i not in group]


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


def _near(a, b, min_iou=0.2):
    """Overlapping, or centres closer than 0.6 of the larger box side (stitch()'s continuation test)."""
    if iou(a, b) >= min_iou:
        return True
    ca, cb = ((a[0] + a[2]) / 2, (a[1] + a[3]) / 2), ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
    size = max(a[2] - a[0], a[3] - a[1], b[2] - b[0], b[3] - b[1])
    return ((ca[0] - cb[0]) ** 2 + (ca[1] - cb[1]) ** 2) ** 0.5 < 0.6 * size


def split_jumps(frames, tracks, max_gap=10):
    """Cut a track where SAM reused its ID for another object. 11/3 IMAS TF_52: a large fish crossed the top of the
    frame (frames 0-15) and left; SAM gave its ID to a 22 px speck at frame 52, so the audit's crops were the fish cut
    off at the frame edge and the speck, and Spark rejected the fish as "kelp frond". A track is cut where it is gone
    for more than `max_gap` frames and comes back somewhere its last box is not near (stitch()'s test, so stitch()
    would not have joined the two pieces either); later pieces get ids "<id>/2", "/3", ...
    Mutates `frames` in place; returns (frames, new tracks dict)."""
    last = {}
    for f in sorted(frames):
        for k in frames[f]:
            t = k["track"]
            n = 1
            if t in last:
                lf, lb, n = last[t]
                if f - lf > max_gap and not _near(lb, k["box"]):
                    n += 1
            last[t] = (f, k["box"], n)
            if n > 1:
                k["track"] = f"{t}/{n}"
    base = lambda tid: tid.rsplit("/", 1)[0] if "/" in tid else tid
    new = {}
    for f in sorted(frames):
        for k in frames[f]:
            src = tracks[base(k["track"])]
            new.setdefault(k["track"], dict(src, frames=[]))["frames"].append(f)
    return frames, new


def stitch(frames, tracks, max_gap=10, min_iou=0.2, apart=()):
    """Re-join fragmented IDs: track B is a continuation of track A if B starts within `max_gap` frames after A
    ends, they never co-occur, share a label, and A's last box overlaps / is near B's first box.
    apart: source prefixes (e.g. ("camo",)) whose tracks are joined only with each other, so adding them leaves every
    other track as it was (11/3 TF_52: a camo box joined a crowd track, every later track number moved by one and the
    audit sheets were asked again).
    Mutates `frames` in place; returns the new tracks dict."""
    span = {}
    for f in sorted(frames):
        for k in frames[f]:
            s = span.setdefault(k["track"], [f, f, k["box"], k["box"]])
            s[1], s[3] = f, k["box"]
    near = lambda a, b: _near(a, b, min_iou)
    alias = {}
    root = lambda t: root(alias[t]) if t in alias else t
    order = sorted(span, key=lambda t: span[t][0])
    for b in order:
        best = None
        for a in order:
            ra = root(a)
            if ra == b or a == b or tracks[a]["label"] != tracks[b]["label"]:
                continue
            if tracks[ra]["source"].startswith(apart) != tracks[b]["source"].startswith(apart):
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
