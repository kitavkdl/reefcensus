"""Videos longer than one SAM 3.1 call takes (10 minutes per file): split into back-to-back segments, run the
normal pipeline on each, and merge the segments into one ordinary run (runs/<id>/result.json in the same format),
so the review screen, the human queue and the CSV export work on it unchanged.

Boundary design (why the merge is exact for the survey numbers):
- The video is re-encoded once to 5 fps, then cut by frame number into contiguous, non-overlapping segments of equal
  length (ceil(N / k) frames for the smallest k that keeps each segment within the limit; no short leftover piece).
  Every frame belongs to exactly one segment.
- MaxN and first arrival are per-frame quantities: the count curve of the whole video is the segments' curves laid
  end to end. So whole-video MaxN = the largest segment MaxN, and first arrival = segment start + time within the
  segment. Nothing is double-counted at a cut, because no frame is counted twice.
- What a cut does change: an animal on screen across a cut becomes two tracks (one per segment) and can appear twice
  in the human queue; and each segment picks animals up afresh, as any clip does (SAM starts a track once an animal is
  clearly in view; the discovery step's reversed pass back-fills the earlier frames within the segment). Neither
  touches MaxN, which counts boxes in one frame.
- Names: each segment's Spark names its own animals, so one kind can come out under two names ("chambered nautilus"
  in one segment, "nautilus" in another). Rows are merged only on the exact same name. Names that share a head noun
  are listed in result["name_variants"] for the reviewer, who can rename one to the other on the review screen (the
  counts are then recomputed). They are never merged silently: "hermit crab" and "red crab" share a head noun too.
- Links across a cut (boundary_links): a box in the last frame before a cut and one in the first frame after it that
  overlap (IoU >= 0.3) are recorded as one animal continuing; if the two sides counted it under different names, the
  pair is added to name_variants for the reviewer. Counts are unchanged.
- Evidence frames, the annotated video and the queue thumbnails come from the segment runs (an evidence image is
  labelled with the frame number inside its segment; result["segments"] gives each segment's start)."""
import concurrent.futures as cf, json, math, os, re, shutil, subprocess, sys, threading, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fishcount import api, pipeline, render, screen, tracks, video

MAX_SEGMENT_S = 600          # one SAM 3.1 video call takes up to 10 minutes


def needs_split(inf, segment=None, skip_empty=False):
    """Whether the CLI runs a video through run_long (segments) rather than run_pipeline: asked for (segment,
    skip_empty), longer than MAX_SEGMENT_S, or of unknown length. A raw .h264 stream has no frame count (OpenCV
    gives a negative one), so it took the short path and run_pipeline analysed its first 600 s only (round 3,
    11/21c); run_long re-encodes the whole file first and splits by the frames it actually got."""
    if segment or skip_empty:
        return True
    if not inf.get("fps") or not 0 < inf.get("n_frames", 0) < 10 ** 9:
        return True
    return inf["n_frames"] / inf["fps"] > MAX_SEGMENT_S
CAP_PER_HOUR_SPLIT = 6       # long video default whole-video cap, $ an hour (user, 11/21 22:01)
CAP_PER_HOUR_SKIP_EMPTY = 4  # --skip-empty default whole-video cap (11/11)
CAP_MIN_USD = 1              # a long video's default cap is never below this (not --skip-empty: as before)


def _up(usd):
    """usd rounded up to the cent, for "give ... or more" (0.15 * 100 is 15.000000000000002, not 16 cents)."""
    return math.ceil(round(usd * 100, 6)) / 100


def first_pass_floor(n, prompts):
    """F: the --prompts words' first pass on n frames as if nothing were cached, the least a segment is given."""
    return len(dict.fromkeys(prompts or ["fish"])) * max(api.SAM_MIN_FRAMES, n) * api.SAM_PER_FRAME


def video_cap(floors, given, default, offline=False):
    """-> (the video cap used, a note when the default was raised). given: the cap a person set (None: default).
    A cap set below the first pass of every segment stops the run before anything is paid (it could not be kept);
    a default below it is raised to it and said. Offline nothing is paid: the cap is only recorded."""
    need = sum(floors)
    if given is not None:
        if given + 1e-9 < need and not offline:
            raise api.BudgetExceeded(f"video cap ${given:.2f} is below the first pass of the --prompts words on every "
                                     f"segment, ${need:.2f}: give --max-usd-video {_up(need):.2f} or more")
        return given, None
    if default + 1e-9 < need:
        return need, (f"video cap raised from the default ${default:.2f} to ${need:.2f}, the first pass of the --prompts "
                      "words on every segment")
    return default, None


def short_cap(max_usd, max_usd_video, floor, offline=False):
    """A short video's cap: --max-usd, else --max-usd-video, else $1 raised to its first pass F when below it (as a
    long video's default is) -> (cap, note or None). A cap set below F stops before anything is paid (else the
    scout / discover Spark calls were paid and then the --prompts words stopped the run with no result)."""
    given = max_usd if max_usd is not None else max_usd_video
    if given is not None:
        if given + 1e-9 < floor and not offline:
            raise api.BudgetExceeded(f"cap ${given:.2f} is below the first pass of the --prompts words, ${floor:.2f}: "
                                     f"give --max-usd {_up(floor):.2f} or more")
        return given, None
    if floor > 1.0 + 1e-9:
        return floor, f"cap raised from the default $1.00 to ${floor:.2f}, the first pass of the --prompts words"
    return 1.0, None


def shares(floors, cap, ceiling=None, offline=False):
    """Each segment's cap: its floor F_k plus an equal part of what the video cap has over the floors, so the shares
    add up to max(cap, sum F) even when the floors differ (a short last segment); at most ceiling (--max-usd). A
    ceiling set below a segment's F stops before anything is paid (offline: F). Fixed: the same whatever order or how
    many at once the segments run, and a segment that spends less passes nothing on."""
    if ceiling is not None and ceiling + 1e-9 < max(floors) and not offline:
        raise api.BudgetExceeded(f"per-segment cap --max-usd ${ceiling:.2f} is below the first pass of the --prompts "
                                 f"words on a segment, ${max(floors):.2f}: give --max-usd {_up(max(floors)):.2f} or more, "
                                 "or leave it out")
    extra = max(0.0, cap - sum(floors)) / len(floors)
    return [round(max(f, f + extra if ceiling is None else min(ceiling, f + extra)), 4) for f in floors]


