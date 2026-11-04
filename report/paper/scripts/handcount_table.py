"""Table 1d: held-out MaxN against the hand count of the 24 full videos, with constant baselines and per-clip
error statistics. Offline, no model calls.
  python3 report/paper/scripts/handcount_table.py [--tag held1]
Reads runs/<tag>_<clip>/result.json, else the bundle report/paper/data/heldout/runs/<tag>_<clip>/result.json.
The hand count is report/paper/data/heldout/recount/scores.json["hand"] (protocol in recount/key.json).
Constant baselines predict one value for every clip; "always 1" is also the most common hand count (12 of 24), so it
is the strongest constant a reader could pick after seeing the labels."""
import argparse, json, math, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, ROOT)
from fishcount import pipeline  # noqa: E402

B = os.path.join(ROOT, "report/paper/data/heldout")


def load_run(tag, cid):
    for d in (os.path.join(ROOT, "runs", f"{tag}_{cid}"), os.path.join(B, "runs", f"{tag}_{cid}")):
        p = os.path.join(d, "result.json")
        if os.path.exists(p):
            return json.load(open(p))
    raise FileNotFoundError(f"no result.json for {tag}_{cid}")


def maxn(res, frames=None, drop_queue=False, drop=None):
    q = {t for t, v in res["verdicts"].items() if pipeline.needs_review(v)} if drop_queue else set(drop or ())
    lab = lambda t: res["auto_labels"].get(t, res["tracks"].get(t, {}).get("label"))
    best = 0
    for f, ks in res["frames"].items():
        if frames is not None and int(f) not in frames:
            continue
        best = max(best, sum(1 for k in ks if lab(k["track"]) and k["track"] not in q))
    return best


def iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])); iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ix * iy
    return ix * iy / u if u > 0 else 0.0


def answer_queue(res, gt, cards, answers):
    """Answer each queued track from judgements a person has already recorded, without new judging: a queued track
    with a box on a person's reference box (IoU >= 0.3, annotated frames) is accepted (the annotator drew that fish);
    otherwise the gapfind card on the same boxes (IoU >= 0.5 on a shared frame) decides: 'fish, no grey box' and
    'already boxed' accept, 'part of a fish', 'not a fish' and 'can't tell' reject. Returns (rejected ids, unanswered)."""
    q = [t for t, v in res["verdicts"].items() if pipeline.needs_review(v)]
    boxes = {}
    for f, ks in res["frames"].items():
        for k in ks:
            boxes.setdefault(k["track"], []).append((int(f), k["box"]))
    rej, unanswered = set(), []
    for t in q:
        if any(iou(b, [x, y, x + w, y + h]) >= 0.3 for f, b in boxes.get(t, [])
               for x, y, w, h, *_ in gt.get(str(f), [])):
            continue
        ans = [answers[str(i + 1)] for i, c in enumerate(cards)
               if any(iou(b, cb) >= 0.5 for f, b in boxes.get(t, []) for cf, cb in c["boxes"] if cf == f)]
        if not ans:
            unanswered.append(t); rej.add(t)
        elif not any(x in ("O", "D") for x in ans):
            rej.add(t)
    return rej, unanswered


def stats(pred, ref):
    e = [pred[c] - ref[c] for c in ref]
    n = len(e)
    return dict(exact=sum(x == 0 for x in e), within1=sum(abs(x) <= 1 for x in e), sum_abs=sum(abs(x) for x in e),
                mae=sum(abs(x) for x in e) / n, rmse=math.sqrt(sum(x * x for x in e) / n), bias=sum(e) / n, n=n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="held1")
    a = ap.parse_args()
    sc = json.load(open(os.path.join(B, "recount/scores.json")))
    hand, boxes = sc["hand"], sc["boxes"]
    pipe, pipe_full, pipe_rej, pipe_ans = {}, {}, {}, {}
    gk = json.load(open(os.path.join(B, "gapfind/key.json"))); ga = json.load(open(os.path.join(B, "gapfind/answers.json")))
    cards_by_clip = {}
    for i, c in enumerate(gk["cards"]):
        cards_by_clip.setdefault(c["clip"], []).append((i, c))
    n_q = n_un = 0
    for cid in hand:
        gtf = {int(k) for k in json.load(open(os.path.join(B, "gt", f"{cid}.json")))["frames"]}
        r = load_run(a.tag, cid)
        pipe[cid], pipe_full[cid], pipe_rej[cid] = maxn(r, gtf), maxn(r), maxn(r, gtf, drop_queue=True)
        gt = json.load(open(os.path.join(B, "gt", f"{cid}.json")))["frames"]
        cl = cards_by_clip.get(cid, [])
        rej, un = answer_queue(r, gt, [c for _, c in cl], {str(k + 1): ga["answers"][str(i + 1)] for k, (i, _) in enumerate(cl)})
        pipe_ans[cid] = maxn(r, gtf, drop=rej)
        n_q += sum(1 for v in r["verdicts"].values() if pipeline.needs_review(v)); n_un += len(un)
    rows = [("human reference boxes (luderick annotation)", boxes),
            (f"pipeline ({a.tag}), queue accepted, annotated frames", pipe),
            (f"pipeline ({a.tag}), queue accepted, every frame", pipe_full),
            (f"pipeline ({a.tag}), queue rejected, annotated frames", pipe_rej),
            (f"pipeline ({a.tag}), queue answered from recorded judgements", pipe_ans),
            ("constant: always 1 (most common hand count)", {c: 1 for c in hand}),
            ("constant: always 2", {c: 2 for c in hand})]
    out = {}
    for ref_name, ref in (("hand count", hand), ("reference boxes", boxes)):
        print(f"\nagainst the {ref_name} (24 clips)")
        print(f"{'system':55s} exact  ±1  Σ|err|   MAE  RMSE   bias")
        for name, pred in rows:
            if pred is ref:
                continue
            s = stats(pred, ref)
            out.setdefault(ref_name, {})[name] = s
            print(f"{name:55s} {s['exact']:2d}/24 {s['within1']:2d}/24 {s['sum_abs']:4d}  {s['mae']:.2f}  {s['rmse']:.2f} {s['bias']:+.2f}")
    print(f"\nqueue answered from recorded judgements: {n_q} queued tracks, {n_un} with no recorded judgement (rejected)")
    big = [c for c in hand if hand[c] >= 3]
    print(f"\nclips with hand count >= 3 ({len(big)}): " + ", ".join(
        f"{c[5:]} hand {hand[c]} pipeline {pipe[c]} boxes {boxes[c]}" for c in big))
    json.dump(dict(tag=a.tag, pipeline=pipe, pipeline_full=pipe_full, pipeline_queue_rejected=pipe_rej, pipeline_queue_answered=pipe_ans, n_queued=n_q, n_unanswered=n_un, stats=out),
              open(os.path.join(B, f"recount/table1d_{a.tag}.json"), "w"), indent=1)


main()
