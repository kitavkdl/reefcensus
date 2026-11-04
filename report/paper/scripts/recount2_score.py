"""Second independent hand count of the 24 held-out videos (protocol in data/heldout/recount2/key.json).

Paste the counter's reply ("v01: 2 (+1) | note" per line) into data/heldout/recount2/answers.txt, then
  python3 report/paper/scripts/recount2_score.py [--tag cr7]
prints agreement between the two counters and Table 1d against the second count and against the two counters' mean
(sure fish only). Offline, $0."""
import argparse, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
B = os.path.join(os.path.dirname(HERE), "data", "heldout")
D = os.path.join(B, "recount2")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="cr7")
    a = ap.parse_args()
    key = json.load(open(os.path.join(D, "key.json")))["key"]
    second, plus = {}, {}
    for line in open(os.path.join(D, "answers.txt")):
        m = re.match(r"\s*(v\d\d)\s*:\s*(\d+)(?:\s*\(\+(\d+)\))?", line)
        if m:
            second[key[m.group(1)]] = int(m.group(2)); plus[key[m.group(1)]] = int(m.group(3) or 0)
    missing = sorted(set(key.values()) - set(second))
    if missing:
        sys.exit(f"no answer for {len(missing)} clips: {missing}")
    sc = json.load(open(os.path.join(B, "recount", "scores.json")))
    first, boxes = sc["hand"], sc["boxes"]
    d = [second[c] - first[c] for c in first]
    print(f"two counters: exact {sum(x == 0 for x in d)}/24, within ±1 {sum(abs(x) <= 1 for x in d)}/24, "
          f"Σ|diff| {sum(abs(x) for x in d)}; second person marked '+' on {sum(v > 0 for v in plus.values())} clips")
    for c in first:
        if first[c] != second[c]:
            print(f"  {c}: first {first[c]}, second {second[c]}{' (+%d)' % plus[c] if plus[c] else ''}")
    import handcount_table as h   # noqa: E402  (reuses its run loading and statistics)
    t = json.load(open(os.path.join(B, "recount", f"table1d_{a.tag}.json")))
    rows = [("human reference boxes", boxes), ("pipeline, queue accepted", t["pipeline"]),
            ("pipeline, queue answered from recorded judgements", t["pipeline_queue_answered"]),
            ("pipeline, queue rejected", t["pipeline_queue_rejected"])]
    for name, ref in (("second person's count", second), ("first author's count", first)):
        print(f"\nagainst the {name}")
        for rn, pred in rows:
            s = h.stats(pred, ref)
            print(f"  {rn:52s} exact {s['exact']:2d}/24  ±1 {s['within1']:2d}/24  Σ|err| {s['sum_abs']:3d}  MAE {s['mae']:.2f}")
    json.dump(dict(second=second, plus=plus), open(os.path.join(D, "scores.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
