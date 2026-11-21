"""--haze: a washed-out (not dark) clip gets CLAHE on L alone before the analysis (no network, no spend)."""
import os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fishcount import video
import cv2, numpy as np


def clip(path, lo, hi, n=10, W=160, H=96):
    """n frames of a horizontal ramp from grey `lo` to `hi` with a darker square (a 'fish') in the middle."""
    vw = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), 5, (W, H))
    ramp = np.tile(np.linspace(lo, hi, W, dtype=np.float32), (H, 1))
    for i in range(n):
        f = ramp.copy()
        f[40:56, 60 + i:76 + i] -= (hi - lo) * 0.2
        vw.write(cv2.cvtColor(f.clip(0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR))
    vw.release()


class Haze(unittest.TestCase):
    def test_bound(self):
        self.assertTrue(video.is_hazy(dict(l_width=video.HAZE_WIDTH - 1)))
        self.assertFalse(video.is_hazy(dict(l_width=video.HAZE_WIDTH)))
        self.assertFalse(video.is_hazy(dict(l_width=None)))
        self.assertFalse(video.is_hazy({}))

    def test_contrast_stats_tells_milky_from_clear(self):
        with tempfile.TemporaryDirectory() as d:
            clip(os.path.join(d, "milky.mp4"), 130, 175)
            clip(os.path.join(d, "clear.mp4"), 30, 230)
            milky = video.contrast_stats(os.path.join(d, "milky.mp4"))["l_width"]
            clear = video.contrast_stats(os.path.join(d, "clear.mp4"))["l_width"]
        self.assertLess(milky, video.HAZE_WIDTH)
        self.assertGreater(clear, video.HAZE_WIDTH)

    def test_clahe_frame_stretches_contrast_without_lifting_shadows(self):
        img = np.full((96, 160, 3), 150, np.uint8)
        img[:, :80] = 135
        img[40:56, 60:76] = 120
        out = video.clahe_frame(img)
        self.assertEqual((out.shape, out.dtype), (img.shape, img.dtype))
        L = lambda x: cv2.cvtColor(x, cv2.COLOR_BGR2LAB)[:, :, 0].astype(float)
        self.assertGreater(L(out).std(), L(img).std())
        # no gamma: the mean brightness stays near the input's (brighten_frame lifts it a lot)
        self.assertLess(abs(L(out).mean() - L(img).mean()), abs(L(video.brighten_frame(img)).mean() - L(img).mean()))

    def test_brighten_takes_the_frame_function(self):
        with tempfile.TemporaryDirectory() as d:
            src, dst = os.path.join(d, "a.mp4"), os.path.join(d, "b.mp4")
            clip(src, 130, 175)
            seen = []
            video.brighten(src, dst, frame_fn=lambda f: seen.append(1) or video.clahe_frame(f))
            self.assertEqual((len(seen), video.info(dst)["n_frames"]), (10, 10))
            self.assertGreater(video.contrast_stats(dst)["l_width"], video.contrast_stats(src)["l_width"])


if __name__ == "__main__":
    unittest.main()
