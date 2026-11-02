"""Video helpers: re-encode to the analysis rate, read frames, crop tiles. Uses the ffmpeg binary shipped with
imageio-ffmpeg and OpenCV for frame access (pip install -r requirements.txt, or a vendored folder via FISH_PYLIB)."""
import os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fishcount import _pylib  # noqa: F401
import cv2
import numpy as np

import imageio_ffmpeg
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


def ingest(src, dst, fps=5, max_w=1920, max_seconds=600):
    """Re-encode `src` to H.264 at `fps`, width <= max_w, no audio. Returns dict(n_frames, fps, width, height)."""
    vf = f"fps={fps},scale='min({max_w},iw)':-2"
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", src, "-t", str(max_seconds),
                    "-vf", vf, "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", dst],
                   check=True)
    return info(dst)


# Low-light correction (11/2, fixes branch). Night BRUV footage (s001, a wire trap lit by a lamp) is mostly black:
# SAM tracked no word there and the motion look found 2 of the 4+ nautiluses. A post-hoc test
# (report/paper/lowlight_s001.md) brightened the clip with gamma 0.5 then CLAHE 2.0 and the unchanged pipeline counted 4,
# none wrongly. The correction is applied only to clips that are dark by both measures below, fixed before any run
# from the development clips' brightness (Lab L, every 5th frame at 480 px wide):
#   s001 night trap: median 5, mean 26.5 (on)  |  s004 deep, lit: median 26, mean 42.0 (off, nearest)
#   s003 70/61, s002 85/90, six luderick clips mean 148-160 (off)
DARK_MEDIAN_L = 15
DARK_MEAN_L = 35


def light_stats(path, every=5, width=480):
    """Brightness of a clip: mean and median Lab L (0-255) and the share of pixels with L < 50, every `every`-th frame."""
    cap = cv2.VideoCapture(path)
    Ls, i = [], 0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        if i % every == 0:
            f = cv2.resize(f, (width, max(1, int(width * f.shape[0] / f.shape[1]))))
            Ls.append(cv2.cvtColor(f, cv2.COLOR_BGR2LAB)[:, :, 0])
        i += 1
    cap.release()
    if not Ls:
        return dict(mean_l=None, median_l=None, dark_share=None)
    L = np.stack(Ls).astype(float)
    return dict(mean_l=round(float(L.mean()), 1), median_l=round(float(np.median(L)), 1), dark_share=round(float((L < 50).mean()), 3))


def is_dark(st):
    return st.get("median_l") is not None and st["median_l"] < DARK_MEDIAN_L and st["mean_l"] < DARK_MEAN_L


def brighten_frame(img):
    """gamma 0.5 per channel, then CLAHE (clipLimit 2.0, 8x8 tiles) on the Lab L channel."""
    lut = (255.0 * (np.arange(256) / 255.0) ** 0.5).clip(0, 255).astype(np.uint8)
    lab = cv2.cvtColor(cv2.LUT(img, lut), cv2.COLOR_BGR2LAB)
    lab[:, :, 0] = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(lab[:, :, 0])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def brighten(src, dst):
    """Write `src` brightened frame by frame to `dst` (H.264 crf 18, same size and rate; the encoding of the post-hoc
    test, so its cached API answers still apply)."""
    cap = cv2.VideoCapture(src)
    fps = cap.get(cv2.CAP_PROP_FPS)
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    p = subprocess.Popen([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
                          "-s", f"{w}x{h}", "-r", f"{fps}", "-i", "-", "-an", "-c:v", "libx264", "-preset", "veryfast",
                          "-crf", "18", "-pix_fmt", "yuv420p", dst], stdin=subprocess.PIPE)
    while True:
        ok, f = cap.read()
        if not ok:
            break
        p.stdin.write(brighten_frame(f).tobytes())
    cap.release()
    p.stdin.close()
    if p.wait():
        raise RuntimeError(f"ffmpeg failed brightening {src}")
    return info(dst)


def info(path):
    cap = cv2.VideoCapture(path)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    d = dict(n_frames=n, fps=cap.get(cv2.CAP_PROP_FPS), width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
             height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    cap.release()
    return d


def frames(path, indices):
    """Return {index: BGR ndarray} for the requested frame indices (sequential read; clips are short)."""
    want, out = set(indices), {}
    cap = cv2.VideoCapture(path)
    i = 0
    while want - out.keys():
        ok, f = cap.read()
        if not ok:
            break
        if i in want:
            out[i] = f
        i += 1
    cap.release()
    return out


def jpg(img, max_w=None, q=85):
    if max_w and img.shape[1] > max_w:
        img = cv2.resize(img, (max_w, int(img.shape[0] * max_w / img.shape[1])), interpolation=cv2.INTER_AREA)
    return cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])[1].tobytes()


def label(img, text):
    img = img.copy()
    cv2.rectangle(img, (0, 0), (12 + 14 * len(text), 34), (0, 0, 0), -1)
    cv2.putText(img, text, (6, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    return img


def grid(imgs, cols, cell_w):
    """Tile images (already labelled) into one sheet, each resized to cell_w wide."""
    cells = []
    for im in imgs:
        h = int(im.shape[0] * cell_w / im.shape[1])
        cells.append(cv2.resize(im, (cell_w, h), interpolation=cv2.INTER_AREA))
    ch = max(c.shape[0] for c in cells)
    cells = [np.pad(c, ((0, ch - c.shape[0]), (0, 0), (0, 0))) for c in cells]
    while len(cells) % cols:
        cells.append(np.zeros_like(cells[0]))
    rows = [np.hstack(cells[i:i + cols]) for i in range(0, len(cells), cols)]
    return np.vstack(rows)


def crop_tile(src, dst, box, scale=2, fps=5):
    """Crop box=(x,y,w,h) from every frame of src and upscale by `scale` (for small/far objects)."""
    x, y, w, h = box
    vf = f"crop={w}:{h}:{x}:{y},scale={int(w * scale) // 2 * 2}:{int(h * scale) // 2 * 2}:flags=lanczos"
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", src, "-vf", vf, "-an",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", dst], check=True)
    return info(dst)


def reverse(src, dst):
    """Same clip played backwards. SAM only tracks forward from the frame where it first recognises an object
    (11/1 s003: forward 'nautilus' starts at frame 27; reversed run covers all 60), so a reversed pass back-fills."""
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", src, "-vf", "reverse", "-an",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", dst], check=True)
    return info(dst)
