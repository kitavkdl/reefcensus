"""D-LOCALSAM: SAM 3.1 on the user's own GPU (FISH_SAM=local) instead of the Meta API. Nothing here needs a GPU or
torch: the worker process is a fake script that speaks the same JSON-line protocol, and samworker's output builder
is checked on synthetic masks and on records of a real API answer (public clip clips/nautilus_s002_0_12.mp4).
What must hold: (1) with local SAM or FISH_PRIVATE no clip ever goes to the Meta API (fail-closed, any other FISH_SAM
value is refused), (2) with FISH_SAM unset nothing changes (cache keys, CLI defaults, provenance), (3) a local
failure stops the run instead of being counted as "nothing found", (4) the worker's text has the API's format.
Run: python3 -m unittest discover -s tests -v"""
import csv, fcntl, json, os, subprocess, sys, tempfile, textwrap, threading, time, types, unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fishcount import _pylib  # noqa: F401
from fishcount import api, longvideo, pipeline, provenance, samworker, video
import numpy as np

CLIP = os.path.join(ROOT, "tests", "data", "nautilus_s004_0_12.mp4")
INFO = dict(torch="2.9.0", cuda=True, gpu="NVIDIA GeForce RTX 4060 Ti", vram_mb=8188, sam3_commit="31cb7e6abcdef",
            checkpoint="/hf/sam3.1_multiplex.pt", checkpoint_sha256="0123456789abcdef" * 4, meta_sam_parser="0.1.0", batch=1)
TAG = "sam3.1-local:0123456789ab:31cb7e6:b1"

# The fake worker: same protocol as fishcount/samworker.py (one JSON object a line each way). FAKE_MODE in its
# environment: ok | die_once (exits on its first track, a marker file remembers) | die_always | fail | hang |
# bad_version (cannot name its checkpoint) | no_batch (no FISH_SAM_BATCH in version) | version_fails (an error reply to version) | die_at_start.
FAKE = textwrap.dedent('''
    import json, os, sys, time
    mode, d = os.environ.get("FAKE_MODE", "ok"), os.environ["FAKE_DIR"]
    print("noise a library printed", flush=True, file=sys.stderr)
    for line in sys.stdin:
        req = json.loads(line)
        if mode == "die_at_start":
            sys.exit(4)
        if req["cmd"] == "version":
            out = dict(INFO)
            if mode == "bad_version":
                out["checkpoint_sha256"] = None
            if mode == "no_batch":
                out.pop("batch")
            if mode == "version_fails":
                out = dict(ok=False, error="no GPU")
        else:
            open(os.path.join(d, "tracks"), "a").write(req["prompt"] + "\\n")
            if mode == "die_always" or (mode == "die_once" and not os.path.exists(os.path.join(d, "died"))):
                open(os.path.join(d, "died"), "w").close()
                sys.exit(3)
            if mode == "hang":
                time.sleep(60)
            if mode == "fail":
                out = dict(ok=False, error="CUDA out of memory")
            else:
                out = dict(text="<0f>0<|box;x1=1;y1=2;x2=3;y2=4;w=10;h=10;c=0.5|>\\n" if req["prompt"] == "fish" else "")
        out.setdefault("ok", True)
        out["id"] = req.get("id")
        sys.stdout.write(json.dumps(out) + "\\n")
        sys.stdout.flush()
''').replace("dict(INFO)", repr(INFO))


class _Local(unittest.TestCase):
    """api in local mode with the fake worker; cache and ledger in a temp folder."""
    MODE = "ok"

    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        fake = os.path.join(self.tmp, "fakeworker.py")
        open(fake, "w").write(FAKE)
        self.posts = []
        for p in (mock.patch.object(api, "SAM_BACKEND", "local"), mock.patch.object(api, "PRIVATE", False),
                  mock.patch.object(api, "SAM_PER_FRAME", 0.0), mock.patch.object(api, "WORKER", fake),
                  mock.patch.object(api, "CACHE", os.path.join(self.tmp, "cache")),
                  mock.patch.object(api, "LOCAL_LOCK", os.path.join(self.tmp, "sam_local.lock")),
                  mock.patch.object(api, "LEDGER", os.path.join(self.tmp, "cache", "ledger.jsonl")),
                  mock.patch.object(api.requests, "post", lambda *a, **k: self.posts.append(a) or 1 / 0),
                  mock.patch.dict(os.environ, FISH_SAM_PYTHON=sys.executable, FAKE_MODE=self.MODE, FAKE_DIR=self.tmp)):
            p.start()
            self.addCleanup(p.stop)
        api._local_reset()
        self.addCleanup(api._local_reset)

    def tracks(self):
        p = os.path.join(self.tmp, "tracks")
        return open(p).read().split() if os.path.exists(p) else []

    def ledger(self):
        return [json.loads(l) for l in open(api.LEDGER)]


