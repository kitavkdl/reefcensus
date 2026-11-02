"""Vocabulary probe on every CC BY clip the paper uses (replaces the three unlicensed IMAS clips).
Fixed before any of these calls (2 Nov 2026): SAM 3.1, full frame, one call per (clip, word):
  * "animal" (hypernym) on all 39 clips: 6 development and 24 held-out luderick clips, 4 nautilus clips, 5 held-out
    discovery clips (DH1-DH5);
  * "luderick" (the species' common name) on the 6 development luderick clips;
  * "fish" on the same clips, for comparison (already cached by the evaluation and discovery runs).
Reported per clip, whatever it shows: frames with at least one box and the largest number of boxes in one frame.
On nautilus and DH clips also: which counted non-fish animals of the audited run an "animal" track overlaps
(IoU >= 0.3 in >= 3 frames, the rule of fixed_vocab.py).
  FISH_BUDGET=<ledger+1> python3 report/paper/scripts/animal_probe.py     (paid only for replies not in cache/)
  python3 report/paper/scripts/animal_probe.py --offline                   (cache, else the bundled replies)
Writes report/paper/data/animal_probe/<clip>__<word>.txt (raw replies) and summary.json."""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
from fishcount import api, tracks  # noqa: E402

SMOKE = os.path.expanduser("~/meta-smoke")
OUT = os.path.join(ROOT, "report/paper/data/animal_probe")
FISHY = ("fish",)


def clips():
    out = []   # (group, id, clip path, n_frames, run dir with result.json or None)
    for grp, man in (("luderick dev", "manifest_fish.json"), ("luderick held-out", "manifest_heldout.json")):
        mp = os.path.join(SMOKE, "clips", man)
        if not os.path.exists(mp):
            mp = os.path.join(ROOT, "report/paper/data/heldout/manifest.json") if "held" in grp else None
        if mp is None:
            continue
        for cid, c in json.load(open(mp))["clips"].items():
            out.append((grp, cid, os.path.join(SMOKE, c["path"]), c["n_frames"], None))
    for s in ("s001", "s002", "s003", "s004"):
        rd = os.path.join(ROOT, "runs", f"L1_{s}_v16")
        out.append(("nautilus", s, os.path.join(rd, "clip.mp4"), 60, rd))
    for n in range(1, 6):
        rd = os.path.join(ROOT, "runs", f"DH{n}_eval")
        out.append(("held-out discovery", f"DH{n}", os.path.join(rd, "clip.mp4"), 60, rd))
    return out


def counted_nonfish(rd):
    """{track: {"label", "boxes": {frame: box}}} for tracks the audited run counted under a non-fish label."""
    from fishcount import pipeline
    res = json.load(open(os.path.join(rd, "result.json")))
    out = {}
    for f, ks in res["frames"].items():
        for k in ks:
            t = k["track"]
            lab = res["auto_labels"].get(t)
            if not lab or any(w in lab.split(" (")[0].split() for w in FISHY):
                continue
            if pipeline.needs_review(res["verdicts"].get(t)):
                continue
            out.setdefault(t, {"label": lab, "boxes": {}})["boxes"][int(f)] = k["box"]
    return out


def reply(cid, path, word, n, offline):
    bp = os.path.join(OUT, f"{cid}__{word}.txt")
    if os.path.exists(path):
        try:
            txt = api.sam_video(path, word, n, offline=True)
        except FileNotFoundError:
            if offline:
                return open(bp).read() if os.path.exists(bp) else None
            txt = api.sam_video(path, word, n)
        open(bp, "w").write(txt)
        return txt
    return open(bp).read() if os.path.exists(bp) else None


def main():
    offline = "--offline" in sys.argv
    os.makedirs(OUT, exist_ok=True)
    rows = []
    for grp, cid, path, n, rd in clips():
        words = ["animal", "fish"] + (["luderick"] if grp == "luderick dev" else [])
        row = {"group": grp, "clip": cid, "frames": n}
        for w in words:
            txt = reply(cid, path, w, n, offline)
            if txt is None:
                row[w] = None
                continue
            det = tracks.parse_boxes(txt)
            row[w] = {"frames_with_box": sum(1 for ds in det.values() if ds), "max_per_frame": tracks.max_per_frame(det)}
            if w == "animal" and rd and os.path.exists(os.path.join(rd, "result.json")):
                ref = counted_nonfish(rd)
                byid = {}
                for f, ds in det.items():
                    for d in ds:
                        byid.setdefault(d["id"], {})[f] = d["box"]
                found = set()
                for bx in byid.values():
                    for t, r in ref.items():
                        shared = [f for f in bx if f in r["boxes"] and tracks.iou(bx[f], r["boxes"][f]) >= 0.3]
                        if len(shared) >= 3:
                            found.add(r["label"])
                row["animal"]["counted_nonfish"] = sorted({r["label"] for r in ref.values()})
                row["animal"]["overlaps"] = sorted(found)
        rows.append(row)
        a, f = row.get("animal"), row.get("fish")
        print(f"{grp:20s} {cid:18s} animal {a and (a['frames_with_box'], a['max_per_frame'])}  "
              f"fish {f and (f['frames_with_box'], f['max_per_frame'])}"
              + (f"  luderick {(row['luderick']['frames_with_box'], row['luderick']['max_per_frame'])}" if row.get("luderick") else "")
              + (f"  animal overlaps {a['overlaps']} of {a['counted_nonfish']}" if a and "overlaps" in a else ""))
    json.dump(rows, open(os.path.join(OUT, "summary.json"), "w"), indent=1)
    zero = [r for r in rows if r.get("animal") and r["animal"]["frames_with_box"] == 0]
    print(f"'animal' returned no box on {len(zero)} of {sum(1 for r in rows if r.get('animal'))} clips")


if __name__ == "__main__":
    main()
