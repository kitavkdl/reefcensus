"""--camo pieces (no network, no spend): finding a mover that has the background's own texture, choosing which
spots to show, the "SAM followed the moving spot" check, and keeping camo tracks out of stitch."""
import os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fishcount import motion, tracks
import cv2
import numpy as np


def cand(path, score=100.0, inside=0.0):
    return dict(first=path[0][0], last=path[-1][0], n=len(path), inside=inside, area=100, path=path, score=score)


def line(t0, t1, x0, y0, dx, dy=0, s=20):
    return [[t, [x0 + dx * (t - t0), y0 + dy * (t - t0), x0 + dx * (t - t0) + s, y0 + dy * (t - t0) + s]] for t in range(t0, t1 + 1)]


class CamoCandidates(unittest.TestCase):
    def test_finds_a_mover_with_the_background_texture(self):
        """A patch cut from the same rock texture, sliding 6 px a frame: no colour difference from the median frame
        (what candidates() needs), but frame-to-frame change shows it."""
        rng = np.random.default_rng(0)
        W, H, n = 640, 360, 30
        rock = cv2.GaussianBlur(rng.integers(0, 255, (H * 2, W * 2, 3), dtype=np.uint8), (0, 0), 3)
        rock = cv2.normalize(rock, None, 50, 200, cv2.NORM_MINMAX)          # rock-like blotches, not flat grey
        bg = rock[:H, :W].copy()
        patch = rock[H:H + 40, W:W + 64].copy()                 # same texture and colours, another place
        d = tempfile.mkdtemp()
        clip = os.path.join(d, "c.mp4")
        vw = cv2.VideoWriter(clip, cv2.VideoWriter_fourcc(*"mp4v"), 5, (W, H))
        for t in range(n):
            f = bg.copy()
            x = 150 + 6 * t
            f[160:200, x:x + 64] = patch
            vw.write(f)
        vw.release()
        cs = motion.camo_candidates(clip, {})
        # the blob track may break once as the change blob reshapes (seen here around frame 12-15); every long one
        # must ride along the patch
        long_ = [c for c in cs if c["n"] >= 10]
        self.assertTrue(long_)
        ends = []
        for c in long_:
            (x0, y0), (x1, y1) = motion._centre(c["path"][0][1]), motion._centre(c["path"][-1][1])
            self.assertGreater(x1, x0 + 10)                     # each one goes right, with the patch
            self.assertTrue(140 < y0 < 220 and 140 < y1 < 220)
            ends += [x0, x1]
        self.assertLess(min(ends), 230)                         # together they cover the patch's whole run (182 -> 356)
        self.assertGreater(max(ends), 330)


class CamoPick(unittest.TestCase):
    def test_drops_edge_near_known_and_second_track_on_one_mover(self):
        W, H = 1920, 1080
        mid = cand(line(0, 9, 900, 500, 10), score=300)
        same = cand(line(3, 9, 905, 502, 10), score=200)      # a second blob track on the same mover
        edge = cand(line(0, 9, 1880, 500, 0, 5), score=900)   # hugs the right edge
        nearby = cand(line(0, 9, 400, 300, 10), score=800)    # next to a box already found
        known = {t: [[400 + 10 * t + 30, 300, 400 + 10 * t + 90, 330]] for t in range(10)}   # just right of `nearby`
        got = motion.camo_pick([mid, same, edge, nearby], known, W, H)
        self.assertEqual(got, [mid])


class Follows(unittest.TestCase):
    def setUp(self):
        self.path = line(0, 9, 100, 100, 10)

    def dets(self, dx):
        return {t: [dict(id=1, box=[100 + dx * t, 100, 120 + dx * t, 120], conf=0.9)] for t in range(10)}

    def test_sam_box_moving_with_the_spot(self):
        ok, hits, shared, moved = motion.follows(self.dets(10), self.path)
        self.assertTrue(ok)
        self.assertEqual((hits, shared), (10, 10))

    def test_box_stuck_on_the_rock_does_not_count(self):
        ok, hits, shared, moved = motion.follows(self.dets(0), self.path)
        self.assertFalse(ok)                                     # hits early frames only, and never moves 30 px

    def test_box_elsewhere(self):
        far = {t: [dict(id=1, box=[800, 600, 820, 620], conf=0.9)] for t in range(10)}
        self.assertFalse(motion.follows(far, self.path)[0])


class StitchApart(unittest.TestCase):
    def frames(self):
        # track A ends at frame 4, B starts at frame 6 right where A ended
        fr = {t: [dict(track="crowd-r0c1:13", box=[100, 100, 140, 140])] for t in range(5)}
        for t in range(6, 10):
            fr[t] = [dict(track="camo0:1", box=[102, 100, 142, 140])]
        trk = {"crowd-r0c1:13": dict(label="fish", source="crowd-r0c1"), "camo0:1": dict(label="fish", source="camo0")}
        return fr, trk

    def test_default_joins(self):
        fr, trk = self.frames()
        self.assertEqual(set(tracks.stitch(fr, trk)), {"crowd-r0c1:13"})

    def test_camo_kept_apart(self):
        fr, trk = self.frames()
        self.assertEqual(set(tracks.stitch(fr, trk, apart=("camo",))), {"crowd-r0c1:13", "camo0:1"})


if __name__ == "__main__":
    unittest.main()
