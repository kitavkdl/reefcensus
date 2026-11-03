"""Open-vocabulary detector baseline (protocol: report/paper/open_detector_protocol.md). $0, CPU only.

OWLv2 (google/owlv2-base-patch16-ensemble) on every frame of the 15 discovery clips (the 5 fps clip.mp4 each final
run tracked, runs/vswap_<clip>/), queried with "animal" plus the 16 fixed words of fixed_vocab.py, all in one pass.
Writes report/paper/data/open_detector/: detections.json (every box with score >= 0.05), summary.json, crops sheet.

  PYTHONPATH=~/venvs/detlib memcap --max 3G -- python3 report/paper/scripts/open_detector.py [--clips ...] [--score]
  (--score re-reads detections.json and only scores; no model load)
"""
import argparse, json, os, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from fishcount import pipeline, tracks  # noqa: E402

WORDS = ["fish", "shark", "ray", "eel", "crab", "shrimp", "lobster", "octopus", "squid", "snail", "shell",
         "starfish", "jellyfish", "sea urchin", "sea cucumber", "worm"]
QUERIES = ["animal"] + WORDS
CLIPS = [f"DH{n}" for n in range(1, 12)] + ["s001", "s002", "s003", "s004"]
THRESHOLDS = (0.1, 0.2, 0.3)          # 0.2 primary, fixed in the protocol before the run
PRIMARY = 0.2
KEEP = 0.05                           # stored, so other thresholds can be scored without a rerun
OUT = "report/paper/data/open_detector"
MODEL = "google/owlv2-base-patch16-ensemble"


def frames(path):
    import cv2
    cap = cv2.VideoCapture(path)
    i = 0
    while True:
        ok, bgr = cap.read()
        if not ok:
            break
        yield i, bgr[:, :, ::-1].copy()
        i += 1
    cap.release()


def detect(clips):
    import torch
    from PIL import Image
    from transformers import Owlv2ForObjectDetection, Owlv2Processor
    torch.set_num_threads(int(os.environ.get("DET_THREADS", "3")))
    proc = Owlv2Processor.from_pretrained(MODEL)
    model = Owlv2ForObjectDetection.from_pretrained(MODEL).eval()
    dpath = os.path.join(OUT, "detections.json")
    det = json.load(open(dpath)) if os.path.exists(dpath) else {}
    for c in clips:
        if c in det:
            continue
        t0, out = time.time(), {}
        for i, rgb in frames(f"runs/vswap_{c}/clip.mp4"):
            img = Image.fromarray(rgb)
            inp = proc(text=[QUERIES], images=img, return_tensors="pt")
            with torch.no_grad():
                o = model(**inp)
            side = max(img.size)                       # OWLv2 pads to a square: boxes are relative to the long side
            r = proc.post_process_object_detection(o, threshold=KEEP, target_sizes=torch.tensor([[side, side]]))[0]
            out[i] = [dict(q=QUERIES[int(l)], s=round(float(s), 4), box=[round(float(v), 1) for v in b])
                      for s, l, b in zip(r["scores"], r["labels"], r["boxes"])]
        det[c] = dict(frames=out, seconds=round(time.time() - t0, 1), n_frames=len(out))
        json.dump(det, open(dpath, "w"))
        print(c, len(out), "frames", det[c]["seconds"], "s", flush=True)
    return det


def is_fish(label):
    base = label.split(" (")[0]
    return "fish" in base.split() or pipeline.name_group(base) == "fish"


def counted_nonfish(c):
    r = json.load(open(f"runs/vswap_{c}/result.json"))
    keep = {t: lab for t, lab in r["auto_labels"].items()
            if lab and not is_fish(lab) and not pipeline.needs_review(r["verdicts"].get(t, {}))}
    ref = {}
    for f, ks in r["frames"].items():
        for k in ks:
            if k["track"] in keep:
                ref.setdefault(k["track"], {"label": keep[k["track"]], "boxes": {}})["boxes"][int(f)] = k["box"]
    return ref, r


def score(det):
    summ = {}
    for c, d in det.items():
        ref, r = counted_nonfish(c)
        allboxes = {int(f): [k["box"] for k in ks] for f, ks in r["frames"].items()}   # every pipeline track box
        row = {"n_frames": d["n_frames"], "seconds": d["seconds"], "pipeline_counted_nonfish": len(ref)}
        for th in THRESHOLDS:
            fr = {int(f): [x for x in xs if x["s"] >= th] for f, xs in d["frames"].items()}
            found, right_word = {}, {}
            for t, rr in ref.items():
                hits = [f for f, b in rr["boxes"].items() if any(tracks.iou(x["box"], b) >= 0.3 for x in fr.get(f, []))]
                found[t] = len(hits) >= 3
                grp = pipeline.name_group(rr["label"].split(" (")[0])
                rw = [f for f, b in rr["boxes"].items()
                      if any(tracks.iou(x["box"], b) >= 0.3 and x["q"] != "animal" and pipeline.name_group(x["q"]) == grp
                             and grp is not None for x in fr.get(f, []))]
                right_word[t] = len(rw) >= 3
            loose = [x for f, xs in fr.items() for x in xs if x["q"] != "fish"
                     and not any(tracks.iou(x["box"], b) >= 0.3 for b in allboxes.get(f, []))]
            row[str(th)] = dict(
                pipeline_tracks_found=sum(found.values()), with_right_word=sum(right_word.values()),
                found=[ref[t]["label"] for t in found if found[t]], missed=[ref[t]["label"] for t in found if not found[t]],
                nonfish_boxes=sum(1 for xs in fr.values() for x in xs if x["q"] != "fish"),
                nonfish_boxes_off_every_pipeline_track=len(loose),
                frames_with_animal_box=sum(1 for xs in fr.values() if any(x["q"] == "animal" for x in xs)))
        summ[c] = row
    json.dump(summ, open(os.path.join(OUT, "summary.json"), "w"), indent=1)
    return summ


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", nargs="*", default=CLIPS)
    ap.add_argument("--score", action="store_true")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    det = json.load(open(os.path.join(OUT, "detections.json"))) if a.score else detect(a.clips)
    for c, row in score(det).items():
        p = row[str(PRIMARY)]
        print(c, f"pipeline non-fish {row['pipeline_counted_nonfish']}, found {p['pipeline_tracks_found']}"
              f" (right word {p['with_right_word']}), non-fish boxes {p['nonfish_boxes']}"
              f" ({p['nonfish_boxes_off_every_pipeline_track']} off every track), {row['seconds']} s")


if __name__ == "__main__":
    main()
