"""Draw two detections' masks (red = first, cyan = second) on one frame crop, for eyeballing a high-containment pair.
  python3 spikes/maskpair_img.py <clip> <run-id> <frame> <trackA> <trackB> <out.jpg>"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fishcount import pipeline, render, maskdedupe, video
import cv2
clip, rid, F, A, B, out = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4], sys.argv[5], sys.argv[6]
def hook(clip, raw, result, out_path):
    W, H = result["video"]["width"], result["video"]["height"]
    dec = maskdedupe.decode_sources(raw, W, H)
    img = video.frames(clip, [F])[F]
    over = img.copy()
    ks = {k["track"]: k for k in result["frames"][str(F)]}
    xs = []
    for t, col in ((A, (0, 0, 255)), (B, (255, 255, 0))):
        k = ks[t]
        m, x0, y0 = maskdedupe.det_mask(dec, t.split(":")[0], F, k["box"])
        print(t, "mask px", int(m.sum()), "box", [round(v) for v in k["box"]])
        over[y0:y0 + m.shape[0], x0:x0 + m.shape[1]][m] = col
        xs.append(k["box"])
    img = cv2.addWeighted(over, 0.5, img, 0.5, 0)
    for b, col in zip(xs, ((0, 0, 255), (255, 255, 0))):
        cv2.rectangle(img, tuple(map(int, b[:2])), tuple(map(int, b[2:])), col, 2)
    x0 = int(max(0, min(b[0] for b in xs) - 60)); y0 = int(max(0, min(b[1] for b in xs) - 60))
    x1 = int(min(W, max(b[2] for b in xs) + 60)); y1 = int(min(H, max(b[3] for b in xs) + 60))
    c = img[y0:y1, x0:x1]
    s = min(1.0, 640 / max(c.shape[:2]))
    cv2.imwrite(out, cv2.resize(c, (int(c.shape[1] * s), int(c.shape[0] * s))), [cv2.IMWRITE_JPEG_QUALITY, 85])
render.annotate = hook
render.evidence = lambda *a, **k: 0
pipeline.run_pipeline(clip, rid, offline=True, do_scout=False, do_discover=True)
