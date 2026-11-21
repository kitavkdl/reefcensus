"""--probe-window: a discovered word is tried on short windows around the frames Spark named before the whole clip
(no network, no spend). 11/21 night, LONG1_cr9 S2: 8 whole-segment ladder calls that found nothing, $4.25."""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fishcount import pipeline, video


class Run:
    def __init__(self): self.status, self.log = {"billed_usd": 0.0}, []
    def path(self, *p): return os.path.join("/r", *p)
    def stage(self, *a): self.log.append(a)


class Windows(unittest.TestCase):
    def test_around_spark_frames(self):
        self.assertEqual(pipeline._probe_windows([2125], 2658, 25), [(2100, 51)])
        self.assertEqual(pipeline._probe_windows([0, 531], 2658, 25), [(0, 26), (506, 51)])

    def test_overlaps_join_and_every_spark_frame_gets_a_window(self):
        self.assertEqual(pipeline._probe_windows([100, 120, 900], 2658, 25), [(75, 71), (875, 51)])
        self.assertEqual(pipeline._probe_windows([2650], 2658, 25), [(2625, 33)])
        # 11/21: a window on only the first two of Spark's frames missed the nautilus in s004 (Spark frames 0, 11,
        # ...; SAM tracks it from frame 44). Every frame Spark named gets one: 347/347 saved words found.
        self.assertEqual(pipeline._probe_windows([0, 531, 1062, 1594, 2125, 2657], 2658, 25),
                         [(0, 26), (506, 51), (1037, 51), (1569, 51), (2100, 51), (2632, 26)])

    def test_windows_over_half_the_clip_mean_no_probe(self):
        self.assertEqual(pipeline._probe_windows([60, 120], 300, 25), [(35, 51), (95, 51)])   # 102 of 300
        self.assertEqual(pipeline._probe_windows([60, 120, 180], 300, 25), [])                 # 153 of 300
        self.assertEqual(pipeline._probe_windows([60, 120, 180], 306, 25), [(35, 51), (95, 51), (155, 51)])

    def test_clips_under_300_frames_keep_the_plain_ladder(self):
        # 11/21: on saved short clips the windows gave back 1,379 frames in 1,162 runs and held every miss (s004
        # nautilus from frame 44, DH7 crab from frame 28 after a sign at frame 0)
        self.assertEqual(pipeline._probe_windows([0, 11], 60, 25), [])
        self.assertEqual(pipeline._probe_windows([0], 60, 25), [])
        self.assertEqual(pipeline._probe_windows([100], 299, 25), [])
        self.assertEqual(pipeline._probe_windows([100], 300, 25), [(75, 51)])

    def test_short_clip_or_no_frames_means_no_probe(self):
        self.assertEqual(pipeline._probe_windows([10, 40], 60, 25), [])     # windows cover the 12-s clip
        self.assertEqual(pipeline._probe_windows([], 2658, 25), [])
        self.assertEqual(pipeline._probe_windows(None, 2658, 25), [])
        self.assertEqual(pipeline._probe_windows(["x", True, -3, 5000], 2658, 25), [])


class Ladder(unittest.TestCase):
    def setUp(self):
        self._c, self._s = pipeline._counted, video.segment
        self.calls, self.cuts = [], []
        self.found_in = {}      # word -> frames (clip numbering) where SAM finds it
        video.segment = lambda src, dst, start, fps=5, length=None: self.cuts.append((dst, start, length))

        def counted(run, fn, path, word, n, offline=False):
            s = next((st for dst, st, _ in self.cuts if dst == path), 0)
            self.calls.append((os.path.basename(path), word, n))
            return "\n".join(f"<{f - s}f>1<|box;x1=1;y1=1;x2=9;y2=9;w=1920;h=1080|>" for f in self.found_in.get(word, ()) if s <= f < s + n)
        pipeline._counted = counted

    def tearDown(self):
        pipeline._counted, video.segment = self._c, self._s

    def test_empty_words_cost_only_the_window(self):
        word, txt, tried = pipeline.word_ladder(Run(), "/r/clip.mp4", 2658, ["crab", "shell", "starfish"], True,
                                                probe=[(2100, 51)])
        self.assertIsNone(word)
        self.assertEqual([c[2] for c in self.calls], [51, 51, 51])
        self.assertEqual([t["frames"] for t in tried], [0, 0, 0])
        self.assertEqual(tried[0]["probe"], [[2100, 51]])

    def test_word_found_in_the_window_goes_to_the_whole_clip(self):
        self.found_in = {"shell": range(2110, 2600)}
        word, txt, tried = pipeline.word_ladder(Run(), "/r/clip.mp4", 2658, ["crab", "shell", "starfish"], True,
                                                probe=[(2100, 51)])
        self.assertEqual(word, "shell")
        self.assertEqual([(c[1], c[2]) for c in self.calls], [("crab", 51), ("shell", 51), ("shell", 2658)])
        self.assertEqual(tried[-1], dict(word="shell", frames=490))

    def test_second_window_tried_when_the_first_is_empty(self):
        self.found_in = {"person": range(500, 520)}
        word, _, _ = pipeline.word_ladder(Run(), "/r/clip.mp4", 2658, ["person"], True, probe=[(0, 26), (506, 51)])
        self.assertEqual(word, "person")
        self.assertEqual([c[2] for c in self.calls], [26, 51, 2658])

    def test_no_probe_is_the_old_ladder(self):
        word, _, tried = pipeline.word_ladder(Run(), "/r/clip.mp4", 2658, ["crab", "shell"], True)
        self.assertEqual(self.calls, [("clip.mp4", "crab", 2658), ("clip.mp4", "shell", 2658)])
        self.assertEqual(tried, [dict(word="crab", frames=0), dict(word="shell", frames=0)])


if __name__ == "__main__":
    unittest.main()
