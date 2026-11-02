"""Cost section of the paper from the spend ledger (every paid call is appended by fishcount/api.py).
  python3 report/paper/scripts/ledger_summary.py      (reads cache/ledger.jsonl, else the copy in report/paper/data)
Windows are fixed by time stamps recorded when each experiment started (UTC epoch seconds)."""
import json, os, statistics

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
LIVE = os.path.join(ROOT, "cache/ledger.jsonl")
COPY = os.path.join(ROOT, "report/paper/data/ledger.jsonl")
T_HELDOUT = 1793610643      # held-out protocol commit 06f1f01 (git log -1 --format=%ct); held-out runs start after it
T_FIXED = 1793611190              # fixed-vocabulary baseline launched (date +%s just before the run)
T_SPARKCOUNT = 1793612367         # Spark-alone counting protocol commit a814c9d; probe and runs after it


def main():
    rows = [json.loads(l) for l in open(LIVE if os.path.exists(LIVE) else COPY)]
    def show(name, rs):
        sam = [r for r in rs if r["kind"] == "sam"]; sp = [r for r in rs if r["kind"] == "spark"]
        print(f"{name:34s} {len(rs):4d} calls (SAM {len(sam)}, Spark {len(sp)})  ${sum(r['usd'] for r in rs):.3f}")
    rep = [r for r in rows if r.get("note", "").startswith("paper repeat_peak")]
    held = [r for r in rows if r["t"] >= T_HELDOUT and (T_FIXED is None or r["t"] < T_FIXED) and r not in rep]
    fixed = [r for r in rows if T_FIXED <= r["t"] < T_SPARKCOUNT]
    scount = [r for r in rows if r["t"] >= T_SPARKCOUNT]
    dev = [r for r in rows if r not in rep and r not in held and r not in fixed and r not in scount]
    show("development + evaluation", dev)
    show("repeated-call experiment", rep)
    show("held-out runs", held)
    show("fixed-vocabulary baseline", fixed)
    show("Spark-alone counting baseline", scount)
    show("total", rows)
    sp = [r for r in dev if r["kind"] == "spark"]
    tin = [int(r["note"].split("in=")[1].split()[0]) for r in sp if "in=" in r.get("note", "")]
    tout = [int(r["note"].split("out=")[1].split()[0]) for r in sp if "out=" in r.get("note", "")]
    print(f"Spark (development): mean ${statistics.mean(r['usd'] for r in sp):.4f}, median tokens in {statistics.median(tin)}, "
          f"out {statistics.median(tout)} (n={len(tin)} with token notes)")


main()
