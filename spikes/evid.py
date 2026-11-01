"""Evidence sheet for a spike: chosen frames with SAM masks and track IDs drawn.
usage: python3 evid.py <clip.mp4> <sam.txt> <out.jpg> <frame> [<frame>...] [--title TEXT] [--cols N]"""
import os, sys
sys.path.insert(0, os.path.expanduser("~/meta-fish"))
from fishcount import render, tracks, video
import cv2

PAL = render.PALETTE


def draw(img, text, f):
    H, W = img.shape[:2]
    over = img.copy()
    dets = tracks.parse_boxes(text).get(f, [])
    for box, m in render.frame_masks(text, f):
        hit = max(dets, key=lambda d: tracks.iou(d["box"], box), default=None)
        col = PAL[(hit["id"] if hit else 0) % len(PAL)]
        x0, y0 = int(round(box[0])), int(round(box[1]))
        x1, y1 = min(W, x0 + m.shape[1]), min(H, y0 + m.shape[0])
        over[y0:y1, x0:x1][m[: y1 - y0, : x1 - x0]] = col
    img = cv2.addWeighted(over, 0.5, img, 0.5, 0)
    for d in dets:
        x0, y0, x1, y1 = map(int, d["box"])
        col = PAL[d["id"] % len(PAL)]
        cv2.rectangle(img, (x0, y0), (x1, y1), col, 3)
        cv2.putText(img, f"#{d['id']}", (x0 + 4, max(30, y0 - 10)), cv2.FONT_HERSHEY_SIMPLEX, 1.2, col, 3)
    return video.label(img, f"frame {f}  objects {len(dets)}")


if __name__ == "__main__":
    a = sys.argv[1:]
    title = a[a.index("--title") + 1] if "--title" in a else ""
    cols = int(a[a.index("--cols") + 1]) if "--cols" in a else 2
    clip, txt, out = a[0], a[1], a[2]
    flags = {i + 1 for i, v in enumerate(a) if v.startswith("--")}
    fs = [int(v) for i, v in enumerate(a[3:], 3) if v.isdigit() and i not in flags]
    text = open(txt).read()
    fr = video.frames(clip, fs)
    sheet = video.grid([draw(fr[f], text, f) for f in fs], cols, 960)
    if title:
        sheet = cv2.copyMakeBorder(sheet, 50, 0, 0, 0, cv2.BORDER_CONSTANT, value=(30, 30, 30))
        cv2.putText(sheet, title, (14, 36), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
    cv2.imwrite(out, sheet, [cv2.IMWRITE_JPEG_QUALITY, 82])
    print(out, sheet.shape)
