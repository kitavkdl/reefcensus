"""Local review UI for reefcensus: serves web/ and runs/, starts pipeline runs, keeps human review edits.
  python3 web/server.py [--port 8793]          then open http://127.0.0.1:8793
Bound to 127.0.0.1 only: POST /api/run can spend API credit (only when the request sets allow_api; the global
FISH_BUDGET guard in fishcount/api.py still applies on top)."""
import argparse, csv, io, json, mimetypes, os, re, sys, threading, time, traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fishcount import api, pipeline, tracks, video

ROOT, WEB = api.ROOT, os.path.dirname(os.path.abspath(__file__))
RUNS, UPLOADS = pipeline.RUNS, os.path.join(api.ROOT, "clips")
# spikes/L1/clips also holds tiles and helper cuts from experiments; only the source clips are offered
CLIP_DIRS = [(UPLOADS, re.compile(r".")), (os.path.join(ROOT, "spikes", "L1", "clips"), re.compile(r"^(imas_TF_\d+|nautilus_s\d{3}_0_12)\.mp4$"))]
VIDEO_EXT = (".mp4", ".mov", ".ogv", ".webm", ".mkv")
SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")
MAX_UPLOAD = 1 << 30
LIVE_CAP_USD = 2.0          # per-run ceiling the UI cannot raise (the pipeline's own check counts SAM only, not Spark)
MAX_SECONDS = 120           # render.annotate holds every frame and mask in memory; 2 min at 5 fps is ~600 frames
STALE_S = 15 * 60           # a run not "done"/"error", not ours, and silent this long was cut off (crash/restart)

_busy = threading.Lock()    # one run at a time: spend accounting and the CPU-heavy render assume it
_current = {}
_review_lock = threading.Lock()


def _json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def clips():
    out = []
    for d, ok in CLIP_DIRS:
        if os.path.isdir(d):
            for fn in sorted(os.listdir(d)):
                if fn.lower().endswith(VIDEO_EXT) and ok.search(fn) and not fn.startswith("."):
                    out.append(dict(name=fn, dir=os.path.relpath(d, ROOT), mb=round(os.path.getsize(os.path.join(d, fn)) / 1e6, 1)))
    return out


def clip_path(name):
    for d, ok in CLIP_DIRS:
        p = os.path.join(d, name)
        if SAFE.match(name) and ok.search(name) and os.path.isfile(p):
            return p
    return None


def run_list():
    out = []
    for rid in os.listdir(RUNS) if os.path.isdir(RUNS) else []:
        st = _json(os.path.join(RUNS, rid, "status.json"))
        if not st:
            continue
        res = _json(os.path.join(RUNS, rid, "result.json"), {})
        stage = st.get("stage")
        if stage not in ("done", "error") and rid != _current.get("id") and \
                time.time() - os.path.getmtime(os.path.join(RUNS, rid, "status.json")) > STALE_S:
            stage = "interrupted"
        out.append(dict(id=rid, stage=stage, started=st.get("started"), source=res.get("source"),
                        maxn={k: v["maxn"] for k, v in res.get("metrics", {}).items()}))
    return sorted(out, key=lambda r: -(r["started"] or 0))


def labels_for(res, review):
    labels = dict(res.get("auto_labels", {}))
    labels.update(review)
    return labels


def origins(res, labels):
    """'asked' if any track behind a label came from a requested prompt (or its zoom tile), else 'found'."""
    asked_src = {j["name"] for j in res.get("jobs", [])}
    out = {}
    for t, v in res.get("tracks", {}).items():
        l = labels.get(t, v["label"])
        if l:
            out[l] = "asked" if v["source"] in asked_src or out.get(l) == "asked" else "found"
    return out


