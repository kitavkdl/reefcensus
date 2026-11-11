"""Long videos: segment plan and the merge of segment runs (no network, no spend).
Run: python3 -m unittest discover -s tests -v"""
import glob, json, os, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fishcount import _pylib  # noqa: F401
from fishcount import longvideo

DEMO = sorted(glob.glob(os.path.join(ROOT, "demo", "runs", "cr11_s00?")))
KEYS = ("maxn", "maxn_frame", "maxn_time", "first_frame", "first_time", "tracks", "curve", "peak_checked")


def pick(m):
    return {k: {x: v[x] for x in KEYS} for k, v in m.items()}


class Plan(unittest.TestCase):
    def test_short_video_is_one_segment(self):
        self.assertEqual(longvideo.plan(60, 5, 600), [(0, 60)])

    def test_segments_are_equal_contiguous_and_within_the_limit(self):
        p = longvideo.plan(18000, 5, 600)          # one hour at 5 fps -> 6 x 10 min
        self.assertEqual(p, [(i * 3000, 3000) for i in range(6)])
        p = longvideo.plan(3001, 5, 600)           # one frame over: two halves, not 3000 + 1
        self.assertEqual(p, [(0, 1501), (1501, 1500)])
        for n, s in ((199, 20), (292, 20), (3001, 600), (17, 1)):
            p = longvideo.plan(n, 5, s)
            self.assertEqual(sum(k for _, k in p), n)
            self.assertTrue(all(a + k == b for (a, k), (b, _) in zip(p, p[1:])))
            self.assertTrue(all(k <= s * 5 for _, k in p))


