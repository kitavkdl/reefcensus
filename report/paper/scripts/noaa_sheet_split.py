"""Hand-count sheets small enough to send to a phone (the one-file sheet from prep_noaa_heldout.py is ~257 MB).

Re-encodes the neutral-name copies (data_noaa/clip_a.mp4 ...) at the original frame rate and resolution with a
bitrate cap, and writes two sheets of four clips each, in the key's (shuffled) order. Nothing about the clip contents
is looked at; the key (handcount_key.json) is not opened, only the clip names on disk are used.

    python3 report/paper/scripts/noaa_sheet_split.py [--dir data_noaa] [--max-mb 25]
"""
import argparse, glob, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
import count_sheet_video  # noqa: E402
from fishcount.video import FFMPEG  # noqa: E402


def encode(src, dst, rate):
    subprocess.run([FFMPEG, "-hide_banner", "-nostdin", "-loglevel", "error", "-y", "-i", src, "-an",
                    "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-maxrate", f"{rate}k",
                    "-bufsize", f"{2 * rate}k", "-pix_fmt", "yuv420p", "-movflags", "+faststart", dst],
                   check=True, timeout=900, stdin=subprocess.DEVNULL)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=os.path.join(ROOT, "data_noaa"))
    ap.add_argument("--max-mb", type=float, default=25.0)
    a = ap.parse_args()
    names = sorted(os.path.basename(p)[:-4] for p in glob.glob(os.path.join(a.dir, "clip_?.mp4")))
    out = os.path.join(a.dir, "sheet")
    os.makedirs(out, exist_ok=True)
    halves = [names[:len(names) // 2], names[len(names) // 2:]]
    for i, part in enumerate(halves, 1):
        rate = 3200
        while True:
            for n in part:
                encode(os.path.join(a.dir, n + ".mp4"), os.path.join(out, n + ".mp4"), rate)
            html = count_sheet_video.build({n: None for n in part}, out, ".mp4", "fishcount-noaa")
            mb = len(html.encode()) / 2 ** 20
            if mb <= a.max_mb or rate <= 1200:
                break
            rate = int(rate * a.max_mb / mb * 0.95)
        path = os.path.join(a.dir, f"noaa-count-sheet-{i}of{len(halves)}.html")
        open(path, "w").write(html)
        print(f"{path}: {', '.join(part)}  {mb:.1f} MB (maxrate {rate} kb/s)")


if __name__ == "__main__":
    main()