def video_spent(rid, t0, path=None):
    """(usd, billed_no_result) of the ledger rows from t0 on whose run is rid or one of its segments / probes
    (rid__S<n>, rid__P<n>). billed_no_result: SAM calls whose stream broke after SAM took them (logged as billed,
    api._sam_live; nothing came back). Broken lines and lines without usd are skipped."""
    pat = re.compile(re.escape(rid) + r"(__[SP]\d+)?")
    usd, broke = 0.0, 0
    try:
        f = open(path or api.LEDGER)
    except OSError:
        return 0.0, 0
    with f:
        for line in f:
            try:
                r = json.loads(line)
                u, t = float(r["usd"]), float(r.get("t", 0))
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
            if t >= t0 and isinstance(r.get("run"), str) and pat.fullmatch(r["run"]):
                usd += u
                broke += str(r.get("note", "")).endswith("(stream broke)")
    return usd, broke


def _budget(rid, t0, cap, parts, capped):
    """result["budget"] when the video spent more than its cap or anything was left out, else None. parts: what this
    try's runs spent on the first pass's SAM calls, later SAM calls and Spark (their status.json)."""
    spent, broke = video_spent(rid, t0)
    if spent <= cap + 1e-9 and not capped:
        return None
    return dict(cap=round(cap, 4), spent=round(spent, 4), over=round(max(0.0, spent - cap), 4), billed_no_result=broke,
                parts={k: round(v, 4) for k, v in parts.items()})


def _parts(parts, sst):
    """Add one run's status.json to the budget parts."""
    first, spark = sst.get("first_pass_sam_usd", 0.0), sst.get("spark_usd", 0.0)
    parts["first_sam"] += first
    parts["spark"] += spark
    parts["later_sam"] += sst.get("billed_usd", 0.0) - first - spark


def plan(n_frames, fps, seg_s):
    """[(start_frame, n_frames)] covering 0..n_frames-1, equal lengths, each <= seg_s seconds."""
    cap = max(1, int(seg_s * fps))
    k = max(1, math.ceil(n_frames / cap))
    size = math.ceil(n_frames / k)
    return [(s, min(size, n_frames - s)) for s in range(0, n_frames, size)]


def cut(clip, dst, start, n):
    """Frames start..start+n-1 of a 5 fps clip, by frame number (exact), re-encoded like video.ingest. Entered by
    seeking (video.seek_args) rather than a select filter that decodes everything before `start`: same bytes
    (11/21: LONG1 S2 and S6 cut both ways, identical sha256), 46-50 s -> 26 s a 600-s segment."""
    if round(video.info(clip)["fps"], 6) == 5:
        cmd = [*video.seek_args(start, 5), "-i", clip, "-frames:v", str(n), "-vf", "setpts=N/5/TB"]
    else:
        cmd = ["-i", clip, "-vf", f"select=between(n\\,{start}\\,{start + n - 1}),setpts=N/5/TB"]
    subprocess.run([video.FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *cmd, "-r", "5", "-fps_mode", "cfr",
                    "-an", "-c:v", "libx264", *video.X264_ARGS, "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", dst], check=True)
    got = video.info(dst)["n_frames"]
    if got != n:
        raise RuntimeError(f"segment {os.path.basename(dst)}: wanted {n} frames, got {got}")


def _concat(paths, dst):
    lst = dst + ".txt"
    with open(lst, "w") as f:
        f.writelines(f"file '{os.path.abspath(p)}'\n" for p in paths)
    subprocess.run([video.FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst,
                    "-c", "copy", dst], check=True)
    os.remove(lst)


def _status(d, **kw):
    p = os.path.join(d, "status.json")
    st = json.load(open(p)) if os.path.exists(p) else dict(log=[])
    st.update(kw)
    with open(p + ".tmp", "w") as f:
        json.dump(st, f, indent=1)
    os.replace(p + ".tmp", p)
    return st


BOUNDARY_IOU = 0.3


def boundary_links(frames, cuts, labels, thr=BOUNDARY_IOU):
    """Tracks that continue across a cut: a box in the last frame before the cut and one in the first frame after it
    overlapping at IoU >= thr, paired one to one (highest IoU first). Each link records both counted names (None =
    not counted); name_conflict = both counted under different names. Counts are not changed: MaxN counts boxes in
    one frame and no frame belongs to two segments; the links tell a reviewer which two queue items are one animal."""
    out = []
    for c in cuts:
        before, after = frames.get(c - 1, []), frames.get(c, [])
        cand = sorted(((tracks.iou(a["box"], b["box"]), i, j) for i, a in enumerate(before) for j, b in enumerate(after)),
                      reverse=True)
        used_a, used_b = set(), set()
        for v, i, j in cand:
            if v < thr or i in used_a or j in used_b:
                continue
            used_a.add(i); used_b.add(j)
            ta, tb = before[i]["track"], after[j]["track"]
            la, lb = labels.get(ta), labels.get(tb)
            out.append(dict(cut_frame=c, before=ta, after=tb, before_label=la, after_label=lb, iou=round(v, 3),
                            name_conflict=bool(la and lb and la != lb)))
    return out


