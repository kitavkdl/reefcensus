"""Re-score saved luderick runs for the paper (Tables 1, 4, 5 and the queue analysis). Offline, no model calls.
  python3 report/paper/scripts/rescore.py
Rows:
  SAM alone            raw SAM 3.1 "fish" track (cached reply)
  merge only           runs/ablnoaudit_*: full pipeline with every audit disabled, replayed from cache
  merge + min length k merge only, then drop tracks shorter than k frames (no model call; the 11/2 review's baseline)
  SAM conf >= c        raw SAM boxes above a confidence cut-off (no model call)
  V1..V6               runs/{eval,eval3,eval4,eval5,eval6,eval7}_*  (V5 = v16 code, V6 = final: A4 asks the requested category)
  V5 queue accepted    = V5 as reported (a queued track keeps its "(unidentified)" label and is counted)
  V5 queue rejected    = V5 with every queued track removed (a reviewer who rejects the whole queue)
"""
import json, math, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
from fishcount import api, tracks, pipeline  # noqa: E402

SMOKE = os.path.expanduser("~/meta-smoke")
RUNS = os.path.join(ROOT, "runs")
VERS = [("V1", "eval"), ("V2", "eval3"), ("V3", "eval4"), ("V4", "eval5"), ("V5", "eval6"), ("V6", "eval7")]
FINAL = "cr7"     # the final code (master), re-run 11/4: Table 1's audited and queue-rejected columns


def match(pred, gt, thr):
    """pred: {frame: [(box, track)]}, gt: {frame: [box]}. Returns tp, fn, fp, MaxN gt, MaxN pred, per-track matched."""
    tp = fn = fp = 0
    mg = mp = 0
    hit = {}
    for i, gb in gt.items():
        pb = pred.get(i, [])
        used = set()
        for a in gb:
            best = max(((tracks.iou(a, b), j) for j, (b, _) in enumerate(pb) if j not in used), default=(0, None))
            if best[0] >= thr:
                tp += 1; used.add(best[1])
            else:
                fn += 1
        for j, (_, t) in enumerate(pb):
            h = hit.setdefault(t, [0, 0]); h[1] += 1; h[0] += j in used
        fp += len(pb) - len(used)
        mg, mp = max(mg, len(gb)), max(mp, len(pb))
    return tp, fn, fp, mg, mp, hit


def match_optimal(pred, gt, thr):
    """Like match() but with a maximum-cardinality bipartite matching per frame (augmenting paths) instead of greedy
    in human-box order. Returns tp, fn, fp."""
    tp = fn = fp = 0
    for i, gb in gt.items():
        pb = pred.get(i, [])
        adj = [[j for j, (b, _) in enumerate(pb) if tracks.iou(a, b) >= thr] for a in gb]
        owner = {}

        def aug(g, seen):
            for j in adj[g]:
                if j not in seen:
                    seen.add(j)
                    if j not in owner or aug(owner[j], seen):
                        owner[j] = g
                        return True
            return False
        m = sum(aug(g, set()) for g in range(len(gb)))
        tp += m; fn += len(gb) - m; fp += len(pb) - m
    return tp, fn, fp


def boxes(res, keep):
    lab = lambda t: res["auto_labels"].get(t, res["tracks"].get(t, {}).get("label"))
    return {int(f): [(k["box"], k["track"]) for k in ks if lab(k["track"]) and keep(k["track"])]
            for f, ks in res["frames"].items()}


def wilson(k, n, z=1.96):
    p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


BUNDLE = os.path.join(ROOT, "report/paper/data/luderick")


