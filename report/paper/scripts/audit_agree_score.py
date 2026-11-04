"""Auditor (A1) against a person. Part 1 scores the blind stratified sheet of audit_agree_sheet.py (rules fixed there).
Part 2 re-reads the three earlier sheets (gapfind 20 tracks, precision 40 boxes, queue 9 tracks): each judged item is
looked up in the run it came from and A1's answer on that track is set against the person's.

  python3 report/paper/scripts/audit_agree_score.py
"""
import collections, json, os

D = os.path.join(os.path.dirname(__file__), "..", "data")
RUNS = os.path.expanduser("~/meta-fish/runs")
STRATA = ("rejected", "accepted_low", "accepted_high")


def kappa(pairs):
    """Cohen's kappa for two binary raters; pairs = [(a, b)]."""
    n = len(pairs)
    if not n:
        return None
    po = sum(a == b for a, b in pairs) / n
    pa, pb = sum(a for a, _ in pairs) / n, sum(b for _, b in pairs) / n
    pe = pa * pb + (1 - pa) * (1 - pb)
    return None if pe == 1 else (po - pe) / (1 - pe)


def part1():
    key = json.load(open(f"{D}/audit_agree/key.json"))
    ap = f"{D}/audit_agree/answers.json"
    print(f"== blind sheet: pool {key['pool_sizes']}, {len(key['cards'])} cards ({key['per_stratum']} per stratum)")
    if not os.path.exists(ap):
        print("   no answers.json yet")
        return
    ans = json.load(open(ap))["answers"]
    rows = collections.defaultdict(collections.Counter)
    pairs, pairs_unsure_wrong = [], []
    for c in key["cards"]:
        a = ans.get(str(c["n"]))
        rows[c["stratum"]][a or "none"] += 1
        if a in ("Y", "O", "N"):
            pairs.append((c["a1_is_target"], a == "Y"))
            pairs_unsure_wrong.append((c["a1_is_target"], a == "Y"))
        elif a == "?":
            pairs_unsure_wrong.append((c["a1_is_target"], not c["a1_is_target"]))
    print("   stratum        Y  O  N  ?  agree/answered")
    est, tot = 0.0, sum(key["pool_sizes"].values())
    for s in STRATA:
        r = rows[s]; want = "Y" if s != "rejected" else None
        agree = r["Y"] if want else r["O"] + r["N"]; answered = r["Y"] + r["O"] + r["N"]
        print(f"   {s:14s} {r['Y']:2d} {r['O']:2d} {r['N']:2d} {r['?']:2d}  {agree}/{answered}")
        if answered:
            est += key["pool_sizes"][s] / tot * agree / answered
    k1, k2 = kappa(pairs), kappa(pairs_unsure_wrong)
    print(f"   agreement {sum(a == b for a, b in pairs)}/{len(pairs)} answered; kappa {k1:.2f} (unsure left out), "
          f"{k2:.2f} (unsure = disagreement); pool-weighted agreement {est:.1%}")


def verdict(run, track):
    p = f"{RUNS}/{run}/result.json"
    if not os.path.exists(p):
        return None
    return json.load(open(p))["verdicts"].get(track)


def part2():
    print("== earlier sheets (cr3 runs; queue sheet on qtime runs)")
    g = json.load(open(f"{D}/heldout/gapfind/key.json")); ga = json.load(open(f"{D}/heldout/gapfind/answers.json"))["answers"]
    c = collections.Counter()
    for card in g["cards"]:
        if card["kind"] != "gap":
            continue
        v = verdict(f"cr3_{card['clip']}", card["track"]) or {}
        acc = "acc_hi" if v.get("is_target") and (v.get("confidence") or 0) >= 0.7 else ("acc_lo" if v.get("is_target") else "rej/none")
        c[(acc, ga.get(str(card["n"])))] += 1
    print("   gapfind (A1 answer, person: O fish / D boxed fish / P part / X not / ?):", dict(sorted(c.items())))
    f = json.load(open(f"{D}/heldout/fp_sheet/key.json")); fa = json.load(open(f"{D}/heldout/fp_sheet/answers.json"))["answers"]
    c = collections.Counter()
    for it in f["items"]:
        v = verdict(f"cr3_{it['clip']}", it["track"]) or {}
        acc = "acc_hi" if v.get("is_target") and (v.get("confidence") or 0) >= 0.7 else ("acc_lo" if v.get("is_target") else "rej/none")
        c[(it["kind"], acc, fa.get(str(it["n"])))] += 1
    print("   precision boxes (kind, A1 answer, person O/P/X/?):", dict(sorted(c.items())))
    q = json.load(open(f"{D}/qtime/key.json")); qa = json.load(open(f"{D}/qtime/answers.json"))["answers"]
    c = collections.Counter()
    for card in q["cards"]:
        acc = ("acc" if card["is_target"] else "rej") + ("_hi" if card["confidence"] >= 0.7 else "_lo")
        c[(acc, qa.get(str(card["n"])))] += 1
    print("   queue (A1 answer, person A accept / R reject / ?):", dict(sorted(c.items())))


if __name__ == "__main__":
    part1(); part2()
