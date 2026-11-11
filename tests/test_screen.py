"""--skip-empty: which stretches of a long video go to the models (fishcount/screen.py), on synthetic 480x270 footage
(no network, no spend). Run: python3 -m unittest discover -s tests -v"""
import os, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fishcount import _pylib  # noqa: F401
import cv2
import numpy as np
from fishcount import screen

FPS = 1          # structure tests at 1 fps (5x fewer synthetic frames); detection delay is measured at 5 fps below
W, H = screen.W, screen.H


def scene(n_s, things=(), stripes=False, ramp=0.0, seed=0, fps=None):
    """Generator of n_s seconds of BGR frames: a still textured seabed with sensor noise, plus `things`
    (functions t_seconds -> (x, y) centre or None) drawn as dark discs of radius 5, an optional swaying-weed strip,
    and an optional brightness ramp (`ramp` grey levels added linearly over the clip)."""
    rng = np.random.default_rng(seed)
    bed = cv2.GaussianBlur(rng.integers(60, 200, (H, W, 3), dtype=np.uint8), (0, 0), 3)
    noise = [rng.normal(0, 2.0, (H, W, 3)).astype(np.float32) for _ in range(7)]     # sensor noise, cycled (speed)
    fps = fps or FPS
    n = int(n_s * fps)
    for i in range(n):
        t = i / fps
        f = bed.astype(np.float32)
        if stripes:     # weed: bands in the right quarter swaying 6 px back and forth every 3.3 s
            x0 = 380 + 6 * np.sin(2 * np.pi * t / 3.3)
            for k in range(5):
                xa = int(x0 + 18 * k)
                f[40:230, xa:xa + 6] = (40, 120, 60)
        for th in things:
            p = th(t)
            if p is not None:
                cv2.circle(f, (int(round(p[0])), int(round(p[1]))), 5, (20, 20, 30), -1)
        f += ramp * i / max(1, n - 1)
        f += noise[i % 7]
        yield np.clip(f, 0, 255).astype(np.uint8)


def sent(wins, f):
    return any(w["start"] <= f < w["start"] + w["n"] for w in wins if w["kind"] != "probe")


def run(n_s, **kw):
    sc = {k: kw.pop(k) for k in ("things", "stripes", "ramp") if k in kw}
    return screen.windows(scene(n_s, **sc), FPS, **kw)


class Windows(unittest.TestCase):
    def test_still_seabed_sends_only_the_first_minute(self):
        wins = run(300, probe_every_s=10 ** 6)
        self.assertEqual([(w["start"], w["n"], w["kind"]) for w in wins], [(0, 60 * FPS, "head")])

    def test_a_change_soon_after_a_stretch_joins_it(self):
        swim = lambda t: (40 + (t - 90) * 60, 135) if 90 <= t < 96 else None     # 30 s after the first minute ends
        wins = run(300, things=[swim], probe_every_s=10 ** 6)
        self.assertEqual([w["kind"] for w in wins], ["head"])
        self.assertEqual(len(wins[0]["triggers"]), 1)
        self.assertGreaterEqual(wins[0]["n"], 96 * FPS)

    def test_a_passing_animal_is_sent_with_padding_and_a_settled_end(self):
        swim = lambda t: (40 + (t - 150) * 60, 135) if 150 <= t < 156 else None   # crosses the frame in ~6 s
        wins = run(400, things=[swim], probe_every_s=10 ** 6)
        ch = [w for w in wins if w["kind"] == "change"]
        self.assertEqual(len(ch), 1, wins)
        w = ch[0]
        self.assertLessEqual(w["start"], 150 * FPS - screen.PAD_S * FPS + FPS)      # padded before the first sighting
        self.assertGreaterEqual(w["start"] + w["n"], 156 * FPS + screen.STABLE_S * FPS)  # ends after it settles
        self.assertGreaterEqual(w["n"], screen.MIN_S * FPS)
        self.assertFalse(sent(wins, 100 * FPS))
        self.assertFalse(sent(wins, 300 * FPS))

    def test_a_resting_animal_is_not_sent_again(self):
        rest = lambda t: (200, 150)          # there from the first frame, never moves: carried, not re-sent
        wins = run(300, things=[rest], probe_every_s=10 ** 6)
        self.assertEqual([w["kind"] for w in wins], ["head"])

    def test_an_animal_that_arrives_and_stays_is_sent_when_it_arrives(self):
        come = lambda t: ((t - 120) * 40 + 10, 100) if 120 <= t < 125 else ((210, 100) if t >= 125 else None)
        wins = run(400, things=[come], probe_every_s=10 ** 6)
        self.assertTrue(sent(wins, 120 * FPS))
        self.assertTrue(sent(wins, 125 * FPS))
        self.assertFalse(sent(wins, 300 * FPS))      # resting afterwards: carried

    def test_swaying_weed_and_slow_light_change_are_not_sent(self):
        wins = run(300, stripes=True, ramp=40, probe_every_s=10 ** 6)
        self.assertEqual([w["kind"] for w in wins], ["head"], wins)

    def test_an_animal_passing_through_the_weed_is_sent(self):
        swim = lambda t: (300 + (t - 150) * 30, 135) if 150 <= t < 155 else None
        wins = run(300, stripes=True, things=[swim], probe_every_s=10 ** 6)
        self.assertTrue(sent(wins, 151 * FPS), wins)

    def test_probes_every_interval_in_a_long_skipped_stretch(self):
        wins = run(400, probe_every_s=90)
        probes = [(w["start"], w["n"]) for w in wins if w["kind"] == "probe"]
        g0 = 60 * FPS
        self.assertEqual(probes, [(g0 + k * 90 * FPS, screen.PROBE_S * FPS) for k in (1, 2, 3)])

    def test_head_s_0_judges_from_the_first_frame(self):
        wins = run(30, head_s=0, probe_every_s=10 ** 6)
        self.assertEqual(wins, [])

    def test_windows_are_split_at_max_s_and_stay_contiguous(self):
        busy = lambda t: (50 + (t * 37) % 380, 60 + (t * 11) % 150)       # moves the whole time
        wins = run(260, things=[busy], probe_every_s=10 ** 6, max_s=100)
        self.assertTrue(all(w["n"] <= 100 * FPS for w in wins))
        self.assertEqual(sum(w["n"] for w in wins), 260 * FPS)          # everything sent, contiguous
        self.assertTrue(all(a["start"] + a["n"] == b["start"] for a, b in zip(wins, wins[1:])))


class Changed(unittest.TestCase):
    def test_crawling_animals_are_seen_within_the_padding(self):
        """At 5 fps, an animal resting in the reference frame that starts crawling at 0.5 / 1 / 2 px/s (480-wide
        frame) is seen to differ within PAD_S, so a stretch padded by PAD_S covers the start of movement."""
        for v in (0.5, 1.0, 2.0):
            fr = scene(30, things=[lambda t, v=v: (150 + max(0.0, t - 5) * v, 120)], fps=5)
            st, ref, hit = screen.State(), None, None
            for i, f in enumerate(fr):
                if i == 0:
                    ref = screen.small(f)
                elif st.changed(ref, screen.small(f)):
                    hit = i / 5 - 5
                    break
            self.assertIsNotNone(hit, f"{v} px/s never seen")
            self.assertLessEqual(hit, screen.PAD_S, f"{v} px/s: seen after {hit:.1f} s")

    def test_whole_frame_shift_counts_as_a_change(self):
        f = next(scene(1))
        g = np.roll(f, 20, axis=1)
        st = screen.State()
        self.assertTrue(st.changed(screen.small(f), screen.small(g)))


if __name__ == "__main__":
    unittest.main()
