"""Spike: where to look, from pixels alone (no model calls).

A BRUV camera sits still on the seabed, so the background barely changes. Anything that differs from the clip's
median frame AND moves is a candidate place for an animal, even one SAM has no word for. Candidates are only
"look here" hints for the existing 3x closer look; they are never counted.

Noise to reject: marine snow (tiny, short-lived, fast), sediment clouds (large, diffuse), the bait bag swaying
(always in the same place), and animals already tracked (inside a counted box).

    python3 spikes/motion.py <clip.mp4> [result.json] [--out demo/out/motion_<name>.jpg] [--probe x,y]
"""
import argparse, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.expanduser("~/meta-smoke/pylib"))
import cv2
import numpy as np
from fishcount import video


def load(clip, scale=0.5):
    n = video.info(clip)["n_frames"]
    fr = video.frames(clip, list(range(n)))
    return [cv2.resize(fr[i], None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) for i in range(n)]


def known_boxes(result, scale):
    if not result:
        return {}
    d = json.load(open(result))
    out = {}
    for f, hits in d["frames"].items():
        out[int(f)] = [[v * scale for v in h["box"]] for h in hits]
    return out


def candidates(frames, known, gap=2, min_area=12, max_area=2500, min_frames=4, link=14, pad=6):
    """Per frame: pixels unlike the median background that also changed over `gap` frames. Blobs are linked frame
    to frame by nearest centroid (within `link` px at analysis scale) into short tracks; a track that lives at least
    `min_frames` and is not inside a counted box is a candidate."""
    stack = np.stack(frames).astype(np.int16)
    bg = np.median(stack, axis=0)
    lab = [cv2.cvtColor(f, cv2.COLOR_BGR2LAB).astype(np.float32) for f in frames]
    bgl = cv2.cvtColor(bg.astype(np.uint8), cv2.COLOR_BGR2LAB).astype(np.float32)
    # colour/brightness distance from background (the 'shading difference' a person sees), robust threshold
    dists = [cv2.GaussianBlur(np.linalg.norm(l - bgl, axis=2), (5, 5), 0) for l in lab]
    allv = np.concatenate([d[::4, ::4].ravel() for d in dists])
    med = np.median(allv); mad = np.median(np.abs(allv - med)) + 1e-6
    thr = max(8.0, med + 6 * mad)
    tracks, live = [], []
    for t, d in enumerate(dists):
        fg = d > thr
        a, b = max(0, t - gap), min(len(frames) - 1, t + gap)
        mv = cv2.GaussianBlur(np.linalg.norm(lab[b] - lab[a], axis=2), (5, 5), 0) > thr * 0.8
        m = (fg & mv).astype(np.uint8)
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
        m = cv2.dilate(m, np.ones((3, 3), np.uint8))
        n, cc, st, cen = cv2.connectedComponentsWithStats(m, 8)
        blobs = []
        for i in range(1, n):
            x, y, w, h, area = st[i]
            if not (min_area <= area <= max_area):
                continue
            cx, cy = cen[i]
            inside = any(bx0 - pad <= cx <= bx1 + pad and by0 - pad <= cy <= by1 + pad for bx0, by0, bx1, by1 in known.get(t, []))
            blobs.append(dict(t=t, c=(float(cx), float(cy)), box=(int(x), int(y), int(x + w), int(y + h)), area=int(area),
                              contrast=float(d[cc == i].mean()), inside=inside))
        nxt = []
        used = set()
        for tr in live:
            last = tr[-1]
            best, bd = None, link
            for j, bl in enumerate(blobs):
                if j in used:
                    continue
                dd = np.hypot(bl["c"][0] - last["c"][0], bl["c"][1] - last["c"][1])
                if dd < bd:
                    best, bd = j, dd
            if best is not None:
                used.add(best); tr.append(blobs[best]); nxt.append(tr)
            elif t - last["t"] <= 1:          # allow one missed frame
                nxt.append(tr)
            else:
                tracks.append(tr)
        for j, bl in enumerate(blobs):
            if j not in used:
                nxt.append([bl])
        live = nxt
    tracks += live
    out = []
    for tr in tracks:
        if len(tr) < min_frames:
            continue
        inside = sum(b["inside"] for b in tr) / len(tr)
        xs = [b["c"][0] for b in tr]; ys = [b["c"][1] for b in tr]
        travel = float(np.hypot(xs[-1] - xs[0], ys[-1] - ys[0]))
        spread = float(np.hypot(np.std(xs), np.std(ys)))
        out.append(dict(first=tr[0]["t"], last=tr[-1]["t"], n=len(tr), inside=round(inside, 2),
                        c=(round(float(np.mean(xs)), 1), round(float(np.mean(ys)), 1)), travel=round(travel, 1),
                        spread=round(spread, 1), area=int(np.median([b["area"] for b in tr])),
                        contrast=round(float(np.mean([b["contrast"] for b in tr])), 1),
                        path=[[b["t"], list(b["box"])] for b in tr],
                        box=[min(b["box"][0] for b in tr), min(b["box"][1] for b in tr),
                             max(b["box"][2] for b in tr), max(b["box"][3] for b in tr)]))
    return out, thr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("clip"); ap.add_argument("result", nargs="?")
    ap.add_argument("--out"); ap.add_argument("--probe", action="append", default=[])
    ap.add_argument("--scale", type=float, default=0.5)
    a = ap.parse_args()
    s = a.scale
    frames = load(a.clip, s)
    cands, thr = candidates(frames, known_boxes(a.result, s))
    new = [c for c in cands if c["inside"] < 0.5]
    print(f"threshold {thr:.1f}; {len(cands)} moving tracks >= 4 frames, {len(new)} outside counted boxes")
    for c in sorted(new, key=lambda c: -c["n"])[:25]:
        print(" ", {k: c[k] for k in ("first", "last", "n", "c", "area", "contrast", "travel", "spread")},
              "full-res", [round(v / s) for v in c["c"]])
    for p in a.probe:
        px, py = [float(v) * s for v in p.split(",")]
        near = sorted(new, key=lambda c: np.hypot(c["c"][0] - px, c["c"][1] - py))[:3]
        print(f"probe {p}:", [(c["c"][0] / s, c["c"][1] / s, c["n"], round(float(np.hypot(c['c'][0] - px, c['c'][1] - py)) / s)) for c in near])
    if a.out:
        img = frames[len(frames) // 2].copy()
        for c in cands:
            x0, y0, x1, y1 = c["box"]
            col = (120, 120, 120) if c["inside"] >= 0.5 else (29, 85, 242)
            cv2.rectangle(img, (x0, y0), (x1, y1), col, 1 if c["inside"] >= 0.5 else 2)
        for p in a.probe:
            px, py = [int(float(v) * s) for v in p.split(",")]
            cv2.circle(img, (px, py), 18, (255, 255, 0), 2)
        cv2.imwrite(a.out, img, [cv2.IMWRITE_JPEG_QUALITY, 80])
        json.dump(dict(threshold=float(thr), scale=s, candidates=cands), open(os.path.splitext(a.out)[0] + ".json", "w"), indent=1)


if __name__ == "__main__":
    main()
