"""--box-window: on a long clip a motion box prompt sends SAM only the frames around its spot (no network, no spend).
11/21 night, LONG1_cr9: the 28 whole-segment box prompts were $14.88 and changed no MaxN."""
import json, os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fishcount import api, motion, pipeline, video


def box_line(f, box, i=1):
    return f"<{f}f>{i}<|box;x1={box[0]};y1={box[1]};x2={box[2]};y2={box[3]};w=1920;h=1080;c=0.9|>"


class Run:
    def __init__(self, d): self.d, self.status, self.log = d, {"billed_usd": 0.0}, []
    def path(self, *p): return os.path.join(self.d, *p)
    def stage(self, *a): self.log.append(a)


class BoxClip(unittest.TestCase):
    def setUp(self):
        self.cuts, self._s = [], video.segment
        video.segment = lambda src, dst, start, fps=5, length=None: self.cuts.append((src, dst, start, length))

    def tearDown(self):
        video.segment = self._s

    def test_off_is_the_whole_clip(self):
        self.assertEqual(pipeline._box_clip(Run("/x"), "clip.mp4", 900, 2658, None, "M1"), ("clip.mp4", 0, 2658))
        self.assertEqual(self.cuts, [])

    def test_short_clip_is_the_whole_clip(self):
        # a 12-s clip (60 frames) and a 201-frame clip: the window is the clip, so the SAM call and its cache key stay
        self.assertEqual(pipeline._box_clip(Run("/x"), "clip.mp4", 30, 60, 100, "M1"), ("clip.mp4", 0, 60))
        self.assertEqual(pipeline._box_clip(Run("/x"), "clip.mp4", 100, 201, 100, "M1"), ("clip.mp4", 0, 201))
        self.assertEqual(self.cuts, [])

    def test_long_clip_is_cut_around_the_spot(self):
        path, s, m = pipeline._box_clip(Run("/r"), "clip.mp4", 941, 2658, 100, "r1M7")
        self.assertEqual((s, m), (841, 201))
        self.assertEqual(self.cuts, [("clip.mp4", path, 841, 201)])
        self.assertEqual(path, "/r/box_r1M7+841.mp4")

    def test_window_stops_at_the_ends(self):
        self.assertEqual(pipeline._box_clip(Run("/r"), "c", 8, 2658, 100, "M4")[1:], (0, 109))
        self.assertEqual(pipeline._box_clip(Run("/r"), "c", 2650, 2658, 100, "M4")[1:], (2550, 108))


class Followed(unittest.TestCase):
    def still(self, f0, f1, box):
        return {f: [dict(id=1, box=tuple(box), conf=0.9)] for f in range(f0, f1)}

    def test_frame_rule_as_before(self):
        d = self.still(100, 120, (10, 10, 50, 50))
        self.assertEqual(pipeline._followed([12, 12, 50, 50], 110, [("M1", d)], windowed=False), "M1")
        self.assertIsNone(pipeline._followed([12, 12, 50, 50], 500, [("M1", d)], windowed=False))

    def test_still_track_covers_its_place_past_the_window(self):
        d = self.still(100, 301, (10, 10, 50, 50))
        self.assertEqual(pipeline._followed([12, 12, 50, 50], 1500, [("M1", d)], windowed=True), "M1")
        self.assertIsNone(pipeline._followed([400, 400, 450, 450], 1500, [("M1", d)], windowed=True))

    def test_moving_track_does_not(self):
        d = {f: [dict(id=1, box=(f, 10, f + 40, 50), conf=0.9)] for f in range(100, 301)}    # swims 200 px
        self.assertIsNone(pipeline._followed([300, 10, 340, 50], 1500, [("M1", d)], windowed=True))
        self.assertFalse(pipeline._sits_still(d))
        self.assertTrue(pipeline._sits_still(self.still(0, 5, (0, 0, 10, 10))))


class MotionLook(unittest.TestCase):
    """motion_look end to end with the Spark verdict cached and SAM / whole_box / segment stubbed."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._cache, self._sha, self._wb, self._seg, self._c = api.CACHE, api.file_sha, motion.whole_box, video.segment, pipeline._counted
        api.CACHE = self.tmp.name
        api.file_sha = lambda p: "clipsha"
        motion.whole_box = lambda clip, f, box, W, H, n: list(box)
        self.cuts, self.calls = [], []
        video.segment = lambda src, dst, start, fps=5, length=None: self.cuts.append((dst, start, length))

        def counted(run, fn, path, prompt, n, offline=False):
            self.calls.append((path, prompt, n))
            f = int(prompt[1:prompt.index("f>")])
            return "\n".join(box_line(g, (900, 900, 960, 960)) for g in range(n) if abs(g - f) < 30)   # 30 frames each way
        pipeline._counted = counted

    def tearDown(self):
        api.CACHE, api.file_sha, motion.whole_box, video.segment, pipeline._counted = self._cache, self._sha, self._wb, self._seg, self._c
        self.tmp.cleanup()

    def look(self, n, said, box_window):
        known = {}
        kb = json.dumps(sorted((f, sorted([round(v) for v in b] for b in bs)) for f, bs in known.items()))
        import hashlib
        key = hashlib.sha256(("clipsha" + kb + pipeline.MOTION_PROMPT + pipeline.MOTION_VERSION).encode()).hexdigest()[:24]
        with open(os.path.join(self.tmp.name, f"motion_{key}.json"), "w") as fh:
            json.dump(dict(n_candidates=len(said), sheet=None, said=said), fh)
        results = []
        log = pipeline.motion_look(Run(self.tmp.name), "clip.mp4", dict(n_frames=n, width=1920, height=1080), results, 5.0, True,
                                   box_window=box_window)
        return log, results

    def spot(self, tile, frame, box=(900, 900, 960, 960)):
        return dict(tile=tile, frame=frame, box=list(box), is_animal=True, confidence=0.9, name="crab", what="crab")

    def test_windowed_prompt_is_renumbered_back(self):
        log, results = self.look(2658, [self.spot("M1", 941)], 100)
        self.assertEqual(self.cuts, [(os.path.join(self.tmp.name, "box_r1M1+841.mp4"), 841, 201)])
        path, prompt, n = self.calls[0]
        self.assertTrue(prompt.startswith("<100f>1<|box;"))     # the spot's frame inside the window
        self.assertEqual(n, 201)
        d = results[0][2]
        self.assertEqual((min(d), max(d)), (912, 970))          # back in the clip's frame numbers

    def test_off_sends_the_whole_clip(self):
        log, results = self.look(2658, [self.spot("M1", 941)], None)
        self.assertEqual(self.cuts, [])
        self.assertEqual(self.calls, [("clip.mp4", motion.box_prompt(941, [900, 900, 960, 960], 1920, 1080), 2658)])

    def test_still_spot_seen_again_later_is_not_sent_twice(self):
        log, results = self.look(2658, [self.spot("M1", 941), self.spot("M2", 2000)], 100)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(log[-1]["note"], "already followed by M1")

    def test_other_place_is_sent(self):
        log, results = self.look(2658, [self.spot("M1", 941), self.spot("M2", 2000, (100, 100, 160, 160))], 100)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.calls[1][1][:6], "<100f>")

    def test_short_clip_unchanged_by_the_option(self):
        self.look(60, [self.spot("M1", 30)], 100)
        self.assertEqual(self.cuts, [])
        self.assertEqual(self.calls, [("clip.mp4", motion.box_prompt(30, [900, 900, 960, 960], 1920, 1080), 60)])


if __name__ == "__main__":
    unittest.main()
