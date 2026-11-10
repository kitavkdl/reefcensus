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
from fishcount import video   # also sets up the optional FISH_PYLIB path before cv2
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


def whole_box(clip, t, box, W, H, n, cover=0.5, max_grow=2.5):
    """The seed box widened to the whole animal at frame t. 11/4 s001: candidates() needs pixels that changed between
    t-2 and t+2, so a large slow animal (moving less than its length in 4 frames) breaks into a front and a back edge,
    and the seed box sat on the back half plus open water; SAM then followed that patch, beside the nautilus. Here:
    the pixels at t that differ from a local background (median of frames 4-10 apart, where a mover has gone), and of
    those the one piece the box overlaps most. Returns the box unchanged when it already covers `cover` of that piece,
    or when the piece is more than `max_grow` times its area (pieces of two animals or of the scene, not this one).
    ponytail: one piece only, so an animal that breaks into two pieces at t keeps the bigger; tune cover/max_grow."""
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0, y1 - y0
    a, b = max(0, int(x0 - bw)), max(0, int(y0 - bh))
    c, d = min(W, int(x1 + bw)), min(H, int(y1 + bh))
    near = sorted({min(n - 1, max(0, t + s)) for s in (-10, -8, -6, -4, 4, 6, 8, 10)} - {t})
    fr = video.frames(clip, [t] + near)
    lab = lambda f: _lab(fr[f][b:d, a:c])
    bg = np.median(np.stack([lab(f) for f in near]), axis=0)
    dist = cv2.GaussianBlur(np.linalg.norm(lab(t) - bg, axis=2), (5, 5), 0)
    med = float(np.median(dist))
    # Otsu as well: on a night clip most of the crop is black, the MAD is 0 and med + 6 MAD alone keeps the noise
    otsu, _ = cv2.threshold(np.clip(dist, 0, 255).astype(np.uint8), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    m = (dist > max(8.0, otsu, med + 6 * (float(np.median(np.abs(dist - med))) + 1e-6))).astype(np.uint8)
    m = cv2.dilate(cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)), np.ones((3, 3), np.uint8))
    k, cc = cv2.connectedComponents(m, 8)
    ins = np.zeros_like(m)
    ins[int(y0) - b:int(y1) - b, int(x0) - a:int(x1) - a] = 1
    ids, cnt = np.unique(cc[(ins > 0) & (m > 0)], return_counts=True)
    if not len(ids):
        return list(box)
    ys, xs = np.nonzero(cc == ids[np.argmax(cnt)])
    u = [a + int(xs.min()), b + int(ys.min()), a + int(xs.max()) + 1, b + int(ys.max()) + 1]
    ua = (u[2] - u[0]) * (u[3] - u[1])
    inter = max(0, min(u[2], x1) - max(u[0], x0)) * max(0, min(u[3], y1) - max(u[1], y0))
    if inter >= cover * ua or ua > max_grow * bw * bh:
        return list(box)
    return _grow(u, W, H, grow=0.2)


def box_prompt(t, box, W, H):
    # SAM takes pixel coordinates 0..W-1 / 0..H-1 and answers HTTP 400 "box ... lies outside the 1920x1080" for x2=W or
    # y2=H (11/9 outside data: IMR HU6/BE10, Exeter G2 lost an edge animal each, HU6 a crab Spark called at 0.70).
    # Clamped here so every caller (motion, miss, camo look) is covered; a box already inside keeps its exact text,
    # which is the SAM cache key (none of the 528 cached box prompts touched an edge on 11/10).
    x0, y0, x1, y1 = box
    x0, x1 = (min(max(v, 0), W - 1) for v in (x0, x1))
    y0, y1 = (min(max(v, 0), H - 1) for v in (y0, y1))
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


# ---- camouflaged movers (opt-in --camo, 11/3) -------------------------------------------------------------------
# 11/3 TF_52: two fish on a rock are the rock's colour; no still frame shows them (SAM "fish" on the whole frame, a 3x
# rock crop and a brightened crop all gave 0, and a person looking at a still could not tell fish from rock either).
# The person found them because they swim. candidates() above needs a blob to differ from the median frame in colour,
# which a camouflaged fish does not, and uses one threshold for the whole frame, which a crowded scene pushes up. Here:
# frame-to-frame change only, with a per-pixel threshold from that pixel's own history (still rock -> low, waving weed
# -> high), and blob tracks ranked by how far and how straight they travel (weed sways in place, a fish goes somewhere).
CAMO_GAP = 2                # change |L[t+g] - L[t-g]|
CAMO_K = 4.0                # per-pixel threshold = median + K * (MAD + 0.5) of that pixel's change over the clip


