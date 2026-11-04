"""Held-out luderick clips (Ditria et al. 2021, PANGAEA doi:10.1594/PANGAEA.926930, CC BY 4.0): every annotated video
in the archive copy that the six development clips did not use. Same preparation as the development clips
(~/meta-smoke/scripts/prep_luderick.py): re-encode at 5 fps, clip frame i <-> annotation frame i+1.
  python3 report/paper/scripts/prep_heldout.py
writes ~/meta-smoke/clips/fish_<video>.mp4, clips/gt/fish_<video>.json, clips/manifest_heldout.json and a copy of the
ground truth in report/paper/data/heldout/gt/ (the bundle the paper's rescoring reads)."""
import csv, collections, glob, json, os, re, shutil, subprocess

SMOKE = os.path.expanduser("~/meta-smoke")
DATA = SMOKE + "/data/luderick"
FFMPEG = SMOKE + "/pylib/imageio_ffmpeg/binaries/ffmpeg-linux-x86_64-v7.0.2"
DEV = {"20190618_9", "20190709_14", "20190618_3", "20190710_4", "20190709_13", "20190709_4"}
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def nframes(path):
    import sys
    sys.path.insert(0, SMOKE + "/pylib")
    import cv2
    cap = cv2.VideoCapture(path); n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)); cap.release()
    return n


def main():
    ann = collections.defaultdict(lambda: collections.defaultdict(list))
    for r in csv.DictReader(open(f"{DATA}/annotations.csv")):
        m = re.match(r"(.+)\.mov_5fps_(\d+)\.jpg", r["image"])
        if m:
            ann[m.group(1)][int(m.group(2)) - 1].append(
                [float(r["bbox_x"]), float(r["bbox_y"]), float(r["bbox_w"]), float(r["bbox_h"]), r["category"]])
    vids = {os.path.basename(p)[:-4]: p for p in glob.glob(f"{DATA}/videos/**/*.mov", recursive=True)}
    pick = sorted(v for v in vids if v not in DEV and v in ann)
    man = {"note": "held-out: every annotated archive video not used in development (11/2, protocol in report/paper/heldout_protocol.md)",
           "clips": {}}
    os.makedirs(f"{HERE}/data/heldout/gt", exist_ok=True)
    for v in pick:
        cid = f"fish_{v}"; dst = f"{SMOKE}/clips/{cid}.mp4"
        subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", vids[v], "-vf", "fps=5", "-an",
                        "-c:v", "libx264", "-threads", "9",  # = fishcount.video.X264_THREADS (cache keys)
                        "-crf", "20", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-movflags", "+faststart", dst], check=True)
        n = nframes(dst)
        gt = {i: b for i, b in ann[v].items() if i < n}
        g = f"{SMOKE}/clips/gt/{cid}.json"
        json.dump(dict(frames=gt, n_frames=n), open(g, "w"))
        shutil.copy(g, f"{HERE}/data/heldout/gt/{cid}.json")
        maxn = max((len(b) for b in gt.values()), default=0)
        print(f"{cid}: {n} frames, GT frames {len(gt)}, boxes {sum(map(len, gt.values()))}, MaxN {maxn}")
        man["clips"][cid] = dict(test="fish", path=f"clips/{cid}.mp4", gt=f"clips/gt/{cid}.json", src=os.path.relpath(vids[v], SMOKE),
                                 out_fps=5, n_frames=n, width=1920, height=1080, prompts=["fish"])
    json.dump(man, open(f"{SMOKE}/clips/manifest_heldout.json", "w"), indent=1)
    json.dump(man, open(f"{HERE}/data/heldout/manifest.json", "w"), indent=1)
    print(len(pick), "clips")


main()
