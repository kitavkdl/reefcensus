"""motion.whole_box (no network): a seed box on the back half of a large slow mover is widened to the whole animal
(11/4 s001 m8), and a box that already covers its animal is left as is."""
import os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fishcount import motion
import cv2
import numpy as np


class WholeBox(unittest.TestCase):
    def setUp(self):
        self.W, self.H, self.n = 640, 360, 30
        rng = np.random.default_rng(1)
        self.clip = os.path.join(tempfile.mkdtemp(), "c.mp4")
        vw = cv2.VideoWriter(self.clip, cv2.VideoWriter_fourcc(*"mp4v"), 5, (self.W, self.H))
        for t in range(self.n):        # dark noisy water, a pale 80x50 oval moving 8 px a frame down-left
            f = rng.integers(0, 25, (self.H, self.W, 3), dtype=np.uint8)
            cv2.ellipse(f, (420 - 8 * t, 60 + 6 * t), (40, 25), 0, 0, 360, (200, 210, 200), -1)
            vw.write(f)
        vw.release()

    def test_back_half_seed_widens_to_the_animal(self):
        cx, cy = 420 - 8 * 15, 60 + 6 * 15                       # oval at frame 15: x 260-340, y 125-175
        b = motion.whole_box(self.clip, 15, [cx - 10, cy - 30, cx + 50, cy + 10], self.W, self.H, self.n)
        self.assertLessEqual(b[0], cx - 38); self.assertLessEqual(b[1], cy - 23)
        self.assertGreaterEqual(b[2], cx + 38); self.assertGreaterEqual(b[3], cy + 23)

    def test_covering_seed_is_unchanged(self):
        cx, cy = 420 - 8 * 15, 60 + 6 * 15
        box = [cx - 48, cy - 32, cx + 48, cy + 32]
        self.assertEqual(motion.whole_box(self.clip, 15, box, self.W, self.H, self.n), box)


if __name__ == "__main__":
    unittest.main()