def load():
    """Live files (~/meta-smoke clips + runs/) when present, else the bundle in report/paper/data/luderick, which
    holds exactly what scoring needs: human boxes (Ditria et al. 2021, CC BY 4.0), SAM's cached "fish" reply per clip
    and each scored run's result.json. `--bundle` refreshes the bundle from the live files."""
    live = os.path.exists(f"{SMOKE}/clips/manifest_fish.json")
    man = json.load(open(f"{SMOKE}/clips/manifest_fish.json" if live else f"{BUNDLE}/manifest.json"))
    clips = []
    for cid, c in man["clips"].items():
        gtp = f"{SMOKE}/{c['gt']}" if live else f"{BUNDLE}/gt/{cid}.json"
        raw = json.load(open(gtp))
        gt = {int(k): [(x, y, x + w, y + h) for x, y, w, h, *_ in v] for k, v in raw["frames"].items()}
        if live:
            txt = api.sam_video(f"{SMOKE}/{c['path']}", "fish", c["n_frames"], offline=True)
        else:
            txt = open(f"{BUNDLE}/sam_fish/{cid}.txt").read()
        runs = {}
        for tag in ["ablnoaudit"] + [t for _, t in VERS] + [FINAL]:
            p = os.path.join(RUNS if live else f"{BUNDLE}/runs", f"{tag}_{cid}", "result.json")
            if os.path.exists(p):
                runs[tag] = json.load(open(p))
        clips.append(dict(cid=cid, gt=gt, det=tracks.parse_boxes(txt), runs=runs, raw_gt=raw, txt=txt, man=c))
    return clips, man, live


def bundle(clips, man):
    import shutil
    os.makedirs(f"{BUNDLE}/gt", exist_ok=True); os.makedirs(f"{BUNDLE}/sam_fish", exist_ok=True)
    json.dump({"note": "luderick clips: Ditria et al. 2021, PANGAEA doi:10.1594/PANGAEA.926930, CC BY 4.0",
               "clips": {k: {kk: v[kk] for kk in ("n_frames", "width", "height", "src")} for k, v in man["clips"].items()}},
              open(f"{BUNDLE}/manifest.json", "w"), indent=1)
    for c in clips:
        json.dump(c["raw_gt"], open(f"{BUNDLE}/gt/{c['cid']}.json", "w"))
        open(f"{BUNDLE}/sam_fish/{c['cid']}.txt", "w").write(c["txt"])
        for tag in c["runs"]:
            d = f"{BUNDLE}/runs/{tag}_{c['cid']}"; os.makedirs(d, exist_ok=True)
            shutil.copy(os.path.join(RUNS, f"{tag}_{c['cid']}", "result.json"), d)
    print("bundle written to", BUNDLE)


def systems(c):
    """name -> {frame: [(box, track)]} for one clip."""
    out = {"SAM alone": {f: [(d["box"], "sam") for d in ds] for f, ds in c["det"].items()}}
    for cut in (0.5, 0.6, 0.7, 0.8):
        out[f"SAM conf >= {cut}"] = {f: [(d["box"], "sam") for d in ds if (d["conf"] or 0) >= cut]
                                    for f, ds in c["det"].items()}
    na = c["runs"]["ablnoaudit"]
    out["merge only"] = boxes(na, lambda t: True)
    for k in range(2, 9):
        out[f"merge + min length {k}"] = boxes(na, lambda t, k=k: na["tracks"][t]["n"] >= k)
    for v, tag in VERS:
        r = c["runs"][tag]
        out[v] = boxes(r, lambda t: True)
    r = c["runs"]["eval6"]
    q = {t for t, v in r["verdicts"].items() if pipeline.needs_review(v)}
    out["V5 queue rejected"] = boxes(r, lambda t: t not in q)
    if FINAL in c["runs"]:
        r = c["runs"][FINAL]
        qf = {t for t, v in r["verdicts"].items() if pipeline.needs_review(v)}
        out["final"] = boxes(r, lambda t: True)
        out["final queue rejected"] = boxes(r, lambda t: t not in qf)
    return out