@unittest.skipUnless(DEMO, "demo runs not present")
class Merge(unittest.TestCase):
    def test_one_segment_reproduces_the_run(self):
        for d in DEMO:
            res = json.load(open(os.path.join(d, "result.json")))
            n, fps = res["video"]["n_frames"], res["video"]["fps"]
            with tempfile.TemporaryDirectory() as out:
                R = longvideo.merge("t", res["source"], [(d, 0, n)], fps, out_dir=out)
            self.assertEqual(pick(R["metrics"]), pick(res["metrics"]), d)

    def test_two_segments_lay_curves_end_to_end(self):
        d = next(x for x in DEMO if x.endswith("s003"))
        res = json.load(open(os.path.join(d, "result.json")))
        n, fps = res["video"]["n_frames"], res["video"]["fps"]
        with tempfile.TemporaryDirectory() as out:
            R = longvideo.merge("t", res["source"], [(d, 0, n), (d, n, n)], fps, out_dir=out)
            self.assertTrue(os.path.exists(os.path.join(out, "thumbs", "S2-T1_trio.jpg")))
        for name, m in res["metrics"].items():
            M = R["metrics"][name]
            self.assertEqual(M["maxn"], m["maxn"])                 # same moment count, not doubled
            self.assertEqual(M["maxn_frame"], m["maxn_frame"])     # first frame reaching it, in segment 1
            self.assertEqual(M["first_frame"], m["first_frame"])
            self.assertEqual(M["curve"], m["curve"] + m["curve"])
            self.assertEqual(M["tracks"], 2 * m["tracks"])         # an animal across a cut is two tracks
        self.assertEqual(R["video"]["n_frames"], 2 * n)
        self.assertEqual([s["start_frame"] for s in R["segments"]], [0, n])

    def test_first_arrival_is_offset_by_the_segment_start(self):
        d = next(x for x in DEMO if x.endswith("s003"))
        res = json.load(open(os.path.join(d, "result.json")))
        n, fps = res["video"]["n_frames"], res["video"]["fps"]
        empty = json.loads(json.dumps(res))
        empty.update(tracks={}, verdicts={}, auto_labels={}, metrics={}, frames={}, peak_checks=[], duplicates=[])
        with tempfile.TemporaryDirectory() as tmp:
            e = os.path.join(tmp, "empty")
            os.makedirs(e)
            json.dump(empty, open(os.path.join(e, "result.json"), "w"))
            R = longvideo.merge("t", res["source"], [(e, 0, n), (d, n, n)], fps, out_dir=os.path.join(tmp, "out"))
        for name, m in res["metrics"].items():
            self.assertEqual(R["metrics"][name]["first_frame"], n + m["first_frame"])
            self.assertAlmostEqual(R["metrics"][name]["first_time"], (n + m["first_frame"]) / fps, places=2)
            self.assertEqual(R["metrics"][name]["maxn"], m["maxn"])

    def test_names_sharing_a_head_noun_are_listed_not_merged(self):
        d = next(x for x in DEMO if x.endswith("s003"))
        res = json.load(open(os.path.join(d, "result.json")))
        n, fps = res["video"]["n_frames"], res["video"]["fps"]
        other = json.loads(json.dumps(res))
        other["auto_labels"] = {t: ("nautilus" if l else l) for t, l in other["auto_labels"].items()}
        with tempfile.TemporaryDirectory() as tmp:
            o = os.path.join(tmp, "other")
            os.makedirs(o)
            json.dump(other, open(os.path.join(o, "result.json"), "w"))
            R = longvideo.merge("t", res["source"], [(d, 0, n), (o, n, n)], fps, out_dir=os.path.join(tmp, "out"))
        self.assertIn("nautilus", R["metrics"])
        self.assertIn("chambered nautilus", R["metrics"])
        self.assertIn(["chambered nautilus", "nautilus"], R["name_variants"])

    def test_an_animal_across_a_cut_is_linked_and_a_name_change_is_listed(self):
        """Segment 2 opens with the boxes segment 1 ended on (one animal crossing the cut), and its Spark named the
        counted tracks differently: each box pairs with its continuation, the counts stay those of the segments, and
        the two names go to the reviewer's name_variants. A box with no overlap on the other side links to nothing."""
        d = next(x for x in DEMO if x.endswith("s003"))
        res = json.load(open(os.path.join(d, "result.json")))
        n, fps = res["video"]["n_frames"], res["video"]["fps"]
        last = res["frames"][str(n - 1)]
        self.assertTrue(last, "s003 should end with boxes on screen")
        other = json.loads(json.dumps(res))
        other["frames"]["0"] = json.loads(json.dumps(last)) + [dict(track="zz:9", box=[0, 0, 5, 5])]
        other["auto_labels"] = {t: ("hermit crab" if l else l) for t, l in other["auto_labels"].items()}
        with tempfile.TemporaryDirectory() as tmp:
            o = os.path.join(tmp, "other")
            os.makedirs(o)
            json.dump(other, open(os.path.join(o, "result.json"), "w"))
            R = longvideo.merge("t", res["source"], [(d, 0, n), (o, n, n)], fps, out_dir=os.path.join(tmp, "out"))
        links = R["boundary_links"]
        self.assertEqual({(x["before"], x["after"]) for x in links}, {("S1:" + k["track"], "S2:" + k["track"]) for k in last})
        self.assertTrue(all(x["cut_frame"] == n and x["iou"] == 1.0 for x in links))
        self.assertTrue(any(x["name_conflict"] for x in links), "s003's last frame should hold a counted track")
        for x in links:
            self.assertEqual(x["name_conflict"], bool(x["before_label"] and x["after_label"]))
            if x["name_conflict"]:
                self.assertIn(sorted([x["before_label"], "hermit crab"]), R["name_variants"])
        for name, m in res["metrics"].items():
            self.assertEqual(R["metrics"][name]["maxn"], m["maxn"])


if __name__ == "__main__":
    unittest.main()


