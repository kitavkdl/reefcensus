"""Drawing: crops for the review queue and the evidence frame (masks + numbered boxes) behind each MaxN."""
import os, sys
sys.path.insert(0, os.path.expanduser("~/meta-smoke/pylib"))
import cv2
import numpy as np
from fishcount import video, tracks

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
    """Decode only frame f's masks from a SAM output (fast: one line). Returns [(box, full-frame bool mask)]."""
    from meta_sam_parser import video_segmentation_format, decode_mask_to_raster, CompletedOutcome
    line = next((ln for ln in text.splitlines() if ln.startswith(f"<{f}f>")), None)
    if not line:
        return []
    p = video_segmentation_format().create_parser()
    p.push(line + "\n")
    res = p.finish(CompletedOutcome()).result
    out = []
    for r in res.records:
        if r.kind != "mask" or r.frame is None:
            continue
        a = np.frombuffer(decode_mask_to_raster(r.mask), np.uint8).reshape(r.mask.height, r.mask.width).astype(bool)
        out.append(((r.bounds.left, r.bounds.top, r.bounds.right, r.bounds.bottom), a))
    return out


def evidence(clip, raw, result, f, out_path):
    """Frame f with every counted object masked and numbered (track names from the audit when present)."""
    img = video.frames(clip, [f])[f]
    H, W = img.shape[:2]
    kept = result["frames"].get(str(f), [])
    drop = {t for t, l in result.get("auto_labels", {}).items() if not l}
    names = {t: v.get("name", "") for t, v in result.get("verdicts", {}).items()}
    over = img.copy()
    for name, (text, tile) in raw.items():
        if tile:   # tile masks are in upscaled crop coordinates; boxes are drawn below instead
            continue
        for box, m in frame_masks(text, f):
            hit = max(kept, key=lambda k: tracks.iou(k["box"], box), default=None)
            if not hit or tracks.iou(hit["box"], box) < 0.5 or hit["track"] in drop:
                continue
            x0, y0 = int(round(box[0])), int(round(box[1]))
            x1, y1 = min(W, x0 + m.shape[1]), min(H, y0 + m.shape[0])
            col = PALETTE[hash(hit["track"]) % len(PALETTE)]
            region = over[y0:y1, x0:x1]
            region[m[: y1 - y0, : x1 - x0]] = col
    img = cv2.addWeighted(over, 0.45, img, 0.55, 0)
    n = 0
    for k in kept:
        if k["track"] in drop:
            continue
        n += 1
        x0, y0, x1, y1 = map(int, k["box"])
        col = PALETTE[hash(k["track"]) % len(PALETTE)]
        cv2.rectangle(img, (x0, y0), (x1, y1), col, 3)
        tag = names.get(k["track"]) or str(n)
        cv2.putText(img, tag, (x0 + 4, max(24, y0 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.9, col, 2)
    cv2.putText(img, f"frame {f}  count {n}", (16, H - 20), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 3)
    cv2.imwrite(out_path, img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return n
