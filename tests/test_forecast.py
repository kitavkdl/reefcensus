"""Long videos say, after every finished segment, what the segments left may cost and take (longvideo.forecast): a range
from the cheapest to the dearest segment run so far, no fitted constants. The merged result is unchanged.
No network, no spend. Run: python3 -m unittest discover -s tests -v"""
import json, os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fishcount import longvideo
import test_resume


class Range(unittest.TestCase):
    def test_left_segments_between_the_cheapest_and_the_dearest(self):
        fc = longvideo.forecast([2.13, 5.88], [600, 1500], 4)
        self.assertEqual(fc, dict(left=4, usd=[8.52, 23.52], s=[2400, 6000]))

    def test_fewer_than_two_run_or_nothing_left_says_nothing(self):
        self.assertIsNone(longvideo.forecast([], [], 5))
        self.assertIsNone(longvideo.forecast([0.54], [627], 5))     # one segment is a point, not a range
        self.assertIsNone(longvideo.forecast([1.0, 2.0], [60, 90], 0))

    def test_workers_share_the_time_not_the_money(self):
        fc = longvideo.forecast([1.0, 2.0], [100, 300], 3, workers=2)
        self.assertEqual(fc["usd"], [3.0, 6.0])
        self.assertEqual(fc["s"], [150, 600])        # 100 x 3/2 .. 300 x ceil(3/2)

    def test_cached_segments_forecast_zero_dollars(self):
        self.assertEqual(longvideo.forecast([0.0, 0.0], [30, 40], 2)["usd"], [0.0, 0.0])


class InTheRun(unittest.TestCase):
    """The same fake long video as test_resume: 4 segments, each billed $0.25."""
    setUp = test_resume.Resume.setUp
    run_long = test_resume.Resume.run_long
    N = test_resume.Resume.N

    def test_a_forecast_line_from_the_second_segment_to_the_one_before_last(self):
        R, st = self.run_long()
        lines = [x for x in st["log"] if " forecast: " in x]
        self.assertEqual(len(lines), 2)
        self.assertIn("2 segment(s) run so far $0.50", lines[0])
        self.assertIn("2 left: $0.50-$0.50", lines[0])
        self.assertIn("1 left: $0.25-$0.25", lines[-1])
        self.assertIsNone(st["forecast"])            # nothing left once the last segment is done
        self.assertNotIn("forecast", R)              # the merged result does not carry it

    def test_kept_segments_count_as_finished_but_not_as_samples(self):
        self.run_long()
        R, st = self.run_long(resume=True)           # all 4 kept: nothing ran, so no range to give
        self.assertEqual(sum(" forecast: " in x for x in st["log"]), 0)
        self.assertIsNone(st["forecast"])


if __name__ == "__main__":
    unittest.main()
