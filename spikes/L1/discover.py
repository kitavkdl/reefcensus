"""L1 discovery spike: SAM 3.1 only finds what you name ('animal' -> 0 on IMAS), so Spark looks first and names
everything the user did NOT ask about, offering several plain nouns per thing; SAM tries them in order until one tracks.
usage: python3 discover.py <clip.mp4> <asked-for target, e.g. fish> [--offline]
Writes out/<clip>__discover.json (Spark reply, per-word SAM summaries)."""
import json, os, sys
sys.path.insert(0, os.path.expanduser("~/meta-fish"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fishcount import api, video
from run import summarise

PROMPT = """You are helping a marine ecologist review underwater survey video. They asked only to count "{target}".
The image is a contact sheet of {n} frames from one clip. Look for every OTHER kind of living thing in the clip that the request did not ask about (including small, partly hidden, or unusual ones).
A segmentation model will search the video for each thing, but it only understands plain everyday English nouns (like "shell", "shrimp", "crab", "jellyfish", "worm", "starfish"); it returns nothing for species names, colours, or vague words like "animal" or "creature".
Return ONLY JSON:
{{"others":[{{"what":"your best identification","why_notable":"<=12 words","search_words":["most likely plain noun","second option","third option"],"frames":[ints]}}]}}
List at most 4 things, most notable first. If nothing else is there, return {{"others":[]}}."""


def main(clip, target, offline=False, max_things=3, max_words=2):
    n = video.info(clip)["n_frames"]
    idx = sorted({int(i * (n - 1) / 5) for i in range(6)})
    fr = video.frames(clip, idx)
    sheet = video.grid([video.label(fr[i], f"frame {i}") for i in idx], 3, 640)
    reply = api.spark(PROMPT.format(target=target, n=len(idx)), [video.jpg(sheet, q=80)], offline=offline)
    spark = api.parse_json(reply)
    print("Spark:", json.dumps(spark, ensure_ascii=False, indent=1))
    res = {"target": target, "spark": spark, "sam": {}}
    for word in [target]:                    # control: what the user asked for
        res["sam"][word] = summarise(api.sam_video(clip, word, n, offline=offline), n)
    for thing in spark.get("others", [])[:max_things]:
        for word in thing["search_words"][:max_words]:
            s = summarise(api.sam_video(clip, word, n, offline=offline), n)
            res["sam"][word] = s
            if s["frames_with"]:
                break
    for w, s in res["sam"].items():
        print(f"  {w!r:>14}: frames {s['frames_with']}/{n}, max/frame {s['max_per_frame']}, ids {s['ids']}  "
              + "".join(str(min(c, 9)) for c in s["per_frame"]))
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(clip))), "out",
                       os.path.splitext(os.path.basename(clip))[0] + "__discover.json")
    json.dump(res, open(out, "w"), ensure_ascii=False, indent=1)
    print(f"ledger total ${api.spent():.3f} (cap ${float(os.environ['FISH_BUDGET']):.3f})")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], offline="--offline" in sys.argv)
