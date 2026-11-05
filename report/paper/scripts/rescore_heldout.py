"""Held-out luderick evaluation (protocol: report/paper/heldout_protocol.md). Offline, no model calls.
  python3 report/paper/scripts/rescore_heldout.py [--tag held1] [--abl heldabl] [--replay] [--bundle]
--tag: the audited runs (<tag>_<clip>; held1 = the protocol run, cr7 = the final code); --abl: the merge-only runs.
--replay makes the merge-only replays runs/<abl>_<clip> from cache with the current code (needed once for the length rule);
--bundle copies SAM replies and run results into report/paper/data/heldout. Without live files the bundle is read."""
import json, os, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT)
from fishcount import api, tracks, pipeline  # noqa: E402

SMOKE = os.path.expanduser("~/meta-smoke")
B = os.path.join(ROOT, "report/paper/data/heldout")
RUNS = os.path.join(ROOT, "runs")
K = 4   # fixed on the development clips
_arg = lambda k, d: sys.argv[sys.argv.index(k) + 1] if k in sys.argv else d
AUD, ABL = _arg("--tag", "held1"), _arg("--abl", "heldabl")


def match(pred, gt, thr=0.3):
    tp = fn = fp = 0; mg = mp = 0
    for i, gb in gt.items():
        pb = pred.get(i, []); used = set()
        for a in gb:
            best = max(((tracks.iou(a, b), j) for j, b in enumerate(pb) if j not in used), default=(0, None))
            if best[0] >= thr: tp += 1; used.add(best[1])
            else: fn += 1
        fp += len(pb) - len(used); mg, mp = max(mg, len(gb)), max(mp, len(pb))
    return tp, fn, fp, mg, mp


def boxes(res, keep):
    lab = lambda t: res["auto_labels"].get(t, res["tracks"].get(t, {}).get("label"))
    return {int(f): [k["box"] for k in ks if lab(k["track"]) and keep(k["track"])] for f, ks in res["frames"].items()}


def main():
    man = json.load(open(f"{B}/manifest.json"))
    live = os.path.exists(f"{SMOKE}/clips/manifest_heldout.json")
    tot = {}; rng = []
    order = ["SAM alone", f"min length {K}", "audited", "queue rejected"]
    print(f"{'clip':18s} " + " | ".join(f"{n:>22s}" for n in order) + "  queued")
    for cid, c in man["clips"].items():
        gt = {int(k): [(x, y, x + w, y + h) for x, y, w, h, *_ in v]
              for k, v in json.load(open(f"{B}/gt/{cid}.json"))["frames"].items()}
        clip = f"{SMOKE}/{c['path']}"
        if live:
            txt = api.sam_video(clip, "fish", c["n_frames"], offline=True)
            if "--replay" in sys.argv and not os.path.exists(f"{RUNS}/{ABL}_{cid}/result.json"):
                pipeline.run_pipeline(clip, f"{ABL}_{cid}", offline=True, do_scout=False, do_audit=False, prompts=["fish"])
            ra = json.load(open(f"{RUNS}/{ABL}_{cid}/result.json")); rv = json.load(open(f"{RUNS}/{AUD}_{cid}/result.json"))
            if "--bundle" in sys.argv:
                os.makedirs(f"{B}/sam_fish", exist_ok=True); open(f"{B}/sam_fish/{cid}.txt", "w").write(txt)
                for tag in (ABL, AUD):
                    d = f"{B}/runs/{tag}_{cid}"; os.makedirs(d, exist_ok=True)
                    shutil.copy(f"{RUNS}/{tag}_{cid}/result.json", d)
        else:
            txt = open(f"{B}/sam_fish/{cid}.txt").read()
            ra = json.load(open(f"{B}/runs/{ABL}_{cid}/result.json")); rv = json.load(open(f"{B}/runs/{AUD}_{cid}/result.json"))
        q = {t for t, v in rv["verdicts"].items() if pipeline.needs_review(v)}
        sysm = {"SAM alone": {f: [d["box"] for d in ds] for f, ds in tracks.parse_boxes(txt).items()},
                f"min length {K}": boxes(ra, lambda t: ra["tracks"][t]["n"] >= K),
                "audited": boxes(rv, lambda t: True), "queue rejected": boxes(rv, lambda t: t not in q)}
        cells = []; mx = {}
        for n in order:
            tp, fn, fp, mg, mp = match(sysm[n], gt); mx[n] = mp
            T = tot.setdefault(n, [0, 0, 0, 0, 0, 0]); T[0] += tp; T[1] += fn; T[2] += fp
            T[3] += mg == mp; T[4] += abs(mg - mp) <= 1; T[5] += abs(mg - mp)
            cells.append(f"{tp / max(1, tp + fn):4.0%} {tp / max(1, tp + fp):4.0%} {mg}->{mp}")
        print(f"{cid:18s} " + " | ".join(f"{x:>22s}" for x in cells) + f"  {len(q)}/{len(rv['verdicts'])}")
        # range high end: every queued track accepted, also those Spark left unlabelled (the review screen's "Yes", §4.7)
        lab = lambda t: rv["auto_labels"].get(t, rv["tracks"].get(t, {}).get("label"))
        acc = {int(f): [k["box"] for k in ks if lab(k["track"]) or k["track"] in q] for f, ks in rv["frames"].items()}
        rng.append((cid, mg, mx["queue rejected"], max(mx["audited"], match(acc, gt)[4])))
    n = len(man["clips"])
    for k in order:
        tp, fn, fp, ex, w1, se = tot[k]
        print(f"{k:16s} recall {tp / (tp + fn):.1%}  precision {tp / (tp + fp):.1%}  exact {ex}/{n}  within1 {w1}/{n}  sum|err| {se}")
    # the review screen's MaxN range: low = queue rejected (unreviewed queued tracks left out), high = every queued track accepted
    inside = [c for c, h, lo, hi in rng if lo <= h <= hi]
    print(f"\nMaxN range [queue rejected, queue accepted] holds the human MaxN on {len(inside)}/{n} clips; "
          f"single value on {sum(lo == hi for _, _, lo, hi in rng)}/{n}; mean width {sum(hi - lo for *_, lo, hi in rng) / n:.2f}")
    for c, h, lo, hi in rng:
        if lo != hi or not lo <= h <= hi:
            print(f"  {c:18s} human {h}  range {lo}-{hi}{'' if lo <= h <= hi else '  OUTSIDE'}")


main()
