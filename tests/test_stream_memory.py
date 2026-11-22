"""Reading a frame at a time gives what holding every frame gave (11/21 memory, LONG1_cr9 S1 under a 4 GB cap):
video.iter_frames = video.frames, motion.candidates' three reads = one held list, dark_tracks a frame at a time,
render.annotate's per-frame masks = all_masks. No network."""
import glob, json, os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fishcount import motion, pipeline, render, video
import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S004 = os.path.join(ROOT, "tests", "data", "nautilus_s004_0_12.mp4")


_TMP = tempfile.TemporaryDirectory()     # removed when the tests end (synthetic() is not a TestCase method)


def synthetic(n, W=320, H=180, seed=0):
    """A still textured background with a dark square drifting right and a bright one drifting down."""
    rng = np.random.default_rng(seed)
    bg = cv2.GaussianBlur(rng.integers(60, 200, (H, W, 3), dtype=np.uint8), (0, 0), 2)
    d = tempfile.mkdtemp(dir=_TMP.name)
    clip = os.path.join(d, "c.mp4")
    vw = cv2.VideoWriter(clip, cv2.VideoWriter_fourcc(*"mp4v"), 5, (W, H))
    for t in range(n):
        f = bg.copy()
        x = 20 + (t % 200)
        f[60:80, x:x + 20] = (15, 15, 15)
        y = 10 + (t % 120) // 2
        f[y:y + 16, 250:266] = (250, 250, 250)
        vw.write(f)
    vw.release()
    return clip


class IterFrames(unittest.TestCase):
    def test_same_frames_as_frames(self):
        want = [0, 3, 4, 17, 59, 500]           # 500 is past the end: neither returns it
        held = video.frames(S004, want)
        got = list(video.iter_frames(S004, want))
        self.assertEqual([i for i, _ in got], sorted(held))
        for i, f in got:
            self.assertTrue(np.array_equal(f, held[i]))
        self.assertEqual(list(video.iter_frames(S004, [])), [])


class MotionThreeReads(unittest.TestCase):
    def test_median_by_bands(self):
        rng = np.random.default_rng(1)
        for n, rows in ((6, 70), (7, 33), (1, 5)):          # even and odd counts, rows not a multiple of the band
            fr = [rng.integers(0, 256, (rows, 41, 3), dtype=np.uint8) for _ in range(n)]
            self.assertTrue(np.array_equal(motion._median_frame(fr), np.median(np.stack(fr), axis=0)))

    def _held(self, clip, known, gap=2, min_area=12, max_area=2500, link=14, pad=6):
        """candidates() as it was before 11/21: every frame held in a list (motion._frames)."""
        n = video.info(clip)["n_frames"]
        scale = motion.SCALE if n <= motion.LONG else motion.SCALE * 2 / 3
        if scale != motion.SCALE:
            k = (scale / motion.SCALE) ** 2
            min_area, max_area, link, pad = max(4, int(min_area * k)), int(max_area * k), link * scale / motion.SCALE, pad * scale / motion.SCALE
        frames, sx, sy = motion._frames(clip, scale)
        step = 1 if len(frames) <= motion.LONG else 3
        bgl = motion._lab(np.median(np.stack(frames[::step]), axis=0).astype(np.uint8))
        dist = lambda f: cv2.GaussianBlur(np.linalg.norm(motion._lab(f) - bgl, axis=2), (5, 5), 0)
        allv = np.concatenate([dist(f)[::4, ::4].ravel() for f in frames])
        med = float(np.median(allv))
        thr = max(8.0, med + 6 * (float(np.median(np.abs(allv - med))) + 1e-6))
        masks = []
        for t in range(len(frames)):
            a, b = max(0, t - gap), min(len(frames) - 1, t + gap)
            moved = cv2.GaussianBlur(np.linalg.norm(motion._lab(frames[b]) - motion._lab(frames[a]), axis=2), (5, 5), 0) > thr * 0.8
            masks.append(int(((dist(frames[t]) > thr) & moved).sum()))
        return thr, masks

    def test_same_threshold_and_blobs_as_holding_every_frame(self):
        for n in (40, motion.LONG + 13):        # short (median of every frame) and long (every 3rd frame, 1/3 scale)
            clip = synthetic(n)
            thr, masks = self._held(clip, {})
            cands, thr2 = motion.candidates(clip, {})
            self.assertEqual(thr, thr2, n)
            self.assertTrue(cands, n)
            # every blob frame candidates() reports is a frame where the held version's mask had pixels
            for c in cands:
                for t, _ in c["path"]:
                    self.assertGreater(masks[t], 0, (n, t))


class DarkTracksStreaming(unittest.TestCase):
    def test_dark_square_is_dark_bright_one_is_not(self):
        clip = synthetic(30)
        frames = {}
        for t in range(30):
            x = 20 + t
            y = 10 + t // 2
            frames[t] = [dict(track="dark", box=[x * 1.0, 60.0, x + 20.0, 80.0]),
                         dict(track="bright", box=[250.0, y * 1.0, 266.0, y + 16.0]),
                         dict(track="tiny", box=[5.0, 5.0, 8.0, 8.0])]
        self.assertEqual(pipeline.dark_tracks(clip, frames, ["dark", "bright", "tiny"], 320, 180), ["dark"])

    def test_per_box_numbers_match_holding_every_frame(self):
        clip = synthetic(30)
        held = video.frames(clip, range(30))
        for t in (0, 13, 29):
            L = cv2.cvtColor(held[t], cv2.COLOR_BGR2LAB)[:, :, 0].astype(np.float32)
            v = pipeline._dark_at(L, [20.0 + t, 60.0, 40.0 + t, 80.0], 320, 180)
            inner = L[64:76, 24 + t:36 + t]
            self.assertAlmostEqual(v[0], float(np.median(inner)) - float(np.median(L[50:90, 10 + t:50 + t][
                ~np.pad(np.ones((20, 20), bool), 10)])), places=4)
        self.assertIsNone(pipeline._dark_at(L, [5, 5, 8, 8], 320, 180))


class AnnotateMasksByFrame(unittest.TestCase):
    def test_frame_masks_match_all_masks(self):
        from fishcount import maskcodec
        if not maskcodec.fast():
            self.skipTest("annotate keeps the process pool without the C decoder")
        checked = 0
        for path in sorted(glob.glob(os.path.join(ROOT, "cache", "sam_*.json")))[:8]:
            with open(path) as fh:
                text = json.load(fh).get("output_text") or ""
            if not text:
                continue
            old, lazy = render.all_masks(text), render._FrameMasks(text)
            for f in range(max(list(old) + [0]) + 2):
                a, b = old.get(f, []), lazy.get(f, [])
                self.assertEqual([x[0] for x in a], [y[0] for y in b], (path, f))
                for x, y in zip(a, b):
                    self.assertTrue(np.array_equal(x[1], y[1]), (path, f))
                checked += len(a)
        if not checked:
            self.skipTest("no cached SAM outputs")


if __name__ == "__main__":
    unittest.main()
