"""Working videos are removed once a run no longer needs them (pipeline.drop_temp, longvideo segment cuts): the
reversed clip, tiles, probe / refill / peak / box cuts of a run, and a long video's segN.mp4 / S<k>.mp4 / P<k>.mp4
cuts (each segment folder keeps its own clip.mp4). The review screen's files (clip.mp4, clip_original.mp4,
annotated.mp4, jpg, json) stay, results are unchanged, FISH_KEEP_TEMP=1 keeps everything.
No network, no spend. Run: python3 -m unittest discover -s tests -v"""
import json, os, shutil, sys, tempfile, unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fishcount import _pylib  # noqa: F401
from fishcount import longvideo, pipeline
import test_longvideo, test_resume
from test_core import replay_or_skip

KEPT = {"clip.mp4", "clip_original.mp4", "annotated.mp4", "result.json", "status.json", "evidence_fish.jpg",
        "motion_sheet.jpg", "discover.json", "resume.json"}
TEMP = {"clip_rev.mp4", "tile_r1c2.mp4", "tile_d0_rev.mp4", "tile_crowd-fish.mp4", "tile_peak+40-fish.mp4",
        "seg_fish+150.mp4", "probe_fish+0.mp4", "peak+40.mp4", "box_m1+12.mp4"}


def _touch(d, names):
    os.makedirs(os.path.join(d, "thumbs"), exist_ok=True)
    open(os.path.join(d, "thumbs", "fish.jpg"), "w").close()
    for n in names:
        with open(os.path.join(d, n), "w") as f:
            f.write(n)


class DropTemp(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d, True)
        _touch(self.d, KEPT | TEMP)

    def test_working_videos_go_the_review_files_stay(self):
        gone = pipeline.drop_temp(self.d)
        self.assertEqual(set(os.listdir(self.d)), KEPT | {"thumbs"})
        self.assertEqual(set(gone), TEMP)
        self.assertEqual(os.listdir(os.path.join(self.d, "thumbs")), ["fish.jpg"])

    def test_keep_temp_keeps_everything(self):
        with mock.patch.dict(os.environ, {"FISH_KEEP_TEMP": "1"}):
            self.assertEqual(pipeline.drop_temp(self.d), [])
        self.assertEqual(set(os.listdir(self.d)), KEPT | TEMP | {"thumbs"})

    def test_a_hard_linked_copy_elsewhere_survives(self):
        other = os.path.join(self.d, "other_rev.mp4.keep")
        os.link(os.path.join(self.d, "clip_rev.mp4"), other)
        pipeline.drop_temp(self.d)
        self.assertEqual(open(other).read(), "clip_rev.mp4")


class LongVideoCuts(unittest.TestCase):
    """The fake 4-segment long video of test_resume (cuts write their own bytes)."""
    setUp = test_resume.Resume.setUp
    run_long = test_resume.Resume.run_long
    N = test_resume.Resume.N

    def seg_cuts(self, rid):
        return sorted(f for f in os.listdir(os.path.join(self.tmp, rid)) if f.startswith("seg") and f.endswith(".mp4"))

    def test_segment_cuts_are_removed_and_the_result_is_the_same(self):
        with mock.patch.dict(os.environ, {"FISH_KEEP_TEMP": "1"}):
            R0, _ = self.run_long("keep")
        self.assertEqual(self.seg_cuts("keep"), ["seg1.mp4", "seg2.mp4", "seg3.mp4", "seg4.mp4"])
        R, _ = self.run_long("v")
        self.assertEqual(self.seg_cuts("v"), [])
        strip = lambda R: json.loads(json.dumps({k: v for k, v in R.items() if k != "id"}).replace("keep__S", "v__S"))
        self.assertEqual(strip(R), strip(R0))

    def test_resume_still_keeps_every_finished_segment(self):
        self.run_long()
        self.started.clear()
        R, st = self.run_long(resume=True)          # the cut is made again to compare its bytes
        self.assertEqual(self.started, [])
        self.assertEqual(sum("kept from the earlier run" in x for x in st["log"]), 4)
        self.assertEqual(self.seg_cuts("v"), [])

    def test_two_workers_remove_them_too(self):
        self.run_long(segment_workers=2)
        self.assertEqual(self.seg_cuts("v"), [])

    def test_the_cut_of_a_failed_segment_stays(self):
        self.fail_at = 1500
        with self.assertRaises(Exception):
            self.run_long()
        self.assertEqual(self.seg_cuts("v"), ["seg3.mp4"])


class SkipEmptyCuts(unittest.TestCase):
    """The fake skip-empty long video of test_longvideo.SkipEmptyRun."""
    N = test_longvideo.SkipEmptyRun.N
    setUp = test_longvideo.SkipEmptyRun.setUp
    tearDown = test_longvideo.SkipEmptyRun.tearDown

    def test_sent_and_probe_cuts_are_removed(self):
        self.wins = [dict(start=0, n=300, kind="head"), dict(start=700, n=50, kind="probe")]
        self.results = {0: [(10, 10, 30, 30)], 700: []}
        longvideo.run_long("v.mp4", "r5", skip_empty=True, max_usd_video=10)
        left = [f for f in os.listdir(os.path.join(self.tmp, "r5")) if f.endswith(".mp4")]
        self.assertEqual(left, [])          # S1, P1, S2 cut and removed (full_5fps was already removed)


class RealReplay(unittest.TestCase):
    """The saved demo clip replayed from cache/: only the review screen's videos are left in the run folder."""
    CLIP = os.path.join(ROOT, "tests", "data", "nautilus_s004_0_12.mp4")

    def setUp(self):
        self._runs, self.tmp = pipeline.RUNS, tempfile.mkdtemp()
        pipeline.RUNS = self.tmp
        self.addCleanup(setattr, pipeline, "RUNS", self._runs)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_only_review_videos_are_left_and_the_counts_are_the_same(self):
        if not os.path.exists(self.CLIP):
            self.skipTest("clip not present (videos are not in git; see README Data)")
        run = lambda rid: replay_or_skip(self, lambda: pipeline.run_pipeline(
            self.CLIP, rid, True, False, True, True, ["fish"], 0.0, True))
        with mock.patch.dict(os.environ, {"FISH_KEEP_TEMP": "1"}):
            r0 = run("keep")
        r = run("swept")
        left = {f for f in os.listdir(os.path.join(self.tmp, "swept")) if f.endswith(".mp4")}
        self.assertTrue(left <= {"clip.mp4", "clip_original.mp4", "annotated.mp4"}, left)
        self.assertIn("annotated.mp4", left)
        strip = lambda r: json.dumps({k: v for k, v in r.items() if k != "id"}, sort_keys=True)
        self.assertEqual(strip(r), strip(r0))


if __name__ == "__main__":
    unittest.main()
