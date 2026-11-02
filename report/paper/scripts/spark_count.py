"""Spark-alone counting baseline (second review, 6c): no segmenter, Muse Spark counts the fish in each annotated
luderick frame; MaxN = the largest count over a clip's annotated frames. Protocol: report/paper/spark_count_protocol.md.
  FISH_BUDGET=<ledger+3> python3 report/paper/scripts/spark_count.py [--only dev|held] [--probe]
  python3 report/paper/scripts/spark_count.py --offline        (cache only)
--probe makes one call (first annotated frame of the first development clip) and prints its tokens and cost."""
import json, os, sys
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
from fishcount import api, video  # noqa: E402

SMOKE = os.path.expanduser("~/meta-smoke")
OUT = os.path.join(ROOT, "report/paper/data/spark_count")
SETS = {"dev": "manifest_fish.json", "held": "manifest_heldout.json"}
PROMPT = ("This is one frame from an underwater video of a seagrass bed. Count every individual fish you can see in "
          "the frame, including fish that are partly visible, cut by the frame edge, or faint. Count each fish once. "
          "Reply with JSON only, no other text: {\"count\": <integer>}")


def _check(text):
    c = api.parse_json(text)
    if not (isinstance(c, dict) and isinstance(c.get("count"), int) and c["count"] >= 0):
        raise ValueError("expected {\"count\": int}")


def count(clip, idx, img, offline):
    # An empty reply (all 2,000 tokens spent on reasoning, seen once on the held-out run) is treated like an
    # unreadable one, as the protocol says: one more call, then the frame is reported missing.
    for attempt in range(2):
        try:
            t = api.spark(PROMPT, [video.jpg(img, max_w=1280)], max_tokens=2000, effort="low", offline=offline, check=_check)
            return api.parse_json(t)["count"]
        except RuntimeError as e:
            if "empty text" not in str(e) or attempt:
                print(f"  missing {clip} frame {idx}: {e}"[:200])
                return None
            print(f"  empty reply {clip} frame {idx}, one more call")
        except (ValueError, FileNotFoundError) as e:
            print(f"  missing {clip} frame {idx}: {e}"[:200])
            return None


def main():
    offline = "--offline" in sys.argv
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
    os.makedirs(OUT, exist_ok=True)
    if "--probe" in sys.argv:
        man = json.load(open(f"{SMOKE}/clips/{SETS['dev']}"))
        cid, c = next(iter(man["clips"].items()))
        gt = json.load(open(f"{SMOKE}/{c['gt']}"))["frames"]
        f0 = min(int(k) for k in gt)
        before = api.spent()
        n = count(cid, f0, video.frames(f"{SMOKE}/{c['path']}", [f0])[f0], offline=False)
        print(f"probe {cid} frame {f0}: count {n}, human boxes {len(gt[str(f0)])}, cost ${api.spent() - before:.4f}")
        print(open(api.LEDGER).read().splitlines()[-1] if hasattr(api, "LEDGER") else "")
        return
    summary = {}
    for name, mf in SETS.items():
        if only and name != only:
            continue
        man = json.load(open(f"{SMOKE}/clips/{mf}"))
        rows = []
        for cid, c in man["clips"].items():
            gt = {int(k): len(v) for k, v in json.load(open(f"{SMOKE}/{c['gt']}"))["frames"].items()}
            imgs = video.frames(f"{SMOKE}/{c['path']}", list(gt))
            with ThreadPoolExecutor(6) as ex:      # parallel calls only; each frame is still one independent call
                per = dict(zip(sorted(gt), ex.map(lambda i: count(cid, i, imgs[i], offline), sorted(gt))))
            got = [v for v in per.values() if v is not None]
            r = dict(clip=cid, frames=len(gt), missing=len(gt) - len(got), human_maxn=max(gt.values()),
                     spark_maxn=max(got) if got else None,
                     frame_abs_err=[abs(per[i] - gt[i]) for i in per if per[i] is not None],
                     per_frame={str(i): [gt[i], per[i]] for i in per})
            rows.append(r)
            print(f"{name} {cid:20s} frames {len(gt):3d}  MaxN human {r['human_maxn']}  Spark {r['spark_maxn']}"
                  f"  missing {r['missing']}")
        ok = [r for r in rows if r["spark_maxn"] is not None]
        errs = [abs(r["spark_maxn"] - r["human_maxn"]) for r in ok]
        fe = [e for r in rows for e in r["frame_abs_err"]]
        s = dict(clips=len(rows), scored=len(ok), exact=sum(e == 0 for e in errs), within1=sum(e <= 1 for e in errs),
                 sum_abs_err=sum(errs), over=sum(r["spark_maxn"] > r["human_maxn"] for r in ok),
                 under=sum(r["spark_maxn"] < r["human_maxn"] for r in ok),
                 frame_mae=round(sum(fe) / len(fe), 3) if fe else None, frames=len(fe))
        summary[name] = s
        json.dump(rows, open(os.path.join(OUT, f"{name}.json"), "w"), indent=1)
        print(f"{name}: MaxN exact {s['exact']}/{s['scored']}, within ±1 {s['within1']}/{s['scored']}, "
              f"Σ|err| {s['sum_abs_err']} (over {s['over']}, under {s['under']}), per-frame MAE {s['frame_mae']} "
              f"over {s['frames']} frames")
    if summary:
        json.dump(summary, open(os.path.join(OUT, "summary.json" if not only else f"summary_{only}.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