class FailClosed(unittest.TestCase):
    """No clip leaves the machine unless SAM is the API and FISH_PRIVATE is not set."""

    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.posts = []
        for p in (mock.patch.object(api, "CACHE", self.tmp), mock.patch.object(api, "LEDGER", os.path.join(self.tmp, "l")),
                  mock.patch.object(api, "_key", lambda: "k"),
                  mock.patch.object(api.requests, "post", lambda url, **k: self.posts.append(url) or _Ok())):
            p.start()
            self.addCleanup(p.stop)

    def settings(self, backend, private):
        for p in (mock.patch.object(api, "SAM_BACKEND", backend), mock.patch.object(api, "PRIVATE", private)):
            p.start()
            self.addCleanup(p.stop)

    def test_private_with_the_api_stops_before_any_upload(self):
        self.settings("", True)
        with self.assertRaises(api.LocalSamError):
            api.sam_video(CLIP, "fish", 60)
        with self.assertRaises(api.LocalSamError):
            api.sam_cached(CLIP, "fish")
        self.assertEqual(self.posts, [])

    def test_a_misspelt_backend_is_refused_and_blocks_uploads(self):
        self.settings("lcoal", False)
        with self.assertRaises(api.LocalSamError):
            api.sam_video(CLIP, "fish", 60)
        with self.assertRaises(api.LocalSamError):
            api._upload(CLIP, "k")
        self.assertEqual(self.posts, [])

    def test_post_refuses_video_but_lets_spark_through(self):
        for backend, private in (("local", False), ("", True), ("api", True)):
            with self.subTest(backend=backend, private=private):
                self.settings(backend, private)
                for url, body in ((f"{api.BASE}/files", None), (f"{api.BASE}/responses", {"input": []}),
                                  (f"{api.BASE}/chat/completions", {"x": [{"type": "input_video", "file_id": "f"}]})):
                    with self.assertRaises(api.LocalSamError):
                        api._post(url, json=body)
                with self.assertRaises(api.LocalSamError):
                    api._upload(CLIP, "k")
                api._post(f"{api.BASE}/chat/completions", json={"messages": [{"role": "user", "content": "hi"}]})
        self.assertEqual(self.posts, [f"{api.BASE}/chat/completions"] * 3)

    def test_unset_is_the_api_as_before(self):
        self.settings("", False)
        self.assertEqual(api.sam_backend(), "api")
        sha = api.file_sha(CLIP)
        cp = api._cache_path("sam", {"clip": sha, "prompt": "fish"})     # the key every cached answer was filed under
        api._write_cache(cp, {"output_text": "cached"})
        self.assertEqual(api.sam_video(CLIP, "fish", 60, offline=True), "cached")
        self.assertTrue(api.sam_cached(CLIP, "fish"))
        api._post(f"{api.BASE}/files")
        self.assertEqual(self.posts, [f"{api.BASE}/files"])


