"""Does the crowd check (pipeline.crowd_check) mark the crowded peak frames, and only those?
  python3 report/paper/scripts/crowd_check_eval.py [--tag cr6] [--offline]
Rule (pipeline.CROWD_MIN_EXTRA, CROWD_RATIO), fixed before any reply was seen: a row is a lower bound when Spark's
unprimed count is >= MaxN + 3 and >= 1.5 x MaxN. The same rule applied to a person's count defines "crowded".
Set A: the 17 peak frames two people counted (Table 3e; report/paper/data/countsheet/). Development data: the frames
come from discovery runs on clips used in development or already scored. MaxN = the run's boxes of that group in
that frame. Crowded = both people's counts pass the rule.
Set B: the peak frame of the "fish" row of each of the 24 held-out luderick runs; the hand count of the whole video
(report/paper/data/heldout/recount/) is an upper bound for that frame, so a mark is a false alarm when the hand count
does not pass the rule. Writes report/paper/data/crowd_check/<tag>.json. About 41 Spark calls (~$0.2) when uncached."""
import argparse, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT)
from fishcount import video, pipeline  # noqa: E402

D = os.path.join(ROOT, "report/paper/data")


def run_dir(tag, clip):
    for p in (f"runs/{clip}_{tag}", f"runs/{tag}_{clip}"):
        if os.path.exists(os.path.join(ROOT, p, "result.json")):
            return os.path.join(ROOT, p)
    raise FileNotFoundError(f"no {tag} run for {clip}")


def crowded(person, maxn):
    return person >= maxn + pipeline.CROWD_MIN_EXTRA and person >= pipeline.CROWD_RATIO * maxn


def in_frame(res, f, group):
    lab = lambda t: res["auto_labels"].get(t, res["tracks"].get(t, {}).get("label"))
    return sum(1 for k in res["frames"].get(str(f), []) if lab(k["track"]) and pipeline.name_group(lab(k["track"])) == group)


def answers():
    a = open(os.path.join(D, "countsheet/answers_jiyul.md")).read()
    first = [int(x) for x in re.search(r"^(\d+(?:, \d+){16})$", a, re.M).group(1).split(", ")]
    second = {int(m.group(1)): int(m.group(2)) for m in
              re.finditer(r"^\| (\d+) \| (\d+)\b", open(os.path.join(D, "countsheet/answers_friend.md")).read(), re.M)}
    return first, [second[q] for q in range(1, 18)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="cr6")
    ap.add_argument("--offline", action="store_true")
    a = ap.parse_args()
    key = json.load(open(os.path.join(D, "countsheet/key.json")))
    p1, p2 = answers()
    rows_a = []
    for e, h1, h2 in zip(key, p1, p2):
        rd = run_dir(a.tag, e["clip"])
        res = json.load(open(os.path.join(rd, "result.json")))
        n = in_frame(res, e["frame"], e["group"])
        img = video.frames(os.path.join(rd, "clip.mp4"), [e["frame"]])[e["frame"]]
        j = pipeline.crowd_count(img, pipeline.CROWD_WORDS[e["group"]], a.offline)
        lb = crowded(j["total"], n) if n else False
        truth = crowded(h1, n) and crowded(h2, n) if n else False
        rows_a.append(dict(clip=e["clip"], group=e["group"], frame=e["frame"], pipeline=n, first=h1, second=h2,
                           spark=j["total"], estimated=j.get("estimated"), reason=j.get("reason"), marked=lb, crowded=truth))
    sc = json.load(open(os.path.join(D, "heldout/recount/scores.json")))
    rows_b = []
    for cid, hand in sc["hand"].items():
        rd = run_dir(a.tag, f"fish_{cid[5:]}") if not os.path.exists(os.path.join(ROOT, "runs", f"{a.tag}_{cid}")) else os.path.join(ROOT, "runs", f"{a.tag}_{cid}")
        res = json.load(open(os.path.join(rd, "result.json")))
        rows = [r for r in pipeline.crowd_rows(res["metrics"], res["video"]["fps"]) if r[0] == "fish"]
        if not rows:
            continue
        _, _, maxn, f, what = rows[0]
        img = video.frames(os.path.join(rd, "clip.mp4"), [f])[f]
        j = pipeline.crowd_count(img, what, a.offline)
        rows_b.append(dict(clip=cid, frame=f, pipeline=maxn, hand=hand, spark=j["total"], reason=j.get("reason"),
                           marked=crowded(j["total"], maxn), crowded=crowded(hand, maxn)))
    print(f"{'Set A frame':24s} pipe  1st  2nd spark  marked crowded")
    for r in rows_a:
        print(f"{r['clip'] + ' ' + r['group']:24s} {r['pipeline']:4d} {r['first']:4d} {r['second']:4d} {r['spark']:5d}  "
              f"{'yes' if r['marked'] else '-':6s} {'yes' if r['crowded'] else '-'}")
    tp = sum(r["marked"] and r["crowded"] for r in rows_a); fn = sum(r["crowded"] and not r["marked"] for r in rows_a)
    fp = sum(r["marked"] and not r["crowded"] for r in rows_a)
    print(f"Set A: crowded {tp + fn}, marked {tp} of them; marked but not crowded {fp} of {len(rows_a) - tp - fn}")
    fb = [r for r in rows_b if r["marked"]]
    print(f"Set B (24 held-out luderick): crowded by hand count {sum(r['crowded'] for r in rows_b)}; marked {len(fb)}"
          + "".join(f"; {r['clip']} MaxN {r['pipeline']} hand {r['hand']} spark {r['spark']}" for r in fb))
    os.makedirs(os.path.join(D, "crowd_check"), exist_ok=True)
    json.dump(dict(tag=a.tag, rule=dict(min_extra=pipeline.CROWD_MIN_EXTRA, ratio=pipeline.CROWD_RATIO),
                   set_a=rows_a, set_b=rows_b), open(os.path.join(D, f"crowd_check/{a.tag}.json"), "w"), indent=1)


main()