def _travel(path):
    """(displacement, straightness) of a blob track: start-to-end distance of the centre, and that over the length of
    the centre's path (1 = straight line)."""
    cs = [((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for _, b in path]
    if len(cs) < 2:
        return 0.0, 0.0
    disp = float(np.hypot(cs[-1][0] - cs[0][0], cs[-1][1] - cs[0][1]))
    length = sum(float(np.hypot(b[0] - a[0], b[1] - a[1])) for a, b in zip(cs, cs[1:]))
    return disp, disp / length if length else 0.0


def camo_candidates(clip, known, gap=CAMO_GAP, k=CAMO_K, min_area=30, max_area=2500, link=14, max_skip=2, pad=6, scale=None):
    """Like candidates() but from change over time only (see above). Returns blob tracks in full-res coordinates with
    first/last/n/inside/area/path as candidates() gives, plus disp, straight, contrast (blob change over the
    pixel's own threshold, median over the track) and score."""
    n = video.info(clip)["n_frames"]
    scale = scale or (SCALE if n <= LONG else SCALE * 2 / 3)
    if scale != SCALE:
        s2 = (scale / SCALE) ** 2
        min_area, max_area, link, pad = max(4, int(min_area * s2)), int(max_area * s2), link * scale / SCALE, pad * scale / SCALE
    frames, sx, sy = _frames(clip, scale)
    L = [cv2.cvtColor(f, cv2.COLOR_BGR2LAB)[:, :, 0] for f in frames]
    del frames

    def change(t):
        a, b = max(0, t - gap), min(len(L) - 1, t + gap)
        d = cv2.absdiff(L[b], L[a])
        d = cv2.medianBlur(d, 5)                    # marine snow: single bright specks
        return cv2.GaussianBlur(d.astype(np.float32), (7, 7), 0)

    step = 1 if len(L) <= LONG else 3
    hist = np.stack([change(t) for t in range(0, len(L), step)])
    med = np.median(hist, axis=0)
    mad = np.median(np.abs(hist - med), axis=0)
    del hist
    thr = np.maximum(3.0, med + k * (mad + 0.5))
    ks = {f: [[b[0] / sx, b[1] / sy, b[2] / sx, b[3] / sy] for b in bs] for f, bs in known.items()}
    done, live = [], []
    for t in range(len(L)):
        d = change(t)
        m = cv2.morphologyEx((d > thr).astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        nc, cc, st, cen = cv2.connectedComponentsWithStats(m, 8)
        ratio = d / thr
        blobs = []
        for i in range(1, nc):
            x, y, w, h, area = (int(v) for v in st[i])
            if not (min_area <= area <= max_area):
                continue
            cx, cy = float(cen[i][0]), float(cen[i][1])
            inside = any(x0 - pad <= cx <= x1 + pad and y0 - pad <= cy <= y1 + pad for x0, y0, x1, y1 in ks.get(t, []))
            blobs.append(dict(t=t, c=(cx, cy), box=(x, y, x + w, y + h), area=area, inside=inside,
                              contrast=float(np.median(ratio[cc == i])), bg=float(np.median(thr[y:y + h, x:x + w]))))
        nxt, used = [], set()
        for tr in live:
            last, best, bd = tr[-1], None, link * (1 + 0.5 * (t - tr[-1]["t"] - 1))
            for j, bl in enumerate(blobs):
                if j not in used:
                    dd = float(np.hypot(bl["c"][0] - last["c"][0], bl["c"][1] - last["c"][1]))
                    if dd < bd:
                        best, bd = j, dd
            if best is not None:
                used.add(best)
                tr.append(blobs[best])
                nxt.append(tr)
            elif t - last["t"] <= max_skip:
                nxt.append(tr)
            else:
                done.append(tr)
        nxt += [[bl] for j, bl in enumerate(blobs) if j not in used]
        live = nxt
    out = []
    for tr in done + live:
        path = [[b["t"], [round(b["box"][0] * sx), round(b["box"][1] * sy), round(b["box"][2] * sx), round(b["box"][3] * sy)]] for b in tr]
        disp, straight = _travel(path)
        c = dict(first=tr[0]["t"], last=tr[-1]["t"], n=len(tr), inside=round(sum(b["inside"] for b in tr) / len(tr), 2),
                 area=int(np.median([b["area"] for b in tr]) * (SCALE / scale) ** 2), path=path,
                 disp=round(disp, 1), straight=round(straight, 2), contrast=round(float(np.median([b["contrast"] for b in tr])), 2),
                 bg=round(float(np.median([b["bg"] for b in tr])), 2))
        c["score"] = round(c["n"] * straight * min(disp, 150.0), 1)
        out.append(c)
    return out


def _centre(b):
    return (b[0] + b[2]) / 2, (b[1] + b[3]) / 2


def camo_pick(cands, known, W, H, k=8, min_frames=5, edge=80, near=60):
    """Candidates worth a look, best score first. Dropped (11/3 TF_52, where these filled the top of the list): a
    track whose median centre is within `edge` px of the picture edge (the moving part of an animal mostly outside the
    picture, or one already boxed whose box lags), one within `near` px of an already-found box in half or more of
    its frames (a tracked fish's tail or shadow), and a second blob track on the same mover (centres within `near`
    px in two or more shared frames: the lower score goes)."""
    def edge_d(c):
        xs = [_centre(b) for _, b in c["path"]]
        mx, my = float(np.median([p[0] for p in xs])), float(np.median([p[1] for p in xs]))
        return min(mx, W - mx, my, H - my)

    def near_share(c):
        hit = 0
        for t, b in c["path"]:
            x, y = _centre(b)
            hit += any(x0 - near <= x <= x1 + near and y0 - near <= y <= y1 + near for x0, y0, x1, y1 in known.get(t, []))
        return hit / len(c["path"])

    keep = [c for c in cands if c["n"] >= min_frames and c["inside"] < 0.5 and edge_d(c) > edge and near_share(c) < 0.5]
    keep.sort(key=lambda c: (-c["score"], c["first"]))
    out = []
    for c in keep:
        at = {t: _centre(b) for t, b in c["path"]}
        same = lambda o: sum(1 for t, b in o["path"] if t in at and np.hypot(*np.subtract(_centre(b), at[t])) < near) >= 2
        if not any(same(o) for o in out):
            out.append(c)
        if len(out) >= k:
            break
    return out


def change_image(fr, t, n, gap=CAMO_GAP, gain=4):
    """What changed around frame t (|L[t+gap] - L[t-gap]|, specks removed, amplified) as a grey BGR image: a
    camouflaged animal that no still frame shows is a bright shape here, moving from crop to crop."""
    a, b = max(0, t - gap), min(n - 1, t + gap)
    d = cv2.absdiff(cv2.cvtColor(fr[b], cv2.COLOR_BGR2LAB)[:, :, 0], cv2.cvtColor(fr[a], cv2.COLOR_BGR2LAB)[:, :, 0])
    d = cv2.medianBlur(d, 5)
    d = np.clip(d.astype(np.float32) * gain, 0, 255).astype(np.uint8)
    return cv2.cvtColor(d, cv2.COLOR_GRAY2BGR)


def frames_for(tr, n, gap=CAMO_GAP):
    """Frame indices camo_group needs for the (frame, box) list tr."""
    need = set()
    for t, _ in tr:
        need |= {t, max(0, t - gap), min(n - 1, t + gap)}
    return need


def camo_group(fr, tr, name, n, side=200, words=("early", "middle", "late")):
    """trio() of the still crops over trio() of the same crops of change_image(); fr must hold frames_for(tr, n)."""
    half = max(max(b[2] - b[0], b[3] - b[1]) for _, b in tr)
    chg = {t: change_image(fr, t, n) for t, _ in tr}
    top = trio(fr, tr, name, side, half=half, words=words)
    bottom = trio(chg, tr, "moved", side, half=half, words=words)
    return np.vstack([top, np.full((6, top.shape[1], 3), 60, np.uint8), bottom])


def camo_sheet(clip, picks, W, H, n, side=200, per_row=2, gap=16):
    """Per candidate (K1, K2, ...): the three crops of three() on top, and below them the same crops of
    change_image(), so a reader can judge what only movement shows (a person found the 11/3 TF_52 rock fish that
    way). Returns JPEG bytes and [(number, prompt frame, prompt box)]."""
    trios = [three(c, W, H, n=n) for c in picks]
    fr = video.frames(clip, sorted(set().union(*[frames_for(tr, n) for tr in trios])))
    groups = [camo_group(fr, tr, f"K{i + 1}", n, side) for i, tr in enumerate(trios)]
    meta = [(i + 1, tr[1][0], tr[1][1]) for i, tr in enumerate(trios)]
    return layout(groups, per_row, gap), meta


def follows(dets, path, min_hits=3, min_move=30):
    """Did a SAM box-prompt track follow this blob track? dets = {frame: [det]} from the box prompt, path = the blob
    track's [[frame, box], ...]. A frame is a hit when some SAM box centre is within max(40 px, the blob box's
    longer side) of the blob centre. True when hits >= max(min_hits, half the frames both have) and the SAM boxes on
    the hit frames themselves travel >= min_move px (a box stuck on the rock while the blob moves does not count).
    Returns (ok, hits, shared, moved_px)."""
    hits, shared, cs = 0, 0, []
    for t, b in path:
        ds = dets.get(t) or []
        if not ds:
            continue
        shared += 1
        x, y = _centre(b)
        r = max(40.0, b[2] - b[0], b[3] - b[1])
        best = min(ds, key=lambda d: np.hypot(*np.subtract(_centre(d["box"]), (x, y))))
        if np.hypot(*np.subtract(_centre(best["box"]), (x, y))) <= r:
            hits += 1
            cs.append(_centre(best["box"]))
    moved = float(np.hypot(*np.subtract(cs[-1], cs[0]))) if len(cs) >= 2 else 0.0
    ok = hits >= max(min_hits, shared / 2) and moved >= min_move
    return ok, hits, shared, round(moved, 1)
