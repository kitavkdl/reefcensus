"""Run SAM 3.1 on a spike clip through fishcount.api (cache + ledger) and summarise the tracks.
usage: python3 run.py <clip.mp4> <prompt | @box_prompt_file> [--offline]
Session cap: FISH_BUDGET is set to (ledger at session start + $0.30) unless already set.
Writes <spike>/out/<clip>__<prompt>.txt (raw SAM text) and prints per-frame counts and track lengths."""
import os, sys
from collections import Counter
sys.path.insert(0, os.path.expanduser("~/meta-fish"))
os.environ.setdefault("FISH_BUDGET", "0.679")    # 0.379 spent before 11/1 afternoon session + 0.30
from fishcount import api, tracks, video


def summarise(text, n):
    dets = tracks.parse_boxes(text)
    per = [len(dets.get(f, [])) for f in range(n)]
    life = Counter(d["id"] for ds in dets.values() for d in ds)
    sizes = [(d["box"][2] - d["box"][0]) * (d["box"][3] - d["box"][1]) for ds in dets.values() for d in ds]
    return dict(frames_with=sum(1 for c in per if c), max_per_frame=max(per), mean_per_frame=round(sum(per) / n, 2),
                ids=len(life), median_track_len=sorted(life.values())[len(life) // 2] if life else 0,
                median_box_area=sorted(sizes)[len(sizes) // 2] if sizes else 0, per_frame=per)


if __name__ == "__main__":
    clip, prompt = sys.argv[1], sys.argv[2]
    name = prompt
    if prompt.startswith("@"):            # box/point prompt read from a file; output named after the file
        name = os.path.splitext(os.path.basename(prompt[1:]))[0]
        prompt = open(prompt[1:]).read().strip()
    n = video.info(clip)["n_frames"]
    text = api.sam_video(clip, prompt, n, offline="--offline" in sys.argv)
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(clip))), "out",
                       f"{os.path.splitext(os.path.basename(clip))[0]}__{name.replace(' ', '_')}.txt")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, "w").write(text)
    s = summarise(text, n)
    print(f"{os.path.basename(clip)} {name!r}: n={n}", {k: v for k, v in s.items() if k != "per_frame"})
    print("  per frame:", "".join(str(min(c, 9)) for c in s["per_frame"]))
    print(f"  ledger total ${api.spent():.3f} (cap ${float(os.environ['FISH_BUDGET']):.3f})")
