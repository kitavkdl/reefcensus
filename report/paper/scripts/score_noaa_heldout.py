"""NOAA held-out set (report/paper/noaa_heldout_protocol.md, Scoring 1-4): fish MaxN against the hand count, the MaxN
range (queue rejected .. queue accepted, as the review screen shows it), counted non-fish rows for the label-free
"is this an animal?" sheet, and cost / time per clip. No API calls.

    python3 report/paper/scripts/score_noaa_heldout.py
Writes report/paper/data/noaa_heldout/score.json and, when a counted non-fish row exists, crops_sheet.jpg (crop
numbers map to rows in the JSON, which the judge does not see). Reads runs/N<k>_eval, or, in a fresh clone, the
copies in report/paper/data/noaa_heldout/runs/N<k>.
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import score_discovery_heldout as S   # noqa: E402
from fishcount import pipeline   # noqa: E402
sys.path.insert(0, os.path.join(S.ROOT, "web"))
import cv2, numpy as np   # noqa: E402

OUT = os.path.join(S.ROOT, "report", "paper", "data", "noaa_heldout")
HAND = os.path.join(OUT, "handcount.md")


def hand_counts():
    out = {}
    for line in open(HAND):
        m = re.match(r"\|\s*(N\d)\s*\|\s*clip_\w\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|", line)
        if m:
            out[m.group(1)] = (int(m.group(2)), int(m.group(3)))
    return out


TAG = "eval"   # --tag crowd: the after-seeing re-run with the opt-in crowd tiles (runs/N<k>_crowd)


def run_dir(k):
    live = os.path.join(S.ROOT, "runs", f"{k}_{TAG}")
    return live if os.path.exists(os.path.join(live, "result.json")) else os.path.join(OUT, "runs", k if TAG == "eval" else f"{k}_{TAG}")


def fish_curve(metrics, fish_names):
    """Same-frame total over the fish labels (group_metrics' rule, min one label)."""
    names = [x for x in metrics if x in fish_names]
    if not names:
        return 0
    n = max(len(metrics[x]["curve"]) for x in names)
    return max(sum(metrics[x]["curve"][i] for x in names if i < len(metrics[x]["curve"])) for i in range(n))


def effective_from(rd):
    """web/server.effective() on a run folder (it reads runs/<id>; a fresh-clone copy is pointed at by RUNS)."""
    import server
    server.RUNS = os.path.dirname(rd)
    return server.effective(os.path.basename(rd))


def score(k, hand):
    rd = run_dir(k)
    r = json.load(open(os.path.join(rd, "result.json")))
    st = json.load(open(os.path.join(rd, "status.json")))
    e = effective_from(rd)
    v = r["video"]
    # range ends from effective(): maxn (queue accepted) and the metrics with every open queued track dropped
    open_q = {t for t, vd in r.get("verdicts", {}).items() if pipeline.needs_review(vd)}
    from fishcount import tracks
    labels = {t: l for t, l in r["auto_labels"].items()}
    frames = {int(f): ks for f, ks in r["frames"].items()}
    lo = tracks.metrics(frames, r["tracks"], v["n_frames"], v["fps"], {**labels, **{t: None for t in open_q}}) if open_q else r["metrics"]
    isgroup = lambda x: pipeline.name_group(x.split(" (")[0]) == "fish" or x.split(" (")[0] == "fish"
    group = {x for x in r["metrics"] if isgroup(x)}
    # range high end: every open queued track accepted under the name its "Yes" gives (fishcount/settle.py, §4.7)
    from fishcount import settle
    hi = tracks.metrics(frames, r["tracks"], v["n_frames"], v["fps"], {**labels, **{t: settle.accept_label(r, t) for t in open_q}}) if open_q else r["metrics"]
    fishy = {x for x in r["metrics"] if S.is_fish(x)}
    rows = []
    for lab, m in r["metrics"].items():
        rows.append(dict(label=lab, maxn=m["maxn"], maxn_confirmed=e["metrics"].get(lab, {}).get("maxn_confirmed"),
                         in_fish_group=lab in group, non_fish=not S.is_fish(lab)))
    sure, faint = hand
    out = dict(clip=k, hand_sure=sure, hand_faint=faint,
               fish_maxn=fish_curve(r["metrics"], group), fish_maxn_low=fish_curve(lo, group),
               fish_maxn_high=fish_curve(hi, {x for x in hi if isgroup(x)}),
               # every label the scorer's is_fish() calls a fish (adds names the word groups miss, see below)
               fishlike_maxn=fish_curve(r["metrics"], fishy), fishlike_maxn_low=fish_curve(lo, fishy),
               rows=rows, discovered=[d["what"] for d in r.get("discovered") or []],
               queued_tracks=len(open_q), lower_bound=[c for c in r.get("crowd_checks", []) if c.get("lower_bound")],
               cost_usd=round(st["billed_usd"], 4), live_calls=st["live_calls"],
               seconds=round(st["done"] - st["started"], 1) if st.get("done") else None)
    return out, r


def main():
    hand = hand_counts()
    res, tiles, k = [], [], 0
    for cid in sorted(hand):
        if not os.path.exists(os.path.join(run_dir(cid), "result.json")):
            print(f"{cid}: no result yet")
            continue
        s, r = score(cid, hand[cid])
        res.append(s)
        lo, hi = s["fish_maxn_low"], s["fish_maxn_high"]
        print(f"{cid}: hand {s['hand_sure']}(+{s['hand_faint']})  fish MaxN {s['fish_maxn']}  range {lo}..{hi}"
              f"  fish-like {s['fishlike_maxn_low']}..{s['fishlike_maxn']}  queued {s['queued_tracks']}"
              f"  spark-unprimed {[(c['row'], c['maxn'], c['total']) for c in s['lower_bound']]}  ${s['cost_usd']}  {s['seconds']}s  discovered {s['discovered']}")
        # metric 3: counted non-fish rows -> label-free crop
        summ = {row["label"]: row for row in _rows(r)}
        for row in s["rows"]:
            if row["non_fish"] and row["maxn"]:
                k += 1
                row["crop"] = k
                b = summ[row["label"]]
                clip = os.path.join(S.ROOT, "runs", f"{cid}_{TAG}", "clip.mp4")
                if os.path.exists(clip) and b.get("box"):
                    t = _crop(clip, b)
                    cv2.putText(t, f"#{k}", (10, 38), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 2, cv2.LINE_AA)
                    tiles.append(t)
                print(f"   non-fish row {row['label']!r} maxn {row['maxn']} (confirmed {row['maxn_confirmed']})  crop #{k}")
    suf = "" if TAG == "eval" else "_" + TAG
    json.dump(res, open(os.path.join(OUT, f"score{suf}.json"), "w"), indent=1)
    if tiles:
        while len(tiles) % 4:
            tiles.append(np.zeros_like(tiles[0]))
        grid = np.vstack([np.hstack(tiles[i:i + 4]) for i in range(0, len(tiles), 4)])
        cv2.imwrite(os.path.join(OUT, f"crops_sheet{suf}.jpg"), grid, [cv2.IMWRITE_JPEG_QUALITY, 90])
    sc = [s for s in res]
    for key, name in (("fish_maxn", "fish group"), ("fishlike_maxn", "fish-like")):
        err = [s[key] - s["hand_sure"] for s in sc]
        err2 = [s[key] - s["hand_sure"] - s["hand_faint"] for s in sc]
        inr = sum(1 for s in sc if s[key + "_low"] <= s["hand_sure"] <= s[key])
        print(f"{name}: vs sure exact {sum(1 for x in err if x == 0)}/{len(sc)}, ±1 {sum(1 for x in err if abs(x) <= 1)}, "
              f"Σ|err| {sum(map(abs, err))};  vs sure+faint exact {sum(1 for x in err2 if x == 0)}, ±1 "
              f"{sum(1 for x in err2 if abs(x) <= 1)}, Σ|err| {sum(map(abs, err2))};  range contains sure {inr}/{len(sc)}")
    print("total $%.4f, %.0f s" % (sum(s["cost_usd"] for s in sc), sum(s["seconds"] or 0 for s in sc)))


def _rows(r):
    """Best track (frame, box) per label, as score_discovery_heldout.summarise picks it."""
    out = {}
    for t, lab in r["auto_labels"].items():
        if lab is None:
            continue
        vd = r["verdicts"].get(t, {})
        cur = out.get(lab)
        if cur is None or pipeline._conf(vd) > cur["conf"]:
            out[lab] = dict(label=lab, conf=pipeline._conf(vd), frame=vd.get("frame"), box=vd.get("box"))
    return out.values()


def _crop(clip, row, size=360):
    from fishcount import video
    f = int(row["frame"])
    img = video.frames(clip, [f])[f]
    x0, y0, x1, y1 = map(int, row["box"])
    m = max(x1 - x0, y1 - y0) // 2 + 20
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    H, W = img.shape[:2]
    a, b, c, d = max(0, cx - m), max(0, cy - m), min(W, cx + m), min(H, cy + m)
    p = img[b:d, a:c].copy()
    cv2.rectangle(p, (x0 - a, y0 - b), (x1 - a, y1 - b), (255, 255, 255), 1)
    sc = size / max(p.shape[:2])
    p = cv2.resize(p, (int(p.shape[1] * sc), int(p.shape[0] * sc)), interpolation=cv2.INTER_CUBIC)
    tile = np.zeros((size + 50, size, 3), np.uint8)
    tile[50:50 + p.shape[0], :p.shape[1]] = p
    return tile


if __name__ == "__main__":
    if "--tag" in sys.argv:
        TAG = sys.argv[sys.argv.index("--tag") + 1]
    main()
