"""A long video's budget (D-NIGHT3): one cap for the whole video ($6 an hour by default, at least $1; --max-usd-video),
paid out as a fixed equal share per segment that is never below the first pass of the --prompts words; a first pass
that would pass its share leaves the discovery words, then the tiles, then the scout's words unsent (listed in
capped) instead of stopping the video; --resume keeps a segment only while its result still holds; spending past
the cap shows in result["budget"]. The ledger is a temp file in every test.
No network, no spend. Run: python3 -m unittest discover -s tests -v"""
import json, os, shutil, subprocess, sys, tempfile, time, unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fishcount import _pylib  # noqa: F401
from fishcount import api, batch, longvideo, pipeline, video
from test_longvideo import _fake_seg

CLIP = os.path.join(ROOT, "tests", "data", "nautilus_s004_0_12.mp4")     # 60 frames
CALL = 60 * api.SAM_PER_FRAME                                             # one call on the clip: $0.012


class FirstPass(unittest.TestCase):
    """The real _run_pipeline on the 12-s test clip, discovery on, every API call replaced by a fake."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.cache, self.sent = set(), []

        def spark(prompt, images=(), offline=False, check=None, **k):
            return json.dumps(dict(others=[dict(what="crab", search_words=["crab", "shell"], approx_max_count=1,
                                                cells=[], frames=[0])], signs=[]))

        def sam_video(path, prompt, n, offline=False):
            if prompt in self.cache:        # answered from the cache: nothing sent
                return ""
            if offline:
                raise FileNotFoundError(f"not cached: SAM {prompt!r} on {path}")
            self.sent.append(prompt)
            self.cache.add(prompt)
            return ""

        for p in (mock.patch.object(pipeline, "RUNS", self.tmp), mock.patch.object(api, "LEDGER", os.path.join(self.tmp, "l.jsonl")),
                  mock.patch.object(api, "spark", spark), mock.patch.object(api, "sam_video", sam_video),
                  mock.patch.object(api, "sam_cached", lambda path, prompt: prompt in self.cache)):
            p.start()
        self.addCleanup(mock.patch.stopall)

    def run_(self, rid, cap, offline=False):
        return pipeline.run_pipeline(CLIP, rid, offline, False, False, False, ["fish"], cap, True)

    def test_reproduction_a_first_pass_over_its_cap_sends_less_instead_of_stopping(self):
        # fish + the ladder crab, shell = $0.036 > $0.02: before D-NIGHT3 this raised "estimate > per-video cap"
        # (a long video stopped at its first segment); now the discovery ladder is left unsent
        R = self.run_(rid="r", cap=0.02)
        self.assertEqual(self.sent, ["fish"])
        self.assertEqual([(c["stage"], c["item"]) for c in R["capped"]], [("first_pass", "d0")])
        self.assertIn("not sent", R["capped"][0]["msg"])
        self.assertEqual(R["discovered"][0]["not_sent"], True)
        self.assertEqual(R["discovered"][0]["tried"], [])

    def test_under_the_cap_nothing_changes(self):
        R = self.run_(rid="r", cap=0.04)
        self.assertEqual(sorted(self.sent), ["crab", "fish", "shell"])     # the ladder and the prompt run at once
        self.assertNotIn("capped", R)
        self.assertNotIn("not_sent", R["discovered"][0])

    def test_the_crowd_peak_second_pass_keeps_out_what_the_first_left_out(self):
        # $0.025: the first pass leaves the $0.024 ladder out; in the second pass (same run) fish is cached and the
        # ladder alone would fit, but it must stay out so capped stays true and the inputs are the first pass's
        run = pipeline.Run("r")
        pipeline.run_pipeline(CLIP, "r", False, False, False, False, ["fish"], 0.025, True, _run=run)
        R = pipeline.run_pipeline(CLIP, "r", False, False, False, False, ["fish"], 0.025, True, crowd_peak=5,
                                  _peak=dict(windows=[], first=[]), _run=run)
        self.assertEqual(self.sent, ["fish"])
        self.assertEqual([c["item"] for c in R["capped"]], ["d0"])

    def test_the_prompts_alone_over_the_cap_still_stop_before_paying(self):
        with self.assertRaises(api.BudgetExceeded):
            self.run_(rid="r", cap=0.005)
        self.assertEqual(self.sent, [])

    def test_offline_replay_leaves_out_what_the_live_run_left_unsent(self):
        self.run_(rid="r", cap=0.02)
        R = self.run_(rid="r", cap=0.02, offline=True)          # same folder: the live result says d0 was not sent
        self.assertEqual([c["item"] for c in R["capped"]], ["d0"])
        self.assertNotIn("budget", R)

    def test_offline_any_other_miss_raises_as_before(self):
        self.run_(rid="r", cap=0.02)
        with self.assertRaises(FileNotFoundError) as e:         # another folder: nothing says d0 was left unsent
            self.run_(rid="other", cap=0.02, offline=True)
        self.assertIn("not cached", str(e.exception))
        self.assertNotIn("cap", str(e.exception))


class Trim(unittest.TestCase):
    jobs = [("p0", "crab", "crab", "clip.mp4", None), ("p1", "fish", "fish", "clip.mp4", None),
            ("zoom-r1c1", "fish", "fish", "tile_r1c1.mp4", (0, 0, 1, 1)), ("crowd-a", "fish", "fish", "tile_crowd-a.mp4", (0, 0, 1, 1))]
    others = [({"what": "eel"}, ["eel"]), ({"what": "diver"}, []), ({"what": "ray"}, ["ray", "skate"])]

    def trim(self, cap, cached=()):
        with mock.patch.object(api, "sam_cached", lambda clip, prompt: (clip, prompt) in cached):
            return pipeline.first_pass_trim(self.jobs, self.others, "clip.mp4", 60, cap, {"fish"})

    def test_order_discovery_from_the_last_then_tiles_then_scout_words(self):
        est, out = self.trim(CALL + 1e-6)
        self.assertEqual([x for x, _ in out], ["d2", "d0", "crowd-a", "zoom-r1c1", "p0"])
        self.assertAlmostEqual(est, CALL)
        self.assertEqual(self.trim(CALL + 1e-6), (est, out))                  # deterministic

    def test_stops_as_soon_as_it_fits(self):
        est, out = self.trim(4 * CALL + 1e-6)                                # 7 calls: d2 (2), then d0 (1)
        self.assertEqual([x for x, _ in out], ["d2", "d0"])
        self.assertAlmostEqual(est, 4 * CALL)

    def test_a_cached_item_is_never_left_out(self):
        est, out = self.trim(CALL + 1e-6, cached={("clip.mp4", "ray"), ("clip.mp4", "skate")})
        self.assertNotIn("d2", [x for x, _ in out])

    def test_the_required_words_alone_over_the_cap_raise(self):
        with self.assertRaises(api.BudgetExceeded):
            self.trim(CALL / 2)


class LadderEstimate(unittest.TestCase):
    def test_probe_windows_never_price_more_than_the_old_estimate(self):
        with mock.patch.object(api, "sam_cached", lambda clip, prompt: False):
            old = pipeline.ladder_estimate("c", ["a", "b", "c"], 3000)
            new = pipeline.ladder_estimate("c", ["a", "b", "c"], 3000, [(100, 51), (900, 51)])
            self.assertAlmostEqual(old, 3 * 3000 * api.SAM_PER_FRAME)
            self.assertAlmostEqual(new, 3 * 102 * api.SAM_PER_FRAME + 3000 * api.SAM_PER_FRAME)
            wide = pipeline.ladder_estimate("c", ["a"], 3000, [(0, 1500), (1600, 1400)])
            self.assertAlmostEqual(wide, 3000 * api.SAM_PER_FRAME)            # min(old, windows + whole)
        with mock.patch.object(api, "sam_cached", lambda clip, prompt: True):
            self.assertEqual(pipeline.ladder_estimate("c", ["a", "b"], 3000), 0)

    def test_first_estimate_takes_the_probes(self):
        with mock.patch.object(api, "sam_cached", lambda clip, prompt: False):
            jobs, others = [("p0", "fish", "fish", "c", None)], [({}, ["a", "b"])]
            self.assertLess(pipeline.first_estimate(jobs, others, "c", 3000, [[(100, 51)]]),
                            pipeline.first_estimate(jobs, others, "c", 3000))


class Shares(unittest.TestCase):
    def test_equal_share_never_below_the_floor(self):
        self.assertEqual(longvideo.shares([0.6] * 6, 6.0), [1.0] * 6)
        self.assertEqual(longvideo.shares([0.6] * 6, 6.0, ceiling=0.8), [0.8] * 6)
        with self.assertRaises(api.BudgetExceeded) as e:                        # --max-usd below F: stop before paying
            longvideo.shares([0.6] * 6, 6.0, ceiling=0.1)
        self.assertIn("--max-usd 0.60", str(e.exception))
        self.assertEqual(longvideo.shares([0.6] * 6, 6.0, ceiling=0.1, offline=True), [0.6] * 6)

    def test_unequal_floors_share_exactly_the_cap(self):
        # Codex P1: max(F_k, cap/n) gave [2, 1, 1] = $4 of a $3 cap; now F_k + what the cap has over the floors / n
        s = longvideo.shares([2, 0.1, 0.1], 3.0)
        self.assertAlmostEqual(sum(s), 3.0, places=3)
        self.assertTrue(all(x >= f for x, f in zip(s, [2, 0.1, 0.1])))
        self.assertEqual(sorted(longvideo.shares([0.1, 2, 0.1], 3.0)), sorted(s))       # whatever the order
        self.assertEqual(longvideo.shares([2, 0.1, 0.1], 1.0), [2, 0.1, 0.1])            # a cap below the floors: F each
        self.assertEqual(longvideo.shares([2, 0.1, 0.1], 3.0, ceiling=2.1), [2.1, 0.3667, 0.3667])

    def test_a_cap_set_below_the_first_passes_stops_before_paying(self):
        with self.assertRaises(api.BudgetExceeded) as e:
            longvideo.video_cap([1.2] * 6, 3.0, 6.0)
        self.assertIn("7.20", str(e.exception))
        self.assertEqual(longvideo.video_cap([1.2] * 6, 3.0, 6.0, offline=True), (3.0, None))

    def test_a_default_below_the_first_passes_is_raised_and_said(self):
        cap, note = longvideo.video_cap([1.2] * 6, None, 6.0)
        self.assertAlmostEqual(cap, 7.2)
        self.assertIn("raised", note)
        self.assertEqual(longvideo.video_cap([0.6] * 6, None, 6.0), (6.0, None))

    def test_short_video_cap_default_is_raised_to_its_first_pass(self):
        self.assertEqual(longvideo.short_cap(None, None, 0.6), (1.0, None))
        cap, note = longvideo.short_cap(None, None, 1.2)
        self.assertEqual(cap, 1.2)
        self.assertIn("raised", note)
        self.assertEqual(longvideo.short_cap(1.5, 3.0, 1.2), (1.5, None))     # a cap set is kept
        self.assertEqual(longvideo.short_cap(None, 3.0, 1.2), (3.0, None))

    def test_short_video_cap_set_below_its_first_pass_stops_before_paying(self):
        # Codex P1: the scout / discover Spark calls were paid first, then the --prompts words raised with no result
        for given in [(0.5, None), (None, 0.5), (0.0, None)]:
            with self.assertRaises(api.BudgetExceeded) as e:
                longvideo.short_cap(*given, 1.2)
            self.assertIn("1.20 or more", str(e.exception))
        self.assertEqual(longvideo.short_cap(0.5, None, 1.2, offline=True), (0.5, None))

    def test_floor_counts_the_prompts_words(self):
        self.assertAlmostEqual(longvideo.first_pass_floor(3000, None), 0.6)
        self.assertAlmostEqual(longvideo.first_pass_floor(3000, ["fish", "crab", "fish"]), 1.2)
        self.assertAlmostEqual(longvideo.first_pass_floor(10, ["fish"]), 50 * api.SAM_PER_FRAME)


class Spent(unittest.TestCase):
    def test_rows_of_the_video_its_segments_and_probes_from_t0(self):
        with tempfile.TemporaryDirectory() as tmp:
            led = os.path.join(tmp, "l.jsonl")
            rows = [dict(t=5, usd=1, run="a.b"), dict(t=5, usd=2, run="a.b__S1"), dict(t=5, usd=4, run="a.b__P2"),
                    dict(t=5, usd=8, run="aXb"), dict(t=5, usd=16, run="a.b__S1x"), dict(t=5, usd=32, run="a.bb"),
                    dict(t=1, usd=64, run="a.b"), dict(usd=128, run="a.b"),
                    dict(t=5, usd=256, run="a.b__S2", note="clip:fish (stream broke)"), dict(t=5, run="a.b")]
            with open(led, "w") as f:
                f.writelines(json.dumps(r) + "\n" for r in rows)
                f.write("not json\n[1]\n")
            self.assertEqual(longvideo.video_spent("a.b", 2, led), (263.0, 1))
            self.assertEqual(longvideo.video_spent("a.b", 0, led), (455.0, 1))     # a row without t counts as t=0


def _ledger(path, rid, usd):
    with open(path, "a") as f:
        f.write(json.dumps(dict(t=time.time(), kind="sam", usd=usd, note="", run=rid)) + "\n")


class LongRun(unittest.TestCase):
    """run_long on a fake 600-s video (4 segments of 150 s), the fake pipeline writing its spend to a temp ledger."""
    N = 3000

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.led = os.path.join(self.tmp, "ledger.jsonl")
        self.cuts, self.calls, self.fail_at, self.capped, self.usd = {}, [], None, {}, 0.25

        def ingest(src, dst, **k):
            open(dst, "w").close()

        def cut(clip, dst, start, n):
            self.cuts[dst] = (start, n)
            with open(dst, "w") as f:
                f.write(f"{start}+{n}")

        def run_pipeline(sp, srid, **kw):
            start, n = self.cuts[sp]
            self.calls.append((start, kw["max_usd"]))
            _ledger(self.led, srid, self.usd)
            if self.fail_at == start:
                raise api.BudgetExceeded("would spend $1.2 > budget $1.00 (set FISH_BUDGET)")
            d = os.path.join(self.tmp, srid)
            _fake_seg(d, n, [(10, 10, 5, 5)], capped=self.capped.get(start))
            json.dump(dict(live_calls=1, cached_calls=0, billed_usd=self.usd, first_pass_sam_usd=0.1, spark_usd=0.05),
                      open(os.path.join(d, "status.json"), "w"))

        for p in (mock.patch.object(pipeline, "RUNS", self.tmp), mock.patch.object(api, "LEDGER", self.led),
                  mock.patch.object(video, "ingest", ingest),
                  mock.patch.object(video, "info", lambda p: dict(n_frames=self.N, fps=5.0, width=100, height=100)),
                  mock.patch.object(video, "light_stats", lambda p: dict(median_l=100, mean_l=100)),
                  mock.patch.object(longvideo, "cut", cut), mock.patch.object(pipeline, "run_pipeline", run_pipeline),
                  mock.patch.dict(os.environ, {"FISH_BUDGET": "1000"})):
            p.start()
        self.addCleanup(mock.patch.stopall)

    def run_long(self, rid="v", **kw):
        R = longvideo.run_long("v.mp4", rid, seg_s=150, **kw)
        return R, json.load(open(os.path.join(self.tmp, rid, "status.json")))

    def budget(self, rid="v"):
        return json.load(open(os.path.join(self.tmp, rid, "budget.json")))

    def test_default_cap_is_six_dollars_an_hour_at_least_one_split_evenly(self):
        self.run_long()
        self.assertEqual([u for _, u in self.calls], [0.25] * 4)                # 10 min -> $1 (the minimum), / 4
        self.assertEqual(self.budget()["cap"], 1.0)

    def test_hour_long_video_gets_six_dollars(self):
        self.N = 18000
        R = longvideo.run_long("v.mp4", "h", seg_s=600)
        self.assertEqual(self.budget("h")["cap"], 6.0)
        self.assertEqual([u for _, u in self.calls], [1.0] * 6)

    def test_floor_raises_a_default_cap_and_refuses_a_set_one(self):
        self.N = 18000
        R = longvideo.run_long("v.mp4", "h", seg_s=600, prompts=["fish", "crab"])       # F = 2 x 3000 x $0.0002 = $1.2
        self.assertEqual([u for _, u in self.calls], [1.2] * 6)
        st = json.load(open(os.path.join(self.tmp, "h", "status.json")))
        self.assertTrue(any("raised from the default $6.00 to $7.20" in l for l in st["log"]))
        self.calls.clear()
        with self.assertRaises(api.BudgetExceeded) as e:
            longvideo.run_long("v.mp4", "h2", seg_s=600, prompts=["fish", "crab"], max_usd_video=3)
        self.assertIn("--max-usd-video 7.20", str(e.exception))
        self.assertEqual(self.calls, [])                                         # nothing was sent

    def test_a_ceiling_below_a_segments_first_pass_stops_before_paying(self):
        with self.assertRaises(api.BudgetExceeded) as e:                        # F = 750 x $0.0002 = $0.15 a segment
            self.run_long(max_usd_video=1.0, max_usd=0.1)
        self.assertIn("--max-usd 0.15", str(e.exception))
        self.assertEqual(self.calls, [])

    def test_resume_after_a_crash_gives_the_segment_what_its_share_has_left(self):
        # Codex P1: the segment that died half-way was given its whole share again on --resume
        self.usd, self.fail_at = 0.2, 1500
        with self.assertRaises(api.BudgetExceeded):
            self.run_long(max_usd_video=2.0)                                     # shares $0.50; S3 spent $0.20, died
        self.fail_at, self.calls[:] = None, []
        self.run_long(max_usd_video=2.0, resume=True)
        self.assertEqual(self.calls, [(1500, 0.3), (2250, 0.5)])
        self.usd, self.fail_at = 0.45, 1500                                      # its share all but spent: F ($0.15) still
        with self.assertRaises(api.BudgetExceeded):
            self.run_long("w", max_usd_video=2.0)
        self.fail_at, self.calls[:] = None, []
        self.run_long("w", max_usd_video=2.0, resume=True)
        self.assertEqual(self.calls, [(1500, 0.15), (2250, 0.5)])
        self.assertEqual(json.load(open(os.path.join(self.tmp, "w__S3", "resume.json")))["cap"], 0.5)

    def test_resume_after_a_crash_in_the_first_segment_counts_on(self):
        # nothing finished, so nothing is kept: the try still died half-way and its t0 carries over (H3)
        self.usd, self.fail_at = 0.5, 0
        with self.assertRaises(api.BudgetExceeded):
            self.run_long(max_usd_video=1.0)
        t0 = self.budget()["t0"]
        self.fail_at = None
        R, _ = self.run_long(max_usd_video=1.0, resume=True)
        self.assertEqual(self.budget()["t0"], t0)
        self.assertEqual(R["budget"]["spent"], 2.5)                              # S1 (failed), then S1-S4

    def test_same_share_with_two_workers_and_a_ceiling(self):
        self.run_long(max_usd_video=2.0, segment_workers=2)
        self.assertEqual(sorted(u for _, u in self.calls), [0.5] * 4)
        self.calls.clear()
        self.run_long("c", max_usd_video=2.0, max_usd=0.3)
        self.assertEqual([u for _, u in self.calls], [0.3] * 4)

    def test_money_a_segment_leaves_is_not_passed_on(self):
        self.usd = 0.0
        self.run_long(max_usd_video=2.0)
        self.assertEqual([u for _, u in self.calls], [0.5] * 4)

    def test_over_the_cap_shows_in_budget(self):
        self.usd = 0.5
        R, st = self.run_long(max_usd_video=1.0)                               # 4 x 0.5 = $2 of $1
        self.assertEqual(R["budget"], dict(cap=1.0, spent=2.0, over=1.0, billed_no_result=0,
                                           parts=dict(first_sam=0.4, later_sam=1.4, spark=0.2)))
        self.assertEqual(st["budget"], R["budget"])
        self.assertTrue(any("WARNING: budget: spent $2.00 of the $1.00 video cap" in l for l in st["log"]))

    def test_under_the_cap_and_nothing_left_out_has_no_budget_key(self):
        R, _ = self.run_long(max_usd_video=2.0)
        self.assertNotIn("budget", R)

    def test_capped_segments_are_named_in_the_warning(self):
        self.capped = {750: [dict(stage="first_pass", msg="first pass: x not sent", item="d0")]}
        R, st = self.run_long(max_usd_video=2.0)
        self.assertEqual(R["capped"][0]["segment"], "S2")
        self.assertIn("budget", R)
        self.assertTrue(any("stages left out in S2" in l for l in st["log"]))

    def test_offline_writes_no_budget(self):
        self.usd = 0.5
        R, _ = self.run_long(max_usd_video=1.0, offline=True)
        self.assertNotIn("budget", R)

    def test_a_new_start_of_the_same_id_does_not_inherit_the_old_spend(self):
        self.usd = 0.5
        self.run_long(max_usd_video=1.0)
        R, _ = self.run_long(max_usd_video=1.0)
        self.assertEqual(R["budget"]["spent"], 2.0)

    def test_resume_after_a_crash_counts_on(self):
        self.usd = 0.5
        self.fail_at = 1500
        with self.assertRaises(api.BudgetExceeded) as e:
            self.run_long(max_usd_video=1.0)
        self.assertIn("FISH_BUDGET reached at S3: raise it, then the same command with --resume", str(e.exception))
        t0 = self.budget()["t0"]
        self.fail_at = None
        R, _ = self.run_long(max_usd_video=1.0, resume=True)
        self.assertEqual(self.budget()["t0"], t0)
        self.assertEqual(R["budget"]["spent"], 2.5)                              # S1, S2, S3 (failed), S3, S4

    def test_resume_after_a_finished_run_starts_a_new_budget(self):
        self.usd = 0.5
        self.run_long(max_usd_video=1.0)
        t0 = self.budget()["t0"]
        R, _ = self.run_long(max_usd_video=1.0, resume=True, prompts=["crab"])   # batch: other options, always --resume
        self.assertGreater(self.budget()["t0"], t0)
        self.assertEqual(R["budget"]["spent"], 2.0)

    def test_resume_where_every_segment_runs_again_starts_a_new_budget(self):
        self.usd = 0.5
        self.fail_at = 1500
        with self.assertRaises(api.BudgetExceeded):
            self.run_long(max_usd_video=1.0)
        t0 = self.budget()["t0"]
        self.fail_at = None
        R, _ = self.run_long(max_usd_video=1.0, resume=True, prompts=["crab"])
        self.assertGreater(self.budget()["t0"], t0)
        self.assertEqual(R["budget"]["spent"], 2.0)

    def test_resume_keeps_a_cut_segment_at_the_same_cap_and_reruns_it_at_a_higher_one(self):
        self.capped = {750: [dict(stage="recover", msg="skipped second look")]}
        self.run_long(max_usd_video=1.0)
        self.calls.clear()
        self.run_long(max_usd_video=1.0, resume=True)
        self.assertEqual(self.calls, [])
        self.run_long(max_usd_video=2.0, resume=True)
        self.assertEqual(self.calls, [(750, 0.5)])                               # only the cut segment
        self.calls.clear()
        self.run_long(max_usd_video=1.0, resume=True)                            # lower again: kept
        self.assertEqual(self.calls, [])

    def test_kept_segments_do_not_change_the_others_share(self):
        self.fail_at = 1500
        with self.assertRaises(api.BudgetExceeded):
            self.run_long(max_usd_video=2.0)
        self.fail_at, self.calls[:] = None, []
        self.run_long(max_usd_video=2.0, resume=True)
        self.assertEqual(self.calls, [(1500, 0.25), (2250, 0.5)])                # S3 spent $0.25 before it died

    def test_a_segment_fish_budget_cut_runs_again_whatever_the_cap(self):
        self.capped = {750: [dict(stage="motion", msg="motion look skipped: BudgetExceeded", reason="fish")]}
        self.run_long(max_usd_video=1.0)
        self.capped, self.calls[:] = {}, []
        self.run_long(max_usd_video=1.0, resume=True)
        self.assertEqual(self.calls, [(750, 0.25)])

    def test_resume_json_holds_fingerprint_and_cap_and_the_old_form_still_reads(self):
        self.run_long(max_usd_video=1.0)
        rp = os.path.join(self.tmp, "v__S1", "resume.json")
        j = json.load(open(rp))
        self.assertEqual(set(j), {"fp", "cap"})
        self.assertEqual(j["cap"], 0.25)
        json.dump(j["fp"], open(rp, "w"))                                        # as written before D-NIGHT3
        self.calls.clear()
        self.run_long(max_usd_video=1.0, resume=True)
        self.assertEqual(self.calls, [])

    def test_fish_budget_warning_before_the_start_is_only_a_warning(self):
        with mock.patch.dict(os.environ, {"FISH_BUDGET": "0.1"}):
            R, st = self.run_long(max_usd_video=1.0, offline=False)
        self.assertTrue(any("WARNING: FISH_BUDGET has" in l for l in st["log"]))
        self.assertEqual(len(self.calls), 4)                                     # the fake pipeline pays nothing real


class SkipEmptyDefault(unittest.TestCase):
    """--skip-empty with no --max-usd-video: the default $4 an hour paid out as equal shares (re-sends too)."""
    N = 18000

    def setUp(self):
        from fishcount import screen
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.led = os.path.join(self.tmp, "ledger.jsonl")
        self.cuts, self.calls, self.results, self.usd = {}, [], {}, 0.1

        def cut(clip, dst, start, n):
            self.cuts[dst] = (start, n)
            open(dst, "w").close()

        def run_pipeline(sp, srid, **kw):
            start, n = self.cuts[sp]
            self.calls.append((start, n, kw["max_usd"]))
            _ledger(self.led, srid, self.usd)
            d = os.path.join(self.tmp, srid)
            _fake_seg(d, n, self.results.get(start, []))
            json.dump(dict(live_calls=1, cached_calls=0, billed_usd=self.usd), open(os.path.join(d, "status.json"), "w"))

        for p in (mock.patch.object(pipeline, "RUNS", self.tmp), mock.patch.object(api, "LEDGER", self.led),
                  mock.patch.object(video, "ingest", lambda src, dst, **k: open(dst, "w").close()),
                  mock.patch.object(video, "info", lambda p: dict(n_frames=self.N, fps=5.0, width=100, height=100)),
                  mock.patch.object(video, "light_stats", lambda p: dict(median_l=100, mean_l=100)),
                  mock.patch.object(longvideo, "cut", cut),
                  mock.patch.object(longvideo, "_filler", lambda full, d, a, *k: os.path.join(d, f"skip{a}")),
                  mock.patch.object(longvideo, "_review_videos", lambda d, dirs: None),
                  mock.patch.object(pipeline, "run_pipeline", run_pipeline),
                  mock.patch.object(screen, "scan", lambda clip, fps, **k: self.wins)):
            p.start()
        self.addCleanup(mock.patch.stopall)

    def test_each_send_and_a_re_send_get_the_same_share(self):
        # 1 h at $4 = $4.00 over 4 planned sends = $1.00 each; the probe disagrees, so 300-700 is re-sent at $1.00 too
        self.wins = [dict(start=0, n=300, kind="head"), dict(start=700, n=50, kind="probe"),
                     dict(start=5000, n=300, kind="change", triggers=[5100]), dict(start=9000, n=300, kind="change", triggers=[9100])]
        self.results = {0: [(10, 10, 30, 30)], 700: []}
        R = longvideo.run_long("v.mp4", "s", skip_empty=True)
        self.assertEqual([(s, u) for s, _, u in self.calls], [(0, 1.0), (700, 1.0), (300, 1.0), (5000, 1.0), (9000, 1.0)])
        self.assertNotIn("budget", R)
        self.assertEqual(R["skip_empty"]["video_cap_usd"], 4.0)

    def test_a_ceiling_below_a_sends_first_pass_stops_before_paying(self):
        self.wins = [dict(start=0, n=300, kind="head"), dict(start=5000, n=300, kind="change", triggers=[5100])]
        with self.assertRaises(api.BudgetExceeded) as e:                        # F = 300 x $0.0002 = $0.06
            longvideo.run_long("v.mp4", "s", skip_empty=True, max_usd=0.05)
        self.assertIn("--max-usd 0.06", str(e.exception))
        self.assertEqual(self.calls, [])

    def test_a_re_send_over_the_ceiling_is_left_unsent(self):
        self.wins = [dict(start=0, n=300, kind="head"), dict(start=1000, n=50, kind="probe")]
        self.results = {0: [(10, 10, 30, 30)], 1000: []}                        # disagrees: 300-1000 (F $0.14) re-sent
        R = longvideo.run_long("v.mp4", "s", skip_empty=True, max_usd=0.1)
        self.assertEqual([s for s, _, _ in self.calls], [0, 1000])
        self.assertEqual(R["unsent"][0]["start_frame"], 300)

    def test_fish_budget_warning_before_the_first_send(self):
        self.wins = [dict(start=0, n=300, kind="head")]
        with mock.patch.dict(os.environ, {"FISH_BUDGET": "0.01"}), mock.patch.object(api, "spent", lambda: 0.0):
            longvideo.run_long("v.mp4", "s", skip_empty=True)
        st = json.load(open(os.path.join(self.tmp, "s", "status.json")))
        self.assertTrue(any("WARNING: FISH_BUDGET has" in l for l in st["log"]))
        self.assertEqual(len(self.calls), 1)

    def test_spending_past_the_default_cap_is_shown_not_stopped(self):
        self.usd = 1.5
        self.wins = [dict(start=0, n=300, kind="head"), dict(start=5000, n=300, kind="change", triggers=[5100]),
                     dict(start=9000, n=300, kind="change", triggers=[9100])]
        R = longvideo.run_long("v.mp4", "s", skip_empty=True)
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(R["budget"]["spent"], 4.5)
        self.assertEqual(R["unsent"], [])


class IdsAndBatch(unittest.TestCase):
    def test_cli_refuses_an_id_naming_a_segment(self):
        p = subprocess.run([sys.executable, os.path.join(ROOT, "fishcount", "pipeline.py"), "missing.mp4", "--id", "x__S3"],
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(p.returncode, 2, p.stderr)
        self.assertIn("__S<n>", p.stderr)

    def test_batch_fails_only_that_video(self):
        states = {}
        with tempfile.TemporaryDirectory() as out, mock.patch.object(batch, "write_tables", lambda *a, **k: []), \
                mock.patch.object(batch, "run_one", lambda *a: (True, 1.0, 0)) as ro:
            batch.run_all(out, ["/a/x__S3.mp4"], ["x__S3"], [], states)
        self.assertEqual(states["x__S3"]["status"], "error")
        self.assertIn("__S<n>", states["x__S3"]["error"])

    def test_ledger_by_run_adds_probes(self):
        with tempfile.TemporaryDirectory() as tmp:
            led = os.path.join(tmp, "l.jsonl")
            with open(led, "w") as f:
                for rid, usd in (("v__S1", 0.5), ("v__P1", 0.25), ("v", 0.125), ("vv__P10", 9.0)):
                    f.write(json.dumps(dict(t=1, kind="sam", usd=usd, note="", run=rid)) + "\n")
            self.assertEqual(batch.ledger_by_run(led), {"v": 0.875, "vv": 9.0})

    def test_old_stamp_is_kept_a_stamp_with_other_defaults_is_not(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(pipeline, "RUNS", tmp):
            src = os.path.join(tmp, "v.mp4")
            open(src, "w").close()
            d = os.path.join(tmp, "v")
            os.makedirs(d)
            json.dump(dict(stage="done"), open(os.path.join(d, "status.json"), "w"))
            json.dump({}, open(os.path.join(d, "result.json"), "w"))
            new = batch.stamp(src, ["--discover"])
            json.dump(new, open(os.path.join(d, "batch.json"), "w"))
            self.assertTrue(batch.is_kept("v", src, ["--discover"]))
            old = {k: v for k, v in new.items() if k != "defaults"}
            json.dump(old, open(os.path.join(d, "batch.json"), "w"))
            self.assertTrue(batch.is_kept("v", src, ["--discover"]))             # written before D-NIGHT3
            json.dump(dict(new, defaults=dict(new["defaults"], cap_per_hour=1)), open(os.path.join(d, "batch.json"), "w"))
            self.assertFalse(batch.is_kept("v", src, ["--discover"]))

    def test_capped_column_names_the_segments(self):
        self.assertEqual(batch.COLUMNS[-1], "capped")
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(pipeline, "RUNS", tmp):
            d = os.path.join(tmp, "v")
            os.makedirs(d)
            json.dump(dict(stage="done"), open(os.path.join(d, "status.json"), "w"))
            json.dump(dict(video=dict(n_frames=10, fps=5), capped=[dict(segment="S2"), dict(segment="S2"), dict(segment="S5")]),
                      open(os.path.join(d, "result.json"), "w"))
            sys.path.insert(0, os.path.join(ROOT, "web"))
            import server
            with mock.patch.object(server, "effective", lambda rid: None):
                r, _ = batch.row("v.mp4", "v", dict(status="done"), {})
        self.assertEqual(r["capped"], "S2; S5")

    def test_capped_column_names_what_skip_empty_left_unsent(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(pipeline, "RUNS", tmp):
            d = os.path.join(tmp, "v")
            os.makedirs(d)
            json.dump(dict(stage="done"), open(os.path.join(d, "status.json"), "w"))
            json.dump(dict(video=dict(n_frames=10, fps=5), capped=[dict(segment="S2")],
                           unsent=[dict(start_frame=600, end_frame=18000, start_s=120.0, end_s=3600.0)]),
                      open(os.path.join(d, "result.json"), "w"))
            sys.path.insert(0, os.path.join(ROOT, "web"))
            import server
            with mock.patch.object(server, "effective", lambda rid: None):
                r, _ = batch.row("v.mp4", "v", dict(status="done"), {})
        self.assertEqual(r["capped"], "S2; unsent 120.0-3600.0 s")

    def test_cli_short_video_cap_below_its_first_pass_stops_before_any_call(self):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        rid = f"test_shortcap_{os.getpid()}"
        run = os.path.join(ROOT, "runs", rid)
        self.addCleanup(shutil.rmtree, run, True)
        led = os.path.join(d, "ledger.jsonl")       # a bad key: should the check fail, nothing could be billed
        env = dict(os.environ, FISH_CACHE_DIR=d, FISH_LEDGER=led, META_API_KEY="invalid-test-key")
        p = subprocess.run([sys.executable, os.path.join(ROOT, "fishcount", "pipeline.py"), CLIP, "--id", rid,
                            "--max-usd", "0.005"], capture_output=True, text=True, env=env, timeout=300)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("0.02 or more", p.stderr)                                  # F = 60 frames x $0.0002 = $0.012
        self.assertFalse(os.path.exists(led) and open(led).read().strip())
        self.assertIn("BudgetExceeded", json.load(open(os.path.join(run, "provenance.json")))["runs"][-1]["error"])


class ProbeWindowDefault(unittest.TestCase):
    """K2: long videos probe discovered words by default (--no-probe-window turns it off); short ones do not.
    The option the run really used is in provenance.json "effective"."""

    def effective(self, *flags):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        rid = f"test_k2_{os.getpid()}_{len(flags)}_{'_'.join(f.strip('-') for f in flags)}"
        run = os.path.join(ROOT, "runs", rid)
        self.addCleanup(shutil.rmtree, run, True)
        env = dict(os.environ, FISH_CACHE_DIR=d, FISH_LEDGER=os.path.join(d, "ledger.jsonl"))
        subprocess.run([sys.executable, os.path.join(ROOT, "fishcount", "pipeline.py"), CLIP, "--id", rid, "--offline",
                        "--discover", *flags], capture_output=True, text=True, env=env, timeout=300)
        return json.load(open(os.path.join(run, "provenance.json")))["runs"][-1]["effective"]

    def test_long_path_on_by_default_off_with_the_flag_short_path_off(self):
        self.assertEqual(self.effective("--segment", "6")["probe_window"], pipeline.PROBE_WINDOW)
        self.assertIsNone(self.effective("--segment", "6", "--no-probe-window")["probe_window"])
        self.assertIsNone(self.effective()["probe_window"])
        self.assertEqual(self.effective()["max_usd"], 1.0)

    def test_offline_probe_miss_says_what_to_do(self):
        class Run:
            status = {"billed_usd": 0.0}
            def path(self, *p): return os.path.join("/r", *p)
        def counted(run, fn, *a, **k):
            raise FileNotFoundError("not cached: SAM 'crab' on probe")
        with mock.patch.object(pipeline, "_counted", counted), mock.patch.object(video, "segment", lambda *a, **k: None):
            with self.assertRaises(FileNotFoundError) as e:
                pipeline._probe(Run(), "/r/clip.mp4", "crab", [(0, 51)], True)
        self.assertIn("--no-probe-window", str(e.exception))


class CappedOnce(unittest.TestCase):
    def test_the_crowd_peak_second_pass_does_not_list_a_skip_twice(self):
        class Run:
            def stage(self, *a): pass
        r = Run()
        pipeline._capped(r, "first_pass", "first pass: x not sent", item="d0")
        pipeline._capped(r, "first_pass", "first pass: x not sent", item="d0")
        self.assertEqual(len(r.capped), 1)

    def test_a_fish_budget_stop_is_marked(self):
        class Run:
            def stage(self, *a): pass
        r = Run()
        pipeline._skip_stage(r, "motion", "motion look skipped", api.BudgetExceeded("set FISH_BUDGET"))
        self.assertEqual(r.capped, [dict(stage="motion", msg="motion look skipped", reason="fish")])


if __name__ == "__main__":
    unittest.main()
