"""Where to look, from pixels alone (no model calls), and a SAM box prompt for what no word can find.

A BRUV camera sits still on the seabed, so the background barely changes. Pixels that differ from the clip's median
frame (in colour or brightness, the shading difference a person notices) AND changed over a few frames are linked
into short blob tracks. A blob track that lives a while and is not inside any box already found is a candidate.
Candidates are only "look here" hints: Spark is shown a crop of each and says which are animals, and SAM tracks
those from a box instead of a word. Nothing here is counted directly.

Measured 11/2 (spikes/motion.py, spikes/M): on nautilus clip s004 the top candidates include red shrimp that no
pass had tracked; a box on one (frame 32) tracked it in 57 of 60 frames, before and after the prompt frame. On s002
the candidates were sediment, shadows, bait and nautilus tentacles; on a busy reef clip (IMAS TF_52) they were too
many to be useful. Hence Spark decides, and at most a few boxes go to SAM.
"""
from fishcount import video   # puts ~/meta-smoke/pylib (cv2) on sys.path
import cv2
import numpy as np

SCALE = 0.5                 # analysis scale (1920x1080 -> 960x540)
GRID = 8                    # prompt boxes snap to this grid (stable cache keys)
LONG = 200                  # clips longer than this are analysed at 1/3 scale and a sparser median (memory)


def _frames(clip, scale):
    """Every frame, shrunk while reading (a 600-frame clip at full size would be ~3.7 GB). Returns (frames, sx, sy)
    where sx, sy map analysis pixels back to full-frame pixels."""
    inf = video.info(clip)
    w, h = round(inf["width"] * scale), round(inf["height"] * scale)
    out, cap = [], cv2.VideoCapture(clip)
    while True:
        ok, f = cap.read()
        if not ok:
            break
        out.append(cv2.resize(f, (w, h), interpolation=cv2.INTER_AREA))
    cap.release()
    return out, inf["width"] / w, inf["height"] / h


def _lab(f):
    return cv2.cvtColor(f, cv2.COLOR_BGR2LAB).astype(np.float32)


def candidates(clip, known, gap=2, min_area=12, max_area=2500, link=14, pad=6, scale=None):
    """Blob tracks in full-resolution coordinates. `known` = {frame: [[x0,y0,x1,y1], ...]} full-res boxes already
    found; a blob whose centre is inside one (plus `pad` px at analysis scale) is marked inside for that frame."""
    n = video.info(clip)["n_frames"]
    scale = scale or (SCALE if n <= LONG else SCALE * 2 / 3)
    if scale != SCALE:      # areas are in analysis pixels; keep them meaning the same animal size
        k = (scale / SCALE) ** 2
        min_area, max_area, link, pad = max(4, int(min_area * k)), int(max_area * k), link * scale / SCALE, pad * scale / SCALE
    frames, sx, sy = _frames(clip, scale)
    step = 1 if len(frames) <= LONG else 3
    bgl = _lab(np.median(np.stack(frames[::step]), axis=0).astype(np.uint8))
    dist = lambda f: cv2.GaussianBlur(np.linalg.norm(_lab(f) - bgl, axis=2), (5, 5), 0)
    allv = np.concatenate([dist(f)[::4, ::4].ravel() for f in frames])     # pass 1: threshold only
    med = float(np.median(allv))
    thr = max(8.0, med + 6 * (float(np.median(np.abs(allv - med))) + 1e-6))
    ks = {f: [[b[0] / sx, b[1] / sy, b[2] / sx, b[3] / sy] for b in bs] for f, bs in known.items()}
    done, live = [], []
    for t in range(len(frames)):                                            # pass 2: blobs
        d = dist(frames[t])
        a, b = max(0, t - gap), min(len(frames) - 1, t + gap)
        moved = cv2.GaussianBlur(np.linalg.norm(_lab(frames[b]) - _lab(frames[a]), axis=2), (5, 5), 0) > thr * 0.8
        m = ((d > thr) & moved).astype(np.uint8)
        m = cv2.dilate(cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8)), np.ones((3, 3), np.uint8))
        n, cc, st, cen = cv2.connectedComponentsWithStats(m, 8)
        blobs = []
        for i in range(1, n):
            x, y, w, h, area = (int(v) for v in st[i])
            if not (min_area <= area <= max_area):
                continue
            cx, cy = float(cen[i][0]), float(cen[i][1])
            inside = any(x0 - pad <= cx <= x1 + pad and y0 - pad <= cy <= y1 + pad for x0, y0, x1, y1 in ks.get(t, []))
            blobs.append(dict(t=t, c=(cx, cy), box=(x, y, x + w, y + h), area=area, inside=inside))
        nxt, used = [], set()
        for tr in live:
            last, best, bd = tr[-1], None, link
            for j, bl in enumerate(blobs):
                if j not in used:
                    dd = float(np.hypot(bl["c"][0] - last["c"][0], bl["c"][1] - last["c"][1]))
                    if dd < bd:
                        best, bd = j, dd
            if best is not None:
                used.add(best)
                tr.append(blobs[best])
                nxt.append(tr)
            elif t - last["t"] <= 1:
                nxt.append(tr)
            else:
                done.append(tr)
        nxt += [[bl] for j, bl in enumerate(blobs) if j not in used]
        live = nxt
    out = []
    for tr in done + live:
        out.append(dict(first=tr[0]["t"], last=tr[-1]["t"], n=len(tr),
                        inside=round(sum(b["inside"] for b in tr) / len(tr), 2),
                        area=int(np.median([b["area"] for b in tr]) * (SCALE / scale) ** 2),
                        path=[[b["t"], [round(b["box"][0] * sx), round(b["box"][1] * sy), round(b["box"][2] * sx), round(b["box"][3] * sy)]] for b in tr]))
    return out, thr