class CrowdAndEmptyTracks(unittest.TestCase):
    def _seg(self, d, maxn_boxes, crowd_total):
        trk = {f"t{i}": dict(label="fish", source="j", first=0, last=0, n=1) for i in range(maxn_boxes)}
        trk["gone"] = dict(label="fish", source="j", first=None, last=None, n=0)   # every box removed by verify_peaks
        res = dict(source="v.mp4", video=dict(n_frames=2, fps=5, width=10, height=10), tracks=trk,
                   metrics={"fish": dict(maxn=maxn_boxes)}, auto_labels={},
                   frames={"0": [dict(track=t, box=[0, 0, 1, 1]) for t in trk if t != "gone"]},
                   crowd_checks=[dict(row="fish", labels=["fish"], frame=0, maxn=maxn_boxes, total=crowd_total, lower_bound=True)])
        os.makedirs(d)
        json.dump(res, open(os.path.join(d, "result.json"), "w"))

    def test_crowd_check_survives_the_merge_and_is_judged_on_the_whole_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = os.path.join(tmp, "a"), os.path.join(tmp, "b")
            self._seg(a, 4, 12)        # 12 >= 4+3 and >= 1.5*4: lower bound for MaxN 4
            self._seg(b, 9, 12)        # segment 2 lifts MaxN to 9: 12 < 9+3, no longer a lower bound
            R = longvideo.merge("t", "v.mp4", [(a, 0, 2), (b, 2, 2)], 5, out_dir=os.path.join(tmp, "o"))
        self.assertEqual(R["metrics"]["fish"]["maxn"], 9)
        self.assertEqual(R["metrics"]["fish"]["tracks"], 13)      # the two emptied tracks are not counted
        self.assertEqual([(c["frame"], c["maxn"], c["lower_bound"]) for c in R["crowd_checks"]], [(0, 9, False), (2, 9, False)])
        self.assertIsNone(R["tracks"]["S1:gone"]["first"])


def _fake_seg(d, n, last_boxes=(), capped=None, label="fish"):
    """A segment run: track t<i> on frame 0 and on frame n-1 for each box in last_boxes."""
    trk = {f"t{i}": dict(label=label, source="p0", first=0, last=n - 1, n=2) for i in range(len(last_boxes))}
    fr = {"0": [dict(track=f"t{i}", box=list(b)) for i, b in enumerate(last_boxes)]}
    fr[str(n - 1)] = [dict(track=f"t{i}", box=list(b)) for i, b in enumerate(last_boxes)]
    res = dict(source="v.mp4", video=dict(n_frames=n, fps=5, width=100, height=100), tracks=trk,
               metrics={label: dict(maxn=len(last_boxes))} if last_boxes else {}, auto_labels={}, frames=fr)
    if capped:
        res["capped"] = capped
    os.makedirs(d, exist_ok=True)
    json.dump(res, open(os.path.join(d, "result.json"), "w"))


