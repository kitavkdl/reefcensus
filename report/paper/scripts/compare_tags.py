"""Compare two re-run tags of the 15 discovery runs row by row (no API calls).
    python3 report/paper/scripts/compare_tags.py cr3 cr6
A row is a counted label with its MaxN; also the MaxN of each animal group and every discovery (what Spark saw, the
word that worked or none, the words tried, MaxN). Prints only what differs, then a one-line tally; runs missing under
either tag are skipped. Reads runs/<run>/result.json; each tag's rows are also saved to
report/paper/data/cr_rows/<tag>.json, which a fresh clone (no runs/) reads instead."""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
SAVED = os.path.join(ROOT, "report", "paper", "data", "cr_rows")
RUNS = [(f"s00{k}", lambda t, k=k: f"{t}_s00{k}") for k in (1, 2, 3, 4)] + \
       [(f"DH{n}", lambda t, n=n: f"DH{n}_{t}") for n in range(1, 12)]


def rows_from_run(path):
    d = json.load(open(path))
    return [
        {k: v["maxn"] for k, v in d.get("metrics", {}).items()},
        {k: v["maxn"] for k, v in d.get("group_metrics", {}).items()},
        [[x["what"], x["word"], [w["word"] for w in x["tried"]], x["maxn_full"]] for x in d.get("discovered", [])],
    ]


def load(tag):
    """{clip: rows} for every run of the tag found under runs/ (and saved), else from the saved copy."""
    live = {clip: os.path.join(ROOT, "runs", name(tag), "result.json") for clip, name in RUNS}
    live = {clip: rows_from_run(p) for clip, p in live.items() if os.path.exists(p)}
    saved = os.path.join(SAVED, f"{tag}.json")
    if live:
        os.makedirs(SAVED, exist_ok=True)
        json.dump(live, open(saved, "w"), indent=1)
        return live
    return json.load(open(saved)) if os.path.exists(saved) else {}


def main(a, b):
    ra, rb = load(a), load(b)
    same = n = 0
    for clip, _ in RUNS:
        if clip not in ra or clip not in rb:
            continue
        n += 1
        if ra[clip] == rb[clip]:
            same += 1
            continue
        print(f"== {clip}")
        for what, x, y in zip(("rows", "groups", "discovered"), ra[clip], rb[clip]):
            if x != y:
                print(f"  {what}:\n    {a}: {x}\n    {b}: {y}")
    print(f"{same}/{n} runs identical in rows, group MaxN and discoveries ({a} vs {b})")


main(*(sys.argv[1:3] if len(sys.argv) > 2 else ("cr3", "cr6")))
