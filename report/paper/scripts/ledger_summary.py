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
T_L7A1 = 1793779500              # LONG1_cr7 first attempt, segment 2 (first ledger row 08:05:16 UTC 11/4; nothing else paid)
T_L7A2 = 1793779857              # LONG1_cr7 restarted (reef-long1-cr7 unit, 08:10:57 UTC); its calls are in the status files
T_REHEARSAL2_END = 1793697520    # last call of take 2 (09:18:39 UTC); the next paid call is 10 h later (19:29 UTC)
T_TAKE, T_TAKE_END = 1793811581, 1793811809   # live take filmed for the video (s002, empty cache; runs/nautilus_s002_0_12_1104-165941 status.json started/done)
                                 # after it: final-code development (crowd, refill, clean, shadow, camo, miss look), the
                                 # re-runs of every frozen evaluation (cr, cr2, cr3), gapfind and LONG1 re-runs; the LONG1
                                 # re-runs overlapped the rest, so they are split by runs/LONG1_cr*__S*/status.json billed_usd



def _status(pattern):
    """Segment status files of the 53-min runs: runs/ when present, else the copies in report/paper/data/long_video/status
    (a fresh clone has no runs/)."""
    fs = sorted(glob.glob(os.path.join(ROOT, pattern)))
    if not fs:
        name = pattern.split("/")[1]
        fs = sorted(glob.glob(os.path.join(ROOT, "report/paper/data/long_video/status", name + ".json")))
    return [json.load(open(f)) for f in fs]


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
    rehearsal2 = [r for r in rows if T_REHEARSAL2 <= r["t"] < T_REHEARSAL2_END]
    take = [r for r in rows if T_TAKE <= r["t"] < T_TAKE_END]
    final = [r for r in rows if r["t"] >= T_REHEARSAL2_END and r not in take]
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
    show("re-runs of seen data (protocol-commit code)", frz)
    show("live rehearsal, empty cache (2 takes)", rehearsal)
    show("site-memory demo runs", sitedemo)
    show("LONG1 attempts 1-2 (stopped at memory cap)", long1_early)
    show("fixed list on brightened s001", fixed_bright)
    wonder = [r for r in conc if r["kind"].startswith("muse-wonder")]
    show("Muse Wonder swap (concurrent)", wonder)
    seg = _status("runs/LONG1__S*/status.json")
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
    seg2 = _status("runs/LONG1_cr*__S*/status.json")
    l2_usd, l2_n = sum(d["billed_usd"] for d in seg2), sum(d["live_calls"] for d in seg2)
    # LONG1_cr7's first attempt was stopped by its memory cap in segment 2 after a SAM refill call; the restart re-ran
    # segment 2 from the cache and overwrote its status file, so that attempt's calls are taken from the ledger window
    a1 = [r for r in rows if T_L7A1 <= r["t"] < T_L7A2]
    l2_usd, l2_n = l2_usd + sum(r["usd"] for r in a1), l2_n + len(a1)
    print(f"{'LONG1 re-runs on final code':34s} {l2_n:4d} calls (from {len(seg2)} segment status files)  ${l2_usd:.3f}")
    show("live take for the video (s002, empty cache)", take)
    # NOAA held-out set (protocol run N*_eval + after-seeing --crowd re-run N*_crowd), from their status files
    nq = [json.load(open(f)) for f in sorted(glob.glob(os.path.join(ROOT, "runs/N[1-8]_eval/status.json")) + glob.glob(os.path.join(ROOT, "runs/N[1-8]_crowd/status.json")))] or \
         [json.load(open(f)) for f in sorted(glob.glob(os.path.join(ROOT, "report/paper/data/noaa_heldout/runs/N*/status.json")))]
    n_usd, n_n = sum(d["billed_usd"] for d in nq), sum(d["live_calls"] for d in nq)
    print(f"{'NOAA held-out (run + crowd re-run)':34s} {n_n:4d} calls (from {len(nq)} status files)  ${n_usd:.3f}")
    print(f"{'final-code development + re-runs':34s} {len(final) - l2_n - n_n:4d} calls  ${sum(r['usd'] for r in final) - l2_usd - n_usd:.3f}")
    show("total", rows)
    sp = [r for r in dev if r["kind"] == "spark"]
    tin = [int(r["note"].split("in=")[1].split()[0]) for r in sp if "in=" in r.get("note", "")]
    tout = [int(r["note"].split("out=")[1].split()[0]) for r in sp if "out=" in r.get("note", "")]
    print(f"Spark (development): mean ${statistics.mean(r['usd'] for r in sp):.4f}, median tokens in {statistics.median(tin)}, "
          f"out {statistics.median(tout)} (n={len(tin)} with token notes)")


main()
