"""Drawing: crops for the review queue and the evidence frame (masks + numbered boxes) behind each MaxN."""
import os, re, subprocess, sys, tempfile, zlib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fishcount import _pylib  # noqa: F401
import cv2
import numpy as np
from fishcount import maskcodec, video, tracks

def colour(track):
    """Stable per track across runs (built-in hash() of a str changes every process)."""
    return PALETTE[zlib.crc32(track.encode()) % len(PALETTE)]


PALETTE = [(80, 220, 255), (90, 255, 120), (255, 160, 60), (255, 90, 200), (120, 140, 255), (60, 255, 255), (200, 255, 90), (255, 255, 120)]


def crop(img, box, pad=0.2, min_side=64):
    H, W = img.shape[:2]
    x0, y0, x1, y1 = box
    w, h = max(x1 - x0, min_side), max(y1 - y0, min_side)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    w, h = w * (1 + 2 * pad), h * (1 + 2 * pad)
    a, b = int(max(0, cx - w / 2)), int(max(0, cy - h / 2))
    c, d = int(min(W, cx + w / 2)), int(min(H, cy + h / 2))
    return img[b:d, a:c]


def square(img, side):
    h, w = img.shape[:2]
    s = side / max(h, w)
    r = cv2.resize(img, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_CUBIC)
    out = np.zeros((side, side, 3), np.uint8)
    y, x = (side - r.shape[0]) // 2, (side - r.shape[1]) // 2
    out[y:y + r.shape[0], x:x + r.shape[1]] = r
    return out


def frame_masks(text, f):
    """Decode only frame f's masks from a SAM output. Returns [(box, full-frame bool mask)]."""
    return maskcodec.masks(text, f).get(f, [])


def evidence(clip, raw, result, f, out_path):
    """Frame f with every counted object masked and numbered (track names from the audit when present)."""
    img = video.frames(clip, [f])[f]
    H, W = img.shape[:2]
    kept = result["frames"].get(str(f), [])
    drop = {t for t, l in result.get("auto_labels", {}).items() if not l}
    names = {t: v.get("name", "") for t, v in result.get("verdicts", {}).items()}
    over = img.copy()
    for name, (text, tile) in raw.items():
        # 11/2: tile masks used to be skipped here (boxes only) though annotate() maps them back; same helper now
        for box, m, x0, y0 in _masks_full(text, tile, frame_masks(text, f), W, H):
            hit = max(kept, key=lambda k: tracks.iou(k["box"], box), default=None)
            if not hit or tracks.iou(hit["box"], box) < 0.5 or hit["track"] in drop:
                continue
            over[y0:y0 + m.shape[0], x0:x0 + m.shape[1]][m] = colour(hit["track"])
    img = cv2.addWeighted(over, 0.45, img, 0.55, 0)
    n, placed = 0, []
    for k in kept:
        if k["track"] in drop:
            continue
        n += 1
        x0, y0, x1, y1 = map(int, k["box"])
        col = colour(k["track"])
        cv2.rectangle(img, (x0, y0), (x1, y1), col, 3)
        tag = names.get(k["track"]) or str(n)
        placed.append(_tag(img, tag, (x0, y0, x1, y1), col, placed))
    cv2.putText(img, f"frame {f}  count {n}", (16, H - 20), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 3)
    cv2.imwrite(out_path, img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return n


def _tag(img, text, box, col, placed, scale=0.9):
    """Name tag on a dark plate at the first spot around the box that clears the tags already drawn
    (11/1: neighbouring tracks' T1/T2 tags were printed on top of each other). Returns the plate rect."""
    H, W = img.shape[:2]
    (tw, th), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 2)
    w, h = tw + 10, th + base + 8
    x0, y0, x1, y1 = box
    spots = [(x0, y0 - h - 2), (x0 + 3, y0 + 3), (x0, y1 + 2), (x1 - w, y0 - h - 2), (x1 - w, y1 + 2), (x1 + 2, y0), (x0 - w - 2, y0)]
    hit = lambda r: any(r[0] < q[2] and q[0] < r[2] and r[1] < q[3] and q[1] < r[3] for q in placed)
    rects = [(min(max(0, x), W - w), min(max(0, y), H - h)) for x, y in spots]
    rects = [(x, y, x + w, y + h) for x, y in rects]
    r = next((r for r in rects if not hit(r)), None)
    if r is None:       # crowded: stack below the lowest overlapping plate
        r = rects[0]
        while hit(r) and r[3] + h < H:
            r = (r[0], r[1] + h + 2, r[2], r[3] + h + 2)
    cv2.rectangle(img, (r[0], r[1]), (r[2], r[3]), (20, 24, 28), -1)
    cv2.putText(img, text, (r[0] + 5, r[3] - base - 4), cv2.FONT_HERSHEY_SIMPLEX, scale, col, 2)
    return r


