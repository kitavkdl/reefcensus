"""Held-out discovery evaluation (report/paper/discovery_heldout_protocol.md): list what each DH run counted, queued
and cost, and draw the label-free evidence sheet for metric 3 (a person answers "is this an animal: yes / no" per
crop without seeing any label). Reads runs/DH<n>_eval, or, in a fresh clone, the copies of result.json and
status.json in report/paper/data/discovery_heldout/runs/DH<n>; no API calls. The crop sheet needs the run's clip.mp4
and is redrawn only when it is present.

    python3 report/paper/scripts/score_discovery_heldout.py
Writes report/paper/data/discovery_heldout/runs_summary.json and crops_sheet.jpg (crop numbers map to rows in the
JSON, which the judge does not see).
"""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
from fishcount import pipeline, video
from fishcount import _pylib  # noqa: F401  (optional vendored packages, see README)
import cv2
import numpy as np

OUT = os.path.join(ROOT, "report", "paper", "data", "discovery_heldout")
FISHY = ("fish",)


def is_fish(label):
    return any(w in label.split(" (")[0].split() for w in FISHY)


def run_dir(n):
    live = os.path.join(ROOT, "runs", f"DH{n}_eval")
    return live if os.path.exists(os.path.join(live, "result.json")) else os.path.join(OUT, "runs", f"DH{n}")


def summarise(n):
    rd = run_dir(n)
    r = json.load(open(os.path.join(rd, "result.json")))
    st = json.load(open(os.path.join(rd, "status.json")))
    labels, verdicts = r["auto_labels"], r["verdicts"]
    rows = {}
    for t, lab in labels.items():
        if lab is None:
            continue
        v = verdicts.get(t, {})
        rows.setdefault(lab, []).append((t, v, not pipeline.needs_review(v)))
    out = []
    for lab, ts in rows.items():
        counted = [x for x in ts if x[2]]
        best = max(counted or ts, key=lambda x: pipeline._conf(x[1]))
        m = r["metrics"].get(lab, {})
        out.append(dict(label=lab, counted=bool(counted), non_fish=not is_fish(lab), tracks=len(ts),
                        maxn=m.get("maxn"), track=best[0], frame=best[1].get("frame"), box=best[1].get("box"),
                        confidence=pipeline._conf(best[1]), reason=best[1].get("reason")))
    named = [d["what"] for d in r.get("discovered") or []]
    queued = sum(1 for v in verdicts.values() if pipeline.needs_review(v))   # same count as the run log's "need a human look"
    return dict(clip=f"DH{n}", named=named, rows=out, queued_tracks=queued, cost_usd=round(st["billed_usd"], 4),
                live_calls=st["live_calls"])


def crop(n, row, size=360):
    clip = os.path.join(ROOT, "runs", f"DH{n}_eval", "clip.mp4")
    f = int(row["frame"])
    img = video.frames(clip, [f])[f]
    x0, y0, x1, y1 = map(int, row["box"])
    w, h = x1 - x0, y1 - y0
    m = max(w, h) // 2 + 20
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    H, W = img.shape[:2]
    a, b, c, d = max(0, cx - m), max(0, cy - m), min(W, cx + m), min(H, cy + m)
    p = img[b:d, a:c].copy()
    cv2.rectangle(p, (x0 - a, y0 - b), (x1 - a, y1 - b), (255, 255, 255), 1)
    s = size / max(p.shape[:2])
    p = cv2.resize(p, (int(p.shape[1] * s), int(p.shape[0] * s)), interpolation=cv2.INTER_CUBIC)
    tile = np.zeros((size + 50, size, 3), np.uint8)
    tile[50:50 + p.shape[0], :p.shape[1]] = p
    return tile


if __name__ == "__main__":
    res = [summarise(n) for n in range(1, 6) if os.path.exists(os.path.join(run_dir(n), "result.json"))]
    tiles, k = [], 0
    for s in res:
        n = int(s["clip"][2:])
        print(f"{s['clip']}: named {s['named']}  queued tracks {s['queued_tracks']}  ${s['cost_usd']}")
        for row in s["rows"]:
            tag = ""
            if row["counted"] and row["non_fish"]:
                k += 1
                row["crop"] = k
                if os.path.exists(os.path.join(ROOT, "runs", f"DH{n}_eval", "clip.mp4")):
                    t = crop(n, row)
                    cv2.putText(t, f"#{k}", (10, 38), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 2, cv2.LINE_AA)
                    tiles.append(t)
                tag = f"  crop #{k}"
            print(f"   {'COUNTED' if row['counted'] else 'queued '} {row['label']!r} maxn {row['maxn']} "
                  f"conf {row['confidence']} {'non-fish' if row['non_fish'] else 'fish'}{tag}")
    json.dump(res, open(os.path.join(OUT, "runs_summary.json"), "w"), indent=1)
    if len(tiles) == k and tiles:   # all crops drawn; never overwrite the judged sheet with a partial one
        cols = 4
        while len(tiles) % cols:
            tiles.append(np.zeros_like(tiles[0]))
        grid = np.vstack([np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)])
        cv2.imwrite(os.path.join(OUT, "crops_sheet.jpg"), grid, [cv2.IMWRITE_JPEG_QUALITY, 90])
    print("total cost $%.4f" % sum(s["cost_usd"] for s in res))