def merge(rid, src_name, segs, fps, out_dir=None, n_total=None, carry=None, videos=True):
    """segs: [(segment run dir, start_frame, n_frames)] in order. Writes <out_dir or runs/rid>/result.json etc.
    --skip-empty only: n_total = the video's length (the last stretch may not have been sent); carry = [(a, b)]
    skipped stretches, each given frame a-1's boxes (the last analysed frame), marked carried, listed in
    result["skipped"]; videos=False leaves the review videos to the caller (it adds the skipped pieces)."""
    d = out_dir or os.path.join(pipeline.RUNS, rid)
    os.makedirs(os.path.join(d, "thumbs"), exist_ok=True)
    R = dict(id=rid, source=src_name, prompts=[], jobs=[], scout=[], tracks={}, verdicts={}, auto_labels={},
             discovered=[], signs=[], recovered=[], peak_checks=[], duplicates=[], crowd_checks=[], frames={}, segments=[])
    frames, total, W, H, capped = {}, 0, None, None, []
    for k, (sd, start, n) in enumerate(segs):
        res = json.load(open(os.path.join(sd, "result.json")))
        p, tag = f"S{k + 1}:", f"S{k + 1}"
        W, H = res["video"]["width"], res["video"]["height"]
        if res["video"]["n_frames"] != n:
            raise RuntimeError(f"{sd}: {res['video']['n_frames']} frames, plan said {n}")
        total = max(total, start + n)
        R["segments"].append(dict(segment=tag, run=os.path.basename(sd), start_frame=start, n_frames=n,
                                  start_s=round(start / fps, 2), maxn={m: v["maxn"] for m, v in res["metrics"].items()}))
        for pl in res.get("prompts", []):
            if pl not in R["prompts"]:
                R["prompts"].append(pl)
        R["jobs"] += [dict(j, name=p + j["name"], segment=tag) for j in res.get("jobs", [])]
        if res.get("site"):      # opt-in site memory (docs/site_memory.md): one block, entries tagged with their segment
            R.setdefault("site", dict(name=res["site"]["name"], entries=[]))["entries"] += [
                dict(e, source=p + e["source"], segment=tag) for e in res["site"].get("entries", []) if e.get("source")]
        R["scout"].append(dict(segment=tag, **(res.get("scout") or {})))
        for t, v in res["tracks"].items():
            R["tracks"][p + t] = dict(v, source=p + v["source"], first=v["first"] + start if v["first"] is not None else None,
                                    last=v["last"] + start if v["last"] is not None else None, segment=tag)
        for t, v in res.get("verdicts", {}).items():
            nm = f"{tag}-{v.get('name')}"
            R["verdicts"][p + t] = dict(v, name=nm, frame=(v["frame"] + start) if isinstance(v.get("frame"), int) else v.get("frame"))
            for suffix in (".jpg", "_trio.jpg"):
                a = os.path.join(sd, "thumbs", f"{v.get('name')}{suffix}")
                if os.path.exists(a):
                    shutil.copy(a, os.path.join(d, "thumbs", f"{nm}{suffix}"))
        R["auto_labels"].update({p + t: l for t, l in res.get("auto_labels", {}).items()})
        if "queue_conf" in res:     # --queue-conf (pipeline.unqueue): only when not 0.7, as in a segment's result
            R["queue_conf"] = res["queue_conf"]
        for key in ("discovered", "signs", "recovered"):
            R[key] += [dict(x, segment=tag) if isinstance(x, dict) else x for x in res.get(key, [])]
        R["peak_checks"] += [dict(c, frame=c["frame"] + start, segment=tag) for c in res.get("peak_checks", [])]
        R["duplicates"] += [dict(x, outer=p + x["outer"], inner=p + x["inner"], frame=x["frame"] + start, segment=tag)
                            for x in res.get("duplicates", [])]
        R["crowd_checks"] += [dict(c, frame=c["frame"] + start, segment=tag) for c in res.get("crowd_checks", [])]
        capped += [dict(c, segment=tag) for c in res.get("capped", [])]
        for f, ks in res["frames"].items():
            frames[int(f) + start] = [dict(kk, track=p + kk["track"]) for kk in ks]
    total = n_total or total
    R["video"] = dict(n_frames=total, fps=fps, width=W, height=H)
    if capped:          # stages a segment skipped at the cap: that segment is half analysed
        R["capped"] = capped
    if carry is not None:
        R["skipped"] = []
        for a, b in carry:
            src = frames.get(a - 1, [])
            for f in range(a, b) if src else ():
                frames[f] = [dict(k, carried=True) for k in src]
            for k in src:
                t = R["tracks"][k["track"]]
                t.update(last=max(t["last"], b - 1), n=t.get("n", 0) + b - a)
            R["skipped"].append(dict(start_frame=a, end_frame=b, start_s=round(a / fps, 2), end_s=round(b / fps, 2), carried=len(src)))
    R["boundary_links"] = boundary_links(frames, [start for _, start, _ in segs[1:]], R["auto_labels"])
    m = tracks.metrics(frames, R["tracks"], total, fps, R["auto_labels"])
    checked = {(c["label"], c["frame"]) for c in R["peak_checks"]}
    for name, mm in m.items():
        mm["peak_checked"] = (name, mm["maxn_frame"]) in checked
    R["metrics"] = m
    # a segment's crowd check counted its own peak; judged again against the whole video's row (labels, MaxN)
    rows = {r[0]: r for r in pipeline.crowd_rows(m, fps)}
    for c in R["crowd_checks"]:
        r = rows.get(c["row"])
        if r is None or c.get("total") is None:
            c["lower_bound"] = False
            continue
        c.update(labels=r[1], maxn=r[2], lower_bound=c["total"] >= r[2] + pipeline.CROWD_MIN_EXTRA and c["total"] >= pipeline.CROWD_RATIO * r[2])
    heads = {}
    for name in m:
        h = pipeline._head(name)
        if h:
            heads.setdefault(h, []).append(name)
    R["name_variants"] = [sorted(v) for v in heads.values() if len(v) > 1]
    for b in R["boundary_links"]:       # one animal across a cut, named differently on each side: a person picks
        if not b["name_conflict"]:      # an uncounted side has label None (11/4 LONG1_cr9: sorted() failed on it)
            continue
        pair = sorted({b["before_label"], b["after_label"]})
        if pair not in R["name_variants"]:
            R["name_variants"].append(pair)
    R["frames"] = {str(f): ks for f, ks in sorted(frames.items())}
    with open(os.path.join(d, "result.json"), "w") as f:
        json.dump(R, f)
    # evidence: the segment holding the whole-video MaxN frame drew it
    for name, mm in m.items():
        if mm["maxn_frame"] is None:
            continue
        ev = f"evidence_{pipeline.api_safe(name)}.jpg"
        for sd, start, n in segs:
            if start <= mm["maxn_frame"] < start + n and os.path.exists(os.path.join(sd, ev)):
                shutil.copy(os.path.join(sd, ev), os.path.join(d, ev))
                break
    if videos:
        _review_videos(d, [sd for sd, _, _ in segs])
    return R


def _review_videos(d, dirs):
    """The review screen's videos: each piece's clip/annotated/clip_original laid end to end, in the order given."""
    for kind in ("clip.mp4", "annotated.mp4", "clip_original.mp4"):
        parts = [os.path.join(x, kind) for x in dirs]
        if parts and all(os.path.exists(x) for x in parts):
            _concat(parts, os.path.join(d, kind))