def main():
    clips, man, live = load()
    if "--bundle" in sys.argv:
        return bundle(clips, man) if live else print("--bundle needs the live files")
    print("source:", "live files" if live else "bundle report/paper/data/luderick")
    names = list(systems(clips[0]).keys())
    for thr in (0.3, 0.5, 0.7):
        print(f"\n== IoU >= {thr} ==")
        print(f"{'system':24s} recall  precision  exact  |err|<=1  sum|err|  per-clip gt->pred")
        for n in names:
            T = [0, 0, 0]; ex = w1 = se = 0; per = []
            for c in clips:
                tp, fn, fp, mg, mp, _ = match(systems(c)[n], c["gt"], thr)
                T[0] += tp; T[1] += fn; T[2] += fp
                ex += mg == mp; w1 += abs(mg - mp) <= 1; se += abs(mg - mp); per.append(f"{mg}->{mp}")
            print(f"{n:24s} {T[0] / (T[0] + T[1]):6.1%}  {T[0] / max(1, T[0] + T[2]):8.1%}   {ex}/6     {w1}/6      {se}   "
                  + " ".join(per) + f"   (tp {T[0]} fn {T[1]} fp {T[2]})")
    print("\n== greedy (human-box order) vs maximum bipartite matching: recall / precision ==")
    for thr in (0.3, 0.5, 0.7):
        for n in ("SAM alone", "merge + min length 4", "V5", "V6", "V5 queue rejected"):
            g = [0, 0, 0]; o = [0, 0, 0]
            for c in clips:
                s = systems(c)[n]
                for k, v in enumerate(match(s, c["gt"], thr)[:3]): g[k] += v
                for k, v in enumerate(match_optimal(s, c["gt"], thr)): o[k] += v
            print(f"IoU {thr}  {n:22s} greedy {g[0] / (g[0] + g[1]):.1%} / {g[0] / max(1, g[0] + g[2]):.1%}   "
                  f"optimal {o[0] / (o[0] + o[1]):.1%} / {o[0] / max(1, o[0] + o[2]):.1%}   (tp {g[0]} vs {o[0]})")
    print("\n== recall 95% Wilson intervals (IoU 0.3) ==")
    for n in ("SAM alone", "V1", "V5", "V5 queue rejected"):
        tp = fn = 0
        for c in clips:
            a, b, *_ = match(systems(c)[n], c["gt"], 0.3); tp += a; fn += b
        lo, hi = wilson(tp, tp + fn)
        print(f"{n:20s} {tp}/{tp + fn} = {tp / (tp + fn):.1%}  [{lo:.1%}, {hi:.1%}]")

    print("\n== recall, 95% percentile bootstrap over clips (10,000 resamples of the 6 clips, seed 0; IoU 0.3) ==")
    import random
    per = {n: [match(systems(c)[n], c["gt"], 0.3)[:2] for c in clips]
           for n in ("SAM alone", "merge + min length 4", "V5", "V5 queue rejected", "final", "final queue rejected") if n in systems(clips[0])}
    for n, pc in per.items():
        rng = random.Random(0)      # same resamples for every system
        vals = []
        for _ in range(10000):
            smp = [pc[rng.randrange(len(pc))] for _ in pc]
            tp = sum(a for a, _ in smp); fn = sum(b for _, b in smp)
            vals.append(tp / max(1, tp + fn))
        vals.sort()
        tp = sum(a for a, _ in pc); fn = sum(b for _, b in pc)
        print(f"{n:22s} {tp / (tp + fn):.1%}  [{vals[249]:.1%}, {vals[9749]:.1%}]")
    print("\n== minimum track length k chosen leave-one-clip-out (k in 2..8 minimising sum|MaxN err| on the other five,"
          " then max recall, then smallest k) ==")
    T = [0, 0, 0]; ex = se = 0; ks = []
    for i, c in enumerate(clips):
        def crit(k):
            e = r_tp = r_fn = 0
            for j, o in enumerate(clips):
                if j != i:
                    tp, fn, _, mg, mp, _ = match(systems(o)[f"merge + min length {k}"], o["gt"], 0.3)
                    e += abs(mg - mp); r_tp += tp; r_fn += fn
            return (e, -r_tp / max(1, r_tp + r_fn), k)
        k = min(range(2, 9), key=crit); ks.append(k)
        tp, fn, fp, mg, mp, _ = match(systems(c)[f"merge + min length {k}"], c["gt"], 0.3)
        T[0] += tp; T[1] += fn; T[2] += fp; ex += mg == mp; se += abs(mg - mp)
    print(f"k per held-out clip {ks}: recall {T[0] / (T[0] + T[1]):.1%}, precision {T[0] / max(1, T[0] + T[2]):.1%}, "
          f"exact {ex}/6, sum|err| {se}")
    if all(FINAL in c["runs"] for c in clips):
        print(f"\n== final code ({FINAL}) per clip, IoU 0.3: audited R / P / MaxN, queue rejected R / P / MaxN, queued ==")
        for c in clips:
            s = systems(c); r = c["runs"][FINAL]
            a = match(s["final"], c["gt"], 0.3); b = match(s["final queue rejected"], c["gt"], 0.3)
            nq = sum(1 for v in r["verdicts"].values() if pipeline.needs_review(v))
            f = lambda m: f"{m[0] / max(1, m[0] + m[1]):.0%} / {m[0] / max(1, m[0] + m[2]):.0%} / {m[3]}->{m[4]}"
            print(f"{c['cid']:20s} {f(a):22s} {f(b):22s} {nq} of {len(r['verdicts'])}")
    print("\n== per clip, V5 queue accepted vs rejected (IoU 0.3): recall ==")
    for c in clips:
        s = systems(c)
        a = match(s["V5"], c["gt"], 0.3); b = match(s["V5 queue rejected"], c["gt"], 0.3)
        print(f"{c['cid']:20s} accepted {a[0] / (a[0] + a[1]):6.1%}  rejected {b[0] / (b[0] + b[1]):6.1%}")
    print("\n== MaxN range on the review screen: low = V5 queue rejected (unreviewed queued tracks left out), high = V5 ==")
    k = 0
    for c in clips:
        s = systems(c); h = match(s["V5"], c["gt"], 0.3)[3]
        lo, hi = match(s["V5 queue rejected"], c["gt"], 0.3)[4], match(s["V5"], c["gt"], 0.3)[4]
        k += lo <= h <= hi
        print(f"{c['cid']:20s} human {h}  range {lo}-{hi}{'' if lo <= h <= hi else '  OUTSIDE'}")
    print(f"range holds the human MaxN on {k}/{len(clips)} clips")
    for qtag, qsys in (("eval6", "V5"), (FINAL, "final")):
      if not all(qtag in c["runs"] for c in clips):
        continue
      print(f"\n== queued tracks in {qsys} (IoU 0.3): boxes in annotated frames matched / total, verdict ==")
      for c in clips:
        r = c["runs"][qtag]
        _, _, _, _, _, hit = match(systems(c)[qsys], c["gt"], 0.3)
        for t, v in r["verdicts"].items():
            if pipeline.needs_review(v):
                h = hit.get(t, [0, 0])
                print(f"{c['cid']:20s} {t:7s} n={r['tracks'][t]['n']:3d}  matched {h[0]:3d}/{h[1]:3d}  "
                      f"is_target={v.get('is_target')} conf={v.get('confidence')} species={v.get('species')!r} "
                      f"label={r['auto_labels'].get(t)!r} shadow={bool(v.get('shadow'))}")
    print("\n== confident target with species 'unknown' (counted as '(unidentified)', not queued) ==")
    k = 0
    for c in clips:
        r = c["runs"]["eval6"]
        for t, v in r["verdicts"].items():
            if not pipeline.needs_review(v) and (r["auto_labels"].get(t) or "").endswith("(unidentified)"):
                k += 1; print(f"{c['cid']:20s} {t:7s} conf={v.get('confidence')} reason={v.get('reason')!r}")
    print(f"total {k}")
    print("\n== tracks the A1 audit removed in V5 vs tracks min length 4 removes (merge only) ==")
    for c in clips:
        r = c["runs"]["eval6"]; na = c["runs"]["ablnoaudit"]
        rej = sorted(t for t, l in r["auto_labels"].items() if l is None)
        short = sorted(t for t, d in na["tracks"].items() if d["n"] < 4)
        print(f"{c['cid']:20s} A1 removed {[(t, r['tracks'][t]['n']) for t in rej]}  short {[(t, na['tracks'][t]['n']) for t in short]}")


main()
