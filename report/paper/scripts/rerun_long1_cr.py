"""11/3: LONG1 once more on the final code (clean + refill on), tag LONG1_cr. The 5 fps source was removed to free disk,
but each segment's clip.mp4 from the original run is kept; run_pipeline copies a 5 fps mp4 as is, so every cache key
(clip hash + prompt) is the original run's and only calls the new code changes are made. Segment starts are those of
the original run's log. Low light was decided once for the whole video in that run ("off"), so it is passed as is.
    FISH_BUDGET=<cap> python3 report/paper/scripts/rerun_long1_cr.py [run id, default LONG1_cr]"""
import filecmp, json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, ROOT)
from fishcount import longvideo, pipeline, video

old = json.load(open(os.path.join(pipeline.RUNS, "LONG1", "result.json")))
rid, done, start = (sys.argv[1] if len(sys.argv) > 1 else "LONG1_cr"), [], 0   # 11/3 evening: LONG1_cr2
os.makedirs(os.path.join(pipeline.RUNS, rid), exist_ok=True)
for k in range(1, 7):
    sp = os.path.join(pipeline.RUNS, f"LONG1__S{k}", "clip.mp4")
    n = video.info(sp)["n_frames"]
    srid = f"{rid}__S{k}"
    if not os.path.exists(os.path.join(pipeline.RUNS, srid, "result.json")):
        pipeline.run_pipeline(sp, srid, do_scout=False, prompts=["fish"], do_discover=True, do_zoom=True, max_usd=8,
                              lowlight="off")
    # 11/3: the disk filled during LONG1_cr2. A finished segment's SAM chunks (seg_*.mp4, cut again from the clip on
    # any re-run) go, and its clip.mp4, a byte copy of the source segment, becomes a hard link to it.
    sd = os.path.join(pipeline.RUNS, srid)
    for f in os.listdir(sd):
        if f.startswith("seg_") and f.endswith(".mp4"):
            os.remove(os.path.join(sd, f))
    cp = os.path.join(sd, "clip.mp4")
    if os.path.exists(cp) and not os.path.samefile(cp, sp) and filecmp.cmp(cp, sp, shallow=False):
        os.link(sp, cp + ".lnk_tmp"); os.replace(cp + ".lnk_tmp", cp)
    st =json.load(open(os.path.join(pipeline.RUNS, srid, "status.json")))
    print(f"S{k} start {start} n {n} billed ${st['billed_usd']:.3f}", flush=True)
    done.append((os.path.join(pipeline.RUNS, srid), start, n))
    start += n
R = longvideo.merge(rid, old["source"], done, old["video"]["fps"])
R["video"]["lowlight"] = old["video"]["lowlight"]
json.dump(R, open(os.path.join(pipeline.RUNS, rid, "result.json"), "w"))
print("merged:", {m: v["maxn"] for m, v in R["metrics"].items()})