def _fingerprint(seg_clip, kw):
    """What a finished segment's result depends on: its clip's bytes, the run options (except offline: a replay from
    cache gives the same result as the live run that filled it; nor the cap, which _kept compares on its own) and the
    code (every fishcount/*.py file)."""
    h = __import__("hashlib").sha256()      # seg_clip None: options and code only (budget.json, the whole video)
    here = os.path.dirname(os.path.abspath(__file__))
    for f in sorted(os.listdir(here)):
        if f.endswith(".py"):
            h.update(f.encode() + open(os.path.join(here, f), "rb").read())
    opts = {k: v for k, v in kw.items() if k not in ("offline", "max_usd")}     # the cap: resume.json, _kept
    if api.sam_backend() == "local":    # an API segment is not kept for a local run, nor one of another checkpoint
        opts["sam_backend"] = api.local_tag()
    return dict(clip=api.file_sha(seg_clip) if seg_clip else None, options=json.loads(json.dumps(opts, sort_keys=True, default=repr)),
                code=h.hexdigest()[:24])


def _drop_cut(sp):
    """A finished segment's cut from the whole video: its folder holds the same bytes as clip.mp4 (run_pipeline copies a
    5-fps mp4), and --resume cuts again to compare bytes, so the cut is not kept (1.94 of the 53-min NOAA video's
    6.6 GB). A segment that failed keeps its cut. FISH_KEEP_TEMP=1 keeps it."""
    if os.environ.get("FISH_KEEP_TEMP") != "1" and os.path.exists(sp):
        os.remove(sp)


REVIEW_VIDEOS = ("clip.mp4", "annotated.mp4", "clip_original.mp4")     # what _review_videos lays end to end


def _bytes(d, names=None):
    """Bytes under folder d (names: only these files at its top)."""
    tot = 0
    for root, _, fs in os.walk(d):
        for f in fs:
            if names is None or (root == d and f in names):
                try:
                    tot += os.path.getsize(os.path.join(root, f))
                except OSError:     # removed while walking (another worker's temp cut)
                    pass
    return tot


def disk_need(seg_bytes, review_bytes, left, n_segs):
    """Bytes the rest of a long run may still write: each segment left like the largest segment folder so far, plus the
    merged review videos (one more copy of every segment's clip / annotated / clip_original, as large as the largest
    so far). Measured, no constants: a segment folder is mostly its clip, whose size follows its length, so the first
    segment already says most of it. The whole-video re-encode is freed only after the merge, so it is not counted."""
    return max(seg_bytes) * left + max(review_bytes) * n_segs


FORECAST_MIN = 2 # segments run before a range is given: one segment is a point, not a range


def forecast(costs, secs, left, workers=1):
    """What the segments still to run may cost, from the segments this run has finished: each left segment between the
    cheapest and the dearest one so far, in dollars and wall seconds. No constants: segments of one video differ a lot
    (the 53-min NOAA video's cold segments cost $1.63 to $5.88), so the range is the honest answer and it narrows only
    by being measured. The pipeline's own 'est' line counts the first pass alone (2.8-5.1x under on that video).
    From FORECAST_MIN segments on. Backtest on saved runs (after 2-5 segments, dollars and minutes): the NOAA video's
    cold run 8 of 8 inside, its partly cached runs 6, 4 and 4 of 8, the second NOAA video (cache only) 8 of 8; the
    misses are a dearer segment still to come, so it is a range from what has been seen, not a cap. After 1 segment
    ($0.54) it would have said $2.72 for a rest that cost $14.54.
    workers segments run at once: the time range is min x left/workers to max x ceil(left/workers).
    -> dict(left, usd=[lo, hi], s=[lo, hi]) or None before FORECAST_MIN segments have run or when nothing is left."""
    if len(costs) < FORECAST_MIN or left <= 0:
        return None
    w = max(1, int(workers or 1))
    return dict(left=left, usd=[round(min(costs) * left, 3), round(max(costs) * left, 3)],
                s=[round(min(secs) * left / w), round(max(secs) * math.ceil(left / w))])


def run_long(src, rid=None, *a, **kw):
    """_run_long (below: every option), and on any exception the video's status.json says "error" (pipeline.mark_error;
    a segment that raised has its own folder marked by run_pipeline too)."""
    rid = rid or time.strftime("%m%d-%H%M%S")
    try:
        return _run_long(src, rid, *a, **kw)
    except BaseException as e:
        pipeline.mark_error(os.path.join(pipeline.RUNS, rid), e)
        raise


def _kept(sd, fp, resume, cap=None):
    """True when --resume finds a finished run of this segment with the same fingerprint (_fingerprint) and its result
    holds: nothing left out at its cap, or this cap is no higher than the one it ran with (raising the cap runs only
    the cut segments again). A segment FISH_BUDGET cut (capped reason "fish") always runs again. resume.json =
    {"fp", "cap"}; the old form (the fingerprint alone) has no cap."""
    rp, res = os.path.join(sd, "resume.json"), os.path.join(sd, "result.json")
    if not (resume and os.path.exists(rp) and os.path.exists(res)):
        return False
    try:
        j = json.load(open(rp))
        capped = json.load(open(res)).get("capped") or []
    except (ValueError, AttributeError):
        return False
    old_fp, old_cap = (j.get("fp"), j.get("cap")) if isinstance(j, dict) and "fp" in j else (j, None)
    if old_fp != fp or any(isinstance(c, dict) and c.get("reason") == "fish" for c in capped):
        return False
    return not capped or (old_cap is not None and cap is not None and cap <= old_cap + 1e-9)


