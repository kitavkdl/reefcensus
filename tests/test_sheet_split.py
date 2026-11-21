"""Shadow and confirm sheets split when they hold too many tracks (no network, no spend).

11/21 verify: a 2-minute TNC clip (rockfish crowd, 600 frames) had about 226 dark tracks; shadow_look put them all on
one 46,992 x 1,228 sheet and Spark refused it ("image decode limit exceeded"), so the run died after the audit with
no result. The largest sheet that ever went through (LONG1_cr9 S1) held 32 tracks, so a sheet of up to
SHADOW_PER_SHEET tracks is sent exactly as before and only a longer list is cut into sheets of that size."""
import json, os, re, sys, tempfile, threading, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from fishcount import api, pipeline, video


class Run:
    def __init__(self, d):
        self.d, self.log, self._lock = d, [], threading.Lock()
        self.status = {"billed_usd": 0.0, "live_calls": 0, "cached_calls": 0}
    def path(self, *p): return os.path.join(self.d, *p)
    def stage(self, *a): self.log.append(a)


def tracks(n):
    """n tracks, each boxed on frames 0..7 at its own place."""
    frames = {}
    for i in range(n):
        x, y = 40 + (i % 20) * 60, 40 + (i // 20) * 60
        for f in range(8):
            frames.setdefault(f, []).append(dict(track=f"t{i}", box=[x, y, x + 30 + i % 5, y + 20]))
    return frames, [f"t{i}" for i in range(n)]


class FakeSpark:
    """Answers every tile name the prompt could use (S1.. / C1..), each tagged with the call number."""
    def __init__(self):
        self.calls = []

    def __call__(self, prompt, images=(), offline=False, check=None, **k):
        self.calls.append(images[0])
        no = len(self.calls)
        reply = json.dumps([dict(tile=f"{p}{i}", is_animal=True, what="fish", confidence=0.9, reason=f"call{no}-{p}{i}")
                            for p in "SC" for i in range(1, 200)])
        if check:
            check(reply)
        return reply


def blank_frames(clip, wanted, **k):
    return {f: np.zeros((720, 1280, 3), np.uint8) for f in wanted}


class SheetSplit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run_ = Run(self.tmp.name)
        self.spark = FakeSpark()
        self.p = [mock.patch.object(api, "spark", self.spark), mock.patch.object(video, "frames", blank_frames)]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()
        self.tmp.cleanup()

    def test_shadow_up_to_the_limit_is_one_sheet(self):
        frames, ts = tracks(pipeline.SHADOW_PER_SHEET)
        got = pipeline.shadow_look(self.run_, "clip.mp4", frames, ts, False)
        self.assertEqual(len(self.spark.calls), 1)
        self.assertEqual(sorted(os.listdir(self.tmp.name)), ["shadow_1.jpg"])
        self.assertEqual(open(self.run_.path("shadow_1.jpg"), "rb").read(), self.spark.calls[0])
        self.assertEqual(got[ts[-1]]["reason"], f"call1-S{pipeline.SHADOW_PER_SHEET}")

    def test_shadow_over_the_limit_is_cut_into_sheets(self):
        k = pipeline.SHADOW_PER_SHEET
        frames, ts = tracks(2 * k + 5)
        got = pipeline.shadow_look(self.run_, "clip.mp4", frames, ts, False)
        self.assertEqual(len(self.spark.calls), 3)
        # each track gets the answer for its own tile on its own sheet
        for i, t in enumerate(ts):
            self.assertEqual(got[t]["reason"], f"call{i // k + 1}-S{i % k + 1}", t)
        # first sheet keeps its old file name; the rest are numbered after it
        self.assertEqual(sorted(os.listdir(self.tmp.name)), ["shadow_1.jpg", "shadow_1_2.jpg", "shadow_1_3.jpg"])
        # the first sheet is the sheet the first k tracks alone would make
        first = self.spark.calls[0]
        self.spark.calls.clear()
        pipeline.shadow_look(Run(tempfile.mkdtemp(dir=self.tmp.name)), "clip.mp4", frames, ts[:k], False)
        self.assertEqual(self.spark.calls[0], first)

    def test_shadow_peak_sheet_number_kept(self):
        frames, ts = tracks(pipeline.SHADOW_PER_SHEET + 1)
        pipeline.shadow_look(self.run_, "clip.mp4", frames, ts, False, sheet_no=2)
        self.assertEqual(sorted(os.listdir(self.tmp.name)), ["shadow_2.jpg", "shadow_2_2.jpg"])

    def test_confirm_up_to_the_limit_is_one_sheet(self):
        frames, ts = tracks(pipeline.CONFIRM_PER_SHEET)
        pipeline.confirm_motion(self.run_, "clip.mp4", frames, ts, False)
        self.assertEqual(len(self.spark.calls), 1)
        self.assertEqual(sorted(os.listdir(self.tmp.name)), ["confirm_1.jpg"])

    def test_confirm_over_the_limit_is_cut_into_sheets(self):
        k = pipeline.CONFIRM_PER_SHEET
        frames, ts = tracks(k + 3)
        got = pipeline.confirm_motion(self.run_, "clip.mp4", frames, ts, False, sheet_no=3)
        self.assertEqual(len(self.spark.calls), 2)
        for i, t in enumerate(ts):
            self.assertEqual(got[t]["reason"], f"call{i // k + 1}-C{i % k + 1}", t)
        self.assertEqual(sorted(os.listdir(self.tmp.name)), ["confirm_3.jpg", "confirm_3_2.jpg"])

    def test_limits_keep_every_saved_sheet(self):
        # the largest sheets that went through: shadow 32 tracks (LONG1_cr9 S1, 6,640 px tall); confirm far fewer
        self.assertGreaterEqual(pipeline.SHADOW_PER_SHEET, 32)
        self.assertGreaterEqual(pipeline.CONFIRM_PER_SHEET, 32)


if __name__ == "__main__":
    unittest.main()
