"""SAM box prompts must lie inside the picture (no network, no spend). 11/9 outside data (IMR HU6, BE10; Exeter G2):
Spark's box for an animal at the bottom or right edge came back as y2=1080 or x2=1920 on a 1920x1080 clip, SAM answered
HTTP 400 "box ... lies outside the 1920x1080", and the animal was dropped (HU6: a crab Spark called at 0.70)."""
import os, re, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fishcount import motion


def coords(p):
    m = re.search(r"x1=(-?\d+);y1=(-?\d+);x2=(-?\d+);y2=(-?\d+);w=(\d+);h=(\d+)", p)
    return tuple(int(v) for v in m.groups())


class BoxPrompt(unittest.TestCase):
    def test_inside_box_unchanged(self):
        # every box prompt in the cache is like this one: the prompt text (= the cache key) must not change
        self.assertEqual(motion.box_prompt(7, [100, 200, 300, 400], 1920, 1080),
                         "<7f>1<|box;x1=100;y1=200;x2=300;y2=400;w=1920;h=1080|>")

    def test_bottom_edge_clamped(self):
        x0, y0, x1, y1, W, H = coords(motion.box_prompt(3, [1120, 996, 1282, 1080], 1920, 1080))  # IMR HU6
        self.assertEqual((x0, y0, x1, y1), (1120, 996, 1282, 1079))

    def test_right_and_bottom_edge_clamped(self):
        x0, y0, x1, y1, W, H = coords(motion.box_prompt(3, [1824, 890, 1920, 1080], 1920, 1080))  # IMR BE10
        self.assertEqual((x1, y1), (1919, 1079))

    def test_negative_and_beyond_clamped(self):
        x0, y0, x1, y1, W, H = coords(motion.box_prompt(0, [-5, -2, 2000, 1200], 1920, 1080))
        self.assertEqual((x0, y0, x1, y1), (0, 0, 1919, 1079))

    def test_box_beyond_edge_keeps_a_width(self):
        # a box wholly past the right edge clamped both x to 1919: a zero-width box (11/10 develop review)
        x0, y0, x1, y1, W, H = coords(motion.box_prompt(0, [1920, 300, 1960, 380], 1920, 1080))
        self.assertLess(x0, x1)
        x0, y0, x1, y1, W, H = coords(motion.box_prompt(0, [-40, -30, -2, -1], 1920, 1080))
        self.assertLess(x0, x1)
        self.assertLess(y0, y1)
        self.assertGreaterEqual(x0, 0)


class MissBox(unittest.TestCase):
    def test_size_checked_after_clamping(self):
        from fishcount import pipeline
        # Spark's missed-animal box, scale 1: 45 px wide but only 5 px of it inside a 1920-wide frame
        self.assertIsNone(pipeline._miss_box({"box": [1915, 300, 1960, 380]}, 1, 1920, 1080))
        self.assertIsNone(pipeline._miss_box({"box": [1930, 300, 1990, 380]}, 1, 1920, 1080))
        self.assertEqual(pipeline._miss_box({"box": [1800, 300, 1960, 380]}, 1, 1920, 1080), [1800, 300, 1920, 380])
        self.assertEqual(pipeline._miss_box({"box": [200, 100, 400, 300]}, 2, 1920, 1080), [100, 50, 200, 150])
        self.assertIsNone(pipeline._miss_box({"box": [1, 2]}, 1, 1920, 1080))
        self.assertIsNone(pipeline._miss_box({"what": "x"}, 1, 1920, 1080))


if __name__ == "__main__":
    unittest.main()