class PrivateMarker(unittest.TestCase):
    """D-LOCALSAM-F1: a marker file makes the machine private for every checkout, .env or not, and no environment
    value turns it off. Paths are arguments here, so the real ~/.config and /etc are never read."""

    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.m = os.path.join(self.tmp, "private")

    def on(self, env, path=None):
        return api._private(env, [("home-marker", path or self.m)])

    def test_marker_and_env_table(self):
        self.assertEqual(self.on({}), (False, []))
        self.assertEqual(self.on({"FISH_PRIVATE": "1"}), (True, ["env"]))
        open(self.m, "w").close()
        for env in ({}, {"FISH_PRIVATE": ""}, {"FISH_PRIVATE": "0"}):
            with self.subTest(env=env):
                self.assertEqual(self.on(env), (True, ["home-marker"]))
        self.assertEqual(self.on({"FISH_PRIVATE": "1"}), (True, ["env", "home-marker"]))

    def test_what_counts_as_there(self):
        link = os.path.join(self.tmp, "link")
        os.symlink(os.path.join(self.tmp, "gone"), link)
        self.assertEqual(self.on({}, link), (True, ["home-marker"]))            # a broken link is there
        afile = os.path.join(self.tmp, "afile")
        open(afile, "w").close()
        self.assertEqual(self.on({}, os.path.join(afile, "private")), (False, []))     # ENOTDIR: not there
        if os.geteuid() != 0:                       # root reads anything
            shut = os.path.join(self.tmp, "shut")
            os.mkdir(shut)
            os.chmod(shut, 0)
            self.addCleanup(os.chmod, shut, 0o700)
            self.assertEqual(self.on({}, os.path.join(shut, "private")), (True, ["home-marker"]))  # cannot look: there

    def test_markers_looked_at(self):
        pw = lambda uid: type("pw", (), {"pw_dir": "/home/a"})
        self.assertEqual(api._markers({"HOME": "/home/a"}, pw),
                         [("home-marker", "/home/a/.config/fishcount/private"), ("etc-marker", "/etc/fishcount/private")])
        self.assertEqual(api._markers({"HOME": "/tmp/elsewhere"}, pw)[:2],
                         [("home-marker", "/home/a/.config/fishcount/private"),
                          ("home-marker", "/tmp/elsewhere/.config/fishcount/private")])

        def nobody(uid):
            raise KeyError(uid)
        for env in ({}, {"HOME": self.tmp}):        # no account: private whatever HOME says
            with self.subTest(env=env):
                self.assertIsNone(api._markers(env, nobody))
                self.assertEqual(api._private(env, None), (True, ["no-home"]))

    def test_errors_say_what_made_it_private(self):
        for p in (mock.patch.object(api, "SAM_BACKEND", ""), mock.patch.object(api, "PRIVATE", True),
                  mock.patch.object(api, "PRIVATE_BY", ["etc-marker"])):
            p.start()
            self.addCleanup(p.stop)
        with self.assertRaisesRegex(api.LocalSamError, "/etc/fishcount/private exists.*replay them where"):
            api.sam_backend()
        with self.assertRaisesRegex(api.LocalSamError, "/etc/fishcount/private exists: refusing"):
            api._no_clip_out(f"{api.BASE}/files")

    def test_a_marker_made_after_import_still_blocks(self):
        """PRIVATE is worked out at import; the last gate looks at the markers again (or at a PRIVATE a test set)."""
        for p in (mock.patch.object(api, "SAM_BACKEND", ""), mock.patch.object(api, "PRIVATE", False),
                  mock.patch.object(api, "_markers", lambda environ: [("home-marker", self.m)])):
            p.start()
            self.addCleanup(p.stop)
        api._no_clip_out(f"{api.BASE}/files")          # no marker yet: the API as before
        open(self.m, "w").close()
        with self.assertRaisesRegex(api.LocalSamError, "marker ~/.config/fishcount/private exists: refusing"):
            api._no_clip_out(f"{api.BASE}/files")
        api._no_clip_out(f"{api.BASE}/chat/completions", {"messages": []})    # Spark still goes

    def test_provenance_keeps_the_labels_and_survives_a_refused_backend(self):
        for p in (mock.patch.object(api, "SAM_BACKEND", ""), mock.patch.object(api, "PRIVATE", True),
                  mock.patch.object(api, "PRIVATE_BY", ["home-marker"])):
            p.start()
            self.addCleanup(p.stop)
        e = provenance.start(os.path.join(self.tmp, "run"), ["pipeline.py"], CLIP)
        self.assertEqual(e["private"], {"on": True, "by": ["home-marker"]})
        self.assertIsNone(e["models"]["sam"])
        self.assertIn("FISH_SAM=local", e["models"]["sam_error"])


class _Ok:
    status_code = 200


