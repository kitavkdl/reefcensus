"""D-H1APPLY: a counted mid-confidence yes leaves the human queue (--queue-conf, 0.5 on the command line and the
review screen; 0.7 = every one queued, as before). No network, no spend.
Run: python3 -m unittest discover -s tests -v"""
import glob, json, os, shutil, subprocess, sys, tempfile, unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "web"))
from fishcount import _pylib  # noqa: F401,E402
from fishcount import api, longvideo, pipeline, video  # noqa: E402

DEMO = sorted(glob.glob(os.path.join(ROOT, "demo", "runs", "cr11_s00?")))


def yes(conf, **kw):
    return dict(is_target=True, species="unknown", confidence=conf, **kw)


class Unqueue(unittest.TestCase):
    def case(self, source, v, label="fish (unidentified)", conf=0.5):
        trk = {"T": dict(source=source, label="fish")}
        verdicts = {"T": dict(v)}
        out = pipeline.unqueue(trk, verdicts, {"T": label}, conf)
        return out == ["T"], verdicts["T"]

    def test_counted_prompt_and_discovered_yes_leaves_the_queue(self):
        for src in ("p0", "p0+177", "d0", "d3"):
            for c in (0.5, 0.55, 0.69):
                left, v = self.case(src, yes(c))
                self.assertTrue(left, (src, c))
                self.assertTrue(v["unqueued"])
                self.assertFalse(pipeline.needs_review(v))
        self.assertTrue(pipeline.needs_review(yes(0.6)))     # no mark: queued as before

    def test_motion_and_other_sources_stay_queued(self):
        """Explicit source rule (review 1, condition 1): a motion track is counted only on a confident yes, so the
        queue is where a person can restore it; even a motion track counted after confirm_2 stays. Camo, crowd tiles,
        crowd-peak tiles, site memory, zoom, a discovered word's zoom / cell / backfill jobs (d0z-, d0c-, d0rev; 2-axis
        review at wrap) and the missed-animal look were not measured: they stay too."""
        for src in ("m0", "m12", "camo0", "crowd-r1c2", "peak+p0", "s0", "zoom-top", "x0", "k0",
                    "d0rev", "d1z-center", "d0c-bottom", "d0c-bottomrev", "p0x", "d0+3rev"):
            left, v = self.case(src, yes(0.6))
            self.assertFalse(left, src)
            self.assertNotIn("unqueued", v)
            self.assertTrue(pipeline.needs_review(v))

    def test_other_reasons_and_bounds_stay_queued(self):
        for v in (yes(0.49), yes(0.7), yes(0.6, shadow={"what": "shadow"}), yes(0.6, peak_doubt="peak frame 3"),
                  yes(0.6, name_disagrees="crab vs fish"), yes(0.6, confirm={"is_animal": True, "confidence": 0.9}),
                  yes(0.6, relabelled="fish -> crab"), dict(yes(0.6), is_target=False), dict(yes(0.6), is_target=None)):
            left, out = self.case("p0", v)
            self.assertFalse(left, v)
            self.assertEqual(pipeline.needs_review(out), pipeline.needs_review(v), v)
        self.assertFalse(self.case("p0", yes(0.6), label=None)[0])      # not counted: left out of the queue = lost

    def test_threshold(self):
        self.assertFalse(self.case("p0", yes(0.6), conf=0.7)[0])         # 0.7: nothing changes
        self.assertFalse(self.case("p0", yes(0.6), conf=0.65)[0])
        self.assertTrue(self.case("p0", yes(0.4), conf=0.3)[0])           # lower: more leave

    def test_a_later_reason_queues_it_again(self):
        v = yes(0.6, unqueued=True)
        self.assertFalse(pipeline.needs_review(v))
        for k, x in (("shadow", {"what": "shadow"}), ("peak_doubt", "p"), ("name_disagrees", "a vs b")):
            self.assertTrue(pipeline.needs_review(dict(v, **{k: x})), k)