def effective(rid):
    """result.json joined with the human review: metrics recomputed from the stored (post-peak-check) frames."""
    d = os.path.join(RUNS, rid)
    res = _json(os.path.join(d, "result.json"))
    if not res:
        return None
    review = _json(os.path.join(d, "review.json"), {})
    labels = labels_for(res, review)
    frames = {int(f): ks for f, ks in res["frames"].items()}
    v = res["video"]
    m = tracks.metrics(frames, res["tracks"], v["n_frames"], v["fps"], labels) if review else res["metrics"]
    # MaxN as a range: the lower end drops every queued track no person has looked at yet (only confident Spark
    # answers and human edits remain); the upper end is the count above. Reviewing the queue closes the range.
    open_q = {t for t, vd in res.get("verdicts", {}).items() if pipeline.needs_review(vd) and t not in review}
    lo = tracks.metrics(frames, res["tracks"], v["n_frames"], v["fps"], {**labels, **{t: None for t in open_q}}) if open_q else {}
    checked = {(c["label"], c["frame"]) for c in res.get("peak_checks", [])}
    for name, mm in m.items():
        mm["maxn_confirmed"] = lo.get(name, {}).get("maxn", 0) if open_q else mm["maxn"]
        if open_q and lo.get(name, {}).get("curve") != mm["curve"]:
            mm["curve_confirmed"] = lo[name]["curve"] if name in lo else [0] * len(mm["curve"])
        mm["peak_checked"] = (name, mm["maxn_frame"]) in checked
        ev = f"evidence_{pipeline.api_safe(name)}.jpg"
        mm["evidence"] = ev if os.path.exists(os.path.join(d, ev)) else None
    queue = []
    for t, vd in res.get("verdicts", {}).items():
        if pipeline.needs_review(vd) or t in review:
            queue.append(dict(track=t, name=vd.get("name"), thumb=f"thumbs/{vd.get('name')}.jpg", trio=f"thumbs/{vd.get('name')}_trio.jpg",
                              has_trio=os.path.exists(os.path.join(d, "thumbs", f"{vd.get('name')}_trio.jpg")), species=vd.get("species"),
                              confidence=vd.get("confidence"), is_target=vd.get("is_target"), reason=(f"Name in doubt: audit and the unprimed second look disagree ({vd['name_disagrees']}). " if vd.get("name_disagrees") else "") + (vd.get("reason") or ""),
                              category=res["tracks"][t]["label"], auto=res["auto_labels"].get(t),
                              reviewed=t in review, label=labels.get(t)))
    out = {k: v for k, v in res.items() if k != "frames"}
    out.update(metrics=m, origin=origins(res, labels), queue=queue, review=review,
               annotated=os.path.exists(os.path.join(d, "annotated.mp4")),
               n_reviewed=len(review), n_flagged=sum(1 for q in queue if not q["reviewed"]))
    return out


def start_run(body):
    src = clip_path(body.get("clip", ""))
    if not src:
        raise ValueError("pick a clip from the list")
    prompts = [w.strip().lower() for w in body.get("prompts", ["fish"]) if w.strip()][:3] or ["fish"]
    if any(not re.fullmatch(r"[a-z][a-z -]{0,30}", p) for p in prompts):
        raise ValueError("request words: plain lowercase nouns, like fish or shark")
    live = bool(body.get("allow_api"))
    inf = video.info(src)
    secs = inf["n_frames"] / inf["fps"] if inf["fps"] else 0
    if not 0 < secs <= MAX_SECONDS:
        raise ValueError(f"clip is {secs:.0f} s; this screen takes clips up to {MAX_SECONDS} s (cut it first)")
    cap = min(float(body.get("max_usd") or 1.0), LIVE_CAP_USD)
    if not _busy.acquire(blocking=False):
        raise RuntimeError(f"run {_current.get('id')} is still going; wait for it to finish")
    stem = re.sub(r"[^A-Za-z0-9_-]", "_", os.path.splitext(os.path.basename(src))[0])[:40]
    rid = f"{stem}_{time.strftime('%m%d-%H%M%S')}"
    _current.update(id=rid)

    def work():
        try:
            # discovery already has Spark look at the clip; the scout look only runs when discovery is off
            disc = bool(body.get("discover", True))
            pipeline.run_pipeline(src, rid, offline=not live, do_scout=not disc, do_audit=True, do_zoom=False, prompts=prompts,
                                  max_usd=cap, do_discover=disc)
        except Exception as e:      # surface the reason in status.json so the UI can show it
            p = os.path.join(RUNS, rid, "status.json")
            st = _json(p, dict(id=rid, log=[]))
            msg = str(e) if isinstance(e, (api.BudgetExceeded, FileNotFoundError, KeyError)) else f"{type(e).__name__}: {e}"
            if not live and isinstance(e, (FileNotFoundError, KeyError, RuntimeError)):
                msg += " (free replay only reuses saved answers, and this step has none; allow paid API calls to run it live)"
            st.update(stage="error", error=msg)
            st["log"].append(f"{time.strftime('%H:%M:%S')} stopped: {msg}")
            with open(p + ".tmp", "w") as f:
                json.dump(st, f)
            os.replace(p + ".tmp", p)
            traceback.print_exc()
        finally:
            _current.clear()
            _busy.release()

    os.makedirs(os.path.join(RUNS, rid), exist_ok=True)
    with open(os.path.join(RUNS, rid, "status.json"), "w") as f:
        json.dump(dict(id=rid, stage="queued", log=[], live_calls=0, cached_calls=0, billed_usd=0.0, started=time.time()), f)
    threading.Thread(target=work, daemon=True).start()
    return dict(id=rid, live=live, max_usd=cap)