class SkipEmptyMerge(unittest.TestCase):
    def test_a_skipped_stretch_carries_the_last_analysed_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = os.path.join(tmp, "a"), os.path.join(tmp, "b")
            _fake_seg(a, 10, [(10, 10, 30, 30)])
            _fake_seg(b, 10, [])
            R = longvideo.merge("t", "v.mp4", [(a, 0, 10), (b, 20, 10)], 5, out_dir=os.path.join(tmp, "o"),
                                n_total=40, carry=[(10, 20), (30, 40)])
        self.assertEqual(R["video"]["n_frames"], 40)
        self.assertEqual(len(R["metrics"]["fish"]["curve"]), 40)
        for f in range(10, 20):
            self.assertEqual(R["frames"][str(f)], [dict(track="S1:t0", box=[10, 10, 30, 30], carried=True)])
        self.assertNotIn("35", R["frames"])                   # segment 2 ended on empty water: nothing to carry
        self.assertEqual(R["metrics"]["fish"]["curve"][15], 1)
        self.assertEqual(R["tracks"]["S1:t0"]["last"], 19)
        self.assertEqual([(s["start_frame"], s["end_frame"], s["carried"]) for s in R["skipped"]], [(10, 20, 1), (30, 40, 0)])
        # the link across the skipped stretch compares the last carried frame with segment 2's first
        self.assertEqual(R["boundary_links"], [])

    def test_without_skip_empty_the_merge_adds_no_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = os.path.join(tmp, "a")
            _fake_seg(a, 10, [(10, 10, 30, 30)])
            R = longvideo.merge("t", "v.mp4", [(a, 0, 10)], 5, out_dir=os.path.join(tmp, "o"))
        for k in ("skipped", "unsent", "capped", "probes"):
            self.assertNotIn(k, R)

    def test_capped_stages_are_collected_with_their_segment(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = os.path.join(tmp, "a"), os.path.join(tmp, "b")
            _fake_seg(a, 10, [], capped=[dict(stage="miss", msg="skipped the missed-animal look")])
            _fake_seg(b, 10, [])
            R = longvideo.merge("t", "v.mp4", [(a, 0, 10), (b, 10, 10)], 5, out_dir=os.path.join(tmp, "o"))
        self.assertEqual(R["capped"], [dict(stage="miss", msg="skipped the missed-animal look", segment="S1")])


class SkipEmptyRun(unittest.TestCase):
    """run_long(skip_empty=True) with the video tools and run_pipeline replaced by fakes: which frames go to the
    models, the remaining video cap each run gets, and what happens when the cap or FISH_BUDGET stops a run."""
    N = 1000

    def setUp(self):
        from unittest import mock
        from fishcount import api, pipeline, screen, video
        self.tmp = tempfile.mkdtemp()
        self.cuts, self.calls, self.results = {}, [], {}
        self.bill, self.cap_need = 0.5, 0.5

        def ingest(src, dst, **k):
            open(dst, "w").close()

        def cut(clip, dst, start, n):
            self.cuts[dst] = (start, n)
            open(dst, "w").close()

        def run_pipeline(sp, srid, **kw):
            start, n = self.cuts[sp]
            self.calls.append((start, n, round(kw["max_usd"], 3)))
            d = os.path.join(self.tmp, srid)
            os.makedirs(d, exist_ok=True)
            if kw["max_usd"] < self.cap_need:
                raise api.BudgetExceeded("estimate > per-video cap")
            _fake_seg(d, n, self.results.get(start, []))
            json.dump(dict(live_calls=1, cached_calls=0, billed_usd=self.bill), open(os.path.join(d, "status.json"), "w"))

        self.patches = [mock.patch.object(pipeline, "RUNS", self.tmp), mock.patch.object(video, "ingest", ingest),
                        mock.patch.object(video, "info", lambda p: dict(n_frames=self.N, fps=5.0, width=100, height=100)),
                        mock.patch.object(video, "light_stats", lambda p: dict(median_l=100, mean_l=100)),
                        mock.patch.object(longvideo, "cut", cut), mock.patch.object(longvideo, "_filler", lambda full, d, a, *k: os.path.join(d, f"skip{a}")),
                        mock.patch.object(pipeline, "run_pipeline", run_pipeline),
                        mock.patch.object(screen, "scan", lambda clip, fps, **k: self.wins)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        import shutil
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def sent_frames(self):
        return {f for s, n, _ in self.calls for f in range(s, s + n)}

    def test_skipped_stretches_get_no_call_and_the_cap_stops_what_it_cannot_pay(self):
        self.wins = [dict(start=0, n=300, kind="head"), dict(start=500, n=300, kind="change", triggers=[550])]
        self.results = {0: [(10, 10, 30, 30)]}
        R = longvideo.run_long("v.mp4", "r1", skip_empty=True, max_usd_video=0.8, max_usd=1.0)
        self.assertEqual(self.calls, [(0, 300, 0.8), (500, 300, 0.3)])     # cap minus what earlier runs spent
        self.assertFalse(self.sent_frames() & set(range(300, 500)))         # completion criterion 1: no call there
        self.assertEqual([(s["start_frame"], s["end_frame"]) for s in R["skipped"]], [(300, 500)])
        self.assertEqual([(u["start_frame"], u["end_frame"]) for u in R["unsent"]], [(500, 1000)])
        self.assertEqual(R["video"]["n_frames"], self.N)
        self.assertEqual(R["metrics"]["fish"]["curve"][400], 1)            # carried
        self.assertEqual(R["metrics"]["fish"]["curve"][600], 0)            # unsent: not carried

    def test_fish_budget_mid_video_keeps_the_segments_already_done(self):
        from fishcount import api
        self.wins = [dict(start=0, n=300, kind="head"), dict(start=500, n=300, kind="change", triggers=[550])]
        self.cap_need = 0.0
        orig = self.patches[6].new

        def second_fails(sp, srid, **kw):
            if self.cuts[sp][0] == 500:
                raise api.BudgetExceeded("would spend > budget (set FISH_BUDGET)")
            return orig(sp, srid, **kw)
        from fishcount import pipeline
        pipeline.run_pipeline = second_fails
        R = longvideo.run_long("v.mp4", "r2", skip_empty=True, max_usd_video=5)
        self.assertEqual([s["start_frame"] for s in R["segments"]], [0])
        self.assertEqual([(u["start_frame"], u["end_frame"]) for u in R["unsent"]], [(500, 1000)])

    def test_a_probe_that_disagrees_re_sends_the_stretch_before_it_once(self):
        self.wins = [dict(start=0, n=300, kind="head"), dict(start=700, n=50, kind="probe")]
        self.results = {0: [(10, 10, 30, 30)], 700: []}                    # the box is gone by the probe
        R = longvideo.run_long("v.mp4", "r3", skip_empty=True, max_usd_video=10)
        # the re-send stops where the probe starts: the probe's own frames are not paid twice, its run is used as is
        self.assertEqual([(s, n) for s, n, _ in self.calls], [(0, 300), (700, 50), (300, 400)])
        self.assertEqual([p["match"] for p in R["probes"]], [False])
        self.assertEqual([(s["start_frame"], s["end_frame"]) for s in R["skipped"]], [(750, 1000)])
        self.assertEqual([s["start_frame"] for s in R["segments"]], [0, 300, 700])
        self.assertEqual(R["metrics"]["fish"]["curve"][720], 0)            # the probe's empty frames, not carried boxes

    def test_a_probe_that_agrees_keeps_the_carried_boxes(self):
        self.wins = [dict(start=0, n=300, kind="head"), dict(start=700, n=50, kind="probe")]
        self.results = {0: [(10, 10, 30, 30)], 700: [(11, 10, 31, 30)]}
        R = longvideo.run_long("v.mp4", "r4", skip_empty=True, max_usd_video=10)
        self.assertEqual([(s, n) for s, n, _ in self.calls], [(0, 300), (700, 50)])
        self.assertEqual([p["match"] for p in R["probes"]], [True])
        self.assertEqual([(s["start_frame"], s["end_frame"]) for s in R["skipped"]], [(300, 1000)])
        self.assertEqual(R["metrics"]["fish"]["curve"][720], 1)
        self.assertEqual(R["frames"]["720"][0]["track"], "S1:t0")


class SkipEmptyFlags(unittest.TestCase):
    def test_video_cap_and_probe_flags_need_skip_empty(self):
        """--max-usd-video / --probe-every without --skip-empty would be ignored, so the CLI refuses them."""
        for flag in (["--max-usd-video", "3"], ["--probe-every", "90"]):
            p = subprocess.run([sys.executable, os.path.join(ROOT, "fishcount", "pipeline.py"), "missing.mp4"] + flag,
                               capture_output=True, text=True, timeout=120)
            self.assertEqual(p.returncode, 2, p.stderr)
            self.assertIn("need --skip-empty", p.stderr)


class CappedStages(unittest.TestCase):
    def test_every_cap_skip_is_recorded(self):
        """The seven stages that skip quietly at the per-video cap go through pipeline._capped."""
        import re
        src = open(os.path.join(ROOT, "fishcount", "pipeline.py")).read()
        lines = [l for l in src.splitlines() if "would pass the per-video cap ${" in l]
        self.assertEqual(len(lines), 7)
        self.assertTrue(all("_capped(" in l for l in lines), [l for l in lines if "_capped(" not in l])

    def test_capped_logs_and_records(self):
        from fishcount import pipeline
        with tempfile.TemporaryDirectory() as tmp:
            old = pipeline.RUNS
            pipeline.RUNS = tmp
            try:
                run = pipeline.Run("x")
                pipeline._capped(run, "miss", "skipped the missed-animal look: est $0.10 would pass the per-video cap $0.05")
            finally:
                pipeline.RUNS = old
        self.assertEqual(run.capped, [dict(stage="miss", msg="skipped the missed-animal look: est $0.10 would pass the per-video cap $0.05")])
        self.assertTrue(run.status["log"][-1].endswith("would pass the per-video cap $0.05"))


class ReviewVideoLength(unittest.TestCase):
    """--skip-empty review videos, with the real ffmpeg: sent piece + skipped piece (carried box) + sent piece laid end
    to end are as long as the video, for clip, annotated and (dark video) clip_original."""

    def test_pieces_add_up_to_the_video(self):
        from fishcount import render, video
        for brightened in (False, True):
            with tempfile.TemporaryDirectory() as d:
                full = os.path.join(d, "full.mp4")
                subprocess.run([video.FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                                "testsrc=size=160x120:rate=5", "-frames:v", "60", "-c:v", "libx264", "-pix_fmt", "yuv420p", full],
                               check=True)
                R = dict(video=dict(fps=5.0), jobs=[], auto_labels={}, tracks={"t1": dict(label="fish", source="discover")},
                         frames={"20": [dict(track="t1", box=[10, 10, 50, 40], carried=True)]})
                segs = []
                for a, n in ((0, 20), (40, 20)):
                    sd = os.path.join(d, f"S{a}")
                    os.makedirs(sd)
                    clip = os.path.join(sd, "clip.mp4")
                    if brightened:
                        longvideo.cut(full, os.path.join(sd, "clip_original.mp4"), a, n)
                        video.brighten(os.path.join(sd, "clip_original.mp4"), clip)
                    else:
                        longvideo.cut(full, clip, a, n)
                    render.annotate(clip, {}, dict(video=dict(n_frames=n, fps=5.0), tracks={}, frames={}), os.path.join(sd, "annotated.mp4"))
                    segs.append(sd)
                fd = longvideo._filler(full, d, 20, 40, R, brightened)
                longvideo._review_videos(d, [segs[0], fd, segs[1]])
                kinds = ("clip.mp4", "annotated.mp4") + (("clip_original.mp4",) if brightened else ())
                for kind in kinds:
                    self.assertEqual(video.info(os.path.join(d, kind))["n_frames"], 60, (kind, brightened))
                self.assertEqual(brightened, os.path.exists(os.path.join(d, "clip_original.mp4")))

    def test_run_long_n_frames_is_the_real_frame_count(self):
        """run_long(skip_empty) on a real ffmpeg video, only screen.scan and the model run faked: result n_frames,
        the curve and the review clip all match the frames decoded from the source (63, an odd count)."""
        import cv2
        from unittest import mock
        from fishcount import pipeline, render, screen, video
        with tempfile.TemporaryDirectory() as d:
            src = os.path.join(d, "src.mp4")
            subprocess.run([video.FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                            "testsrc=size=160x120:rate=5", "-frames:v", "63", "-c:v", "libx264", "-pix_fmt", "yuv420p", src],
                           check=True)
            cap, real = cv2.VideoCapture(src), 0
            while cap.read()[0]:
                real += 1
            cap.release()

            def run_pipeline(sp, srid, **kw):
                rd = os.path.join(d, srid)
                n = video.info(sp)["n_frames"]
                _fake_seg(rd, n, [(10, 10, 30, 30)])
                json.dump(dict(live_calls=1, cached_calls=0, billed_usd=0.0), open(os.path.join(rd, "status.json"), "w"))
                os.replace(sp, os.path.join(rd, "clip.mp4"))
                render.annotate(os.path.join(rd, "clip.mp4"), {}, dict(video=dict(n_frames=n, fps=5.0), tracks={}, frames={}),
                                os.path.join(rd, "annotated.mp4"))

            wins = [dict(start=0, n=20, kind="head"), dict(start=40, n=20, kind="change", triggers=[45])]
            with mock.patch.object(pipeline, "RUNS", d), mock.patch.object(pipeline, "run_pipeline", run_pipeline), \
                    mock.patch.object(screen, "scan", lambda clip, fps, **k: wins):
                R = longvideo.run_long(src, "rv", skip_empty=True, max_usd_video=10)
            self.assertEqual(real, 63)
            self.assertEqual(R["video"]["n_frames"], real)
            self.assertEqual(len(R["metrics"]["fish"]["curve"]), real)
            self.assertEqual(video.info(os.path.join(d, "rv", "clip.mp4"))["n_frames"], real)