def pick(cands, k=8, min_frames=6, min_area=20):
    """Long-lived blob tracks mostly outside every found box, largest and longest first."""
    keep = [c for c in cands if c["n"] >= min_frames and c["inside"] < 0.5 and c["area"] >= min_area]
    keep.sort(key=lambda c: (-(c["n"] * min(c["area"], 400)), c["first"], c["path"][0][1]))
    return keep[:k]


def _grow(b, W, H, grow=0.4, min_side=48):
    """A blob box grown by `grow`, at least `min_side` px, snapped to the grid and kept strictly inside the frame
    (the API rejects a box that touches the edge: y2=1080 on a 1080-high clip)."""
    x0, y0, x1, y1 = b
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    w, h = max(min_side, (x1 - x0) * (1 + grow)), max(min_side, (y1 - y0) * (1 + grow))
    g = GRID
    return [max(0, int(cx - w / 2) // g * g), max(0, int(cy - h / 2) // g * g),
            min(W - 2, -(-int(cx + w / 2) // g) * g), min(H - 2, -(-int(cy + h / 2) // g) * g)]


def prompt_box(c, W, H):
    """The frame where the blob is at its median size, and its grown box."""
    areas = sorted(((b[2] - b[0]) * (b[3] - b[1]), t, b) for t, b in c["path"])
    _, t, b = areas[len(areas) // 2]
    return t, _grow(b, W, H)


def three(c, W, H, gap=4, n=None):
    """(frame, box) early, at the prompt frame, and late along the blob track. 11/2 s003: one crop of a sediment
    cloud looked like a dark fish; across three frames its shape kept changing (a person told them apart that way).
    Early and late are at least `gap` frames from the prompt frame: when the blob path does not reach that far
    (11/2 s003 M6: early and middle were the same frame), the crop is taken there anyway, at the nearest path box,
    so it shows what that spot looked like before or after."""
    t, b = prompt_box(c, W, H)
    path = sorted(c["path"])
    last = (n - 1) if n else max(path[-1][0], t + gap)

    def at(g):
        f, pb = min(path, key=lambda p: (abs(p[0] - g), p[0]))
        return (g, _grow(pb, W, H))

    # at a clip end there is no room on one side: both other crops go to the side that has room (11/2 review: a
    # prompt frame 0 gave early == middle)
    if t - gap < 0 and t + gap <= last:
        far = (path[-1][0], _grow(path[-1][1], W, H)) if path[-1][0] >= t + 2 * gap else at(min(last, t + 2 * gap))
        return [(t, b), at(t + gap), far]
    if t + gap > last and t - gap >= 0:
        far = (path[0][0], _grow(path[0][1], W, H)) if path[0][0] <= t - 2 * gap else at(max(0, t - 2 * gap))
        return [far, at(t - gap), (t, b)]
    early = (path[0][0], _grow(path[0][1], W, H)) if path[0][0] <= t - gap else at(max(0, t - gap))
    late = (path[-1][0], _grow(path[-1][1], W, H)) if path[-1][0] >= t + gap else at(min(last, t + gap))
    return [early, (t, b), late]


def box_prompt(t, box, W, H):
    x0, y0, x1, y1 = box
    return f"<{t}f>1<|box;x1={x0};y1={y0};x2={x1};y2={y1};w={W};h={H}|>"


def _crop(img, box, half, side):
    x0, y0, x1, y1 = box
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    cx, cy = min(max(cx, 0), img.shape[1]), min(max(cy, 0), img.shape[0])   # a box mapped back from a tile can poke out
    # pad with black instead of clipping: 11/2 s004 a shrimp at the bottom edge came out stretched and cut, and
    # Spark called it "part of an animal reaching in from outside"
    img = cv2.copyMakeBorder(img, half, half, half, half, cv2.BORDER_CONSTANT, value=(0, 0, 0))
    tile = cv2.resize(img[cy:cy + 2 * half, cx:cx + 2 * half], (side, side), interpolation=cv2.INTER_CUBIC)
    # the box is drawn after scaling (11/2 review: drawn before, a 2 px line on a big box shrank to a faint trace)
    s = side / (2 * half)
    pt = lambda x, y: (int(round((x - cx + half) * s)), int(round((y - cy + half) * s)))
    cv2.rectangle(tile, pt(x0, y0), pt(x1, y1), (29, 85, 242), 3)
    return tile


def trio(fr, tr, name, side=200, half=None, words=("early", "middle", "late")):
    """Three crops of one object side by side (same zoom, each centred on its own box, box drawn), tagged `name`.
    `half` defaults to the largest box side, so a size or shape change across the three shows. `words` labels the
    crops in order (verify_peaks passes its own per object)."""
    half = half or max(max(b[2] - b[0], b[3] - b[1]) for _, b in tr)
    tiles = []
    for j, (t, b) in enumerate(tr):
        tile = _crop(fr[t], b, half, side)
        cv2.putText(tile, words[j], (6, side - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        tiles.append(tile)
        if j < 2:
            tiles.append(np.full((side, 3, 3), 60, np.uint8))
    g = np.hstack(tiles)
    cv2.rectangle(g, (0, 0), (max(52, 12 + 17 * len(name)), 34), (0, 0, 0), -1)
    cv2.putText(g, name, (4, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
    return g


def layout(groups, per_row=2, gap=16):
    """Groups (same size) in rows of `per_row` with white gaps; returns JPEG bytes."""
    groups = list(groups)
    while len(groups) % per_row:
        groups.append(np.zeros_like(groups[0]))
    gh, gw = groups[0].shape[:2]
    rows = []
    for r in range(0, len(groups), per_row):
        row = []
        for k, g in enumerate(groups[r:r + per_row]):
            row.append(g)
            if k < per_row - 1:
                row.append(np.full((gh, gap, 3), 255, np.uint8))
        rows.append(np.hstack(row))
        rows.append(np.full((gap, rows[-1].shape[1], 3), 255, np.uint8))
    img = np.vstack(rows[:-1])
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()


def sheet(clip, picks, W, H, side=200, per_row=2, gap=16, n=None):
    """Per candidate, three crops side by side (early, prompt frame, late; same zoom, following the blob), numbered
    M1, M2, ...; `per_row` candidates per sheet row. Returns JPEG bytes and [(number, prompt frame, prompt box)]."""
    trios = [three(c, W, H, n=n) for c in picks]
    fr = video.frames(clip, sorted({t for tr in trios for t, _ in tr}))
    groups = [trio(fr, tr, f"M{i + 1}", side) for i, tr in enumerate(trios)]
    meta = [(i + 1, tr[1][0], tr[1][1]) for i, tr in enumerate(trios)]
    return layout(groups, per_row, gap), meta
