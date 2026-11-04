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
import json, math, os, shutil, subprocess, sys, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fishcount import api, pipeline, tracks, video

MAX_SEGMENT_S = 600          # one SAM 3.1 video call takes up to 10 minutes


def plan(n_frames, fps, seg_s):
    """[(start_frame, n_frames)] covering 0..n_frames-1, equal lengths, each <= seg_s seconds."""
    cap = max(1, int(seg_s * fps))
    k = max(1, math.ceil(n_frames / cap))
    size = math.ceil(n_frames / k)
    return [(s, min(size, n_frames - s)) for s in range(0, n_frames, size)]


def cut(clip, dst, start, n):
    """Frames start..start+n-1 of a 5 fps clip, by frame number (exact), re-encoded like video.ingest."""
    subprocess.run([video.FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-i", clip,
                    "-vf", f"select=between(n\\,{start}\\,{start + n - 1}),setpts=N/5/TB", "-r", "5", "-fps_mode", "cfr",
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


def merge(rid, src_name, segs, fps, out_dir=None):
    """segs: [(segment run dir, start_frame, n_frames)] in order. Writes <out_dir or runs/rid>/result.json etc."""
    d = out_dir or os.path.join(pipeline.RUNS, rid)
    os.makedirs(os.path.join(d, "thumbs"), exist_ok=True)
    R = dict(id=rid, source=src_name, prompts=[], jobs=[], scout=[], tracks={}, verdicts={}, auto_labels={},
             discovered=[], signs=[], recovered=[], peak_checks=[], duplicates=[], frames={}, segments=[])
    frames, total, W, H = {}, 0, None, None
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
            R["tracks"][p + t] = dict(v, source=p + v["source"], first=v["first"] + start, last=v["last"] + start, segment=tag)
        for t, v in res.get("verdicts", {}).items():
            nm = f"{tag}-{v.get('name')}"
            R["verdicts"][p + t] = dict(v, name=nm, frame=(v["frame"] + start) if isinstance(v.get("frame"), int) else v.get("frame"))
            for suffix in (".jpg", "_trio.jpg"):
                a = os.path.join(sd, "thumbs", f"{v.get('name')}{suffix}")
                if os.path.exists(a):
                    shutil.copy(a, os.path.join(d, "thumbs", f"{nm}{suffix}"))
        R["auto_labels"].update({p + t: l for t, l in res.get("auto_labels", {}).items()})
        for key in ("discovered", "signs", "recovered"):
            R[key] += [dict(x, segment=tag) if isinstance(x, dict) else x for x in res.get(key, [])]
        R["peak_checks"] += [dict(c, frame=c["frame"] + start, segment=tag) for c in res.get("peak_checks", [])]
        R["duplicates"] += [dict(x, outer=p + x["outer"], inner=p + x["inner"], frame=x["frame"] + start, segment=tag)
                            for x in res.get("duplicates", [])]
        for f, ks in res["frames"].items():
            frames[int(f) + start] = [dict(kk, track=p + kk["track"]) for kk in ks]
    R["video"] = dict(n_frames=total, fps=fps, width=W, height=H)
    R["boundary_links"] = boundary_links(frames, [start for _, start, _ in segs[1:]], R["auto_labels"])
    m = tracks.metrics(frames, R["tracks"], total, fps, R["auto_labels"])
    checked = {(c["label"], c["frame"]) for c in R["peak_checks"]}
    for name, mm in m.items():
        mm["peak_checked"] = (name, mm["maxn_frame"]) in checked
    R["metrics"] = m
    heads = {}
    for name in m:
        h = pipeline._head(name)
        if h:
            heads.setdefault(h, []).append(name)
    R["name_variants"] = [sorted(v) for v in heads.values() if len(v) > 1]
    for b in R["boundary_links"]:       # one animal across a cut, named differently on each side: a person picks
        pair = sorted({b["before_label"], b["after_label"]})
        if b["name_conflict"] and pair not in R["name_variants"]:
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
    for kind in ("clip.mp4", "annotated.mp4", "clip_original.mp4"):
        parts = [os.path.join(sd, kind) for sd, _, _ in segs]
        if all(os.path.exists(x) for x in parts):
            _concat(parts, os.path.join(d, kind))
    return R


def run_long(src, rid=None, seg_s=MAX_SEGMENT_S, **kw):
    """Split `src` into segments of at most seg_s seconds, run the pipeline on each, merge. kw -> run_pipeline."""
    rid = rid or time.strftime("%m%d-%H%M%S")
    d = os.path.join(pipeline.RUNS, rid)
    os.makedirs(d, exist_ok=True)
    t0 = time.time()
    st = _status(d, id=rid, stage="ingest", started=t0, log=[f"{time.strftime('%H:%M:%S')} re-encoding to 5 fps (whole video)"])
    full = os.path.join(d, "full_5fps.mp4")
    video.ingest(src, full, max_seconds=10 ** 7)
    inf = video.info(full)
    # low-light is decided once for the whole video, so every segment gets the same treatment
    light = video.light_stats(full)
    mode = kw.get("lowlight", "auto")
    light.update(mode=mode, brightened=mode == "on" or (mode == "auto" and video.is_dark(light)))
    kw["lowlight"] = "on" if light["brightened"] else "off"
    inf["lowlight"] = light
    segs = plan(inf["n_frames"], inf["fps"], seg_s)
    st["log"].append(f"{time.strftime('%H:%M:%S')} {inf['n_frames']} frames -> {len(segs)} segment(s) of <= {seg_s:g} s: "
                     + ", ".join(f"{s}+{n}" for s, n in segs))
    _status(d, stage="segments", log=st["log"], video=inf)
    done, live, cached, billed = [], 0, 0, 0.0
    for k, (start, n) in enumerate(segs):
        sp = os.path.join(d, f"seg{k + 1}.mp4")
        cut(full, sp, start, n)
        srid = f"{rid}__S{k + 1}"
        pipeline.run_pipeline(sp, srid, **kw)
        sst = json.load(open(os.path.join(pipeline.RUNS, srid, "status.json")))
        live, cached, billed = live + sst["live_calls"], cached + sst["cached_calls"], billed + sst["billed_usd"]
        done.append((os.path.join(pipeline.RUNS, srid), start, n))
        st["log"].append(f"{time.strftime('%H:%M:%S')} segment S{k + 1} ({start / inf['fps']:.1f}-{(start + n) / inf['fps']:.1f} s) done: "
                         + ", ".join(f"{m} {v['maxn']}" for m, v in json.load(open(os.path.join(done[-1][0], "result.json")))["metrics"].items()))
        _status(d, stage="segments", log=st["log"], live_calls=live, cached_calls=cached, billed_usd=billed)
    R = merge(rid, os.path.basename(src), done, inf["fps"])
    R["video"]["lowlight"] = light
    with open(os.path.join(d, "result.json"), "w") as f:
        json.dump(R, f)
    os.remove(full)
    t1 = time.time()
    st["log"].append(f"{time.strftime('%H:%M:%S')} merged {len(segs)} segment(s): "
                     + ", ".join(f"{m} MaxN {v['maxn']} at {v['maxn_time']} s" for m, v in R["metrics"].items())
                     + f"; finished in {t1 - t0:.0f}s; live calls {live}, cached {cached}, billed ${billed:.3f}")
    _status(d, stage="done", done=t1, log=st["log"], live_calls=live, cached_calls=cached, billed_usd=billed, video=R["video"])
    return R
