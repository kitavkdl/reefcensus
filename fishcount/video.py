"""Video helpers: re-encode to the analysis rate, read frames, crop tiles. Uses the ffmpeg binary shipped with
imageio-ffmpeg and OpenCV for frame access (pip install -r requirements.txt; ~/meta-smoke/pylib also works)."""
import os, re, subprocess, sys

sys.path.insert(0, os.path.expanduser("~/meta-smoke/pylib"))
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
    vf = f"crop={w}:{h}:{x}:{y},scale={w * scale}:{h * scale}:flags=lanczos"
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", src, "-vf", vf, "-an",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", dst], check=True)
    return info(dst)
