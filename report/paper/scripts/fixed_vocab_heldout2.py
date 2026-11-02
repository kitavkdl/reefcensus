"""Fixed-vocabulary baseline on the second held-out discovery set (protocol: report/paper/discovery_heldout2_protocol.md).
No VLM naming: SAM 3.1 on the full frame, one call per (clip, word), with the same 16 basic-level words as
fixed_vocab.py (copied here because that script runs on import). Uses each discovery run's clip.mp4
(runs/DH<n>_eval/) so "fish" comes from the pipeline's cache and the clip hash matches.
  python3 report/paper/scripts/fixed_vocab_heldout2.py --dry                      (no network: calls, cache hits, cost)
  FISH_BUDGET=<ledger+1.6> python3 report/paper/scripts/fixed_vocab_heldout2.py   (paid: about 15 x $0.012 per clip)
  python3 report/paper/scripts/fixed_vocab_heldout2.py --offline                  (cache / saved replies only)
Writes report/paper/data/discovery_heldout2/fixed_vocab/: raw replies <clip>__<word>.txt, summary.json, and the
label-free crop sheet for protocol metrics 4-5 (crops_sheet.jpg; crop number -> clip/word/track in crops_key.json,
which the judge does not see; crops are shuffled with a fixed seed so neighbouring crops do not reveal the word).
Rules: a track of word w overlaps a counted non-fish pipeline track when IoU >= 0.3 in >= 3 shared frames (as in
fixed_vocab.py). Crops: for every non-fish word, the 3 longest tracks per clip, each at its highest-confidence frame."""
import json, os, random, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
from fishcount import api, tracks, pipeline, video  # noqa: E402
import cv2, numpy as np  # noqa: E402

WORDS = ["fish", "shark", "ray", "eel", "crab", "shrimp", "lobster", "octopus", "squid", "snail", "shell",
         "starfish", "jellyfish", "sea urchin", "sea cucumber", "worm"]
CLIPS = [f"DH{n}" for n in range(6, 12)]
OUT = os.path.join(ROOT, "report/paper/data/discovery_heldout2/fixed_vocab")
FISHY = ("fish",)
MAX_CROPS = 3


def is_fish(label):
    return any(w in label.split(" (")[0].split() for w in FISHY)


def clip_path(cid):
    return os.path.join(ROOT, "runs", f"{cid}_eval", "clip.mp4")


def counted_nonfish(cid):
    """{track: {"label", "boxes": {frame: box}}} for non-fish tracks the audited run counted (not queued)."""
    rd = os.path.join(ROOT, "runs", f"{cid}_eval")
    r = json.load(open(os.path.join(rd, "result.json")))
    keep = {t: lab for t, lab in r["auto_labels"].items()
            if lab and not is_fish(lab) and not pipeline.needs_review(r["verdicts"].get(t, {}))}
    ref = {}
    for f, ks in r["frames"].items():
        for k in ks:
            if k["track"] in keep:
                ref.setdefault(k["track"], {"label": keep[k["track"]], "boxes": {}})["boxes"][int(f)] = k["box"]
    return ref


def analyse(det, ref):
    byid = {}
    for f, ds in det.items():
        for d in ds:
            byid.setdefault(d["id"], {})[f] = (d["box"], d["conf"] or 0.0)
    rows = []
    for tid, fb in byid.items():
        hit = None
        for t, r in ref.items():
            shared = [f for f in fb if f in r["boxes"] and tracks.iou(fb[f][0], r["boxes"][f]) >= 0.3]
            if len(shared) >= 3:
                hit = r["label"]; break
        bf = max(fb, key=lambda f: fb[f][1])
        rows.append(dict(track=tid, frames=len(fb), overlaps_counted=hit, best_frame=bf, box=list(fb[bf][0])))
    return rows


