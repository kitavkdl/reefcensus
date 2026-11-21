"""Long videos with segments run at once (longvideo.run_long segment_workers, --segment-workers), the one-at-a-time
reverse filter (video.REVERSE_SLOT) and the thread-safe C mask decoder load. No network, no spend.
Run: python3 -m unittest discover -s tests -v"""
import json, os, shutil, subprocess, sys, tempfile, threading, time, unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fishcount import _pylib  # noqa: F401
from fishcount import api, longvideo, maskcodec, pipeline, video
from test_longvideo import _fake_seg


class Overlap:
    """Counts how many callers are inside at once."""

    def __init__(self):
        self.now, self.most, self.lock = 0, 0, threading.Lock()

    def __enter__(self):
        with self.lock:
            self.now += 1
            self.most = max(self.most, self.now)

    def __exit__(self, *exc):
        with self.lock:
            self.now -= 1


class SegmentWorkers(unittest.TestCase):
    N = 3000    # 600 s at 5 fps -> 4 segments of 150 s at seg_s=150

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.cuts, self.started, self.fail_at = {}, [], None
        self.inside = Overlap()
        self.other_in = threading.Event()

        def ingest(src, dst, **k):
            open(dst, "w").close()

        def cut(clip, dst, start, n):
            self.cuts[dst] = (start, n)
            open(dst, "w").close()

        def run_pipeline(sp, srid, **kw):
            start, n = self.cuts[sp]
            self.started.append(start)
            with self.inside:
                if self.fail_at == start:
                    # fail while another segment is running: when both just slept 0.3 s, the other could finish first
                    # and start a third segment before the failure was seen (2 in 10 runs), or, failing at once, the
                    # other had not started yet; so wait until another segment is in, then fail
                    self.other_in.wait(5)
                    raise api.BudgetExceeded("FISH_BUDGET")
                self.other_in.set()
                time.sleep(0.3)
                d = os.path.join(self.tmp, srid)
                # a different count per segment, so a merge that took them out of order would show
                _fake_seg(d, n, [(10 * i, 10, 5, 5) for i in range(start // 750 + 1)])
                json.dump(dict(live_calls=2, cached_calls=1, billed_usd=0.25), open(os.path.join(d, "status.json"), "w"))

        self.patches = [mock.patch.object(pipeline, "RUNS", self.tmp), mock.patch.object(video, "ingest", ingest),
                        mock.patch.object(video, "info", lambda p: dict(n_frames=self.N, fps=5.0, width=100, height=100)),
                        mock.patch.object(video, "light_stats", lambda p: dict(median_l=100, mean_l=100)),
                        mock.patch.object(longvideo, "cut", cut), mock.patch.object(pipeline, "run_pipeline", run_pipeline)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_long(self, rid, workers):
        t = time.time()
        R = longvideo.run_long("v.mp4", rid, seg_s=150, segment_workers=workers, max_usd=1.0)
        st = json.load(open(os.path.join(self.tmp, rid, "status.json")))
        return R, st, time.time() - t

    def test_two_workers_give_the_same_merge_in_about_half_the_time(self):
        R1, st1, t1 = self.run_long("serial", 1)
        self.assertEqual(self.inside.most, 1)
        self.inside.most = 0
        R2, st2, t2 = self.run_long("pair", 2)
        self.assertEqual(self.inside.most, 2)
        strip = lambda R: json.loads(json.dumps({k: v for k, v in R.items() if k != "id"}).replace("pair__S", "serial__S"))
        self.assertEqual(strip(R2), strip(R1))
        self.assertEqual([s["start_frame"] for s in R2["segments"]], [0, 750, 1500, 2250])
        self.assertEqual(R2["metrics"]["fish"]["maxn"], 4)        # the last segment's 4 boxes
        for st in (st1, st2):
            self.assertEqual((st["live_calls"], st["cached_calls"], st["billed_usd"]), (8, 4, 1.0))
            self.assertEqual(sum(" done: " in line for line in st["log"]), 4)
        self.assertLess(t2, t1 * 0.75)

    def test_more_workers_than_segments_is_fine(self):
        R, st, _ = self.run_long("many", 9)
        self.assertEqual(self.inside.most, 4)
        self.assertEqual(len(R["segments"]), 4)

    def test_a_failing_segment_stops_the_ones_not_started(self):
        self.fail_at = 0
        with self.assertRaises(api.BudgetExceeded):
            self.run_long("stop", 2)
        self.assertEqual(sorted(self.started), [0, 750])     # 1500 and 2250 were never sent

    def test_skip_empty_keeps_one_at_a_time(self):
        from fishcount import screen
        with mock.patch.object(screen, "scan", lambda clip, fps, **k: [dict(start=0, n=self.N, kind="head")]), \
                mock.patch.object(longvideo, "_filler", lambda full, d, a, *k: os.path.join(d, f"skip{a}")):
            longvideo.run_long("v.mp4", "skip", seg_s=150, skip_empty=True, max_usd_video=10, segment_workers=2)
        self.assertEqual(self.inside.most, 1)
        st = json.load(open(os.path.join(self.tmp, "skip", "status.json")))
        self.assertTrue(any("not used with skip_empty" in line for line in st["log"]))


class SegmentWorkersFlag(unittest.TestCase):
    def test_flag_is_refused_with_skip_empty_and_below_one(self):
        for extra in (["--skip-empty", "--segment-workers", "2"], ["--segment-workers", "0"]):
            p = subprocess.run([sys.executable, os.path.join(ROOT, "fishcount", "pipeline.py"), "missing.mp4"] + extra,
                               capture_output=True, text=True, timeout=120)
            self.assertEqual(p.returncode, 2, p.stderr)
            self.assertIn("--segment-workers", p.stderr)


class ReverseSlot(unittest.TestCase):
    def test_one_reverse_filter_at_a_time(self):
        inside = Overlap()

        def fake_run(cmd, check):
            with inside:
                time.sleep(0.1)
        with mock.patch.object(video.subprocess, "run", fake_run):
            ts = [threading.Thread(target=video._reverse_run, args=(["ffmpeg"],)) for _ in range(4)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
        self.assertEqual(inside.most, 1)

    def test_reverse_still_gives_the_backward_clip(self):
        """A short clip (single command) and a chunked one through the slot: frame i of the reversed clip is frame
        n-1-i of the source (the counter is drawn as a grey level)."""
        import numpy as np
        d = tempfile.mkdtemp()
        try:
            src = os.path.join(d, "src.mp4")
            subprocess.run([video.FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                            "color=c=black:s=64x48:r=5:d=6", "-vf", "geq=lum='N*8':cb=128:cr=128", "-c:v", "libx264",
                            "-g", "25", "-pix_fmt", "yuv420p", src], check=True)
            n = video.info(src)["n_frames"]
            fw = [int(f.mean()) for _, f in video.iter_frames(src, range(n))]
            for chunk in (100, 10):     # 30 frames: one command at chunk 100, three chunks at chunk 10
                dst = os.path.join(d, f"rev{chunk}.mp4")
                video.reverse(src, dst, chunk=chunk)
                bw = [int(f.mean()) for _, f in video.iter_frames(dst, range(n))]
                self.assertEqual(len(bw), n)
                self.assertTrue(np.all(np.abs(np.array(bw) - np.array(fw[::-1])) <= 3), (chunk, bw, fw))
        finally:
            shutil.rmtree(d, ignore_errors=True)


class MaskDecoderLoad(unittest.TestCase):
    def test_threads_loading_at_once_all_get_the_c_decoder(self):
        if not maskcodec.fast():
            self.skipTest("no C compiler here")
        got = []
        with mock.patch.object(maskcodec, "_lib", None):
            ts = [threading.Thread(target=lambda: got.append(maskcodec._load())) for _ in range(8)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
        self.assertEqual(len(got), 8)
        self.assertTrue(all(got))


if __name__ == "__main__":
    unittest.main()
