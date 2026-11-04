"""How many queue answers settle every MaxN and first arrival (fishcount/settle.py), and a check that stopping there gives
the same numbers as answering the whole queue. No person's answers exist for most queued tracks, so three answer rules
stand in for the person: accept every track, reject every track, and follow the auditor (accept what A1 accepted).
For each run and rule: ask the rank-1 track, record the answer, recompute, until nothing can change a count; then
compare MaxN and first arrival per label with those after answering every queued track by the same rule. No API calls.

  python3 report/paper/scripts/settle_sim.py [tag ...]      (default: cr7 runs + LONG1_cr7; writes data/settle/<tag>.json)"""
import glob, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
from fishcount import pipeline, settle, tracks

RULES = {"accept_all": lambda v: True, "reject_all": lambda v: False, "auditor": lambda v: bool(v and v.get("is_target"))}


def numbers(res, review):
    labels = dict(res.get("auto_labels", {})); labels.update(review)
    frames = {int(f): ks for f, ks in res["frames"].items()}
    m = tracks.metrics(frames, res["tracks"], res["video"]["n_frames"], res["video"]["fps"], labels)
    return {k: (v["maxn"], v["first_frame"]) for k, v in m.items() if v["maxn"]}


def answer(res, t, rule):
    return settle.accept_label(res, t) if RULES[rule](res["verdicts"].get(t)) else None


def run_one(res):
    q = [t for t, v in res.get("verdicts", {}).items() if pipeline.needs_review(v)]
    out = dict(queue=len(q))
    for rule in RULES:
        review = {}
        while True:
            d = settle.decisive(res, review)
            if not d:
                break
            t = min(d, key=d.get)
            review[t] = answer(res, t, rule)
        full = {t: answer(res, t, rule) for t in q}
        out[rule] = dict(asked=len(review), same=numbers(res, review) == numbers(res, full))
    return out


def main(paths):
    rows = {}
    for p in paths:
        b = os.path.basename(p)
        rows["LONG1_" + b[7:-5] if b.startswith("result_cr") else os.path.basename(os.path.dirname(p))] = run_one(json.load(open(p)))
    return rows


if __name__ == "__main__":
    tags = sys.argv[1:] or ["cr7"]
    od = os.path.join(ROOT, "report", "paper", "data", "settle"); os.makedirs(od, exist_ok=True)
    for tag in tags:
        L1 = f"{ROOT}/runs/LONG1_{tag}/result.json"     # the 53-min run of this tag (cr7, cr9), if there is one
        L1B = f"{ROOT}/report/paper/data/long_video/result_{tag}.json"   # bundled copy for a clone without runs/
        paths = sorted(glob.glob(f"{ROOT}/runs/{tag}_*/result.json") + glob.glob(f"{ROOT}/runs/DH*_{tag}/result.json")
                       + ([L1 if os.path.exists(L1) else L1B] if os.path.exists(L1) or os.path.exists(L1B) else []))
        paths = [p for p in paths if "__S" not in p]
        rows = main(paths)
        out = f"{tag}.json"
        if tag == "cr7" and len(rows) < 46:      # a clone without runs/ has only the bundled 53-min run: keep the full file
            out = f"{tag}_partial.json"
            print(f"only {len(rows)} of the 46 cr7 runs found; writing {out}, data/settle/cr7.json left as it is")
        json.dump(rows, open(os.path.join(od, out), "w"), indent=1)
        tot = {r: sum(x[r]["asked"] for x in rows.values()) for r in RULES}
        same = all(x[r]["same"] for x in rows.values() for r in RULES)
        print(f"{tag}: {len(rows)} runs, queue {sum(x['queue'] for x in rows.values())}, asked {tot}, "
              f"same numbers as answering everything: {same}")
        for k, x in rows.items():
            if x["queue"] >= 30 or not all(x[r]["same"] for r in RULES):
                print("  ", k, x)