class LocalCalls(_Local):
    def test_answered_by_the_worker_cached_and_logged_free(self):
        before = api.thread_real()
        txt = api.sam_video(CLIP, "fish", 60)
        self.assertTrue(txt.startswith("<0f>0<|box"))
        self.assertEqual(api.thread_real(), before + 1)
        row = self.ledger()[-1]
        self.assertEqual((row["kind"], row["usd"]), ("sam", 0.0))
        self.assertIn("(local)", row["note"])
        cp = api._cache_path("sam", {"clip": api.file_sha(CLIP), "prompt": "fish", "backend": TAG})
        self.assertEqual(api._read_cache(cp)["output_text"], txt)
        self.assertTrue(api.sam_cached(CLIP, "fish"))
        self.assertEqual(api.sam_video(CLIP, "fish", 60), txt)          # from cache: the worker is not asked again
        self.assertEqual(self.tracks(), ["fish"])
        self.assertEqual(api.thread_real(), before + 1)
        self.assertEqual(self.posts, [])
        self.assertFalse(api.sam_cached(CLIP, "nautilus"))
        with self.assertRaises(FileNotFoundError):
            api.sam_video(CLIP, "nautilus", 60, offline=True)

    def test_an_api_answer_is_not_a_local_one(self):
        cp = api._cache_path("sam", {"clip": api.file_sha(CLIP), "prompt": "fish"})
        os.makedirs(api.CACHE, exist_ok=True)
        api._write_cache(cp, {"output_text": "from the API"})
        self.assertNotEqual(api.sam_video(CLIP, "fish", 60), "from the API")

    def test_preflight_reports_the_worker(self):
        self.assertEqual(api.local_preflight(), INFO)
        self.assertEqual(api.local_tag(), TAG)

    def test_another_batch_is_another_backend(self):
        # FISH_SAM_BATCH changes a word call's bytes on the GPU (step 0): its answers must not stand in for batch 1's
        w = types.SimpleNamespace(version=lambda: dict(INFO, batch=2))
        with mock.patch.object(api, "_worker", lambda: w):
            self.assertEqual(api.local_tag(), "sam3.1-local:0123456789ab:31cb7e6:b2")

    def test_without_the_sam_python_it_stops(self):
        with mock.patch.dict(os.environ, FISH_SAM_PYTHON=""):
            with self.assertRaises(api.LocalSamError):
                api.sam_video(CLIP, "fish", 60)

    def test_one_worker_per_machine(self):
        with open(api.LOCAL_LOCK, "a") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)          # another process (the web server, a second CLI) has the GPU
            with self.assertRaises(api.LocalSamError) as e:
                api.sam_video(CLIP, "fish", 60)
            self.assertIn("another process", str(e.exception))

    def test_threads_take_turns(self):
        out = []
        ts = [threading.Thread(target=lambda w=w: out.append(api.sam_video(CLIP, w, 60))) for w in ("fish", "a", "b", "c")]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(sorted(self.tracks()), ["a", "b", "c", "fish"])
        self.assertEqual(len(out), 4)

    def test_the_lock_is_per_machine_not_per_cache(self):
        self.assertNotIn(api.CACHE, api.LOCAL_LOCK)
        self.assertFalse(api.__dict__["LOCAL_LOCK"].startswith(api.ROOT))

    def test_the_worker_holds_the_lock_too(self):
        """The parent killed while a call hangs: the worker keeps the GPU, so it keeps the lock as well."""
        api.sam_video(CLIP, "fish", 60)
        api._local.lockfh.close()       # as if the parent were gone
        api._local.lockfh = None
        with open(api.LOCAL_LOCK, "a") as fh:
            with self.assertRaises(OSError):
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_a_python_that_cannot_start_is_a_local_failure(self):
        with mock.patch.dict(os.environ, FISH_SAM_PYTHON=api.WORKER):    # exists, not executable
            with self.assertRaises(api.LocalSamError):
                api.sam_video(CLIP, "fish", 60)

    def test_no_clip_in_files_or_data_either(self):
        for kw in (dict(files={"file": ("c.mp4", b"x")}), dict(data=b"x")):
            with self.assertRaises(api.LocalSamError):
                api._post(f"{api.BASE}/chat/completions", **kw)
        self.assertEqual(self.posts, [])

    def test_the_worker_is_stopped_at_the_end(self):
        api.sam_video(CLIP, "fish", 60)
        proc = api._local.proc
        api._local_reset()
        self.assertIsNotNone(proc.poll())


class ShortClip(_Local):
    def test_a_whole_short_run_sends_no_clip(self):
        """design-v3 3-4 (2): a short clip through run_pipeline with local SAM; nothing reaches requests.post."""
        with mock.patch.object(pipeline, "RUNS", self.tmp):
            pipeline.run_pipeline(CLIP, "short", do_scout=False, do_audit=False, prompts=["fish"], refill=False,
                                  crowd_look=False, clean=False, max_usd=0.0)
        self.assertEqual(self.posts, [])
        self.assertIn("fish", self.tracks())


class WorkerBetweenCalls(_Local):
    def test_a_worker_dead_between_calls_is_cleaned_before_the_next(self):
        api.sam_video(CLIP, "fish", 60)
        old = api._local.proc
        old.kill()
        old.wait()
        self.assertTrue(api.sam_video(CLIP, "a", 60) == "" and api._local.proc is not old)
        self.assertTrue(old.stdin.closed and old.stdout.closed)


class NoBatch(_Local):
    MODE = "no_batch"

    def test_refused_and_stopped(self):
        with self.assertRaisesRegex(api.LocalSamError, "batch"):
            api.local_preflight()
        self.assertIsNone(api._local.proc)


class WorkerBadVersion(_Local):
    MODE = "bad_version"

    def test_refused_and_stopped(self):
        with self.assertRaises(api.LocalSamError):
            api.local_preflight()
        self.assertIsNone(api._local.proc)