def crop(clip, frame, box, size=300):
    img = video.frames(clip, [frame])[frame]
    x0, y0, x1, y1 = map(int, box)
    m = max(x1 - x0, y1 - y0) // 2 + 20
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    H, W = img.shape[:2]
    a, b, c, d = max(0, cx - m), max(0, cy - m), min(W, cx + m), min(H, cy + m)
    p = img[b:d, a:c].copy()
    cv2.rectangle(p, (x0 - a, y0 - b), (x1 - a, y1 - b), (255, 255, 255), 1)
    s = size / max(p.shape[:2])
    p = cv2.resize(p, (max(1, int(p.shape[1] * s)), max(1, int(p.shape[0] * s))), interpolation=cv2.INTER_CUBIC)
    tile = np.zeros((size + 50, size, 3), np.uint8)
    tile[50:50 + p.shape[0], :p.shape[1]] = p
    return tile


def main():
    dry, offline = "--dry" in sys.argv, "--offline" in sys.argv
    os.makedirs(OUT, exist_ok=True)
    if dry:
        paid = 0
        for cid in CLIPS:
            cp = clip_path(cid)
            if not os.path.exists(cp):
                print(f"{cid}: no run yet ({cp}); would need all {len(WORDS)} words except a cached 'fish'")
                paid += len(WORDS) - 1
                continue
            n = video.info(cp)["n_frames"]
            miss = [w for w in WORDS if not os.path.exists(api._cache_path("sam", {"clip": api.file_sha(cp), "prompt": w}))]
            paid += len(miss)
            print(f"{cid}: {n} frames, {len(miss)} of {len(WORDS)} words not cached: {miss}")
        est = paid * max(api.SAM_MIN_FRAMES, 60) * api.SAM_PER_FRAME
        print(f"paid SAM calls {paid}, estimated ${est:.2f}; ledger now ${api.spent():.2f}")
        return
    summary, cands = {}, []
    for cid in CLIPS:
        cp = clip_path(cid)
        n = video.info(cp)["n_frames"]
        ref = counted_nonfish(cid)
        summary[cid] = {"counted_nonfish": sorted({r["label"] for r in ref.values()}), "words": {}}
        for w in WORDS:
            bp = os.path.join(OUT, f"{cid}__{w.replace(' ', '_')}.txt")
            if offline and os.path.exists(bp):
                txt = open(bp).read()
            else:
                txt = api.sam_video(cp, w, n, offline=offline)
                open(bp, "w").write(txt)
            det = tracks.parse_boxes(txt)
            rows = analyse(det, ref)
            summary[cid]["words"][w] = dict(frames=len(det), maxn=tracks.max_per_frame(det), tracks=len(rows),
                                            overlaps=sorted({r["overlaps_counted"] for r in rows if r["overlaps_counted"]}),
                                            unmatched=sum(1 for r in rows if not r["overlaps_counted"]))
            if w != "fish":
                for r in sorted(rows, key=lambda r: -r["frames"])[:MAX_CROPS]:
                    cands.append(dict(clip=cid, word=w, **r))
    random.Random(20261102).shuffle(cands)
    tiles = []
    for k, c in enumerate(cands, 1):
        c["crop"] = k
        t = crop(clip_path(c["clip"]), c["best_frame"], c["box"])
        cv2.putText(t, f"#{k}", (10, 38), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 2, cv2.LINE_AA)
        tiles.append(t)
    json.dump(summary, open(os.path.join(OUT, "summary.json"), "w"), indent=1)
    json.dump(cands, open(os.path.join(OUT, "crops_key.json"), "w"), indent=1)
    if tiles:
        cols = 6
        while len(tiles) % cols:
            tiles.append(np.zeros_like(tiles[0]))
        grid = np.vstack([np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)])
        cv2.imwrite(os.path.join(OUT, "crops_sheet.jpg"), grid, [cv2.IMWRITE_JPEG_QUALITY, 90])
    for cid, s in summary.items():
        print(cid, "counted non-fish:", s["counted_nonfish"])
        print("   ", {w: (r["tracks"], r["overlaps"]) for w, r in s["words"].items() if r["tracks"]})
    print(f"{len(cands)} label-free crops for the judge")


if __name__ == "__main__":
    main()
