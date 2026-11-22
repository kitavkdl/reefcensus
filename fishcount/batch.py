"""Many videos in one go: each runs through the normal CLI (fishcount/pipeline.py) in its own process, one after
another, and the batch keeps two tables that always cover every input video (round 3, 11/21c: a survey with
hundreds of deployments had to script this loop itself, and a video that counted nothing or failed left no line).

  python3 fishcount/batch.py <videos | folders | list.txt> ... --out <dir> [--prefix P] [-- <pipeline.py options>]

  e.g. python3 fishcount/batch.py /data/bruv/2026/ --out batch_2026 --prefix y26_ -- --discover --zoom --max-usd 3

Inputs: video files, folders (their video files, not sub-folders, sorted by name) and .txt lists (one path a line,
# for comments), in the order given. Run id = prefix + the file name without extension (characters other than
letters, digits, . _ - become _; a repeated name gets _2, _3, ...). Everything after -- goes to every
pipeline.py call unchanged, so each video's run is exactly what `pipeline.py <video> --id <run id> <options>`
gives on its own (long videos split as usual).

<out>/videos.csv, one line per input video in input order, rewritten after every video:
  source_file, run_id, status (done / kept / error / pending), error, analysed_s, source_warnings, labels_counted,
  maxn_by_label ("fish 14; crab 2", after any human review), maxn_lower_bound (labels the crowd check marks a lower
  bound), review_queue (tracks waiting for a person), live_calls, cached_calls, billed_usd (that run's status),
  ledger_usd (every ledger row tagged with this run id or its segments and probes: earlier failed tries too), wall_s,
  capped (the segments where stages were left out at the video cap, "S2; S5", or "run" for a short video; empty when
  nothing was: raise --max-usd-video and run again to finish them).
  A video that counted nothing is a line with labels_counted 0; one that failed says why (status.json "error").
<out>/maxn_all.csv: every finished video's standard MaxN rows (maxn_export.py, the GlobalArchive / CheckEM layout)
  under one header. OpCode is the video's file name as in maxn_export.py; two inputs with the same file name take
  their run ids instead (x, x_2), so no two videos share an OpCode.
<out>/logs/<run id>.log: that video's pipeline output.

Run the same command again after a crash, a kill or a full disk: a video whose run finished with the same options
and the same source file (path, size, modification time; <run>/batch.json) is kept and not run again (no API call);
the others run, a long one with --resume so its finished segments are kept (not with --skip-empty). A failed video
does not stop the batch; the exit code is 1 if any video failed. Ctrl-C or SIGTERM stops the running video's
process too, writes the tables (videos not reached: pending) and exits with 130."""
import csv, json, os, re, signal, subprocess, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "web"))
from fishcount import api, longvideo, maxn_export, pipeline

PIPELINE = os.path.join(ROOT, "fishcount", "pipeline.py")
VIDEO_EXT = (".mp4", ".mov", ".avi", ".mkv", ".m4v", ".mts", ".mpg", ".mpeg", ".wmv", ".h264", ".264")
COLUMNS = ["source_file", "run_id", "status", "error", "analysed_s", "source_warnings", "labels_counted",
           "maxn_by_label", "maxn_lower_bound", "review_queue", "live_calls", "cached_calls", "billed_usd",
           "ledger_usd", "wall_s", "capped"]
# the defaults a run's options leave to the code: a finished video is kept only while they hold (a stamp written
# before D-NIGHT3 has none and is kept as before, so finished videos are not run again on upgrade)
DEFAULTS = dict(probe_window=pipeline.PROBE_WINDOW, cap_per_hour=longvideo.CAP_PER_HOUR_SPLIT,
                cap_per_hour_skip_empty=longvideo.CAP_PER_HOUR_SKIP_EMPTY, cap_min=longvideo.CAP_MIN_USD)
SEGMENT_ID = re.compile(r"__[SP]\d+$")     # a long video's segment / probe runs: rid__S<n>, rid__P<n>


def videos(args):
    """Input paths -> video files in order (folders: their video files by name; .txt: one path a line)."""
    out = []
    for a in args:
        if os.path.isdir(a):
            out += [os.path.join(a, f) for f in sorted(os.listdir(a))
                    if f.lower().endswith(VIDEO_EXT) and os.path.isfile(os.path.join(a, f))]
        elif a.lower().endswith(".txt"):
            base = os.path.dirname(os.path.abspath(a))
            with open(a, encoding="utf-8") as f:
                for line in f:
                    p = line.strip()
                    if p and not p.startswith("#"):
                        out.append(p if os.path.isabs(p) else os.path.join(base, p))
        else:
            out.append(a)
    return [os.path.abspath(p) for p in out]