def _run_long(src, rid=None, seg_s=MAX_SEGMENT_S, skip_empty=False, max_usd_video=None, probe_every_s=None,
              segment_workers=1, resume=False, upload_ahead=False, **kw):
    """Split `src` into segments of at most seg_s seconds, run the pipeline on each, merge. kw -> run_pipeline.
    skip_empty: only the stretches screen.scan picks are sent (_run_skipping); max_usd_video caps the whole video
    (default $4 an hour), probe_every_s overrides screen.PROBE_EVERY_S.
    segment_workers: segments run at once (threads in this process; default 1 = one after another). A segment spends
    most of its time waiting on SAM, so two at once nearly halve the wall time; the answers are the same (each segment
    is its own run, the merge takes them in order). Memory: one segment peaks at ~1.1 GB plus ~2.3 GB while ffmpeg
    reverses a 600-frame chunk, and video.reverse lets one chunk be reversed at a time in the process, so two workers
    peaked at 3.3 GB (11/21, LONG1 S1 + S6 replayed in one 4 GB cgroup); each worker past two adds ~1.2 GB.
    Not used with skip_empty, whose video cap is paid out segment by segment.
    resume: a segment whose folder already holds a finished run of the same clip bytes, options and code
    (resume.json, written whenever a segment finishes) is not run again; the merge reads its saved result. After a crash
    (OOM, network, a bug in the merge) only the unfinished segments run: a fully cached 600-s segment still takes about
    5 minutes to replay. Not used with skip_empty.
    upload_ahead (on in the CLI, --no-upload-ahead; off here so library callers and tests never upload unasked): while
    segment k runs, segment k+1 is cut and its clip uploaded in a background thread, so its first SAM call finds the
    file id waiting instead of sending ~360 MB first (round 3, 11/21c: 4.5-11 min a segment on this server's 0.53-1.3
    MB/s uplink, against 27-43 min for a live LONG1 segment). The upload only gives SAM a file id for the same bytes
    (api._upload, keyed by content; a call for a clip still going up waits for that upload), so answers, cache keys
    and the merge are unchanged. Only one segment at a time, live, and when the segment's clip.mp4 is the cut's bytes
    (not brightened, not --haze); a segment --resume keeps is not uploaded; a failed upload ahead is logged and left
    to the segment's own first call. A fully cached live rerun uploads clips it does not need (free, uplink only)."""
    rid = rid or time.strftime("%m%d-%H%M%S")
    d = os.path.join(pipeline.RUNS, rid)
    os.makedirs(d, exist_ok=True)
    t0 = time.time()
    try:        # the try before this one: only one that died half-way is continued on the same budget (--resume)
        prev = json.load(open(os.path.join(d, "status.json"))).get("stage")
    except (OSError, ValueError, AttributeError):
        prev = None
    st = _status(d, id=rid, stage="ingest", started=t0, log=[f"{time.strftime('%H:%M:%S')} re-encoding to 5 fps (whole video)"])
    full = os.path.join(d, "full_5fps.mp4")
    src_warn = (video.ingest(src, full, max_seconds=10 ** 7) or {}).get("source_warnings") or []
    for w in src_warn:      # cut short or damaged source (round 3): said once for the whole video
        st["log"].append(f"{time.strftime('%H:%M:%S')} WARNING: {w}")
    if src_warn:
        st = _status(d, log=st["log"], source_warnings=src_warn)
    inf = video.info(full)
    if src_warn:
        inf["source_warnings"] = src_warn       # into the merged result's "video" (both paths), only when there are any
    # low-light is decided once for the whole video, so every segment gets the same treatment
    light = video.light_stats(full)
    mode = kw.get("lowlight", "auto")
    light.update(mode=mode, brightened=mode == "on" or (mode == "auto" and video.is_dark(light)))
    kw["lowlight"] = "on" if light["brightened"] else "off"
    if kw.get("haze", "off") != "off":      # --haze: also decided once, on the whole video (not for a dark one)
        hz = video.contrast_stats(full)
        hz.update(mode=kw["haze"], applied=not light["brightened"] and (kw["haze"] == "on" or video.is_hazy(hz)))
        light["haze"] = hz
        kw["haze"] = "on" if hz["applied"] else "off"
    inf["lowlight"] = light
    if skip_empty:
        if segment_workers > 1:
            st["log"].append(f"{time.strftime('%H:%M:%S')} segment_workers={segment_workers} not used with skip_empty "
                             "(the video cap is paid out segment by segment): one segment at a time")
        return _run_skipping(src, rid, d, full, inf, light, st, t0, seg_s, max_usd_video, probe_every_s, kw)
    segs = plan(inf["n_frames"], inf["fps"], seg_s)
    workers = max(1, min(int(segment_workers or 1), len(segs)))
    floors = [first_pass_floor(n, kw.get("prompts")) for _, n in segs]
    default = max(CAP_MIN_USD, round(inf["n_frames"] / inf["fps"] / 3600 * CAP_PER_HOUR_SPLIT, 2))
    cap, raised = video_cap(floors, max_usd_video, default, kw.get("offline"))
    share = shares(floors, cap, kw.pop("max_usd", None), kw.get("offline"))
    bp, vfp = os.path.join(d, "budget.json"), _fingerprint(None, kw)
    try:    # t0 carries over only from a try that died half-way with the same options and code (H3)
        old = json.load(open(bp)) if resume and prev not in (None, "done") else {}
        bt0 = float(old["t0"]) if old.get("fp") == vfp else t0
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        bt0 = t0
    with open(bp, "w") as f:
        json.dump(dict(t0=bt0, cap=cap, fp=vfp), f)
    st["log"].append(f"{time.strftime('%H:%M:%S')} video cap ${cap:.2f} "
                     + ("(--max-usd-video)" if max_usd_video is not None else f"(default ${CAP_PER_HOUR_SPLIT} an hour)")
                     + f", each segment ${share[0]:.2f}" + (f"; {raised}" if raised else "")
                     + (f"; discovered words probed on +-{kw['probe_window']} frames first" if kw.get("probe_window") else ""))
    if not kw.get("offline"):
        warn = api.budget_warning(sum(floors))
        if warn:
            print(f"WARNING: {warn}", file=sys.stderr)
            st["log"].append(f"{time.strftime('%H:%M:%S')} WARNING: {warn}")
    st["log"].append(f"{time.strftime('%H:%M:%S')} {inf['n_frames']} frames -> {len(segs)} segment(s) of <= {seg_s:g} s: "
                     + ", ".join(f"{s}+{n}" for s, n in segs) + (f"; {workers} at once" if workers > 1 else ""))
    _status(d, stage="segments", log=st["log"], video=inf)
    tally, lock, failed = dict(live=0, cached=0, billed=0.0, kept=0), threading.Lock(), threading.Event()
    parts = dict(first_sam=0.0, later_sam=0.0, spark=0.0)
    ran = dict(usd=[], s=[], finished=0)     # segments run (not kept) this time: their spend and wall time
    room = dict(seg=[], review=[], warned=False)    # every finished segment's folder bytes, for disk_need
    ahead = {}      # k -> dict(ev=Event set once the look-ahead has cut segment k, ok=whether that cut worked)
    look = (upload_ahead and workers == 1 and not kw.get("offline") and kw.get("lowlight") == "off"
            and kw.get("haze", "off") == "off" and api.sam_backend() == "api" and not api.PRIVATE)   # local SAM: never
    if upload_ahead and workers > 1 and not kw.get("offline"):     # the CLI asks for both by default (D-DEFAULTS)
        st["log"].append(f"{time.strftime('%H:%M:%S')} upload ahead not used with {workers} segments at once (the "
                         "other segment keeps running while one uploads); --segment-workers 1 for it")

    def note(msg):
        with lock:      # written to status.json with the next segment's line
            st["log"].append(f"{time.strftime('%H:%M:%S')} {msg}")

    def look_ahead(k):
        """Cut segment k and upload its clip while k-1 runs (upload_ahead). Never raises."""
        start, n = segs[k]
        sp, a = os.path.join(d, f"seg{k + 1}.mp4"), ahead[k]
        try:
            cut(full, sp, start, n)
            a["ok"] = True
        except Exception as e:
            note(f"segment S{k + 1} cut ahead failed ({type(e).__name__}: {e}); it is cut when it starts")
            return
        finally:
            a["ev"].set()
        try:
            if failed.is_set() or _kept(os.path.join(pipeline.RUNS, f"{rid}__S{k + 1}"), _fingerprint(sp, kw), resume, share[k]):
                return
            t = time.time()
            api._upload(sp, api._key())
            note(f"segment S{k + 1} uploaded ahead in {time.time() - t:.0f}s")
        except Exception as e:
            note(f"segment S{k + 1} upload ahead failed ({type(e).__name__}: {str(e)[:120]}); "
                 "its first SAM call uploads it")

    def one(k, start, n):
        if failed.is_set():     # another segment raised: what has not started is not sent
            return None
        t_seg = time.time()
        sp = os.path.join(d, f"seg{k + 1}.mp4")
        if k in ahead:
            ahead[k]["ev"].wait()
        if not (k in ahead and ahead[k]["ok"]):
            cut(full, sp, start, n)
        if look and k + 1 < len(segs):
            ahead[k + 1] = dict(ev=threading.Event(), ok=False)
            threading.Thread(target=look_ahead, args=(k + 1,), daemon=True).start()
        srid = f"{rid}__S{k + 1}"
        sd = os.path.join(pipeline.RUNS, srid)
        fp = _fingerprint(sp, kw)
        rp = os.path.join(sd, "resume.json")
        kept = _kept(sd, fp, resume, share[k])
        if not kept:
            if os.path.exists(rp):      # a run that dies half-way must not leave an older fingerprint on its result
                os.remove(rp)
            mu = share[k]
            if bt0 != t0:   # a try that died half-way: what this segment spent in it is taken from its share (F kept)
                mu = round(max(floors[k], share[k] - video_spent(srid, bt0)[0]), 4)
            try:
                pipeline.run_pipeline(sp, srid, **dict(kw, max_usd=mu))
            except api.BudgetExceeded as e:
                failed.set()
                if "FISH_BUDGET" in str(e):
                    raise api.BudgetExceeded(f"FISH_BUDGET reached at S{k + 1}: raise it, then the same command with "
                                             f"--resume ({e})") from e
                raise
            except BaseException:
                failed.set()
                raise
            with open(rp, "w") as f:     # written on every run, so a run started without --resume can be resumed
                json.dump(dict(fp=fp, cap=share[k]), f)
        _drop_cut(sp)
        sst = json.load(open(os.path.join(sd, "status.json")))
        maxn = ", ".join(f"{m} {v['maxn']}" for m, v in json.load(open(os.path.join(sd, "result.json")))["metrics"].items())
        with lock:      # workers finish in any order; the log says which segment, the merge goes by segment order
            tally["kept"] += kept
            if not kept:    # a kept segment spent nothing this time
                _parts(parts, sst)
                tally["live"] += sst["live_calls"]
                tally["cached"] += sst["cached_calls"]
                tally["billed"] += sst["billed_usd"]
                ran["usd"].append(sst["billed_usd"])
                ran["s"].append(time.time() - t_seg)
            ran["finished"] += 1
            st["log"].append(f"{time.strftime('%H:%M:%S')} segment S{k + 1} ({start / inf['fps']:.1f}-{(start + n) / inf['fps']:.1f} s) "
                             + ("kept from the earlier run (--resume): " if kept else "done: ") + maxn)
            fc = forecast(ran["usd"], ran["s"], len(segs) - ran["finished"], workers)
            if fc:      # so a person watching a long batch sees where money and time are heading, not only the start
                st["log"].append(
                    f"{time.strftime('%H:%M:%S')} forecast: {len(ran['usd'])} segment(s) run so far ${sum(ran['usd']):.2f}, "
                    f"{sum(ran['s']) / 60:.0f} min; {fc['left']} left: ${fc['usd'][0]:.2f}-${fc['usd'][1]:.2f}, "
                    f"{fc['s'][0] / 60:.0f}-{fc['s'][1] / 60:.0f} min (each like the cheapest / dearest segment so far; "
                    "not a cap: a busier segment later costs more)")
            room["seg"].append(_bytes(sd))
            room["review"].append(_bytes(sd, REVIEW_VIDEOS))
            disk = dict(need=disk_need(room["seg"], room["review"], len(segs) - ran["finished"], len(segs)),
                        free=shutil.disk_usage(d).free)
            if disk["need"] > disk["free"] and not room["warned"]:     # said once, so a batch stops before the disk does
                room["warned"] = True
                st["log"].append(
                    f"{time.strftime('%H:%M:%S')} disk: the rest of this video may write about {disk['need'] / 1e9:.1f} GB "
                    f"(each segment left like the largest folder so far, plus the merged review videos), "
                    f"{disk['free'] / 1e9:.1f} GB free: free space or put runs/ on a bigger disk "
                    "(a run stopped by a full disk goes on with --resume)")
            _status(d, stage="segments", log=st["log"], live_calls=tally["live"], cached_calls=tally["cached"],
                    billed_usd=tally["billed"], forecast=fc, disk=disk)
        return sd, start, n

    if workers == 1:
        done = [one(k, start, n) for k, (start, n) in enumerate(segs)]
    else:
        with cf.ThreadPoolExecutor(workers) as ex:
            futs = [ex.submit(one, k, start, n) for k, (start, n) in enumerate(segs)]
            try:
                done = [f.result() for f in futs]
            except BaseException:
                failed.set()        # segments not started yet are not sent; the ones running finish their calls
                for f in futs:
                    f.cancel()
                raise
    live, cached, billed = tally["live"], tally["cached"], tally["billed"]
    R = merge(rid, os.path.basename(src), done, inf["fps"])
    R["video"]["lowlight"] = light
    if inf.get("source_warnings"):
        R["video"]["source_warnings"] = inf["source_warnings"]
    bud = None if kw.get("offline") else _budget(rid, bt0, cap, parts, R.get("capped"))
    if bud:
        R["budget"] = bud
        st["log"].append(_budget_line(bud, R))
    with open(os.path.join(d, "result.json"), "w") as f:
        json.dump(R, f)
    os.remove(full)
    t1 = time.time()
    st["log"].append(f"{time.strftime('%H:%M:%S')} merged {len(segs)} segment(s): "
                     + ", ".join(f"{m} MaxN {v['maxn']} at {v['maxn_time']} s" for m, v in R["metrics"].items())
                     + f"; finished in {t1 - t0:.0f}s; live calls {live}, cached {cached}, billed ${billed:.3f}")
    _status(d, stage="done", done=t1, log=st["log"], live_calls=live, cached_calls=cached, billed_usd=billed, video=R["video"],
            **(dict(budget=bud) if bud else {}))
    return R