class WorkerVersionFails(_Local):
    MODE = "version_fails"

    def test_refused_and_stopped(self):
        with self.assertRaises(api.LocalSamError) as e:
            api.local_preflight()
        self.assertIn("no GPU", str(e.exception))
        self.assertIsNone(api._local.proc)


class WorkerDiesAtStart(_Local):
    MODE = "die_at_start"

    def test_a_local_failure_not_a_traceback(self):
        for f in (api.local_preflight, api.local_tag, lambda: api.sam_video(CLIP, "fish", 60)):
            with self.assertRaises(api.LocalSamError):
                f()


class WorkerDiesOnce(_Local):
    MODE = "die_once"

    def test_started_again_once(self):
        self.assertTrue(api.sam_video(CLIP, "fish", 60).startswith("<0f>"))
        self.assertEqual(self.tracks(), ["fish", "fish"])


class WorkerDiesTwice(_Local):
    MODE = "die_always"

    def test_second_death_is_a_local_failure(self):
        with self.assertRaises(api.LocalSamError):
            api.sam_video(CLIP, "fish", 60)
        self.assertEqual(self.tracks(), ["fish", "fish"])
        self.assertFalse(os.path.exists(api._cache_path("sam", {"clip": api.file_sha(CLIP), "prompt": "fish", "backend": TAG})))


class WorkerFails(_Local):
    MODE = "fail"

    def test_error_reply(self):
        with self.assertRaises(api.LocalSamError) as e:
            api.sam_video(CLIP, "fish", 60)
        self.assertIn("CUDA out of memory", str(e.exception))

    def test_not_swallowed_as_a_motion_error(self):
        self.assertFalse(issubclass(api.LocalSamError, pipeline.MOTION_ERRORS))

    def test_counted_as_a_local_failure_and_raised(self):
        with mock.patch.object(pipeline, "RUNS", self.tmp):
            run = pipeline.Run("r")
            run.stage("audit")
            with self.assertRaises(api.LocalSamError) as e:
                pipeline._counted(run, api.sam_video, CLIP, "fish", 60)
            self.assertEqual(run.status["local_failures"], 1)
            pipeline.mark_error(run.dir, e.exception)       # what run_pipeline does with the error
            from fishcount import batch
            self.assertEqual(batch.local_failures("r"), 1)
            st = json.load(open(run.path("status.json")))
            self.assertEqual((st["stage"], st["local_failures"]), ("error", 1))


class WorkerHangs(_Local):
    MODE = "hang"

    def test_timeout_kills_the_worker(self):
        with mock.patch.object(api, "LOCAL_MIN_TIMEOUT", 1.0), mock.patch.object(api, "LOCAL_LOAD_S", 0.0), \
                mock.patch.object(api, "SAM_FPS", 1e9):
            t = time.time()
            with self.assertRaises(api.LocalSamError) as e:
                api.sam_video(CLIP, "fish", 60)
            self.assertLess(time.time() - t, 20)
        self.assertIn("timed out", str(e.exception))
        self.assertIsNone(api._local.proc)


class Counted(_Local):
    def test_a_local_call_is_live_and_local(self):
        run = pipeline.Run.__new__(pipeline.Run)
        run.id, run._lock = None, threading.Lock()
        run.status = dict(live_calls=0, cached_calls=0, billed_usd=0.0)
        pipeline._counted(run, api.sam_video, CLIP, "fish", 60)
        pipeline._counted(run, api.sam_video, CLIP, "fish", 60)
        self.assertEqual((run.status["live_calls"], run.status["cached_calls"], run.status["local_calls"]), (1, 1, 1))
        self.assertEqual(run.status["billed_usd"], 0.0)
        self.assertNotIn("local_failures", run.status)