def run_ids(paths, prefix=""):
    """One run id per video: prefix + safe file name; a repeated name gets _2, _3, ... in input order."""
    seen, out = {}, []
    for p in paths:
        rid = prefix + re.sub(r"[^A-Za-z0-9._-]", "_", os.path.splitext(os.path.basename(p))[0])
        seen[rid] = seen.get(rid, 0) + 1
        out.append(rid if seen[rid] == 1 else f"{rid}_{seen[rid]}")
    return out


def _json(p, default=None):
    try:
        with open(p) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def stamp(path, opts):
    """What a finished run is kept against: the source file (path, size, mtime) and the options."""
    s = os.stat(path)
    return dict(source=path, size=s.st_size, mtime=round(s.st_mtime, 3), options=list(opts), defaults=DEFAULTS)


def is_kept(rid, path, opts):
    d = os.path.join(pipeline.RUNS, rid)
    old, now = _json(os.path.join(d, "batch.json")), stamp(path, opts)
    if isinstance(old, dict) and "defaults" not in old:
        now.pop("defaults")
    return ((_json(os.path.join(d, "status.json")) or {}).get("stage") == "done"
            and os.path.exists(os.path.join(d, "result.json")) and old == now)


def command(path, rid, opts):
    """The pipeline.py call for one video: the options as given, plus --resume (not with --skip-empty)."""
    extra = [] if "--skip-empty" in opts or "--resume" in opts else ["--resume"]
    return [sys.executable, PIPELINE, path, "--id", rid, *opts, *extra]


class Stopped(Exception):
    """The batch got SIGTERM (kill, systemd stop)."""


def _stop(signum, frame):
    raise Stopped(f"signal {signum}")


def run_one(path, rid, opts, log_path):
    """Run one video; returns (ok, wall seconds, exit code). Never raises for the video's own failure. If the batch
    itself is stopped (Ctrl-C, kill), the video's process is stopped too before the batch exits, so a rerun never
    has two processes writing one run folder."""
    t = time.time()
    with open(log_path, "w") as log:
        p = subprocess.Popen(command(path, rid, opts), stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)
        try:
            rc = p.wait()
        except BaseException:
            p.terminate()
            try:
                p.wait(timeout=30)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
            raise
    st = _json(os.path.join(pipeline.RUNS, rid, "status.json")) or {}
    ok = rc == 0 and st.get("stage") == "done"
    if ok:
        with open(os.path.join(pipeline.RUNS, rid, "batch.json"), "w") as f:
            json.dump(stamp(path, opts), f)
    return ok, time.time() - t, rc


def ledger_by_run(path=None):
    """usd per run id from the ledger rows tagged with a run (round 3); a long video's segments add to its id."""
    out = {}
    try:
        lines = open(path or api.LEDGER)
    except OSError:
        return out
    with lines:
        for line in lines:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            rid = r.get("run")
            if rid:
                rid = SEGMENT_ID.sub("", rid)
                out[rid] = out.get(rid, 0.0) + float(r.get("usd") or 0)
    return out


def row(path, rid, state, ledger, opcodes=None):
    """One videos.csv line from the run folder (state: dict(status, error, wall_s)), and its maxn_all.csv rows.
    opcodes: run id -> OpCode for videos whose file names clash (else maxn_export's default, the file name)."""
    import server
    d = os.path.join(pipeline.RUNS, rid)
    # a video not run yet in this batch: an earlier try's numbers would read as this batch's (the ledger column
    # still counts what earlier tries paid)
    st = (_json(os.path.join(d, "status.json")) or {}) if state["status"] != "pending" else {}
    res = _json(os.path.join(d, "result.json")) if state["status"] in ("done", "kept") else None
    v = (res or {}).get("video") or st.get("video") or {}
    warn = v.get("source_warnings") or st.get("source_warnings") or []
    r = dict(source_file=path, run_id=rid, status=state["status"], error=state.get("error") or "",
             analysed_s=round(v["n_frames"] / v["fps"], 1) if v.get("n_frames") and v.get("fps") else "",
             source_warnings="; ".join(warn), labels_counted="", maxn_by_label="", maxn_lower_bound="",
             review_queue="", live_calls=st.get("live_calls", ""), cached_calls=st.get("cached_calls", ""),
             billed_usd=round(st["billed_usd"], 4) if isinstance(st.get("billed_usd"), (int, float)) else "",
             ledger_usd=round(ledger.get(rid, 0.0), 4), wall_s=state.get("wall_s", ""),
             capped="; ".join(dict.fromkeys(c.get("segment", "run") for c in (res or {}).get("capped", []) if isinstance(c, dict))))
    e = server.effective(rid) if res else None
    if e:
        counted = sorted(((n, m) for n, m in e["metrics"].items() if m["maxn"] > 0), key=lambda kv: (-kv[1]["maxn"], kv[0]))
        r.update(labels_counted=len(counted), maxn_by_label="; ".join(f"{n} {m['maxn']}" for n, m in counted),
                 maxn_lower_bound="; ".join(n for n, m in counted if maxn_export._lower_bound(e, n, m)),
                 review_queue=e.get("n_flagged", 0))
    return r, (maxn_export.rows(e, (opcodes or {}).get(rid)) if e else [])


