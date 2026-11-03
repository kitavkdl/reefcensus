"""Score the shadow replay (protocol: report/paper/vlm_swap_protocol.md). No network.
  python3 report/paper/scripts/vlm_swap_score.py
Writes report/paper/data/vlm_swap/: summary.json, blind_names.md (measure 1 grading sheet, models hidden) and
blind_key.json (which list is which model; not shown to the grader).

Measure 2 reads the boolean field of each tile (audit/verify: is_target, confirm/motion: is_animal, pair:
same_animal). The pipeline also applies confidence thresholds to some of these; they are not re-applied here.
"""
import json, os, random, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
from fishcount import api  # noqa: E402

D = "report/paper/data/vlm_swap"
FIELD = {"audit": ("track", "is_target"), "verify": ("tile", "is_target"), "confirm": ("tile", "is_animal"),
         "motion": ("tile", "is_animal"), "pair": ("tile", "same_animal")}
# counted non-fish (and DH5 fish) rows a person judged from label-free crops; every one was judged an animal
JUDGED = [("DH1", "crab"), ("DH2", "sea anemone"), ("DH2", "crab"), ("DH3", "spider crab"), ("DH5", "pink cusk-eel"),
          ("DH7", "crab"), ("DH11", "scavenging amphipod crustacean")]


def parse(text):
    if not text:
        return None
    try:
        return api.parse_json(text)
    except Exception:
        return None


def tiles(kind, text):
    v = parse(text)
    if v is None:
        return None
    key, field = FIELD[kind]
    out = {}
    for d in v if isinstance(v, list) else [v]:
        if isinstance(d, dict) and key in d:
            out[str(d[key])] = bool(d.get(field))
    return out


def names(text):
    v = parse(text)
    if not isinstance(v, dict):
        return None
    return [o.get("what", "") for o in v.get("others", []) if isinstance(o, dict)]


def main():
    R = [json.loads(l) for l in open(f"{D}/calls_muse-wonder-1.0.jsonl")]
    summ = {"calls": len(R), "errors": sum(1 for r in R if r.get("error")),
            "error_kinds": sorted({r["error"].split(":")[0] for r in R if r.get("error")})}
    # measure 4: cost and time (Spark's cost from its cached usage is in the ledger history; here Wonder's)
    summ["wonder_usd"] = round(sum(r.get("usd_usage", 0) for r in R), 4)
    summ["wonder_usd_per_call"] = round(summ["wonder_usd"] / max(1, len(R) - summ["errors"]), 5)
    ok = [r for r in R if not r.get("error")]
    summ["wonder_seconds_mean"] = round(sum(r["seconds"] for r in ok) / max(1, len(ok)), 1)
    summ["wonder_seconds_max"] = max((r["seconds"] for r in ok), default=None)
    # measure 2: agreement per kind
    agree = {}
    for kind in FIELD:
        n = same = unread = 0
        flips = []
        for r in R:
            if r["kind"] != kind or r.get("error"):
                continue
            s, w = tiles(kind, r["spark"]), tiles(kind, r["other"])
            if w is None or s is None:
                unread += 1
                continue
            for t, sv in s.items():
                if t not in w:
                    unread += 1
                    continue
                n += 1
                same += sv == w[t]
                if sv != w[t]:
                    flips.append(dict(clip=r["clip"], tile=t, spark=sv, wonder=w[t]))
        agree[kind] = dict(tiles=n, agree=same, unreadable=unread, flips=flips)
    summ["agreement"] = agree
    # measure 3: judged rows — Wonder's verify/audit verdicts on calls about that name in that clip
    j = []
    for clip, name in JUDGED:
        rej = []
        for r in R:
            if r["clip"] != clip or r["kind"] not in ("verify", "audit") or r.get("error"):
                continue
            if f'"{name}"' not in r["prompt"]:
                continue
            s, w = tiles(r["kind"], r["spark"]) or {}, tiles(r["kind"], r["other"]) or {}
            rej += [f"{r['kind']} {t}" for t, sv in s.items() if sv and w.get(t) is False]
        j.append(dict(clip=clip, row=name, wonder_rejects=rej))
    summ["judged_rows"] = j
    # measure 1: blind sheet of discovery names
    rng = random.Random(20261103)
    key, lines = {}, ["# Discovery names, two models, blind (measure 1)", "",
                      "For each clip: which reference taxa (primary list) does each list name, by the coarse-group rule?", ""]
    for r in R:
        if r["kind"] != "discover":
            continue
        a, b = names(r["spark"]), names(r["other"]) if not r.get("error") else None
        pair = [("spark", a), ("wonder", b)]
        rng.shuffle(pair)
        key[r["clip"]] = {"A": pair[0][0], "B": pair[1][0]}
        lines += [f"## {r['clip']}", f"- A: {pair[0][1]}", f"- B: {pair[1][1]}", ""]
    open(f"{D}/blind_names.md", "w").write("\n".join(lines))
    json.dump(key, open(f"{D}/blind_key.json", "w"), indent=1)
    json.dump(summ, open(f"{D}/summary.json", "w"), indent=1)
    print(json.dumps({k: v for k, v in summ.items() if k != "agreement"}, indent=1))
    for k, v in agree.items():
        print(k, f"{v['agree']}/{v['tiles']} agree, unreadable {v['unreadable']}, flips {v['flips']}")


if __name__ == "__main__":
    main()