class CommandLine(unittest.TestCase):
    def cli(self, *extra, backend="local"):
        import runpy
        got = {}

        class Stop(Exception):
            pass

        def run_long(*a, **k):
            got.update(k)
            raise Stop
        pre = []
        with mock.patch.object(sys, "argv", ["pipeline.py", "v.mp4", "--id", "cli"] + list(extra)), \
                mock.patch.object(api, "SAM_BACKEND", backend), mock.patch.object(api, "PRIVATE", False), \
                mock.patch.object(api, "local_preflight", lambda offline=False: pre.append(offline) or INFO), \
                mock.patch.object(video, "encoder_probe", lambda: {}), \
                mock.patch.object(api, "encoder_check", lambda probe, write=True: None), \
                mock.patch.object(provenance, "start", lambda *a, **k: None), \
                mock.patch.object(provenance, "effective", lambda *a, **k: None), \
                mock.patch.object(provenance, "finish", lambda *a, **k: None), \
                mock.patch.object(video, "info", lambda p: dict(n_frames=18000, fps=5.0)), \
                mock.patch.object(longvideo, "needs_split", lambda *a: True), \
                mock.patch.object(longvideo, "run_long", run_long), self.assertRaises(Stop):
            runpy.run_path(os.path.join(ROOT, "fishcount", "pipeline.py"), run_name="__main__")
        return got, pre

    def test_local_runs_one_call_at_a_time(self):
        k, pre = self.cli()
        self.assertEqual((k["segment_workers"], k["refill_ahead"], k["upload_ahead"]), (1, 1, False))
        self.assertEqual(pre, [False])          # the worker was checked before anything was paid
        k, pre = self.cli("--offline")
        self.assertEqual(pre, [True])

    def test_api_defaults_unchanged(self):
        k, pre = self.cli(backend="")
        self.assertEqual((k["segment_workers"], k["refill_ahead"], k["upload_ahead"]), (2, 4, True))
        self.assertEqual(pre, [])

    def test_local_refuses_parallel_flags(self):
        for extra in (["--segment-workers", "2"], ["--refill-ahead", "2"]):
            with self.subTest(extra=extra), self.assertRaises(SystemExit) as e:
                self.cli(*extra)
            self.assertEqual(e.exception.code, 2)

    def test_settings_refused_before_anything_runs(self):
        with self.assertRaises(SystemExit) as e:
            self.cli(backend="lcoal")
        self.assertEqual(e.exception.code, 2)


class LongVideo(_Local):
    def test_no_upload_ahead_and_the_backend_in_the_fingerprint(self):
        d = os.path.join(self.tmp, "runs")
        ups = []

        def cut(clip, dst, start, n):
            open(dst, "w").write(f"{start}+{n}")

        def run_pipeline(sp, srid, **kw):
            from test_longvideo import _fake_seg
            sd = os.path.join(d, srid)
            os.makedirs(sd, exist_ok=True)
            _fake_seg(sd, 750, [(10, 10, 5, 5)])
            json.dump(dict(live_calls=1, cached_calls=0, billed_usd=0.0), open(os.path.join(sd, "status.json"), "w"))
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        with mock.patch.object(pipeline, "RUNS", d), mock.patch.object(video, "ingest", lambda s, o, **k: open(o, "w").close()), \
                mock.patch.object(video, "info", lambda p: dict(n_frames=3000, fps=5.0, width=100, height=100)), \
                mock.patch.object(video, "light_stats", lambda p: dict(median_l=100, mean_l=100)), \
                mock.patch.object(longvideo, "cut", cut), mock.patch.object(pipeline, "run_pipeline", run_pipeline), \
                mock.patch.object(api, "_upload", lambda *a, **k: ups.append(a)):
            longvideo.run_long("v.mp4", "lv", seg_s=150, upload_ahead=True, max_usd=1.0)
        st = json.load(open(os.path.join(d, "lv", "status.json")))
        self.assertEqual(ups, [])
        self.assertFalse(any("uploaded ahead" in l or "upload ahead failed" in l for l in st["log"]))
        self.assertEqual(longvideo._fingerprint(None, {})["options"], {"sam_backend": TAG})
        with mock.patch.object(api, "SAM_BACKEND", ""):
            self.assertEqual(longvideo._fingerprint(None, {})["options"], {})

    def test_free_sam_leaves_the_cap_to_spark(self):
        self.assertEqual(longvideo.first_pass_floor(3000, ["fish", "eel"]), 0.0)
        self.assertEqual(longvideo.video_cap([0.0, 0.0], None, 1.0), (1.0, None))
        self.assertEqual(longvideo.shares([0.0, 0.0], 1.0), [0.5, 0.5])
        self.assertEqual(longvideo.short_cap(None, None, 0.0), (1.0, None))


class Provenance(_Local):
    def test_models_name_the_local_backend(self):
        m = provenance.models()
        self.assertEqual((m["sam"], m["sam_local"]), (TAG, INFO))
        with mock.patch.object(api, "SAM_BACKEND", ""):
            self.assertEqual(provenance.models(), dict(sam=api.SAM_MODEL, spark=api.SPARK_MODEL))

    def test_the_settings_are_recorded(self):
        with mock.patch.dict(os.environ, FISH_SAM="local", FISH_PRIVATE="1"):
            e = provenance.start(os.path.join(self.tmp, "run"), ["pipeline.py"], CLIP)
        self.assertEqual((e["environment"]["FISH_SAM"], e["environment"]["FISH_PRIVATE"]), ("local", "1"))
        self.assertEqual(e["models"]["sam"], TAG)


