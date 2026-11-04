"""pipeline._steady (no network): the audit's "largest box" moment skips a box that bled into the water for a frame
or two (11/4 s001 m8:1: the audit crop and the queue thumbnail showed open water beside the nautilus), but keeps an
animal that grows steadily as it swims up to the camera."""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fishcount import pipeline


def sq(s):
    return [0, 0, s, s]


class SteadyBox(unittest.TestCase):
    def test_spike_skipped(self):
        p = [(f, sq(s)) for f, s in enumerate([40, 41, 40, 95, 42, 41, 40])]     # frame 3: mask bled, 5.6x the area
        self.assertFalse(pipeline._steady(p, 3))
        self.assertTrue(all(pipeline._steady(p, j) for j in (0, 1, 2, 4, 5, 6)))

    def test_approach_kept(self):
        p = [(f, sq(s)) for f, s in enumerate([20, 26, 33, 42, 54, 70, 90])]     # a fish swimming up: largest is real
        self.assertTrue(pipeline._steady(p, 6))

    def test_short_track(self):
        self.assertTrue(pipeline._steady([(0, sq(10)), (1, sq(50))], 1))        # too few neighbours to call a spike


if __name__ == "__main__":
    unittest.main()