def save_review(rid, body):
    with _review_lock:
        return _save_review(rid, body)


def _save_review(rid, body):
    d = os.path.join(RUNS, rid)
    res = _json(os.path.join(d, "result.json"))
    if not res:
        raise ValueError("no finished result for this run")
    review = _json(os.path.join(d, "review.json"), {})
    for t, l in body.items():
        if t not in res["tracks"]:
            raise ValueError(f"unknown track {t}")
        if l == "__undo__":
            review.pop(t, None)
        else:
            review[t] = (str(l).strip().lower()[:60] or None) if l is not None else None
    with open(os.path.join(d, "review.json.tmp"), "w") as f:
        json.dump(review, f)
    os.replace(os.path.join(d, "review.json.tmp"), os.path.join(d, "review.json"))
    return effective(rid)


def export_csv(rid):
    e = effective(rid)
    buf = io.StringIO()
    w = csv.writer(buf)
    # maxn_confirmed = the low end of the MaxN range: queued tracks nobody has reviewed yet are left out
    w.writerow(["label", "origin", "maxn", "maxn_confirmed", "maxn_time_s", "maxn_frame", "first_arrival_s", "tracks", "peak_frame_checked",
                "evidence_frame", "source", "human_edits"])
    cell = lambda v: "'" + v if isinstance(v, str) and v[:1] in "=+-@" else v    # no formulas from model text
    for name, m in sorted(e["metrics"].items(), key=lambda kv: -kv[1]["maxn"]):
        w.writerow([cell(name), e["origin"].get(name, ""), m["maxn"], m["maxn_confirmed"], m["maxn_time"], m["maxn_frame"], m["first_time"], m["tracks"],
                    m["peak_checked"], m["evidence"] or "", e["source"], e["n_reviewed"]])
    return buf.getvalue()