class BatchColumn(unittest.TestCase):
    def test_local_failures_add_up_over_segments(self):
        from fishcount import batch
        self.assertEqual(batch.COLUMNS[-2:], ["local_failures", "capped"])
        with tempfile.TemporaryDirectory() as d, mock.patch.object(pipeline, "RUNS", d):
            for rid, st in (("v", {}), ("v__S1", {"local_failures": 1}), ("v__S2", {"local_failures": 1}),
                            ("w", {"live_calls": 3})):
                os.makedirs(os.path.join(d, rid))
                json.dump(st, open(os.path.join(d, rid, "status.json"), "w"))
            self.assertEqual(batch.local_failures("v"), 2)
            self.assertEqual(batch.local_failures("w"), "")
            self.assertEqual(batch.local_failures("x"), "")


def _masks(frames):
    """{frame: [(id, (x0, y0, x1, y1) inclusive rectangle, prob)]} -> what samworker.crops gets per frame."""
    out = {}
    for f, objs in frames.items():
        ids = np.array([o[0] for o in objs], np.int64)
        probs = np.array([o[2] for o in objs], np.float32)
        m = np.zeros((len(objs), 40, 60), bool)
        for i, (_, (x0, y0, x1, y1), _) in enumerate(objs):
            m[i, y0:y1 + 1, x0:x1 + 1] = True
            if x1 > x0:
                m[i, y0, x0] = False        # not a plain rectangle
        out[f] = (ids, probs, m)
    return out


class WorkerCheckpoint(unittest.TestCase):
    def test_build_loads_the_checkpoint_version_hashed(self):
        """FISH_SAM_CHECKPOINT unset: build() must load the same sam3.1 file version() named and hashed (sam3's own
        default is another checkpoint)."""
        d = self.enterContext(tempfile.TemporaryDirectory())
        ck = os.path.join(d, "sam3.1_multiplex.pt")
        open(ck, "wb").write(b"weights")
        mb = mock.MagicMock()
        mb.download_ckpt_from_hf.return_value = ck
        with mock.patch.dict(sys.modules, {"sam3": mock.MagicMock(), "sam3.model_builder": mb}), \
                mock.patch.dict(os.environ, FISH_SAM_CHECKPOINT=""), mock.patch.dict(samworker._SEEN, clear=True):
            samworker._SEEN[ck] = samworker._stat(ck)       # what version() saw when it hashed the file
            samworker.build()
            mb.download_ckpt_from_hf.assert_called_with(version="sam3.1")
            self.assertEqual(mb.build_sam3_multiplex_video_predictor.call_args.kwargs["checkpoint_path"], ck)
            os.utime(ck, ns=(1, 1))                         # replaced after it was hashed
            with self.assertRaises(RuntimeError):
                samworker.build()
            samworker._SEEN.clear()                         # never hashed
            with self.assertRaises(RuntimeError):
                samworker.build()