def _budget_line(bud, R):
    segs = sorted({c.get("segment", "?") for c in R.get("capped", [])}, key=lambda x: (len(x), x))
    p = bud["parts"]
    return (f"{time.strftime('%H:%M:%S')} WARNING: budget: spent ${bud['spent']:.2f} of the ${bud['cap']:.2f} video cap"
            + (f" (${bud['over']:.2f} over)" if bud["over"] else "")
            + f"; first-pass SAM ${p['first_sam']:.2f}, later SAM ${p['later_sam']:.2f}, Spark ${p['spark']:.2f}"
            + (f"; {bud['billed_no_result']} SAM call(s) billed with no answer (stream broke)" if bud["billed_no_result"] else "")
            + (f"; stages left out in {', '.join(segs)} (result capped; raise --max-usd-video and run again with "
               "--resume: only those segments run)" if segs else ""))


def _agree(probe_dir, src_dir, src_frame, thr=BOUNDARY_IOU):
    """Does a probe see what is being carried? The probe's first second, frame with the most counted boxes, against
    the counted boxes of the carried frame, paired one to one at IoU >= thr: any box left unpaired = disagree.
    Names are not compared (Spark's names are not fixed); a box SAM missed on one frame is why the best of 5 is used.
    ponytail: counted boxes only, so a Spark that flips a box between counted and not costs a re-send (money, not a
    miss); a count difference on two probes in a row if real footage shows many."""
    def counted(res, f):
        lab = lambda t: res["auto_labels"].get(t, res["tracks"].get(t, {}).get("label"))
        return [k["box"] for k in res["frames"].get(str(f), []) if lab(k["track"])]
    pr, sr = (json.load(open(os.path.join(x, "result.json"))) for x in (probe_dir, src_dir))
    carried = counted(sr, src_frame)
    seen = max((counted(pr, f) for f in range(min(5, pr["video"]["n_frames"]))), key=len, default=[])
    if len(seen) != len(carried):
        return False
    cand = sorted(((tracks.iou(a, b), i, j) for i, a in enumerate(carried) for j, b in enumerate(seen)), reverse=True)
    ua, ub = set(), set()
    for v, i, j in cand:
        if v >= thr and i not in ua and j not in ub:
            ua.add(i); ub.add(j)
    return len(ua) == len(carried)


