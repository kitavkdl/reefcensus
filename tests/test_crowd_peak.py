"""--crowd-peak: the 3x2 crowd tiles only around a peak frame the crowd check marks a lower bound, and a crowd check
row for a requested word that counted nothing (no network, no spend)."""
import os, sys, threading, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fishcount import api, pipeline, tracks, video


def box_line(f, box, i=1, w=1280, h=720):
    return f"<{f}f>{i}<|box;x1={box[0]};y1={box[1]};x2={box[2]};y2={box[3]};w={w};h={h};c=0.9|>"


class Run:
    def __init__(self, d="/r"):
        self.d, self.log, self.capped, self._lock = d, [], [], threading.Lock()
        self.status = {"billed_usd": 0.0, "live_calls": 0, "cached_calls": 0}
    def path(self, *p): return os.path.join(self.d, *p)
    def stage(self, *a): self.log.append(a)


class PeakWindows(unittest.TestCase):
    def lb(self, f, lb=True):
        return dict(row="fish", frame=f, maxn=8, total=28, lower_bound=lb)

    def test_no_lower_bound_no_window(self):
        self.assertEqual(pipeline.peak_windows([self.lb(1470, False)], 2655, 25), [])
        self.assertEqual(pipeline.peak_windows([], 2655, 25), [])

    def test_window_around_the_peak(self):
        self.assertEqual(pipeline.peak_windows([self.lb(1470)], 2655, 25), [(1445, 1496)])

    def test_window_stops_at_the_ends(self):
        self.assertEqual(pipeline.peak_windows([self.lb(3), self.lb(2650)], 2655, 25), [(0, 29), (2625, 2655)])

    def test_overlapping_windows_join_and_are_capped(self):
        w = pipeline.peak_windows([self.lb(f) for f in (100, 130, 500, 900, 1300, 1700)], 2658, 25)
        self.assertEqual(w[0], (75, 156))
        self.assertEqual(len(w), pipeline.CROWD_PEAK_MAX)

    def test_short_clip_is_the_whole_clip(self):
        # 12 s at 5 fps: a 51-frame window would be most of it, so the tiles are --crowd's own whole-clip calls
        self.assertEqual(pipeline.peak_windows([self.lb(57)], 60, 25), [(0, 60)])


class EmptyRows(unittest.TestCase):
    def setUp(self):
        self.trk = {"t1": dict(label="fish"), "t2": dict(label="fish"), "t3": dict(label="crab")}
        self.frames = {10: [dict(track="t1")], 11: [dict(track="t1"), dict(track="t2")], 12: [dict(track="t3")]}

    def test_counted_group_gets_no_row(self):
        m = {"striped seabream": dict(maxn=3)}       # a fish name: the fish group counted something
        self.assertEqual(pipeline.empty_rows(m, [("fish", "fish")], self.frames, self.trk, 60), [])

    def test_uncounted_word_asked_where_its_boxes_were(self):
        rows = pipeline.empty_rows({}, [("fish", "fish")], self.frames, self.trk, 60)
        self.assertEqual(rows, [("fish", [], 0, 11, pipeline.CROWD_WORDS["fish"])])

    def test_no_boxes_middle_frame(self):
        rows = pipeline.empty_rows({}, [("crab", "crab"), ("fish", "fish")], {}, {}, 60)
        self.assertEqual([(r[0], r[3]) for r in rows], [("crustacean", 30), ("fish", 30)])

    def test_one_row_per_group(self):
        rows = pipeline.empty_rows({}, [("crab", "crab"), ("shrimp", "shrimp")], self.frames, self.trk, 60)
        self.assertEqual([(r[0], r[3]) for r in rows], [("crustacean", 12)])


class CrowdCheckExtra(unittest.TestCase):
    def setUp(self):
        self._f, self._c = video.frames, pipeline.crowd_count
        video.frames = lambda clip, idx: {i: object() for i in idx}
        self.said = {}
        pipeline.crowd_count = lambda img, what, offline, run=None: dict(total=self.said[what], reason="r")

    def tearDown(self):
        video.frames, pipeline.crowd_count = self._f, self._c

    def test_empty_row_marked_lower_bound_at_three(self):
        w = pipeline.CROWD_WORDS["fish"]
        for tot, lb in ((2, False), (3, True), (9, True)):
            self.said[w] = tot
            out = pipeline.crowd_check(Run(), "clip", {}, 5.0, True, extra=[("fish", [], 0, 30, w)])
            self.assertEqual((out[0]["maxn"], out[0]["lower_bound"], out[0]["empty"]), (0, lb, True))

    def test_rows_with_a_maxn_unchanged(self):
        w = pipeline.CROWD_WORDS["fish"]
        self.said[w] = 22
        m = {"fish": dict(maxn=14, maxn_frame=2089, curve=[0] * 2089 + [14], first_frame=0, tracks=3)}
        out = pipeline.crowd_check(Run(), "clip", m, 5.0, True)
        self.assertEqual(out, [dict(row="fish", labels=["fish"], frame=2089, maxn=14, total=22, estimated=False,
                                    reason="r", lower_bound=True)])


class PeakTiles(unittest.TestCase):
    def setUp(self):
        self.saved = (video.segment, video.crop_tile, api.sam_video, api.sam_cached)
        self.cuts, self.sent = [], []
        video.segment = lambda src, dst, start, fps=5, length=None: self.cuts.append((src, dst, start, length))
        video.crop_tile = lambda src, dst, box, scale=2, fps=5: None
        api.sam_cached = lambda path, prompt: False

        def sam(path, prompt, n, offline=False, **k):
            self.sent.append((os.path.basename(path), prompt, n))
            return box_line(0, (20, 20, 60, 60)) + "\n" + box_line(4, (20, 20, 60, 60))
        api.sam_video = sam

    def tearDown(self):
        video.segment, video.crop_tile, api.sam_video, api.sam_cached = self.saved

    def test_window_tiles_renumbered_to_the_clip(self):
        inf = dict(n_frames=2655, width=1920, height=1080)
        out = pipeline.peak_tiles(Run(), "clip.mp4", inf, [(1445, 1496)], "fish", 8.0, False)
        self.assertEqual(self.cuts, [("clip.mp4", "/r/peak+1445.mp4", 1445, 51)])
        self.assertEqual(len(out), 6)
        self.assertEqual(sorted(s[2] for s in self.sent), [51] * 6)
        name, label, d, txt, box = out[0]
        self.assertEqual((name, label), ("peak+1445-r0c0", "fish"))
        self.assertEqual(sorted(d), [1445, 1449])
        x0, y0 = box[0], box[1]
        self.assertAlmostEqual(d[1445][0]["box"][0], x0 + 10)     # 2x tile: pixel 20 in the crop is 10 in the frame
        self.assertEqual(sorted(tracks.parse_boxes(txt)), [1445, 1449])

    def test_whole_clip_window_is_not_cut(self):
        inf = dict(n_frames=60, width=1280, height=720)
        pipeline.peak_tiles(Run(), "clip.mp4", inf, [(0, 60)], "fish", 8.0, False)
        self.assertEqual(self.cuts, [])
        self.assertEqual(sorted(s[2] for s in self.sent), [60] * 6)

    def test_cap_stops_uncached_tiles(self):
        r = Run()
        r.status["billed_usd"] = 0.995
        out = pipeline.peak_tiles(r, "clip.mp4", dict(n_frames=2655, width=1920, height=1080), [(1445, 1496)], "fish", 1.0, False)
        self.assertEqual((out, self.sent, len(r.capped)), ([], [], 6))


if __name__ == "__main__":
    unittest.main()
