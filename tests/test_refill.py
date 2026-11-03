"""refill_saturated sends what follows an out-of-ids frame in windows (no network, no spend)."""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fishcount import pipeline, video


def sam_text(n, used_up_at=None):
    """n frames; with used_up_at, ids 0..15 all appear by that frame (one new id per frame up to it)."""
    lines = []
    for f in range(n):
        k = 1 if used_up_at is None else (16 if f >= used_up_at else min(15, f * 15 // used_up_at + 1))
        lines.append(f"<{f}f>" + "".join(f"{i}<|box;x1={10 * i};y1=0;x2={10 * i + 8};y2=8;w=1920;h=1080;c=0.9|>" for i in range(k)))
    return "\n".join(lines)


class Run:
    def path(self, name): return "/nonexistent/" + name
    def stage(self, *a): pass


class Windows(unittest.TestCase):
    def setUp(self):
        self.calls, self._c, self._s = [], pipeline._counted, video.segment
        self.used_up = {}            # segment start -> frame (within the window) where that call runs out
        def seg(src, dst, start, fps=5, length=None):
            self.calls.append((start, length))
        def counted(run, fn, path, prompt, n, offline=False):
            s = self.calls[-1][0]
            return sam_text(n, self.used_up.get(s))
        video.segment, pipeline._counted = seg, counted

    def tearDown(self):
        pipeline._counted, video.segment = self._c, self._s

    def refill(self, n, first_used_up):
        res = [("p0", "fish", {}, sam_text(n, first_used_up), None)]
        return pipeline.refill_saturated(Run(), [("p0", "fish", "fish", "clip.mp4", None)], res, n, True)

    def test_short_clip_is_one_call_to_the_end(self):
        out = self.refill(60, 22)
        self.assertEqual(self.calls, [(22, None)])
        self.assertEqual([o[0] for o in out], ["p0+22"])

    def test_long_clip_goes_in_overlapping_windows_to_the_end(self):
        W, ov = pipeline.REFILL_WINDOW, pipeline.REFILL_OVERLAP
        self.refill(400, 78)
        starts = [s for s, _ in self.calls]
        self.assertEqual(starts[0], 78)
        self.assertTrue(all(b - a == W - ov for a, b in zip(starts, starts[1:])))
        self.assertTrue(all(l == W for _, l in self.calls[:-1]))
        last_s, last_len = self.calls[-1]
        self.assertTrue(last_len is None and last_s + W >= 400)      # last window reaches the end

    def test_a_window_that_runs_out_is_sent_again_from_there(self):
        self.used_up[78] = 30                    # the first window runs out at 78 + 30
        self.refill(400, 78)
        self.assertEqual([s for s, _ in self.calls][:2], [78, 108])

    def test_out_of_ids_on_the_first_frame_moves_on(self):
        self.used_up[78] = 0
        self.refill(400, 78)
        self.assertEqual([s for s, _ in self.calls][:2], [78, 78 + pipeline.REFILL_WINDOW - pipeline.REFILL_OVERLAP])

    def test_unsaturated_pass_makes_no_call(self):
        self.assertEqual(self.refill(400, None), [])
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
