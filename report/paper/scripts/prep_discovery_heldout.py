"""Held-out discovery clips (protocol: report/paper/discovery_heldout_protocol.md). Five CC BY videos from Wikimedia
Commons copies of PLOS ONE supplements, none used in development. Window fixed by rule: the 12 s centred on the
file's midpoint (whole file if shorter), 5 fps, width <= 1920, no audio. Also writes the 4-frame sheet (frames 0, 20,
40, 59) that the reference lists are written from, before any pipeline run.
  python3 report/paper/scripts/prep_discovery_heldout.py
Raw files are expected in spikes/DH/raw/ (download URLs and sha256 in report/paper/data/discovery_heldout/clips.json)."""
import hashlib, json, os, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
from fishcount import video   # noqa: E402  (sets up the optional FISH_PYLIB path, ffmpeg, cv2)
import cv2, numpy as np   # noqa: E402

RAW = os.path.join(ROOT, "spikes", "DH", "raw")
OUT = os.path.join(ROOT, "spikes", "DH", "clips")
DATA = os.path.join(ROOT, "report", "paper", "data", "discovery_heldout")
C = "https://upload.wikimedia.org/wikipedia/commons/"
CLIPS = [
    ("DH1", "6/62/Deep-Coastal-Marine-Taphonomy-Investigation-into-Carcass-Decomposition-in-the-Saanich-Inlet-British-pone.0110710.s004.ogv",
     "Anderson & Bell 2014, PLOS ONE 9(10):e110710, doi:10.1371/journal.pone.0110710, S4 (Carcass 2 Day 2)", "CC BY 4.0"),
    ("DH2", "e/e8/Deep-Coastal-Marine-Taphonomy-Investigation-into-Carcass-Decomposition-in-the-Saanich-Inlet-British-pone.0110710.s001.ogv",
     "Anderson & Bell 2014, PLOS ONE 9(10):e110710, S1 (Carcass 1 Day 0)", "CC BY 4.0"),
    ("DH3", "5/58/Deep-Coastal-Marine-Taphonomy-Investigation-into-Carcass-Decomposition-in-the-Saanich-Inlet-British-pone.0110710.s003.ogv",
     "Anderson & Bell 2014, PLOS ONE 9(10):e110710, S3 (Carcass 1 Day 6)", "CC BY 4.0"),
    ("DH4", "f/fe/Impact-of-Marine-Submergence-and-Season-on-Faunal-Colonization-and-Decomposition-of-Pig-Carcasses-pone.0149107.s002.ogv",
     "Anderson & Bell 2016, PLOS ONE 11(3):e0149107, doi:10.1371/journal.pone.0149107, S2", "CC BY 4.0"),
    ("DH5", "1/1c/Diversity-and-Composition-of-Demersal-Fishes-along-a-Depth-Gradient-Assessed-by-Baited-Remote-pone.0048522.s005.ogv",
     "Zintzen et al. 2012, PLOS ONE 7(11):e48522, doi:10.1371/journal.pone.0048522, Video S1 (Commons file s005)", "CC BY 2.5"),
]


def duration(path):
    cap = cv2.VideoCapture(path)
    n, fps = cap.get(cv2.CAP_PROP_FRAME_COUNT), cap.get(cv2.CAP_PROP_FPS)
    cap.release()
    return n / fps if fps else 0.0


def main():
    os.makedirs(OUT, exist_ok=True); os.makedirs(DATA, exist_ok=True)
    meta = []
    for cid, path, cite, lic in CLIPS:
        src = os.path.join(RAW, os.path.basename(path))
        sha = hashlib.sha256(open(src, "rb").read()).hexdigest()
        d = duration(src)
        start = max(0.0, d / 2 - 6) if d > 12 else 0.0
        dst = os.path.join(OUT, f"{cid}.mp4")
        subprocess.run([video.FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{start:.2f}", "-i", src, "-t", "12",
                        "-vf", "fps=5,scale='min(1920,iw)':-2", "-an", "-c:v", "libx264", "-threads", "9",  # = fishcount.video.X264_THREADS (cache keys)
                        "-preset", "veryfast", "-crf", "20",
                        "-pix_fmt", "yuv420p", dst], check=True)
        inf = video.info(dst)
        idx = [i for i in (0, 20, 40, 59) if i < inf["n_frames"]]
        imgs = [video.label(im, f"{cid} frame {i}") for i, im in sorted(video.frames(dst, idx).items())]
        open(os.path.join(DATA, f"sheet_{cid}.jpg"), "wb").write(video.jpg(video.grid(imgs, 2, 960)))
        meta.append(dict(id=cid, url=C + path, citation=cite, licence=lic, sha256=sha, duration_s=round(d, 2),
                         window_start_s=round(start, 2), **inf))
        print(cid, round(d, 1), "s ->", inf)
    json.dump(dict(note="held-out discovery clips; window = 12 s centred on the file midpoint", clips=meta),
              open(os.path.join(DATA, "clips.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
