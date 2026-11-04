"""Post-hoc low-light test on development clip s001 (Barord et al. 2014 S1, night, wire trap).

The frozen pipeline counted 2 nautiluses here (motion look only; a person sees 1 inside the trap and 3+ outside).
This script makes brightened copies of the same 12 s clip and runs the unchanged pipeline on each with the same
options as the demo run L1_s001_v16 (--no-scout --prompts fish --discover --zoom). The pipeline code is not touched.

Variants (parameters fixed before any run):
  gamma        out = 255 * (in/255) ** 0.5, per channel
  clahe        CLAHE on the L channel of Lab, clipLimit 3.0, 8x8 tiles
  gamma_clahe  gamma 0.5, then CLAHE clipLimit 2.0, 8x8 tiles

Usage:
  python3 report/paper/scripts/lowlight_s001.py make          # writes spikes/lowlight/s001_<variant>.mp4 (no API)
  FISH_BUDGET=<ledger+1.0> python3 report/paper/scripts/lowlight_s001.py run <variant>   # paid, runs/lowlight_s001_<variant>
  python3 report/paper/scripts/lowlight_s001.py table         # v16 vs variants from runs/*/result.json
"""
import json, os, subprocess, sys

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SRC = os.path.join(ROOT, "spikes", "L1", "clips", "nautilus_s001_0_12.mp4")
OUT = os.path.join(ROOT, "spikes", "lowlight")
VARIANTS = ("gamma", "clahe", "gamma_clahe")
BASE_RUN = os.path.join(ROOT, "demo", "runs", "L1_s001_v16")


def _gamma(img, g=0.5):
    lut = (255.0 * (np.arange(256) / 255.0) ** g).clip(0, 255).astype(np.uint8)
    return cv2.LUT(img, lut)


def _clahe(img, clip):
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    lab[:, :, 0] = cv2.createCLAHE(clipLimit=clip, tileGridSize=(8, 8)).apply(lab[:, :, 0])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


FILTERS = {
    "gamma": lambda f: _gamma(f, 0.5),
    "clahe": lambda f: _clahe(f, 3.0),
    "gamma_clahe": lambda f: _clahe(_gamma(f, 0.5), 2.0),
}


def make():
    import imageio_ffmpeg
    os.makedirs(OUT, exist_ok=True)
    cap = cv2.VideoCapture(SRC)
    fps = cap.get(cv2.CAP_PROP_FPS)
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    procs = {}
    for v in VARIANTS:
        dst = os.path.join(OUT, f"s001_{v}.mp4")
        procs[v] = subprocess.Popen(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo",
             "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", f"{fps}", "-i", "-", "-an", "-c:v", "libx264", "-threads", "9",  # = fishcount.video.X264_THREADS (cache keys)
                       
             "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", dst], stdin=subprocess.PIPE)
    n = 0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        for v, p in procs.items():
            p.stdin.write(FILTERS[v](f).tobytes())
        n += 1
    for p in procs.values():
        p.stdin.close()
        p.wait()
    print(f"{n} frames at {fps:.2f} fps, {w}x{h} -> {OUT}")


def run(v):
    sys.path.insert(0, ROOT)
    from fishcount import pipeline
    src = os.path.join(OUT, f"s001_{v}.mp4")
    r = pipeline.run_pipeline(src, f"lowlight_s001_{v}", False, False, True, True, ["fish"], 0.4, True)
    print(json.dumps({k: {x: y for x, y in m.items() if x != "curve"} for k, m in r["metrics"].items()}, indent=1))


def _summary(path):
    r = json.load(open(os.path.join(path, "result.json")))
    st = json.load(open(os.path.join(path, "status.json")))
    counts = {k: m["maxn"] for k, m in r["metrics"].items() if m.get("maxn")}
    tail = [l for l in st["log"] if "finished in" in l or "need a human look" in l]
    return counts, tail


def table():
    rows = [("v16 (original)", BASE_RUN)] + [(v, os.path.join(ROOT, "runs", f"lowlight_s001_{v}")) for v in VARIANTS]
    for name, p in rows:
        if os.path.exists(os.path.join(p, "result.json")):
            c, t = _summary(p)
            print(f"{name:16s} {c}  |  {' / '.join(x.split(' ', 1)[1] for x in t)}")
        else:
            print(f"{name:16s} (not run)")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "table"
    if cmd == "make":
        make()
    elif cmd == "run":
        run(sys.argv[2])
    else:
        table()
