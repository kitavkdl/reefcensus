"""Rebuild report/figures/compare_s001_night.png on the like-for-like baseline (fixed words on the SAME brightened
clip, report/paper/data/fixed_vocab_brightened/). The right panel (pipeline, frame 2 with its 4 nautilus boxes) is
kept from the 4749de2 still; the left panel, headline, texts and fair note are redrawn.

  python3 report/scripts/compare_s001_night.py
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT); os.chdir(ROOT)
from fishcount import video, tracks  # noqa: E402
import cv2, numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

OUT = "report/figures/compare_s001_night.png"
OLD_REV = "4749de2:report/figures/compare_s001_night.png"   # the first still; its right panel is reused
BG = (14, 20, 30)
F = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FB = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
font = lambda p, s: ImageFont.truetype(p, s)

import io, subprocess  # noqa: E402
old = Image.open(io.BytesIO(subprocess.run(["git", "show", OLD_REV], capture_output=True, check=True).stdout)).convert("RGB")
img = Image.new("RGB", old.size, BG)
img.paste(old.crop((975, 150, 1891, 741)), (975, 150))          # right panel as it was

# left panel: same brightened clip, the frame where 'shell' has its box, box drawn like the pipeline's
dets = tracks.parse_boxes(open("report/paper/data/fixed_vocab_brightened/s001__shell.txt").read())
f = 55 if 55 in dets else sorted(dets)[len(dets) // 2]
fr = video.frames("runs/mg2_s001/clip.mp4", [f])[f].copy()
for d in dets[f]:
    x0, y0, x1, y1 = (int(v) for v in d["box"])
    cv2.rectangle(fr, (x0, y0), (x1, y1), (255, 150, 60), 5)     # BGR blue-ish, the left panel's colour
g = fr.max(axis=2) > 24                                         # the clip is pillar/letterboxed: crop to the picture
ys, xs = np.where(g.any(axis=1))[0], np.where(g.any(axis=0))[0]
x0c, x1c, y0c, y1c = xs[0] + 4, xs[-1] - 4, ys[0] + 4, ys[-1] - 4
h_need = int((x1c - x0c) * 510 / 906)                           # same aspect as the panel; keep the lower part (animals)
y0c = max(y0c, y1c - h_need)
panel = cv2.resize(fr[y0c:y1c, x0c:x1c], (906, 510), interpolation=cv2.INTER_AREA)[:, :, ::-1]
d = ImageDraw.Draw(img)
d.rectangle((30, 150, 945, 740), fill=(120, 150, 190))
img.paste(Image.fromarray(panel), (35, 226))
d.text((50, 160), "FIXED WORD LIST (no Spark)", font=font(FB, 46), fill=(10, 10, 10))
lab = f"frame {f} of 60 (same auto-brightened clip)"
w = d.textlength(lab, font=font(FB, 28))
d.rectangle((35, 226, 35 + w + 12, 262), fill=(120, 150, 190))
d.text((41, 228), lab, font=font(FB, 28), fill=(10, 10, 10))

d.text((30, 25), "Night, behind a mesh trap: words reach 1 of 4, boxes reach 4", font=font(FB, 52), fill=(245, 245, 245))
d.text((30, 92), "s001: baited camera, 300-400 m (12 s clip, 60 frames)", font=font(F, 28), fill=(170, 175, 185))

def para(x, y, text, size, width, fill, bold=False):
    fnt = font(FB if bold else F, size)
    line, lines = "", []
    for wd in text.split():
        t = (line + " " + wd).strip()
        if d.textlength(t, font=fnt) > width:
            lines.append(line); line = wd
        else:
            line = t
    lines.append(line)
    for i, ln in enumerate(lines):
        d.text((x, y + i * int(size * 1.25)), ln, font=fnt, fill=fill)

para(35, 765, "'shell': 1 of 4 nautiluses, 9 of 60 frames", 38, 900, (255, 120, 110), bold=True)
para(35, 822, "16 fixed words plus 'nautilus' on the same brightened frames: 16 track nothing; 'shell' follows "
     "one nautilus for frames 51-59.", 26, 900, (235, 235, 235))
para(980, 765, "4 nautiluses, no word needed", 38, 900, (255, 150, 60), bold=True)
para(980, 822, "Spark's own word tries: 7 of 8 found nothing ('shell': 9 frames). So Spark looked at 8 moving spots "
     "and said 'nautilus'; SAM followed each from a box, 50-60 of 60 frames. A person sees 4 or more.",
     26, 900, (235, 235, 235))
para(30, 1005, "Like for like: both sides use the same auto-brightened clip (gamma 0.5 + CLAHE). Video: Barord et al. "
     "2014, PLOS ONE (CC BY). Sources: report/paper/data/fixed_vocab_brightened/, runs/mg2_s001/status.json + result.json.",
     21, 1860, (150, 155, 165))
img.save(OUT)
print(OUT, img.size, "left frame", f)