def clashing_opcodes(paths, rids):
    """OpCode is the video's file name (maxn_export.default_opcode); two inputs with one name (a/x.mp4, b/x.mp4)
    would share it in maxn_all.csv, so those take their run id (x, x_2) instead."""
    names = [os.path.splitext(os.path.basename(p))[0] for p in paths]
    return {rid: rid for n, rid in zip(names, rids) if names.count(n) > 1}


def write_tables(out, paths, rids, states, ledger_path=None):
    ledger = ledger_by_run(ledger_path)
    opcodes = clashing_opcodes(paths, rids)
    lines, maxn = [], []
    for p, rid in zip(paths, rids):
        r, m = row(p, rid, states.get(rid, dict(status="pending")), ledger, opcodes)
        lines.append(r)
        maxn += m
    for name, header, body in (("videos.csv", COLUMNS, [[r[c] for c in COLUMNS] for r in lines]),
                               ("maxn_all.csv", maxn_export.COLUMNS, maxn)):
        tmp = os.path.join(out, name + ".tmp")
        with open(tmp, "w", newline="") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(header)
            w.writerows(body)
        os.replace(tmp, os.path.join(out, name))
    return lines


def main(argv=None):
    import argparse
    argv = list(sys.argv[1:] if argv is None else argv)
    opts = argv[argv.index("--") + 1:] if "--" in argv else []
    argv = argv[:argv.index("--")] if "--" in argv else argv
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("inputs", nargs="+", help="video files, folders, .txt lists")
    ap.add_argument("--out", required=True, help="folder for videos.csv, maxn_all.csv and logs/")
    ap.add_argument("--prefix", default="", help="put before every run id (e.g. the survey's code)")
    a = ap.parse_args(argv)
    if "--id" in opts:
        ap.error("--id is set per video by the batch")
    paths = videos(a.inputs)
    missing = [p for p in paths if not os.path.isfile(p)]
    if missing:
        ap.error("not found: " + ", ".join(missing[:5]))
    if not paths:
        ap.error("no video files in the inputs")
    rids = run_ids(paths, a.prefix)
    enc_warn = pipeline.api.encoder_check(pipeline.video.encoder_probe(), write=False)   # once here, not only in logs/
    if enc_warn:
        print(f"WARNING: {enc_warn}", flush=True)
    os.makedirs(os.path.join(a.out, "logs"), exist_ok=True)
    states = {}
    write_tables(a.out, paths, rids, states)
    signal.signal(signal.SIGTERM, _stop)
    try:
        run_all(a.out, paths, rids, opts, states)
    except (Stopped, KeyboardInterrupt) as e:
        write_tables(a.out, paths, rids, states)
        print(f"batch stopped ({e or 'Ctrl-C'}); the same command again keeps the finished videos", flush=True)
        return 130
    lines = write_tables(a.out, paths, rids, states)
    n = {s: sum(1 for r in lines if r["status"] == s) for s in ("done", "kept", "error")}
    print(f"batch: {n['done']} done, {n['kept']} kept, {n['error']} failed of {len(paths)}; "
          f"{os.path.join(a.out, 'videos.csv')}, {os.path.join(a.out, 'maxn_all.csv')}", flush=True)
    return 1 if n["error"] else 0


def run_all(out, paths, rids, opts, states):
    for i, (p, rid) in enumerate(zip(paths, rids)):
        if SEGMENT_ID.search(rid):      # its segments' folders and ledger rows would be another video's
            states[rid] = dict(status="error", error=f"run id {rid} ends in __S<n> / __P<n>, which names a long video's "
                               "segment: rename the file or use --prefix")
            print(f"[{i + 1}/{len(paths)}] {rid}: {states[rid]['error']}", flush=True)
        elif is_kept(rid, p, opts):
            states[rid] = dict(status="kept")
            print(f"[{i + 1}/{len(paths)}] {rid}: kept (finished earlier with these options)", flush=True)
        else:
            print(f"[{i + 1}/{len(paths)}] {rid}: {p}", flush=True)
            ok, wall, rc = run_one(p, rid, opts, os.path.join(out, "logs", f"{rid}.log"))
            st = _json(os.path.join(pipeline.RUNS, rid, "status.json")) or {}
            states[rid] = dict(status="done" if ok else "error", wall_s=round(wall, 1),
                               error="" if ok else (st.get("error") or f"exit code {rc} (see logs/{rid}.log)"))
            print(f"[{i + 1}/{len(paths)}] {rid}: {states[rid]['status']} in {wall:.0f}s"
                  + (f": {states[rid]['error']}" if not ok else ""), flush=True)
        write_tables(out, paths, rids, states)


if __name__ == "__main__":
    sys.exit(main())
