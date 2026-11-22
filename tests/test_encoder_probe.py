"""Encoder probe (video.encoder_probe) and the warning when this machine would re-encode to other bytes than the
one that filled the cache (api.encoder_check; round 3, 11/21c). No network, $0."""
import json, os, shutil, subprocess, sys, tempfile, unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fishcount import _pylib  # noqa: F401
from fishcount import api, provenance, video


class Probe(unittest.TestCase):
    def test_same_machine_same_probe(self):
        a, b = video.encoder_probe(), video.encoder_probe()
        self.assertIsInstance(a, str)
        self.assertEqual(len(a), 24)
        self.assertEqual(a, b)

    def test_other_thread_count_other_probe(self):
        # x264 at another thread count gives other bytes on real clips (the 11/3 cache-miss incident): so must the probe
        now = video.encoder_probe()
        args = ["-threads", "4"] + video.X264_ARGS[2:]
        with mock.patch.object(video, "X264_ARGS", args):
            self.assertNotEqual(video.encoder_probe(), now)

    def test_broken_ffmpeg_is_none(self):
        with mock.patch.object(video, "FFMPEG", "/nonexistent/ffmpeg"):
            self.assertIsNone(video.encoder_probe())


class Check(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d)
        p = mock.patch.object(api, "CACHE", self.d)
        p.start()
        self.addCleanup(p.stop)
        self.f = os.path.join(self.d, api.ENCODER_FILE)

    def test_first_live_run_records_then_same_probe_is_quiet(self):
        self.assertIsNone(api.encoder_check("abc", write=True))
        with open(self.f) as fh:
            self.assertEqual(json.load(fh)["probe"], "abc")
        self.assertIsNone(api.encoder_check("abc", write=True))
        self.assertIsNone(api.encoder_check("abc", write=False))

    def test_offline_run_does_not_record(self):
        self.assertIsNone(api.encoder_check("abc", write=False))
        self.assertFalse(os.path.exists(self.f))

    def test_other_probe_warns_and_keeps_the_record(self):
        api.encoder_check("abc", write=True)
        w = api.encoder_check("xyz", write=True)
        self.assertIn("xyz", w)
        self.assertIn("abc", w)
        self.assertIn("paid for again", w)
        with open(self.f) as fh:
            self.assertEqual(json.load(fh)["probe"], "abc")

    def test_no_probe_or_broken_record_never_raises(self):
        self.assertIsNone(api.encoder_check(None))
        with open(self.f, "w") as fh:
            fh.write('{"probe": "ab')         # cut short: treated as no record, replaced by a live run
        self.assertIsNone(api.encoder_check("abc", write=True))
        with open(self.f) as fh:
            self.assertEqual(json.load(fh)["probe"], "abc")
        with mock.patch.object(api, "CACHE", os.path.join(self.f, "not_a_dir")):
            self.assertIsNone(api.encoder_check("abc", write=True))

    def test_new_cache_folder_is_made(self):
        with mock.patch.object(api, "CACHE", os.path.join(self.d, "new")):
            self.assertIsNone(api.encoder_check("abc", write=True))
        self.assertTrue(os.path.exists(os.path.join(self.d, "new", api.ENCODER_FILE)))


class Provenance(unittest.TestCase):
    def test_probe_and_warning_in_the_entry(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        run = os.path.join(d, "r")
        provenance.start(run, ["x"], __file__, probe="abc", encoder_warning="w!")
        provenance.start(run, ["x"], __file__)
        with open(os.path.join(run, "provenance.json")) as fh:
            a, b = json.load(fh)["runs"]
        self.assertEqual((a["encoder"]["probe"], a["encoder_warning"]), ("abc", "w!"))
        self.assertNotIn("probe", b["encoder"])
        self.assertNotIn("encoder_warning", b)


class Cli(unittest.TestCase):
    def test_cli_warns_and_still_runs(self):
        # a cache recorded with another probe: the CLI says so on stderr and in provenance, then runs as before (here:
        # offline with no cached answers, so it stops at the first call, as without the check)
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        with open(os.path.join(d, api.ENCODER_FILE), "w") as fh:
            json.dump({"probe": "0" * 24, "recorded": "2026-01-01"}, fh)
        rid = f"test_encoder_probe_{os.getpid()}"
        run = os.path.join(ROOT, "runs", rid)
        self.addCleanup(shutil.rmtree, run, True)
        env = dict(os.environ, FISH_CACHE_DIR=d, FISH_LEDGER=os.path.join(d, "ledger.jsonl"))
        p = subprocess.run([sys.executable, os.path.join(ROOT, "fishcount", "pipeline.py"),
                            os.path.join(ROOT, "tests", "data", "nautilus_s004_0_12.mp4"), "--id", rid, "--offline",
                            "--discover", "--max-usd", "0"], capture_output=True, text=True, env=env, timeout=300)
        self.assertIn("WARNING: this machine's video encoder makes other clip bytes", p.stderr)
        self.assertIn("not cached", p.stderr)          # the run itself went on to its first call
        with open(os.path.join(run, "provenance.json")) as fh:
            e = json.load(fh)["runs"][-1]
        self.assertEqual(e["encoder"]["probe"], video.encoder_probe())
        self.assertIn("other clip bytes", e["encoder_warning"])
        with open(os.path.join(d, api.ENCODER_FILE)) as fh:
            self.assertEqual(json.load(fh)["probe"], "0" * 24)      # the record is not replaced


if __name__ == "__main__":
    unittest.main()
