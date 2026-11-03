"""Cost section of the paper from the spend ledger (every paid call is appended by fishcount/api.py).
  python3 report/paper/scripts/ledger_summary.py      (reads cache/ledger.jsonl, else the copy in report/paper/data)
Windows are fixed by time stamps recorded when each experiment started (UTC epoch seconds)."""
import json, os, statistics

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
LIVE = os.environ.get("FISH_LEDGER") or os.path.join(ROOT, "cache/ledger.jsonl")
COPY = os.path.join(ROOT, "report/paper/data/ledger.jsonl")
T_HELDOUT = 1793610643      # held-out protocol commit 06f1f01 (git log -1 --format=%ct); held-out runs start after it
T_FIXED = 1793611190              # fixed-vocabulary baseline launched (date +%s just before the run)
T_SPARKCOUNT = 1793612367         # Spark-alone counting protocol commit a814c9d; probe and runs after it
T_DHRERUN = 1793652641             # last commit before the uncached second DH run (aecedfa)
T_DISCHELD = 1793648572           # held-out discovery protocol commit c4c60d0; DH runs after it
T_RERUN_END = 1793653590          # just after the 112th call of the uncached second DH run (next call ~1 h later)
T_DH2 = 1793663752               # DH6-DH11 pipeline batch started (run log, UTC)
T_DH2_FIXED = 1793664426         # DH6-DH11 pipeline batch done; fixed-vocabulary baseline after it
T_FRZ = 1793666284               # re-runs of previously seen data (DH1-5 _frz, luderick frz) started


def main():
    rows = [json.loads(l) for l in open(LIVE if os.path.exists(LIVE) else COPY)]
    def show(name, rs):
        sam = [r for r in rs if r["kind"] == "sam"]; sp = [r for r in rs if r["kind"] == "spark"]
        print(f"{name:34s} {len(rs):4d} calls (SAM {len(sam)}, Spark {len(sp)})  ${sum(r['usd'] for r in rs):.3f}")
    rep = [r for r in rows if r.get("note", "").startswith("paper repeat_peak")]
    held = [r for r in rows if r["t"] >= T_HELDOUT and (T_FIXED is None or r["t"] < T_FIXED) and r not in rep]
    fixed = [r for r in rows if T_FIXED <= r["t"] < T_SPARKCOUNT]
    probe = [r for r in rows if r["t"] >= T_SPARKCOUNT and r["kind"] == "sam" and r.get("note", "").endswith((":animal", ":luderick"))]
    scount = [r for r in rows if T_SPARKCOUNT <= r["t"] < T_DISCHELD and r not in probe]
    dheld = [r for r in rows if T_DISCHELD <= r["t"] < T_DHRERUN and r not in probe and r not in rep]
    rerun = [r for r in rows if T_DHRERUN <= r["t"] < T_RERUN_END and r not in probe and r not in rep]
    later = [r for r in rows if T_RERUN_END <= r["t"] < T_DH2 and r not in probe and r not in rep]
    dh2 = [r for r in rows if T_DH2 <= r["t"] < T_DH2_FIXED]
    dh2f = [r for r in rows if T_DH2_FIXED <= r["t"] < T_FRZ]
    frz = [r for r in rows if r["t"] >= T_FRZ]
    dev = [r for r in rows if r not in rep and r not in held and r not in fixed and r not in scount
           and r not in probe and r not in dheld and r not in rerun
           and r not in later and r not in dh2 and r not in dh2f and r not in frz]
    show("development + evaluation", dev)
    show("repeated-call experiment", rep)
    show("held-out runs", held)
    show("fixed-vocabulary baseline", fixed)
    show("Spark-alone counting baseline", scount)
    show("vocabulary probes (animal, luderick)", probe)
    show("held-out discovery runs", dheld)
    show("held-out discovery, second uncached run", rerun)
    show("later development (final code, long video)", later)
    show("second held-out discovery runs (DH6-11)", dh2)
    show("DH6-11 fixed-vocabulary baseline", dh2f)
    show("re-runs of seen data on frozen code", frz)
    show("total", rows)
    sp = [r for r in dev if r["kind"] == "spark"]
    tin = [int(r["note"].split("in=")[1].split()[0]) for r in sp if "in=" in r.get("note", "")]
    tout = [int(r["note"].split("out=")[1].split()[0]) for r in sp if "out=" in r.get("note", "")]
    print(f"Spark (development): mean ${statistics.mean(r['usd'] for r in sp):.4f}, median tokens in {statistics.median(tin)}, "
          f"out {statistics.median(tout)} (n={len(tin)} with token notes)")


main()
