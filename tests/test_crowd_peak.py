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


class PeakTracksKeepFirstPass(unittest.TestCase):
    """11/21 LONG1_cr9 S5/S6: the second pass must leave every first-pass track, its number and its sheets as they
    were; tile tracks are joined only with each other and audited last on their own sheets."""
    def frames(self):
        # peak tile track A ends at frame 4, first-pass track B starts at frame 6 where A ended
        fr = {t: [dict(track="peak+0-r0c0:1", box=[100, 100, 140, 140])] for t in range(5)}
        for t in range(6, 10):
            fr[t] = [dict(track="p0:3", box=[102, 100, 142, 140])]
        trk = {"peak+0-r0c0:1": dict(label="fish", source="peak+0-r0c0"), "p0:3": dict(label="fish", source="p0")}
        return fr, trk

    def test_stitch_keeps_peak_apart(self):
        fr, trk = self.frames()
        self.assertEqual(set(tracks.stitch(fr, trk)), {"peak+0-r0c0:1"})          # the old join
        fr, trk = self.frames()
        self.assertEqual(set(tracks.stitch(fr, trk, apart=("camo", "peak+"))), {"peak+0-r0c0:1", "p0:3"})

    def test_stitch_camo_and_peak_are_separate_groups(self):
        fr, trk = self.frames()
        trk["p0:3"] = dict(label="fish", source="camo0")
        self.assertEqual(set(tracks.stitch(fr, trk, apart=("camo", "peak+"))), {"peak+0-r0c0:1", "p0:3"})

    def test_stitch_peak_tracks_join_each_other(self):
        fr, trk = self.frames()
        trk["p0:3"] = dict(label="fish", source="peak+0-r0c1")
        self.assertEqual(set(tracks.stitch(fr, trk, apart=("camo", "peak+"))), {"peak+0-r0c0:1"})

    @staticmethod
    def det(i, box, cut=False):
        return dict(id=i, box=box, conf=0.9, cut=cut)

    def test_merge_peak_boxes_do_not_make_a_group_box(self):
        # two uncut tile boxes inside a first-pass box: without apart the first-pass box is dropped as a group box
        src = lambda: [("p0", "fish", {5: [self.det(1, [0, 0, 100, 100])]}),
                       ("peak+5-r0c0", "fish", {5: [self.det(1, [5, 5, 40, 40]), self.det(2, [50, 50, 95, 95])]})]
        fr, _ = tracks.merge(src())
        self.assertNotIn("p0:1", [k["track"] for k in fr[5]])                      # the old drop
        fr, trk = tracks.merge(src(), apart=("peak+",))
        self.assertEqual([k["box"] for k in fr[5] if k["track"] == "p0:1"], [[0, 0, 100, 100]])
        self.assertEqual(len(fr[5]), 3)

    def test_merge_first_pass_group_box_still_dropped(self):
        # two first-pass boxes from other passes inside a first-pass box: the 11/1 s004 group box rule still applies
        src = [("p0", "fish", {5: [self.det(1, [0, 0, 100, 100])]}),
               ("d0", "fish", {5: [self.det(1, [5, 5, 40, 40]), self.det(2, [50, 50, 95, 95])]})]
        fr, _ = tracks.merge(src, apart=("peak+",))
        self.assertEqual(sorted(k["track"] for k in fr[5]), ["d0:1", "d0:2"])

    def test_merge_peak_track_not_aliased_into_first_pass(self):
        # a tile track overlapping a first-pass track on 4 of its 6 frames: without apart its 2 own frames are
        # handed to the first-pass track, which then has frames it never had
        a = [10, 10, 50, 50]
        src = lambda: [("p0", "fish", {f: [self.det(1, a)] for f in range(4)}),
                       ("peak+0-r0c0", "fish", {f: [self.det(7, a)] for f in range(6)})]
        _, trk = tracks.merge(src())
        self.assertEqual(trk["p0:1"]["frames"], [0, 1, 2, 3, 4, 5])               # the old alias
        _, trk = tracks.merge(src(), apart=("peak+",))
        self.assertEqual(trk["p0:1"]["frames"], [0, 1, 2, 3])
        self.assertEqual(trk["peak+0-r0c0:7"]["frames"], [4, 5])

    def test_merge_without_peak_sources_unchanged(self):
        # first-pass tracks still alias each other with apart set
        a = [10, 10, 50, 50]
        src = lambda: [("p0", "fish", {f: [self.det(1, a)] for f in range(4)}),
                       ("d0", "fish", {f: [self.det(3, a)] for f in range(6)})]
        self.assertEqual(tracks.merge(src()), tracks.merge(src(), apart=("peak+",)))
        self.assertEqual(tracks.merge(src())[1]["p0:1"]["frames"], [0, 1, 2, 3, 4, 5])

    def test_audit_first_pass_sheets_unchanged(self):
        import tempfile
        import numpy as np
        from fishcount import motion, render
        saved = (video.frames, video.jpg, render.crop, motion.trio, motion.layout, pipeline._counted)
        sheets, asked = [], []
        video.frames = lambda clip, idx: {i: np.zeros((8, 8, 3), np.uint8) for i in idx}
        video.jpg = lambda img, **k: b"j"
        render.crop = lambda img, b, **k: img
        motion.trio = lambda imgs, trio, name, **k: name
        motion.layout = lambda groups: sheets.append(list(groups)) or b"sheet"
        pipeline._counted = lambda run, fn, prompt, imgs, **k: asked.append(prompt) or "[]"
        try:
            fr = {}
            for i, (t, f0) in enumerate((("p0:1", 0), ("p0:2", 20), ("peak+5-r0c0:1", 5), ("peak+5-r0c1:2", 25))):
                for f in range(f0, f0 + 4):
                    fr.setdefault(f, []).append(dict(track=t, box=[10 * i, 10, 10 * i + 8, 18]))
            trk = {t: dict(label="fish", source=t.split(":")[0]) for ks in fr.values() for t in (k["track"] for k in ks)}
            first = {f: [k for k in ks if not k["track"].startswith("peak+")] for f, ks in fr.items()}
            first = {f: ks for f, ks in first.items() if ks}
            with tempfile.TemporaryDirectory() as d:
                alone = pipeline.audit(Run(d), "c", first, trk, "fish", "ctx", True)
                want = list(sheets)
                sheets.clear()
                is_peak = lambda t: t.startswith("peak+")
                v1 = pipeline.audit(Run(d), "c", fr, trk, "fish", "ctx", True, only=lambda t: not is_peak(t))
                v2 = pipeline.audit(Run(d), "c", fr, trk, "fish", "ctx", True, start=len(v1), only=is_peak, tag="peak_")
                self.assertEqual(sheets[0], want[0])                              # same first-pass sheet
                self.assertEqual({t: v["name"] for t, v in v1.items()}, {t: v["name"] for t, v in alone.items()})
                self.assertEqual({t: v["name"] for t, v in v2.items()}, {"peak+5-r0c0:1": "T3", "peak+5-r0c1:2": "T4"})
                self.assertTrue(os.path.exists(os.path.join(d, "audit_peak_fish_1.jpg")))
        finally:
            video.frames, video.jpg, render.crop, motion.trio, motion.layout, pipeline._counted = saved


if __name__ == "__main__":
    unittest.main()