@unittest.skipUnless(DEMO, "demo runs not present")
class LongMerge(unittest.TestCase):
    def test_mark_and_setting_survive_the_merge(self):
        d = next(x for x in DEMO if x.endswith("s003"))
        res = json.load(open(os.path.join(d, "result.json")))
        t = next(iter(res["verdicts"]))
        res["verdicts"][t]["unqueued"] = True
        res["queue_conf"] = 0.5
        n, fps = res["video"]["n_frames"], res["video"]["fps"]
        with tempfile.TemporaryDirectory() as tmp:
            s = os.path.join(tmp, "seg")
            shutil.copytree(d, s)
            with open(os.path.join(s, "result.json"), "w") as f:
                json.dump(res, f)
            R = longvideo.merge("t", res["source"], [(s, 0, n), (d, n, n)], fps, out_dir=os.path.join(tmp, "out"))
        self.assertTrue(R["verdicts"]["S1:" + t]["unqueued"])
        self.assertNotIn("unqueued", R["verdicts"]["S2:" + t])
        self.assertEqual(R["queue_conf"], 0.5)
        with tempfile.TemporaryDirectory() as tmp:     # segments made at 0.7 (or before this): no key, same bytes
            R = longvideo.merge("t", res["source"], [(d, 0, n)], fps, out_dir=tmp)
        self.assertNotIn("queue_conf", R)


class CommandLine(unittest.TestCase):
    def cli(self, *extra):
        """pipeline.py's command line, in this process, up to run_long (as test_segment_workers)."""
        import runpy
        from fishcount import provenance
        got = {}

        class Stop(Exception):
            pass

        def run_long(*a, **k):
            got.update(k)
            raise Stop
        with mock.patch.object(sys, "argv", ["pipeline.py", "v.mp4", "--id", "cli"] + list(extra)), \
                mock.patch.object(video, "encoder_probe", lambda: {}), \
                mock.patch.object(api, "encoder_check", lambda probe, write=True: None), \
                mock.patch.object(provenance, "start", lambda *a, **k: None), \
                mock.patch.object(provenance, "effective", lambda *a, **k: None), \
                mock.patch.object(provenance, "finish", lambda *a, **k: None), \
                mock.patch.object(video, "info", lambda p: dict(n_frames=18000, fps=5.0)), \
                mock.patch.object(longvideo, "needs_split", lambda *a: True), \
                mock.patch.object(longvideo, "run_long", run_long), self.assertRaises(Stop):
            runpy.run_path(os.path.join(ROOT, "fishcount", "pipeline.py"), run_name="__main__")
        return got

    def test_default_half_and_old_behaviour_on_request(self):
        self.assertEqual(self.cli()["queue_conf"], 0.5)
        self.assertEqual(self.cli("--queue-conf", "0.7")["queue_conf"], 0.7)

    def test_out_of_range_is_refused(self):
        for bad in ("-0.1", "1.5"):
            p = subprocess.run([sys.executable, os.path.join(ROOT, "fishcount", "pipeline.py"), "missing.mp4",
                                "--queue-conf", bad], capture_output=True, text=True, timeout=120)
            self.assertEqual(p.returncode, 2, p.stderr)
            self.assertIn("--queue-conf", p.stderr)

    def test_library_default_unchanged(self):
        import inspect
        self.assertEqual(inspect.signature(pipeline._run_pipeline).parameters["queue_conf"].default, 0.7)
        self.assertEqual(pipeline.QUEUE_CONF, 0.5)


class ReviewScreen(unittest.TestCase):
    def test_screen_runs_use_the_command_line_default(self):
        import server
        got = {}

        class Now:      # the run's thread, run at once
            def __init__(self, target, daemon=None):
                self.target = target

            def start(self):
                self.target()
        with tempfile.TemporaryDirectory() as runs, \
                mock.patch.object(server, "RUNS", runs), \
                mock.patch.object(server, "clip_path", lambda name: "c.mp4"), \
                mock.patch.object(server.video, "info", lambda p: dict(n_frames=50, fps=5.0)), \
                mock.patch.object(server.pipeline, "run_pipeline", lambda *a, **k: got.update(k)), \
                mock.patch.object(server.threading, "Thread", Now):
            server.start_run({"clip": "c.mp4"})
        self.assertEqual(got["queue_conf"], pipeline.QUEUE_CONF)


if __name__ == "__main__":
    unittest.main()
