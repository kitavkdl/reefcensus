"""The first-pass estimate that run_pipeline checks against --max-usd counts only SAM calls not in the cache.
Before, a 600-s segment rerun with every call cached stopped at the default $1 cap ("estimate $2.13 > per-video cap
$1.00", LONG1 S2 replayed live, 11/21c) with nothing to pay. Uncached calls count as before (whole clip each).
No network, no spend. Run: python3 -m unittest discover -s tests -v"""
import os, sys, unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fishcount import _pylib  # noqa: F401
from fishcount import api, pipeline

N = 2662    # LONG1 S2's frames: 4 calls x 2662 x $0.0002 = $2.13, the logged estimate


class FirstEstimate(unittest.TestCase):
    jobs = [("p0", "fish", "fish", "clip.mp4", None)]
    others = [({"what": "dark lump on seabed"}, ["crab", "shell", "starfish"])]

    def est(self, cached):
        with mock.patch.object(api, "sam_cached", lambda clip, prompt: (clip, prompt) in cached):
            return pipeline.first_estimate(self.jobs, self.others, "clip.mp4", N)

    def test_nothing_cached_is_the_old_estimate(self):
        self.assertAlmostEqual(self.est(set()), 4 * N * api.SAM_PER_FRAME)
        self.assertEqual(round(self.est(set()), 2), 2.13)

    def test_all_cached_is_free(self):
        cached = {("clip.mp4", w) for w in ("fish", "crab", "shell", "starfish")}
        self.assertEqual(self.est(cached), 0)

    def test_only_the_uncached_calls_count(self):
        self.assertAlmostEqual(self.est({("clip.mp4", "fish"), ("clip.mp4", "crab")}), 2 * N * api.SAM_PER_FRAME)

    def test_a_tile_job_is_looked_up_by_its_own_file(self):
        jobs = self.jobs + [("zoom-r1c1", "fish", "fish", "tile_r1c1.mp4", (0, 0, 10, 10))]
        with mock.patch.object(api, "sam_cached", lambda clip, prompt: (clip, prompt) == ("clip.mp4", "fish")):
            est = pipeline.first_estimate(jobs, [], "clip.mp4", N)
        self.assertAlmostEqual(est, N * api.SAM_PER_FRAME)

    def test_short_clips_pay_the_minimum(self):
        with mock.patch.object(api, "sam_cached", lambda clip, prompt: False):
            self.assertAlmostEqual(pipeline.first_estimate(self.jobs, [], "clip.mp4", 10),
                                   api.SAM_MIN_FRAMES * api.SAM_PER_FRAME)

    def test_skipped_people_have_no_words(self):
        with mock.patch.object(api, "sam_cached", lambda clip, prompt: False):
            est = pipeline.first_estimate(self.jobs, [({"what": "diver"}, [])], "clip.mp4", N)
        self.assertAlmostEqual(est, N * api.SAM_PER_FRAME)


if __name__ == "__main__":
    unittest.main()
