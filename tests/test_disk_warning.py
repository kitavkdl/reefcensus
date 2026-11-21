"""Long videos say early when the disk will not hold the rest of the run (longvideo.disk_need): after every finished
segment, each segment still to run like the largest segment folder so far plus the merged review videos (one more copy
of every segment's clip / annotated / clip_original), against the free space. status.json carries it; the log warns
once when it does not fit. The merged result is unchanged. No network, no spend.
Run: python3 -m unittest discover -s tests -v"""
import collections, os, sys, unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fishcount import longvideo
import test_resume

Usage = collections.namedtuple("Usage", "total used free")


class Need(unittest.TestCase):
    def test_left_segments_like_the_largest_plus_every_review_video_once_more(self):
        self.assertEqual(longvideo.disk_need([100, 300], [40, 60], left=2, n_segs=4), 300 * 2 + 60 * 4)

    def test_nothing_left_still_needs_the_merged_review_videos(self):
        self.assertEqual(longvideo.disk_need([100], [40], left=0, n_segs=1), 40)


class InTheRun(unittest.TestCase):
    """The fake 4-segment long video of test_resume; segment folders get a 1000-byte clip.mp4."""
    setUp = test_resume.Resume.setUp
    run_long = test_resume.Resume.run_long
    N = test_resume.Resume.N

    def run_with_free(self, free, **kw):
        orig = longvideo.pipeline.run_pipeline

        def with_clip(sp, srid, **k):
            orig(sp, srid, **k)
            with open(os.path.join(self.tmp, srid, "clip.mp4"), "wb") as f:
                f.write(b"x" * 1000)
        with mock.patch.object(longvideo.pipeline, "run_pipeline", with_clip), \
                mock.patch.object(longvideo, "_concat", lambda parts, out: None), \
                mock.patch.object(longvideo.shutil, "disk_usage", lambda p: Usage(10 ** 12, 0, free)):
            return self.run_long(**kw)

    def test_a_disk_too_small_is_said_once_after_the_first_segment(self):
        R, st = self.run_with_free(2000)
        warn = [x for x in st["log"] if "disk:" in x]
        self.assertEqual(len(warn), 1)
        self.assertIn("segment S1", st["log"][st["log"].index(warn[0]) - 1])     # right after the first segment
        self.assertIn("free", warn[0])
        self.assertEqual(st["disk"]["free"], 2000)
        self.assertGreaterEqual(st["disk"]["need"], 1000 * 4)     # the merged clip alone is 4 x 1000 bytes
        self.assertNotIn("disk", R)

    def test_enough_disk_logs_nothing_but_status_has_it(self):
        R, st = self.run_with_free(10 ** 12)
        self.assertEqual(sum("disk:" in x for x in st["log"]), 0)
        self.assertEqual(st["disk"]["free"], 10 ** 12)

    def test_the_result_is_the_same_either_way(self):
        R0, _ = self.run_with_free(10 ** 12, rid="big")
        R, _ = self.run_with_free(2000, rid="v")
        import json
        strip = lambda R: json.loads(json.dumps({k: v for k, v in R.items() if k != "id"}).replace("big__S", "v__S"))
        self.assertEqual(strip(R), strip(R0))


if __name__ == "__main__":
    unittest.main()
