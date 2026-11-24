"""<run>/provenance.json (fishcount/provenance.py): what made a run, one entry per start, never stopping the run.
No network, $0."""
import hashlib, json, os, shutil, subprocess, sys, tempfile, unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fishcount import _pylib  # noqa: F401
from fishcount import api, provenance, video


class Provenance(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.run = os.path.join(self.tmp, "r1")
        self.src = os.path.join(self.tmp, "v.mp4")
        with open(self.src, "wb") as f:
            f.write(b"x" * 1234)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def entries(self):
        with open(os.path.join(self.run, "provenance.json")) as f:
            return json.load(f)["runs"]

    def test_entry_says_code_options_models_encoder_source(self):
        argv = ["fishcount/pipeline.py", self.src, "--id", "r1", "--zoom", "--max-usd", "2"]
        provenance.start(self.run, argv, self.src)
        e = self.entries()[0]
        self.assertEqual(e["command"], argv)
        self.assertEqual(e["models"], dict(sam="sam-3.1", spark=api.SPARK_MODEL))
        self.assertEqual(e["encoder"]["x264_args"], list(video.X264_ARGS))
        self.assertEqual(e["encoder"]["ffmpeg"], video.FFMPEG)
        self.assertTrue(e["encoder"]["version"].startswith("ffmpeg version"))
        self.assertEqual((e["source"]["path"], e["source"]["size"]), (self.src, 1234))
        head = subprocess.run(["git", "-C", ROOT, "rev-parse", "HEAD"], capture_output=True, text=True)
        if head.returncode == 0:
            self.assertEqual(e["code"]["commit"], head.stdout.strip())
            self.assertIn(e["code"]["dirty"], (True, False))
        self.assertIn("python", e["machine"])
        self.assertEqual(e["private"], {"on": api.PRIVATE, "by": list(api.PRIVATE_BY)})
        self.assertNotIn("finished", e)

    def test_local_sam_settings_are_recorded(self):
        with mock.patch.dict(os.environ, FISH_SAM_BATCH="2", FISH_SAM_OFFLOAD="0"):
            provenance.start(self.run, ["x"], self.src)
        env = self.entries()[0]["environment"]
        self.assertEqual((env["FISH_SAM_BATCH"], env["FISH_SAM_OFFLOAD"]), ("2", "0"))

    def test_finish_adds_the_result_hash_or_the_error(self):
        provenance.start(self.run, ["a"], self.src)
        with open(os.path.join(self.run, "result.json"), "w") as f:
            f.write('{"metrics": {}}')
        provenance.finish(self.run)
        e = self.entries()[-1]
        self.assertEqual(e["result_sha256"], hashlib.sha256(b'{"metrics": {}}').hexdigest())
        self.assertIn("finished", e)
        provenance.start(self.run, ["b"], self.src)     # a rerun (--resume, batch): earlier entry kept
        provenance.finish(self.run, error="FileNotFoundError: not cached: spark call")
        es = self.entries()
        self.assertEqual([x["command"] for x in es], [["a"], ["b"]])
        self.assertEqual(es[1]["error"], "FileNotFoundError: not cached: spark call")
        self.assertNotIn("result_sha256", es[1])
        self.assertIn("result_sha256", es[0])

    def test_never_raises(self):
        os.makedirs(self.run)
        with open(os.path.join(self.run, "provenance.json"), "w") as f:
            f.write('{"runs": [half')        # a file cut short: started over, not a crash
        self.assertIsNotNone(provenance.start(self.run, ["a"], self.src))
        self.assertEqual(len(self.entries()), 1)
        blocked = os.path.join(self.tmp, "file_not_dir")
        open(blocked, "w").close()
        self.assertIsNone(provenance.start(os.path.join(blocked, "r"), ["a"], self.src))
        provenance.finish(os.path.join(self.tmp, "nothing_here"))       # no entry: nothing to do
        os.remove(os.path.join(self.run, "provenance.json"))
        provenance.start(self.run, ["a"], self.src)
        provenance.finish(self.run)          # no result.json: reported, not raised
        self.assertNotIn("result_sha256", self.entries()[-1])

    def test_missing_source_and_no_git(self):
        saved = provenance.ROOT
        provenance.ROOT = self.tmp              # not a git checkout
        try:
            provenance.start(self.run, ["a"], os.path.join(self.tmp, "gone.mp4"))
        finally:
            provenance.ROOT = saved
        e = self.entries()[0]
        self.assertIsNone(e["code"])
        self.assertEqual(e["source"], dict(path=os.path.join(self.tmp, "gone.mp4")))


if __name__ == "__main__":
    unittest.main()
