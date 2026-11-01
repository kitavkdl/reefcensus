"""Spike A: render audio as a scrolling spectrogram video (5 fps) so SAM 3.1 can track calls as objects.
usage: python3 -I specvid.py overview <wav>...          -> overview.jpg (whole-file spectrograms, for choosing segments)
       python3 -I specvid.py clip <wav> <start_s> <fmin> <fmax> <out.mp4> [n_frames=50] [win_s=4]"""
import os, subprocess, sys, wave
sys.path.insert(0, os.path.expanduser("~/meta-smoke/pylib"))
import cv2
import numpy as np
from scipy import signal

FFMPEG = os.path.expanduser("~/meta-smoke/pylib/imageio_ffmpeg/binaries/ffmpeg-linux-x86_64-v7.0.2")
FPS, W, H = 5, 1280, 720


def load(path):
    with wave.open(path) as w:
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
    return x, sr


def spec(x, sr, fmin, fmax, hop_s=0.004):
    nper = 1024
    f, t, S = signal.stft(x, sr, nperseg=nper, noverlap=nper - int(sr * hop_s))
    S = 20 * np.log10(np.abs(S) + 1e-9)
    band = (f >= fmin) & (f <= fmax)
    S = S[band][::-1]                                # low frequency at the bottom
    lo, hi = np.percentile(S, 50), np.percentile(S, 99.7)   # noise floor -> black
    return np.clip((S - lo) / (hi - lo), 0, 1), t


def colour(S):
    return cv2.applyColorMap((S * 255).astype(np.uint8), cv2.COLORMAP_INFERNO)


def overview(paths):
    rows = []
    for p in paths:
        x, sr = load(p)
        S, t = spec(x, sr, 0, sr / 2, hop_s=0.02)
        img = cv2.resize(colour(S), (1600, 300))
        for s in range(0, int(t[-1]) + 1, 5):          # tick every 5 s
            cx = int(s / t[-1] * 1599)
            cv2.line(img, (cx, 0), (cx, 12), (255, 255, 255), 2)
            cv2.putText(img, str(s), (cx + 2, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.putText(img, f"{os.path.basename(p)}  0-{sr // 2} Hz", (8, 290), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        rows.append(img)
    cv2.imwrite("overview.jpg", np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 80])


def clip(path, start, fmin, fmax, out, n=50, win=4.0):
    """Window of `win` seconds scrolling right-to-left by 1/FPS s per frame (real-time when played at FPS)."""
    x, sr = load(path)
    S, t = spec(x, sr, fmin, fmax)
    img = colour(S)
    px_per_s = W / win
    img = cv2.resize(img, (int(t[-1] * px_per_s), H), interpolation=cv2.INTER_AREA)
    tmp = out + ".frames"
    os.makedirs(tmp, exist_ok=True)
    for i in range(n):
        x0 = int((start + i / FPS) * px_per_s)
        fr = img[:, x0:x0 + W]
        if fr.shape[1] < W:
            fr = np.pad(fr, ((0, 0), (0, W - fr.shape[1]), (0, 0)))
        cv2.imwrite(f"{tmp}/{i:04d}.png", fr)
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-framerate", str(FPS), "-i", f"{tmp}/%04d.png",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", out], check=True)
    print(out, n, "frames", f"{start}-{start + n / FPS + win:.1f}s", f"{fmin}-{fmax}Hz")


if __name__ == "__main__":
    if sys.argv[1] == "overview":
        overview(sys.argv[2:])
    else:
        a = sys.argv[2:]
        clip(a[0], float(a[1]), float(a[2]), float(a[3]), a[4], *(int(v) for v in a[5:6]), *(float(v) for v in a[6:7]))