def _filler(full, d, a, b, R, brightened):
    """Review-video piece for frames a..b-1 that were not sent: cut and (if the video is dark) brightened as a
    segment is, annotated with the boxes carried over it (none for a stretch the cap left unsent)."""
    fd = os.path.join(d, f"skip{a}")
    os.makedirs(fd, exist_ok=True)
    clip = os.path.join(fd, "clip.mp4")
    if brightened:
        cut(full, os.path.join(fd, "clip_original.mp4"), a, b - a)
        video.brighten(os.path.join(fd, "clip_original.mp4"), clip)
    else:
        cut(full, clip, a, b - a)
    boxes = R["frames"].get(str(a), [])
    piece = dict(video=dict(n_frames=b - a, fps=R["video"]["fps"]), jobs=R["jobs"], auto_labels=R["auto_labels"],
                 tracks={k["track"]: R["tracks"][k["track"]] for k in boxes},
                 frames={str(i): boxes for i in range(b - a)} if boxes else {})
    render.annotate(clip, {}, piece, os.path.join(fd, "annotated.mp4"))
    return fd


def _run_skipping(src, rid, d, full, inf, light, st, t0, seg_s, cap, probe_every_s, kw):
    """run_long with --skip-empty: send what screen.scan picks; probes that disagree with the carried boxes re-send the
    stretch before them once. A cap set with --max-usd-video is a hard stop: each run gets what is left of it, and a
    cap or FISH_BUDGET stop keeps what was done and lists the rest as unsent. The default cap ($4 an hour, raised to
    the first pass of every planned send when below it) is paid out as run_long's: each send, re-sends included, an
    equal share of it (at least its own first pass, at most --max-usd); spending past it shows in result["budget"].
    FISH_BUDGET stops either."""
    fps, N = inf["fps"], inf["n_frames"]

    def log(msg, **fields):
        st["log"].append(f"{time.strftime('%H:%M:%S')} {msg}")
        _status(d, stage="segments", log=st["log"], **fields)

    wins = screen.scan(full, fps, **({} if probe_every_s is None else dict(probe_every_s=probe_every_s)))
    hard = cap is not None
    per = kw.pop("max_usd", None)
    floors = [first_pass_floor(w["n"], kw.get("prompts")) for w in wins] or [0.0]
    if not hard and per is not None and per + 1e-9 < max(floors) and not kw.get("offline"):
        raise api.BudgetExceeded(f"per-segment cap --max-usd ${per:.2f} is below the first pass of the --prompts words "
                                 f"on a stretch, ${max(floors):.2f}: give --max-usd {_up(max(floors)):.2f} or more, or leave it out")
    if hard:        # each run gets what is left of the video cap (a $1 per-run cap stops a 600 s run at its first estimate)
        note = f"video cap ${cap:.2f} (--max-usd-video: a hard stop; per-segment --max-usd {per} not used)"
    else:
        cap, raised = video_cap(floors, None, round(N / fps / 3600 * CAP_PER_HOUR_SKIP_EMPTY, 2), kw.get("offline"))
        even = cap / max(1, len(wins)) if per is None else min(cap / max(1, len(wins)), per)
        note = (f"video cap ${cap:.2f} (default ${CAP_PER_HOUR_SKIP_EMPTY} an hour), each send ${even:.2f}"
                + (f"; {raised}" if raised else ""))
    n_send = sum(w["n"] for w in wins if w["kind"] != "probe")
    log(f"--skip-empty: {len(wins)} stretch(es) to send, {n_send} of {N} frames ({100 * n_send / max(1, N):.1f}%) + "
        f"{sum(1 for w in wins if w['kind'] == 'probe')} probe(s): " + ", ".join(f"{w['kind']} {w['start']}+{w['n']}" for w in wins)
        + f"; {note}", video=inf)
    if not kw.get("offline"):
        warn = api.budget_warning(sum(floors))
        if warn:
            print(f"WARNING: {warn}", file=sys.stderr)
            log(f"WARNING: {warn}")
    done, probes, k, unsent = [], [], 0, None
    acc = dict(spent=0.0, live=0, cached=0, at=0)
    parts = dict(first_sam=0.0, later_sam=0.0, spark=0.0)

    def send(start, n, tag):
        srid, acc["at"] = f"{rid}__{tag}", start
        fl = first_pass_floor(n, kw.get("prompts"))
        if not hard and per is not None and per + 1e-9 < fl and not kw.get("offline"):     # a re-send: not paid
            raise api.BudgetExceeded(f"{tag}: per-segment cap --max-usd ${per:.2f} is below its first pass ${fl:.2f}")
        sp = os.path.join(d, f"{tag}.mp4")
        cut(full, sp, start, n)
        mu = max(0.0, cap - acc["spent"]) if hard else round(max(fl, even), 4)
        try:
            pipeline.run_pipeline(sp, srid, **dict(kw, max_usd=mu))
            _drop_cut(sp)
        finally:
            p = os.path.join(pipeline.RUNS, srid, "status.json")
            if os.path.exists(p):
                sst = json.load(open(p))
                _parts(parts, sst)
                acc.update(spent=acc["spent"] + sst.get("billed_usd", 0.0), live=acc["live"] + sst.get("live_calls", 0),
                           cached=acc["cached"] + sst.get("cached_calls", 0))
        log(f"{tag} ({start / fps:.1f}-{(start + n) / fps:.1f} s) done; video spend ${acc['spent']:.3f} of ${cap:.2f}",
            live_calls=acc["live"], cached_calls=acc["cached"], billed_usd=acc["spent"])
        return os.path.join(pipeline.RUNS, srid)

    for w in wins:
        try:
            if w["kind"] != "probe":
                k += 1
                done.append((send(w["start"], w["n"], f"S{k}"), w["start"], w["n"]))
                continue
            probe_dir = send(w["start"], w["n"], f"P{len(probes) + 1}")
            last_dir, last_start, last_n = done[-1]
            ok = _agree(probe_dir, last_dir, last_n - 1)
            probes.append(dict(start_frame=w["start"], n_frames=w["n"], run=os.path.basename(probe_dir), match=ok))
            # ponytail: the stretches were planned up front, so after a re-send the later "unchanged" calls still
            # compare with the old reference while the carried boxes come from the probe; re-plan from the probe if
            # probes disagree often on real footage.
            if not ok:          # re-send the skipped stretch up to the probe, once; the probe's run is kept as a segment
                a = last_start + last_n
                log(f"probe at {w['start'] / fps:.1f} s disagrees with the boxes carried from {(a - 1) / fps:.1f} s: re-sending {a}-{w['start']}")
                for s, n in plan(w["start"] - a, fps, seg_s):
                    k += 1
                    done.append((send(a + s, n, f"S{k}"), a + s, n))
                done.append((probe_dir, w["start"], w["n"]))
        except api.BudgetExceeded as e:
            unsent = acc["at"]
            log(f"stopped at {unsent / fps:.1f} s: {e}; the rest is not sent and not carried")
            break
    if not done:
        raise api.BudgetExceeded(f"nothing sent under the video cap ${cap:.2f}")
    end = N if unsent is None else unsent
    gaps, pos = [], 0
    for _, s, n in done:
        if s > pos:
            gaps.append((pos, s))
        pos = s + n
    if pos < end:
        gaps.append((pos, end))
    R = merge(rid, os.path.basename(src), done, fps, n_total=N, carry=gaps, videos=False)
    R["unsent"] = [] if unsent is None else [dict(start_frame=unsent, end_frame=N, start_s=round(unsent / fps, 2), end_s=round(N / fps, 2))]
    R["probes"] = probes
    sent = sum(n for _, _, n in done)
    R["skip_empty"] = dict(video_cap_usd=cap, billed_usd=round(acc["spent"], 4), sent_frames=sent,
                           probe_frames=sum(p["n_frames"] for p in probes), n_frames=N, sent_share=round(sent / max(1, N), 4))
    R["video"]["lowlight"] = light
    if inf.get("source_warnings"):
        R["video"]["source_warnings"] = inf["source_warnings"]
    bud = None if kw.get("offline") else _budget(rid, t0, cap, parts, R.get("capped") or R["unsent"])
    if bud:
        R["budget"] = bud
        st["log"].append(_budget_line(bud, R))
    pieces = [(s, sd) for sd, s, _ in done]
    for a, b in gaps + [(u["start_frame"], u["end_frame"]) for u in R["unsent"]]:
        pieces.append((a, _filler(full, d, a, b, R, light["brightened"])))
    _review_videos(d, [x for _, x in sorted(pieces)])
    with open(os.path.join(d, "result.json"), "w") as f:
        json.dump(R, f)
    os.remove(full)
    t1 = time.time()
    n_cap = len({c["segment"] for c in R.get("capped", [])})
    st["log"].append(f"{time.strftime('%H:%M:%S')} merged {len(done)} sent segment(s), {len(gaps)} skipped stretch(es) carried, "
                     f"{len(probes)} probe(s) ({sum(not p['match'] for p in probes)} disagreed): "
                     + ", ".join(f"{m} MaxN {v['maxn']} at {v['maxn_time']} s" for m, v in R["metrics"].items())
                     + f"; cap: {len(R['unsent'])} stretch(es) not sent, {n_cap} segment(s) with stages skipped"
                     + f"; finished in {t1 - t0:.0f}s; live calls {acc['live']}, cached {acc['cached']}, billed ${acc['spent']:.3f}")
    _status(d, stage="done", done=t1, log=st["log"], live_calls=acc["live"], cached_calls=acc["cached"], billed_usd=acc["spent"], video=R["video"],
            **(dict(budget=bud) if bud else {}))
    return R
