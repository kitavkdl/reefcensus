"""Long videos resumed after a crash (longvideo.run_long resume, --resume): a segment that finished with the same clip
bytes, options and code is not run again and the merge is the same; a changed option, clip or code runs it again.
No network, no spend. Run: python3 -m unittest discover -s tests -v"""
import json, os, shutil, subprocess, sys, tempfile, unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fishcount import _pylib  # noqa: F401
from fishcount import api, longvideo, pipeline, video
from test_longvideo import _fake_seg


class Resume(unittest.TestCase):
    N = 3000    # 600 s at 5 fps -> 4 segments of 150 s at seg_s=150

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cuts, self.started, self.fail_at = {}, [], None

        def ingest(src, dst, **k):
            open(dst, "w").close()

        def cut(clip, dst, start, n):
            self.cuts[dst] = (start, n)
            with open(dst, "w") as f:
                f.write(f"{start}+{n}")         # each segment clip its own bytes

        def run_pipeline(sp, srid, **kw):
            start, n = self.cuts[sp]
            self.started.append(start)
            if self.fail_at == start:
                raise api.BudgetExceeded("FISH_BUDGET")
            d = os.path.join(self.tmp, srid)
            _fake_seg(d, n, [(10 * i, 10, 5, 5) for i in range(start // 750 + 1)])
            json.dump(dict(live_calls=2, cached_calls=1, billed_usd=0.25), open(os.path.join(d, "status.json"), "w"))

        for p in (mock.patch.object(pipeline, "RUNS", self.tmp), mock.patch.object(video, "ingest", ingest),
                  mock.patch.object(video, "info", lambda p: dict(n_frames=self.N, fps=5.0, width=100, height=100)),
                  mock.patch.object(video, "light_stats", lambda p: dict(median_l=100, mean_l=100)),
                  mock.patch.object(longvideo, "cut", cut), mock.patch.object(pipeline, "run_pipeline", run_pipeline)):
            p.start()
        self.addCleanup(mock.patch.stopall)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_long(self, rid="v", **kw):
        kw.setdefault("max_usd", 1.0)
        R = longvideo.run_long("v.mp4", rid, seg_s=150, **kw)
        return R, json.load(open(os.path.join(self.tmp, rid, "status.json")))

    def test_crash_then_resume_runs_only_the_rest_and_merges_the_same(self):
        R0, _ = self.run_long("whole")                                  # reference: one run without a crash
        self.started.clear()
        self.fail_at = 1500
        with self.assertRaises(api.BudgetExceeded):
            self.run_long()
        self.assertEqual(self.started, [0, 750, 1500])
        self.fail_at, self.started[:] = None, []
        R, st = self.run_long(resume=True)
        self.assertEqual(self.started, [1500, 2250])                    # S1, S2 kept
        strip = lambda R: json.loads(json.dumps({k: v for k, v in R.items() if k != "id"}).replace("whole__S", "v__S"))
        self.assertEqual(strip(R), strip(R0))
        self.assertEqual(sum("kept from the earlier run" in line for line in st["log"]), 2)
        self.assertEqual((st["live_calls"], st["cached_calls"], st["billed_usd"]), (4, 2, 0.5))   # only S3, S4 spent

    def test_without_resume_every_segment_runs_again(self):
        self.run_long()
        self.started.clear()
        self.run_long()
        self.assertEqual(self.started, [0, 750, 1500, 2250])

    def test_offline_replay_resumes_a_live_run(self):
        self.run_long(offline=False)
        self.started.clear()
        self.run_long(resume=True, offline=True)
        self.assertEqual(self.started, [])

    def test_another_option_runs_again(self):
        self.run_long()
        self.started.clear()
        self.run_long(resume=True, max_usd=2.0)
        self.assertEqual(self.started, [0, 750, 1500, 2250])

    def test_changed_code_runs_again(self):
        self.run_long()
        self.started.clear()
        with mock.patch.object(longvideo, "_fingerprint", lambda sp, kw: dict(code="other")):
            self.run_long(resume=True)
        self.assertEqual(self.started, [0, 750, 1500, 2250])

    def test_changed_clip_runs_that_segment_again(self):
        self.run_long()
        self.started.clear()
        fp = os.path.join(self.tmp, "v__S2", "resume.json")
        j = json.load(open(fp))
        j["clip"] = "0" * 24                                            # as if S2's cut came out different
        json.dump(j, open(fp, "w"))
        self.run_long(resume=True)
        self.assertEqual(self.started, [750])

    def test_fingerprint_follows_the_code(self):
        sp = os.path.join(self.tmp, "c.mp4")
        open(sp, "w").write("x")
        a = longvideo._fingerprint(sp, dict(max_usd=1.0, offline=True))
        self.assertEqual(a, longvideo._fingerprint(sp, dict(max_usd=1.0, offline=False)))
        self.assertNotEqual(a, longvideo._fingerprint(sp, dict(max_usd=1.5)))
        real = open
        def other_code(p, *k, **kw):
            f = real(p, *k, **kw)
            if p.endswith("longvideo.py"):
                return __import__("io").BytesIO(f.read() + b"#")
            return f
        with mock.patch("builtins.open", other_code):
            self.assertNotEqual(a["code"], longvideo._fingerprint(sp, dict(max_usd=1.0))["code"])


class ResumeFlag(unittest.TestCase):
    def test_flag_is_refused_with_skip_empty(self):
        p = subprocess.run([sys.executable, os.path.join(ROOT, "fishcount", "pipeline.py"), "missing.mp4", "--resume",
                            "--skip-empty"], capture_output=True, text=True, timeout=120)
        self.assertEqual(p.returncode, 2, p.stderr)
        self.assertIn("--resume", p.stderr)


if __name__ == "__main__":
    unittest.main()
