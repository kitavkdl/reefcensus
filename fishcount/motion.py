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


def prompt_box(c, W, H, grow=0.4, min_side=48):
    """The frame where the blob is at its median size, and its box grown by `grow`, at least `min_side` px, kept
    strictly inside the frame (the API rejects a box that touches the edge: y2=1080 on a 1080-high clip)."""
    areas = sorted(((b[2] - b[0]) * (b[3] - b[1]), t, b) for t, b in c["path"])
    _, t, (x0, y0, x1, y1) = areas[len(areas) // 2]
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    w, h = max(min_side, (x1 - x0) * (1 + grow)), max(min_side, (y1 - y0) * (1 + grow))
    g = GRID
    bx = [max(0, int(cx - w / 2) // g * g), max(0, int(cy - h / 2) // g * g),
          min(W - 2, -(-int(cx + w / 2) // g) * g), min(H - 2, -(-int(cy + h / 2) // g) * g)]
    return t, bx


def box_prompt(t, box, W, H):
    x0, y0, x1, y1 = box
    return f"<{t}f>1<|box;x1={x0};y1={y0};x2={x1};y2={y1};w={W};h={H}|>"


def sheet(clip, picks, W, H, side=240):
    """One numbered crop (box with context, scaled to `side`) per candidate at its prompt frame. Returns JPEG bytes
    and [(number, frame, box)]."""
    chosen = [prompt_box(c, W, H) for c in picks]
    fr = video.frames(clip, sorted({t for t, _ in chosen}))
    tiles, meta = [], []
    for i, (t, (x0, y0, x1, y1)) in enumerate(chosen):
        img = fr[t].copy()
        cv2.rectangle(img, (x0, y0), (x1, y1), (29, 85, 242), 2)
        cx, cy, half = (x0 + x1) // 2, (y0 + y1) // 2, max(x1 - x0, y1 - y0)
        # pad with black instead of clipping: 11/2 s004 a shrimp at the bottom edge came out stretched and cut, and
        # Spark called it "part of an animal reaching in from outside"
        img = cv2.copyMakeBorder(img, half, half, half, half, cv2.BORDER_CONSTANT, value=(0, 0, 0))
        crop = img[cy:cy + 2 * half, cx:cx + 2 * half]
        tile = cv2.resize(crop, (side, side), interpolation=cv2.INTER_CUBIC)
        cv2.rectangle(tile, (0, 0), (52, 34), (0, 0, 0), -1)
        cv2.putText(tile, f"M{i + 1}", (4, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
        tiles.append(tile)
        meta.append((i + 1, t, [x0, y0, x1, y1]))
    while len(tiles) % 4:
        tiles.append(np.zeros((side, side, 3), np.uint8))
    img = np.vstack([np.hstack(tiles[i:i + 4]) for i in range(0, len(tiles), 4)])
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes(), meta
