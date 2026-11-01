"""Spike G: contact graph from several SAM concept runs on one clip (box overlap as a contact proxy).
usage: python3 contact.py <clip.mp4> <out.jpg> <name>=<sam.txt>... --frames f1,f2,..."""
import os, sys
sys.path.insert(0, os.path.expanduser("~/meta-fish"))
from fishcount import tracks, video
import cv2

COL = {"hand": (80, 200, 255), "knife": (255, 120, 60), "meat": (60, 60, 230), "cutting board": (90, 220, 90)}


def inter(a, b):
    w, h = min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])
    return max(0, w) * max(0, h)


if __name__ == "__main__":
    a = sys.argv[1:]
    clip, out = a[0], a[1]
    fs = [int(v) for v in a[a.index("--frames") + 1].split(",")]
    runs = {kv.split("=")[0]: tracks.parse_boxes(open(kv.split("=", 1)[1]).read()) for kv in a[2:] if "=" in kv}
    n = video.info(clip)["n_frames"]
    objs = lambda f: [(k, d["id"], d["box"]) for k, r in runs.items() for d in r.get(f, [])]
    state, events = {}, []
    for f in range(n):
        cur = set()
        o = objs(f)
        for i in range(len(o)):
            for j in range(i + 1, len(o)):
                if o[i][0] != o[j][0]:
                    small = min((o[i][2][2] - o[i][2][0]) * (o[i][2][3] - o[i][2][1]), (o[j][2][2] - o[j][2][0]) * (o[j][2][3] - o[j][2][1]))
                    if inter(o[i][2], o[j][2]) > 0.2 * small:
                        cur.add(tuple(sorted([f"{o[i][0]}#{o[i][1]}", f"{o[j][0]}#{o[j][1]}"])))
        for p in cur - set(state):
            events.append((f, "touch", p))
        for p in set(state) - cur:
            events.append((f, "release", p))
        state = {p: 1 for p in cur}
    for e in events:
        print(e)
    fr = video.frames(clip, fs)
    cells = []
    for f in fs:
        img = fr[f].copy()
        for k, i, b in objs(f):
            x0, y0, x1, y1 = map(int, b)
            cv2.rectangle(img, (x0, y0), (x1, y1), COL.get(k, (255, 255, 255)), 3)
            cv2.putText(img, f"{k}#{i}", (x0 + 3, max(22, y0 - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, COL.get(k, (255, 255, 255)), 2)
        cells.append(video.label(img, f"frame {f}"))
    cv2.imwrite(out, video.grid(cells, 3, 640), [cv2.IMWRITE_JPEG_QUALITY, 80])
    print(out)