class H(BaseHTTPRequestHandler):
    server_version = "reefcensus"

    def log_message(self, fmt, *a):
        if not self.path.startswith("/runs/") or "status.json" not in self.path:
            sys.stderr.write("%s %s\n" % (time.strftime("%H:%M:%S"), fmt % a))

    def send(self, code, body, ctype="application/json", extra=()):
        if not isinstance(body, (bytes, bytearray)):
            body = (json.dumps(body) if ctype == "application/json" else body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in extra:
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def same_origin(self, need_json=True):
        """A page on another site can POST to 127.0.0.1 with a text/plain body (no preflight); a run can spend money.
        Require our own Host (blocks DNS rebinding), a matching Origin if sent, and a JSON content type."""
        port = self.server.server_address[1]
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        origin = self.headers.get("Origin")
        ok = self.headers.get("Host") in hosts and (origin is None or origin.split("//", 1)[-1] in hosts)
        if need_json:
            ok = ok and (self.headers.get("Content-Type") or "").split(";")[0].strip() == "application/json"
        if not ok:
            self.send(403, {"error": "requests must come from this page"})
        return ok

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n < 1 << 20 else {}

    def file(self, path):
        """Static file with single-range support (the browser seeks video with Range requests)."""
        size = os.path.getsize(path)
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        rng = re.match(r"bytes=(\d*)-(\d*)$", self.headers.get("Range", ""))
        start, end = 0, size - 1
        if rng and (rng.group(1) or rng.group(2)):
            if rng.group(1):
                start = int(rng.group(1))
                end = min(int(rng.group(2)), size - 1) if rng.group(2) else size - 1
            else:
                start = max(0, size - int(rng.group(2)))
            if start > end or start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(end - start + 1))
        self.send_header("Cache-Control", "no-store" if path.endswith(".json") else "no-cache")
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(path, "rb") as f:
            f.seek(start)
            left = end - start + 1
            try:
                while left > 0:
                    chunk = f.read(min(1 << 16, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def static(self, base, rel):
        p = os.path.realpath(os.path.join(base, rel))
        if not p.startswith(os.path.realpath(base) + os.sep) or not os.path.isfile(p):
            return self.send(404, {"error": "not found"})
        self.file(p)

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        try:
            if path in ("/", "/index.html"):
                return self.file(os.path.join(WEB, "index.html"))
            if path.startswith("/static/"):
                return self.static(WEB, path[len("/static/"):])
            if path.startswith("/runs/"):
                return self.static(RUNS, path[len("/runs/"):])
            if path == "/api/runs":
                return self.send(200, dict(runs=run_list(), running=_current.get("id")))
            if path == "/api/clips":
                return self.send(200, dict(clips=clips()))
            m = re.fullmatch(r"/api/runs/([^/]+)(/export\.csv)?", path)
            if m and SAFE.match(m.group(1)):
                if m.group(2):
                    return self.send(200, export_csv(m.group(1)), "text/csv",
                                     [("Content-Disposition", f'attachment; filename="{m.group(1)}_maxn.csv"')])
                e = effective(m.group(1))
                return self.send(200, e) if e else self.send(404, {"error": "no result yet"})
            self.send(404, {"error": "not found"})
        except Exception as e:
            traceback.print_exc()
            self.send(500, {"error": f"{type(e).__name__}: {e}"})

    do_HEAD = do_GET

    def do_POST(self):
        path = unquote(urlparse(self.path).path)
        if not self.same_origin():
            return
        try:
            if path == "/api/run":
                return self.send(200, start_run(self.body()))
            m = re.fullmatch(r"/api/runs/([^/]+)/review", path)
            if m and SAFE.match(m.group(1)):
                return self.send(200, save_review(m.group(1), self.body()))
            self.send(404, {"error": "not found"})
        except (ValueError, RuntimeError) as e:
            self.send(400, {"error": str(e)})
        except Exception as e:
            traceback.print_exc()
            self.send(500, {"error": f"{type(e).__name__}: {e}"})

    def do_PUT(self):
        if not self.same_origin(need_json=False):
            return
        m = re.fullmatch(r"/api/clips/([^/]+)", unquote(urlparse(self.path).path))
        name = m and m.group(1)
        n = int(self.headers.get("Content-Length") or 0)
        if not name or not SAFE.match(name) or not name.lower().endswith(VIDEO_EXT):
            return self.send(400, {"error": "clip name: letters, digits, . _ - and a video extension"})
        if not 0 < n <= MAX_UPLOAD:
            return self.send(400, {"error": "clip must be under 1 GB"})
        if os.path.exists(os.path.join(UPLOADS, name)):
            return self.send(409, {"error": f"{name} already exists; rename the file to keep both"})
        os.makedirs(UPLOADS, exist_ok=True)
        tmp = os.path.join(UPLOADS, f".{name}.part")
        with open(tmp, "wb") as f:
            left = n
            while left > 0:
                chunk = self.rfile.read(min(1 << 20, left))
                if not chunk:
                    break
                f.write(chunk)
                left -= len(chunk)
        if left:
            os.remove(tmp)
            return self.send(400, {"error": "upload cut off"})
        os.replace(tmp, os.path.join(UPLOADS, name))
        self.send(200, dict(name=name, mb=round(n / 1e6, 1)))


def seed_demo_runs():
    """A fresh clone has no runs/: copy the packed demo runs (demo/runs, see demo/pack_runs.py) so the screen
    shows finished results without an API key. Existing runs are never overwritten."""
    import shutil
    demo = os.path.join(ROOT, "demo", "runs")
    for rid in os.listdir(demo) if os.path.isdir(demo) else []:
        if SAFE.match(rid) and not os.path.exists(os.path.join(RUNS, rid)):
            shutil.copytree(os.path.join(demo, rid), os.path.join(RUNS, rid))


if __name__ == "__main__":
    seed_demo_runs()
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8793)     # 8765 crew, 8790/8791 brain
    a = ap.parse_args()
    print(f"reefcensus UI on http://127.0.0.1:{a.port}  (API spend so far ${api.spent():.3f}, FISH_BUDGET={os.environ.get('FISH_BUDGET', '1.0')})")
    ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()
