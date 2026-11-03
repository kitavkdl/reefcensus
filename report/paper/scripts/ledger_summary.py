"""Cost section of the paper from the spend ledger (every paid call is appended by fishcount/api.py).
  python3 report/paper/scripts/ledger_summary.py      (reads cache/ledger.jsonl, else the copy in report/paper/data)
Windows are fixed by time stamps recorded when each experiment started (UTC epoch seconds)."""
import glob, json, os, statistics

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
T_REHEARSAL = 1793678208         # last commit before the empty-cache live rehearsal (9056d80); two DH11 takes, rehearsal/cache_1103-*
T_SITEDEMO = 1793678867          # site-memory demo runs started (runs/site_demo_A/status.json "started")
T_LONG1_EARLY = 1793679409       # LONG1 pre-run record committed, no paid call yet (1a50ab7); attempts 1 and 2 follow
T_FIXED_BRIGHT = 1793683352      # attempt 1 render fix committed (96a1a8c); fixed 16-word list on the brightened s001 clip follows
T_CONC = 1793684200              # LONG1 attempt 3 started (reef-long1c unit, 05:36:40 UTC); Muse Wonder swap and the SAM 3 Agent-style
                                 # loop ran at the same time, so after this point calls are split by run, not by time:
                                 # Wonder by ledger kind, LONG1 by runs/LONG1__S*/status.json billed_usd, the loop by
                                 # report/paper/data/sam_agent/<clip>.json usd (both metered per thread by fishcount/api.py)
T_REHEARSAL2 = 1793697188           # s003 empty-cache rehearsal, 2 takes (rehearsal/cache_1103-0913*, -0915*), after LONG1 finished
                                 # (1793696747) and nothing else paid; takes 1-2 started 1793697190 / 1793697355


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
    frz = [r for r in rows if T_FRZ <= r["t"] < T_REHEARSAL]
    rehearsal = [r for r in rows if T_REHEARSAL <= r["t"] < T_SITEDEMO]
    sitedemo = [r for r in rows if T_SITEDEMO <= r["t"] < T_LONG1_EARLY]
    long1_early = [r for r in rows if T_LONG1_EARLY <= r["t"] < T_FIXED_BRIGHT]
    fixed_bright = [r for r in rows if T_FIXED_BRIGHT <= r["t"] < T_CONC]
    conc = [r for r in rows if T_CONC <= r["t"] < T_REHEARSAL2]
    rehearsal2 = [r for r in rows if r["t"] >= T_REHEARSAL2]
    dev = [r for r in rows if r not in rep and r not in held and r not in fixed and r not in scount
           and r not in probe and r not in dheld and r not in rerun
           and r not in later and r not in dh2 and r not in dh2f and r not in frz
           and r["t"] < T_REHEARSAL]
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
    show("live rehearsal, empty cache (2 takes)", rehearsal)
    show("site-memory demo runs", sitedemo)
    show("LONG1 attempts 1-2 (stopped at memory cap)", long1_early)
    show("fixed list on brightened s001", fixed_bright)
    wonder = [r for r in conc if r["kind"].startswith("muse-wonder")]
    show("Muse Wonder swap (concurrent)", wonder)
    seg = [json.load(open(f)) for f in sorted(glob.glob(os.path.join(ROOT, "runs/LONG1__S*/status.json")))]
    l_usd, l_n = sum(d["billed_usd"] for d in seg), sum(d["live_calls"] for d in seg)
    loop = [json.load(open(f)) for f in sorted(glob.glob(os.path.join(ROOT, "report/paper/data/sam_agent/*.json")))
            if not f.endswith(("_dry.json", "blind_key.json")) and "usd" in json.load(open(f))]
    a_usd = sum(d["usd"] or 0 for d in loop)
    a_n = sum(d["sam_calls"] - d["sam_cached"] + d["spark_calls"] for d in loop)
    print(f"{'LONG1 attempt 3 (concurrent)':34s} {l_n:4d} calls (from {len(seg)} segment status files)  ${l_usd:.3f}")
    print(f"{'SAM 3 Agent-style loop (concurrent)':34s} {a_n:4d} calls (from {len(loop)} clip records)  ${a_usd:.3f}")
    rest = sum(r["usd"] for r in conc) - sum(r["usd"] for r in wonder) - l_usd - a_usd
    print(f"{'concurrent window, not attributed':34s} {len(conc) - len(wonder) - l_n - a_n:4d} calls  ${rest:.3f}")
    show("live rehearsal s003, empty cache (2 takes)", rehearsal2)
    show("total", rows)
    sp = [r for r in dev if r["kind"] == "spark"]
    tin = [int(r["note"].split("in=")[1].split()[0]) for r in sp if "in=" in r.get("note", "")]
    tout = [int(r["note"].split("out=")[1].split()[0]) for r in sp if "out=" in r.get("note", "")]
    print(f"Spark (development): mean ${statistics.mean(r['usd'] for r in sp):.4f}, median tokens in {statistics.median(tin)}, "
          f"out {statistics.median(tout)} (n={len(tin)} with token notes)")


main()
