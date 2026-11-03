import json, os, sys, random
sys.path.insert(0, os.path.expanduser("~/meta-fish"))
from fishcount import video  # noqa (cv2 path)
from fishcount import tracks, pipeline
import cv2, numpy as np
SM = os.path.expanduser("~/meta-smoke"); R = os.path.expanduser("~/meta-fish/runs"); OUT = sys.argv[1]
m = json.load(open(f"{SM}/clips/manifest_heldout.json"))
fp, tp = [], []
for cid, c in m["clips"].items():
    gt = {int(k): [(x, y, x + w, y + h) for x, y, w, h, *_ in v] for k, v in json.load(open(f"{SM}/{c['gt']}"))["frames"].items()}
    res = json.load(open(f"{R}/cr3_{cid}/result.json"))
    lab = lambda t: res["auto_labels"].get(t, res["tracks"].get(t, {}).get("label"))
    q = {t for t, v in res["verdicts"].items() if pipeline.needs_review(v)}
    for f, gb in sorted(gt.items()):
        ks = [k for k in res["frames"].get(str(f), []) if lab(k["track"])]
        used = set()
        for a in gb:
            best = max(((tracks.iou(a, k["box"]), j) for j, k in enumerate(ks) if j not in used), default=(0, None))
            if best[0] >= 0.3: used.add(best[1])
        for j, k in enumerate(ks):
            d = dict(clip=cid, frame=f, track=k["track"], box=k["box"], queued=k["track"] in q)
            (tp if j in used else fp).append(d)
rng = random.Random(1103)
items = [dict(d, kind="unmatched") for d in rng.sample(fp, 40)] + [dict(d, kind="matched") for d in rng.sample(tp, 10)]
rng.shuffle(items)
for i, d in enumerate(items, 1): d["n"] = i
C, cols = 300, 5
sheet = np.full((((len(items) + cols - 1) // cols) * C, cols * C, 3), 255, np.uint8)
caps = {}
for d in items:
    p = f"{SM}/{m['clips'][d['clip']]['path']}"
    if p not in caps:
        cap = cv2.VideoCapture(p); fr = []
        while True:
            ok, im = cap.read()
            if not ok: break
            fr.append(im)
        caps[p] = fr
    im = caps[p][d["frame"]].copy(); H, W = im.shape[:2]
    x0, y0, x1, y1 = map(int, d["box"]); bw, bh = x1 - x0, y1 - y0
    s = max(bw, bh, 120) * 1.0
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    X0, Y0 = int(max(0, cx - s)), int(max(0, cy - s)); X1, Y1 = int(min(W, cx + s)), int(min(H, cy + s))
    cv2.rectangle(im, (x0, y0), (x1, y1), (0, 230, 255), 3)
    cr = im[Y0:Y1, X0:X1]; k = (C - 8) / max(cr.shape[:2]); cr = cv2.resize(cr, None, fx=k, fy=k)
    r, c = divmod(d["n"] - 1, cols); oy, ox = r * C + (C - cr.shape[0]) // 2, c * C + (C - cr.shape[1]) // 2
    sheet[oy:oy + cr.shape[0], ox:ox + cr.shape[1]] = cr
    cv2.rectangle(sheet, (c * C + 4, r * C + 4), (c * C + 58, r * C + 40), (0, 0, 0), -1)
    cv2.putText(sheet, str(d["n"]), (c * C + 8, r * C + 33), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
cv2.imwrite(os.path.join(OUT, "fp-sheet.jpg"), sheet, [cv2.IMWRITE_JPEG_QUALITY, 88])
json.dump(dict(protocol="11/3: held-out 24 clips, cr3 runs (code 6b2244b). Pool = pipeline boxes matching no human box at IoU>=0.3 "
               "(153) and matched boxes (517). Sample: random.Random(1103), 40 unmatched + 10 matched controls, shuffled. "
               "Judge sees crops with our box only, no labels. Answer per number: O animal/fish in box, X not (plant, rock, shadow, water), ? unsure. "
               "Use: share of unmatched judged O estimates unboxed real fish; corrected precision = (517 + 153*share_O)/670. "
               "Controls judged X flag judge strictness. Fixed before the judge saw the sheet.",
               n_pool_unmatched=len(fp), n_pool_matched=len(tp), items=items), open(os.path.join(OUT, "key.json"), "w"), indent=1)
print(len(fp), len(tp), "sheet", sheet.shape, "queued among sampled unmatched", sum(d["queued"] for d in items if d["kind"] == "unmatched"))