class WorkerFormat(unittest.TestCase):
    """samworker's text, read back by the same readers the pipeline uses (no torch, no GPU)."""

    @classmethod
    def setUpClass(cls):
        try:
            import meta_sam_parser  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("meta_sam_parser not installed (FISH_PYLIB)")

    def build(self, frames, box_prompt=False):
        recs = {f: samworker.crops(*v) for f, v in _masks(frames).items()}
        return samworker.assemble(recs, 60, 40, samworker.encode_all, box_prompt)

    def test_prompts(self):
        self.assertEqual(samworker.parse_prompt("fish"), ("text", "fish"))
        self.assertEqual(samworker.parse_prompt("<220f>1<|box;x1=10;y1=20;x2=29;y2=59;w=100;h=80|>"),
                         ("box", 220, [(1, 10, 20, 29, 59)], 100, 80))
        p = "<2f>1<|box;x1=0;y1=0;x2=9;y2=9;w=20;h=10|>,2<|box;x1=10;y1=0;x2=19;y2=9;w=20;h=10|>"
        self.assertEqual(samworker.parse_prompt(p), ("box", 2, [(1, 0, 0, 9, 9), (2, 10, 0, 19, 9)], 20, 10))
        self.assertEqual(samworker.box_points(10, 20, 29, 59, 100, 80), [[0.1, 0.25], [0.3, 0.75]])

    def test_round_trip_through_the_pipeline_readers(self):
        from fishcount import maskcodec, tracks
        frames = {0: [(5, (2, 3, 10, 12), 0.9), (7, (30, 5, 50, 30), 0.6)], 1: [(5, (3, 3, 11, 13), 0.7)], 3: []}
        txt = self.build(frames)
        self.assertTrue(txt.endswith("\n"))
        self.assertEqual(len(txt.splitlines()), 2)          # frames 2 and 3 have nobody: no line, as the API
        b = tracks.parse_boxes(txt)
        self.assertEqual(sorted(b), [0, 1])
        self.assertEqual([o["id"] for o in b[0]], [0, 1])   # word prompts number tracks from 0 by first appearance
        self.assertEqual(b[0][0]["box"], (2, 3, 11, 13))    # inclusive x2/y2 in the text, half-open when read
        self.assertEqual(b[0][0]["conf"], b[1][0]["conf"])  # one conf per track, as the API (94% of its tracks)
        self.assertAlmostEqual(b[0][0]["conf"], 0.8, places=5)
        got = maskcodec.masks(txt)
        want = _masks(frames)
        for f in (0, 1):
            for (box, m), full in zip(got[f], want[f][2]):
                x0, y0, x1, y1 = box
                self.assertTrue((m == full[y0:y1, x0:x1]).all())
                self.assertEqual(int(full.sum()), int(m.sum()))
        self.assertIn(";w=60;h=40;", txt)

    def test_nothing_found_is_empty(self):
        self.assertEqual(self.build({0: [], 1: []}), "")
        self.assertEqual(self.build({0: [(1, (0, 0, 0, 0), 0.9)]}).count("<0f>"), 1)    # a one-pixel mask still counts

    def test_box_prompts_keep_their_ids(self):
        txt = self.build({4: [(1, (2, 2, 9, 9), 0.9), (2, (20, 2, 29, 9), 0.8)]}, box_prompt=True)
        from fishcount import tracks
        self.assertEqual([o["id"] for o in tracks.parse_boxes(txt)[4]], [1, 2])

    def test_sixteen_ids_at_most_like_the_api(self):
        frames = {f: [(100 + f, (f, 0, f + 2, 3), 0.9), (999, (40, 30, 45, 35), 0.8)] for f in range(20)}
        from fishcount import tracks
        b = tracks.parse_boxes(self.build(frames))
        ids = {o["id"] for v in b.values() for o in v}
        self.assertEqual(ids, set(range(16)))       # 999 and frames 0-14's new ids are 16; frames 15-19 add none
        self.assertEqual(len(b[19]), 1)             # the 16-id track 999 goes on

    def test_a_real_api_record_comes_out_byte_identical(self):
        """Lines of a real SAM 3.1 API answer (public clip clips/nautilus_s002_0_12.mp4, word "nautilus"): decoded
        and built again, each line is the same text, mask payload and conf included. (Lines whose box is the mask's
        bounds, as 95.4% of the API's records are; the others' box is a pixel or so wider, samworker docstring.)"""
        from fishcount import maskcodec
        for line in API_LINES:
            f, (x0, y0, x1, y1), mh, mw, payload = next(maskcodec.records(line))
            conf = float(line.split(";c=")[1].split("|")[0])
            full = np.zeros((1, 1080, 1920), bool)
            full[0, y0:y1, x0:x1] = maskcodec.decode(payload, mw, mh)
            recs = {f: samworker.crops(np.array([0]), np.array([conf], np.float32), full)}
            self.assertEqual(samworker.assemble(recs, 1920, 1080, samworker.encode_all, False), line + "\n")


API_LINES = [
    "<51f>0<|box;x1=1507;y1=0;x2=1690;y2=40;w=1920;h=1080;c=0.921951174736023|><|mask;x=0;y=0;c=0.921951174736023;"
    "data=41,184,!!!!!Ny4&BF7^`VQwD5jfwryK7&2/2#-_][frT7%3t=E4.4Diw]c][@:|>",
    "<7f>0<|box;x1=341;y1=798;x2=734;y2=1079;w=1920;h=1080;c=0.921951174736023|><|mask;x=0;y=0;c=0.921951174736023;"
    "data=282,394,!!!!$^@JLjVXpfkilt@E9&jD^lu3azV/WqA.tY)1z$9bi[F%Mf$=jrl[gM54RaY]%^#5v(p*0x#3(I[6fBv(Yq'V'{[0#j-F*"
    "tI=ODz'V1$-GjXr5C0t)mJzX-(#@(5{22Yy5a_bK4D5t39_k+$9E74d8h6Z&.izh!s%[vofd(#7_k4IT@-#TN.t7MldYzgcwW=:/788&/$4vc&"
    "{I*mS21#8hnOdL7jN5jy5MysCZ3Kl_NpKby1@aE2tL_g3079BF_DVB+eljRL/fvoK0KS!5{:tkls{vX!!|>",
]


if __name__ == "__main__":
    unittest.main()
