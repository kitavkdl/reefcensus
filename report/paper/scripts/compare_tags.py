"""Compare two re-run tags of the 15 discovery runs row by row (no API calls).
    python3 report/paper/scripts/compare_tags.py cr3 cr5
A row is a counted label with its MaxN; also the MaxN of each animal group and every discovery (what Spark saw, the
word that worked or none, the words tried, MaxN). Prints only what differs, then a one-line tally; runs missing under either tag are skipped."""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
RUNS = [(f"s00{k}", lambda t, k=k: f"{t}_s00{k}") for k in (1, 2, 3, 4)] + \
       [(f"DH{n}", lambda t, n=n: f"DH{n}_{t}") for n in range(1, 12)]


def rows(tag, name):
    d = json.load(open(os.path.join(ROOT, "runs", name(tag), "result.json")))
    return (
        {k: v["maxn"] for k, v in d.get("metrics", {}).items()},
        {k: v["maxn"] for k, v in d.get("group_metrics", {}).items()},
        [(x["what"], x["word"], [w["word"] for w in x["tried"]], x["maxn_full"]) for x in d.get("discovered", [])],
    )


def main(a, b):
    same = 0
    n = 0
    for clip, name in RUNS:
        if not all(os.path.exists(os.path.join(ROOT, "runs", name(t), "result.json")) for t in (a, b)):
            continue
        n += 1
        ra, rb = rows(a, name), rows(b, name)
        if ra == rb:
            same += 1
            continue
        print(f"== {clip}")
        for what, x, y in zip(("rows", "groups", "discovered"), ra, rb):
            if x != y:
                print(f"  {what}:\n    {a}: {x}\n    {b}: {y}")
    print(f"{same}/{n} runs identical in rows, group MaxN and discoveries ({a} vs {b})")


main(*(sys.argv[1:3] if len(sys.argv) > 2 else ("cr3", "cr5")))
