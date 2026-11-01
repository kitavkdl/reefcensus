"""Spike F: object-permanence check. List tracks born/dying away from frame edges with no overlapping neighbour.
usage: python3 lifecycle.py <clip.mp4> <sam.txt> [margin_frac=0.04]"""
import os, sys
sys.path.insert(0, os.path.expanduser("~/meta-fish"))
from fishcount import tracks, video


def near_edge(b, W, H, m):
    return b[0] < m * W or b[1] < m * H or b[2] > (1 - m) * W or b[3] > (1 - m) * H


def overlap(a, b):
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def events(text, n, W, H, m=0.04):
    dets = tracks.parse_boxes(text)
    life = {}
    for f, ds in dets.items():
        for d in ds:
            life.setdefault(d["id"], []).append((f, d["box"]))
    out = []
    for tid, seq in life.items():
        seq.sort()
        for kind, (f, b) in (("birth", seq[0]), ("death", seq[-1])):
            if (kind == "birth" and f == 0) or (kind == "death" and f == n - 1):
                continue
            others = [d["box"] for d in dets.get(f, []) if d["id"] != tid]
            tag = "edge" if near_edge(b, W, H, m) else ("occluded?" if any(overlap(b, o) for o in others) else "INTERIOR")
            out.append((tid, kind, f, tag, [int(v) for v in b]))
    return out, len(life)


if __name__ == "__main__":
    clip, txt = sys.argv[1], sys.argv[2]
    i = video.info(clip)
    ev, nt = events(open(txt).read(), i["n_frames"], i["width"], i["height"], *(float(v) for v in sys.argv[3:4]))
    inter = [e for e in ev if e[3] == "INTERIOR"]
    print(f"{os.path.basename(txt)}: tracks={nt} events={len(ev)} edge={sum(e[3]=='edge' for e in ev)} occl?={sum(e[3]=='occluded?' for e in ev)} INTERIOR={len(inter)}")
    for e in inter:
        print("   ", e)
