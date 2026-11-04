"""Side-by-side video for the night-trap scene: the same auto-brightened s001 clip the pipeline tracked, left with every
box of the fixed 17-word SAM list (report/paper/data/fixed_vocab_brightened/, 16 words + 'nautilus'), right with the
final run's counted nautilus tracks (runs/cr8_s001/result.json; Spark picked the moving spots, SAM tracked each from a
box with no word) and, in another colour, the fifth nautilus that run left in the human queue (QUEUED). Per-frame box
counts are drawn on each side. All numbers come from those files; nothing is called.

  FISH_PYLIB=... memcap --max 2G -- python3 report/scripts/split_s001_night.py
  -> report/figures/split_s001_night.mp4 (5 fps, the analysis rate; slow it down in the editor if needed)
     report/figures/split_s001_night_f38.jpg (frame 38, all five nautiluses in view: the README image)
"""
import glob, json, os, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT); os.chdir(ROOT)
from fishcount import video, tracks  # noqa: E402
import cv2, numpy as np  # noqa: E402
import imageio_ffmpeg  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

RUN = "runs/cr8_s001"
CLIP = f"{RUN}/clip.mp4"
# m8: the fifth nautilus (second motion look; audit "pale oval shell", 0.4; the unprimed second look saw "a blurry light
# spot"), so it is not counted and waits for a person. The run's other queued tracks (m10, m11) sit on the trap's mesh
# and bait bag, so they are not drawn.
QUEUED = {"m8:1"}
QUEUE_C = (255, 225, 60)               # RGB: yellow = waiting for a person
STILL = 37                             # 0-based frame of the README image
OUT = "report/figures/split_s001_night.mp4"
W, H = 1920, 1080
PW, PH = 944, 531                      # panel size (16:9), two panels with a 32 px gap
BG = (14, 20, 30)
FB = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
F = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
LEFT_C, RIGHT_C = (60, 150, 255), (255, 150, 40)      # RGB: blue = word list, orange = found without being asked


def main():
    words = {}
    for p in sorted(glob.glob("report/paper/data/fixed_vocab_brightened/s001__*.txt")):
        w = os.path.basename(p)[len("s001__"):-4].replace("_", " ")
        words[w] = tracks.parse_boxes(open(p).read())
    r = json.load(open(f"{RUN}/result.json"))
    counted = {t for t, lab in r["auto_labels"].items() if lab and "nautilus" in lab}
    n = video.info(CLIP)["n_frames"] if "n_frames" in video.info(CLIP) else 60
    frs = video.frames(CLIP, list(range(n)))
    word_frames = sorted({f for d in words.values() for f in d if d[f]})
    print("word boxes on frames", word_frames[:3], "...", len(word_frames), "frames;",
          {w: sum(1 for f in d if d[f]) for w, d in words.items() if any(d.values())})
    g = np.max([frs[f].max(axis=2) for f in range(0, n, 10)], axis=0) > 24   # the clip is boxed: crop to the picture
    ys, xs = np.where(g.any(axis=1))[0], np.where(g.any(axis=0))[0]
    cx0, cx1, cy0, cy1 = int(xs[0]) + 4, int(xs[-1]) - 4, int(ys[0]) + 4, int(ys[-1]) - 4
    print("picture area", cx0, cy0, cx1, cy1)
    tmp = tempfile.mkdtemp(prefix="split_")
    big, mid, small = ImageFont.truetype(FB, 46), ImageFont.truetype(FB, 34), ImageFont.truetype(F, 28)
    for f in range(n):
        img = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(img)
        d.text((W // 2, 60), "Night, behind a trap: the same brightened frames", font=big, fill=(235, 235, 235), anchor="mm")
        for side in (0, 1):
            fr = frs[f][cy0:cy1, cx0:cx1, ::-1].copy()                      # picture only, BGR -> RGB
            sx, sy = PW / fr.shape[1], PH / fr.shape[0]
            pil = Image.fromarray(cv2.resize(fr, (PW, PH), interpolation=cv2.INTER_AREA))
            pd = ImageDraw.Draw(pil)
            if side == 0:
                boxes = [(w, b["box"]) for w, dd in words.items() for b in dd.get(f, [])]
                col = LEFT_C
                queued = []
            else:
                boxes = [("", k["box"]) for k in r["frames"].get(str(f), []) if k["track"] in counted]
                col = RIGHT_C
                queued = [k["box"] for k in r["frames"].get(str(f), []) if k["track"] in QUEUED]
            for w, (x0, y0, x1, y1) in boxes:
                x0, x1, y0, y1 = (x0 - cx0) * sx, (x1 - cx0) * sx, (y0 - cy0) * sy, (y1 - cy0) * sy
                pd.rectangle((x0, y0, x1, y1), outline=col, width=5)
                if w:
                    pd.text((x0, y0 - 34), f"'{w}'", font=small, fill=col)
            for x0, y0, x1, y1 in queued:
                x0, x1, y0, y1 = (x0 - cx0) * sx, (x1 - cx0) * sx, (y0 - cy0) * sy, (y1 - cy0) * sy
                pd.rectangle((x0, y0, x1, y1), outline=QUEUE_C, width=4)
                pd.text((x0, y0 - 30), "needs a person", font=small, fill=QUEUE_C)
            x = 0 if side == 0 else PW + 32
            img.paste(pil, (x, 150))
            title = "SAM with 17 fixed words" if side == 0 else "Muse Spark points, SAM tracks a box"
            sub = "(16-word list + 'nautilus')" if side == 0 else "(each one tracked from a box, no word)"
            d.text((x + PW // 2, 112), title, font=mid, fill=col, anchor="mm")
            d.text((x + PW // 2, 150 + PH + 40), sub, font=small, fill=(200, 200, 200), anchor="mm")
            d.text((x + PW // 2, 150 + PH + 110), f"animals boxed in this frame: {len(boxes)}", font=big, fill=col, anchor="mm")
            if queued:
                d.text((x + PW // 2, 150 + PH + 170), f"+ {len(queued)} waiting for a person", font=mid, fill=QUEUE_C, anchor="mm")
        d.text((W // 2, H - 60), f"frame {f + 1} of {n}  ·  same auto-brightened clip on both sides",
               font=small, fill=(170, 170, 170), anchor="mm")
        img.save(os.path.join(tmp, f"{f:04d}.png"))
        if f == STILL:
            img.save("report/figures/split_s001_night_f38.jpg", quality=88)
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    subprocess.run([ff, "-loglevel", "error", "-y", "-framerate", "5", "-i", os.path.join(tmp, "%04d.png"),
                    "-c:v", "libx264", "-threads", "9",  # = fishcount.video.X264_THREADS (cache keys)
                        "-pix_fmt", "yuv420p", "-crf", "18", OUT], check=True)
    for p in glob.glob(os.path.join(tmp, "*.png")):
        os.remove(p)
    os.rmdir(tmp)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