ASKED, FOUND = (200, 99, 29), (29, 85, 242)     # BGR: bait-pipe blue for what was asked, survey orange for finds
TILE_W = re.compile(r";w=(\d+);h=(\d+)")


def _masks_full(text, tile, masks, W, H):
    """One frame's masks in full-frame pixels; tile masks are scaled down from the crop and shifted into place."""
    out = []
    for box, m in masks:
        if tile:
            mw = TILE_W.search(text)
            s = int(mw.group(1)) / tile[2] if mw else 1.0
            m = cv2.resize(m.astype(np.uint8), (max(1, int(m.shape[1] / s)), max(1, int(m.shape[0] / s))), interpolation=cv2.INTER_NEAREST).astype(bool)
            box = (tile[0] + box[0] / s, tile[1] + box[1] / s, tile[0] + box[2] / s, tile[1] + box[3] / s)
        x0, y0 = int(round(box[0])), int(round(box[1]))
        if x0 >= W or y0 >= H:
            continue
        out.append((box, m[: H - y0, : W - x0], x0, y0))
    return out


def all_masks(text):
    """Every frame's masks from one SAM output: {frame: [(box, bool mask)]}."""
    return maskcodec.masks(text)


def asked_labels(result):
    """Labels backed by at least one track from a requested prompt (or its zoom tile); the rest were found by
    discovery. By track source, not label text: 'shrimp (unidentified)' found by discovery is not 'shrimp' asked."""
    jobs = {j["name"] for j in result.get("jobs", [])}
    labels = result.get("auto_labels", {})
    return {labels.get(t, v["label"]) for t, v in result["tracks"].items() if v["source"] in jobs} - {None}


def annotate(clip, raw, result, out_path):
    """Whole clip with every counted object masked and boxed, coloured by asked/found, plus a live count per
    label in the corner. Encoded H.264 so a browser plays it."""
    n = result["video"]["n_frames"]
    imgs = video.frames(clip, range(n))
    labels = result.get("auto_labels", {})
    trk = result["tracks"]
    lab = lambda t: labels.get(t, trk[t]["label"]) if t in trk else None
    asked = asked_labels(result)
    is_asked = lambda l: l in asked
    srcs = [(text, tile) for text, tile in raw.values() if text]
    if maskcodec.fast():      # C decoder: s003's 263 masks in ~1 s
        decoded = [all_masks(t) for t, _ in srcs]
    else:                     # reference decoder ~0.5 s a mask: one process per source
        import concurrent.futures as cf
        with cf.ProcessPoolExecutor(min(6, len(srcs) or 1)) as ex:
            decoded = list(ex.map(all_masks, [t for t, _ in srcs]))
    tmp = tempfile.mkdtemp(dir=os.path.dirname(out_path))
    for f in range(n):
        img = imgs[f]
        H, W = img.shape[:2]
        kept = [k for k in result["frames"].get(str(f), []) if lab(k["track"])]
        over = img.copy()
        for (text, tile), dec in zip(srcs, decoded):
            for box, m, x0, y0 in _masks_full(text, tile, dec.get(f, []), W, H):
                hit = max(kept, key=lambda k: tracks.iou(k["box"], box), default=None)
                if not hit or tracks.iou(hit["box"], box) < 0.5:
                    continue
                col = ASKED if is_asked(lab(hit["track"])) else FOUND
                over[y0:y0 + m.shape[0], x0:x0 + m.shape[1]][m] = col
        img = cv2.addWeighted(over, 0.4, img, 0.6, 0)
        counts = {}
        for k in kept:
            l = lab(k["track"])
            counts[l] = counts.get(l, 0) + 1
            col = ASKED if is_asked(l) else FOUND
            x0, y0, x1, y1 = map(int, k["box"])
            cv2.rectangle(img, (x0, y0), (x1, y1), col, 3)
        y = 44
        for l, c in sorted(counts.items(), key=lambda t: -t[1]):
            txt = f"{c}  {l}"
            cv2.putText(img, txt, (24, y), cv2.FONT_HERSHEY_DUPLEX, 1.1, (0, 0, 0), 6)
            cv2.putText(img, txt, (24, y), cv2.FONT_HERSHEY_DUPLEX, 1.1, (255, 255, 255) if is_asked(l) else (90, 170, 255), 2)
            y += 44
        cv2.imwrite(os.path.join(tmp, f"{f:05d}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 88])
    subprocess.run([video.FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-framerate", str(result["video"]["fps"] or 5),
                    "-i", os.path.join(tmp, "%05d.jpg"), "-vf", "scale='min(1280,iw)':-2", "-c:v", "libx264", "-preset", "veryfast",
                    "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out_path], check=True)
    for fn in os.listdir(tmp):
        os.remove(os.path.join(tmp, fn))
    os.rmdir(tmp)
