"""Site memory (opt-in): records, ranking, review hook, SAM ladder step and the off-by-default guarantee.
No network, no key, $0 (SAM is faked or replayed from cache/)."""
import json, os, shutil, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "web"))
from fishcount import _pylib  # noqa: F401
from fishcount import api, pipeline, sitememory

SAVED = os.path.join(ROOT, "demo", "runs", "mg2_s004", "result.json")
BOX = "<{f}f>0<|box;x1=10;y1=20;x2=29;y2=39;c=0.9|>\n"


class Isolated(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.orig, sitememory.DIR = sitememory.DIR, os.path.join(self.tmp, "mem")

    def tearDown(self):
        sitememory.DIR = self.orig
        shutil.rmtree(self.tmp)


class Records(Isolated):
    def test_site_names_are_file_safe(self):
        self.assertEqual(sitememory.norm_site(" Nautilus-Bait "), "nautilus-bait")
        for bad in ("", "../x", "a/b", "-x", "x" * 60):
            with self.assertRaises(ValueError):
                sitememory.norm_site(bad)

    def test_label_to_noun(self):
        self.assertEqual(sitememory.noun_for("red crab"), "crab")
        self.assertEqual(sitememory.noun_for("hagfish"), "hagfish")
        for no in ("fish (unidentified)", "", None, "../etc", "x=1"):
            self.assertIsNone(sitememory.noun_for(no))

    def test_rename_undo_and_replacement(self):
        self.assertEqual(sitememory.record("s", "r1", "p0:1", "red crab", alt="eel"), "crab")
        self.assertEqual(sitememory.plan("s")[0]["words"], ["crab", "eel"])
        sitememory.record("s", "r1", "p0:1", "hagfish")                      # a new label replaces the old record
        self.assertEqual([e["noun"] for e in sitememory.plan("s")], ["hagfish"])
        sitememory.record("s", "r1", "p0:1", "fish (unidentified)")          # teaches nothing: record dropped
        self.assertEqual(sitememory.plan("s"), [])
        sitememory.record("s", "r1", "p0:2", "crab")
        sitememory.forget_track("s", "r1", "p0:2")
        self.assertEqual(sitememory.plan("s"), [])

    def test_ranking_counts_videos_not_tracks_and_is_capped(self):
        for i in range(10):
            sitememory.record("s", "r1", f"p0:{i}", "worm")                  # one video, ten tracks
        sitememory.record("s", "r2", "p0:0", "crab")
        sitememory.record("s", "r3", "p0:0", "crab")
        sitememory.record("s", "r3", "p0:1", "snail")
        sitememory.record("s", "r4", "p0:1", "urchin")
        self.assertEqual([e["noun"] for e in sitememory.plan("s")], ["crab", "urchin", "snail"])   # cap 3; ties: most recent
        self.assertEqual(sitememory.plan("s", skip_words={"crab"})[0]["noun"], "urchin")
        self.assertEqual(len(sitememory.plan("s", max_entries=99)), 4)

    def test_segment_run_and_merged_run_are_one_video(self):
        sitememory.record("s", "long__S2", "k0:3", "crab")
        sitememory.record("s", "long", "S2:k0:3", "crab")
        self.assertEqual(len(sitememory.load("s")["records"]), 1)

    def test_source_word_is_the_word_that_tracked_it(self):
        res = dict(prompts=[["fish", "fish"]], tracks={"d2rev:1": dict(label="eel", source="d2rev"),
                   "p0:1": dict(label="fish", source="p0"), "m4:1": dict(label="shrimp", source="m4"),
                   "S1:d0:1": dict(label="eel", source="S1:d0")})
        self.assertEqual(sitememory.source_word(res, "d2rev:1"), "eel")
        self.assertEqual(sitememory.source_word(res, "S1:d0:1"), "eel")
        self.assertIsNone(sitememory.source_word(res, "p0:1"))               # a request word
        self.assertIsNone(sitememory.source_word(res, "m4:1"))               # motion box: no word tracked it


class ReviewHook(Isolated):
    def setUp(self):
        super().setUp()
        import server
        self.server = server
        self.runs = os.path.join(self.tmp, "runs")
        for rid, site in (("withsite", "demo-site"), ("nosite", None)):
            os.makedirs(os.path.join(self.runs, rid))
            res = json.load(open(SAVED))
            if site:
                res["site"] = dict(name=site, entries=[])
            json.dump(res, open(os.path.join(self.runs, rid, "result.json"), "w"))
        self.orig_runs, server.RUNS = server.RUNS, self.runs
        res = json.load(open(SAVED))
        self.track = next(t for t, v in res["verdicts"].items() if pipeline.needs_review(v) and (res["auto_labels"].get(t) or "").endswith("(unidentified)"))
        self.auto = res["auto_labels"][self.track]

    def tearDown(self):
        self.server.RUNS = self.orig_runs
        super().tearDown()

    def test_rename_in_a_site_run_is_remembered_and_undo_forgets(self):
        self.server.save_review("withsite", {self.track: "banded shrimp"})
        self.assertEqual(sitememory.plan("demo-site")[0]["noun"], "shrimp")
        self.server.save_review("withsite", {self.track: "__undo__"})
        self.assertEqual(sitememory.plan("demo-site"), [])
        self.server.save_review("withsite", {self.track: "hagfish"})
        self.server.save_review("withsite", {self.track: None})              # "Not an animal" teaches nothing
        self.assertEqual(sitememory.plan("demo-site"), [])

    def test_only_a_correction_is_remembered(self):
        self.server.save_review("withsite", {self.track: self.auto})         # same as the automatic label
        self.assertEqual(sitememory.plan("demo-site"), [])

    def test_run_without_site_never_writes(self):
        self.server.save_review("nosite", {self.track: "hagfish"})
        self.assertFalse(os.path.exists(sitememory.DIR))

    def test_a_memory_failure_never_loses_the_review(self):
        orig, sitememory.record = sitememory.record, lambda *a, **k: 1 / 0
        try:
            e = self.server.save_review("withsite", {self.track: "hagfish"})
        finally:
            sitememory.record = orig
        self.assertEqual(e["review"], {self.track: "hagfish"})

    def test_queue_item_says_it_was_remembered(self):
        e = self.server.save_review("withsite", {self.track: "hagfish"})
        self.assertEqual(next(q for q in e["queue"] if q["track"] == self.track)["remembered"], "hagfish")


class FakeRun:
    def __init__(self):
        self.status = dict(billed_usd=0.0, live_calls=0, cached_calls=0)
        import threading
        self._lock = threading.Lock()
        self.log = []

    def stage(self, name, msg=None):
        self.log.append(msg)


class SiteLook(Isolated):
    INF = dict(n_frames=60)

    def setUp(self):
        super().setUp()
        self.orig_sam = api.sam_video
        self.asked = []

        def fake(path, word, n, offline=False):
            self.asked.append(word)
            if word == "mudskipper" and offline:
                raise FileNotFoundError("not cached")
            return "".join(BOX.format(f=f) for f in range(8)) if word == "eel" else ""
        api.sam_video = fake

    def tearDown(self):
        api.sam_video = self.orig_sam
        super().tearDown()

    def test_ladder_falls_back_to_the_word_that_tracked_before(self):
        sitememory.record("s", "r1", "d2rev:1", "hagfish", alt="eel")       # name 0 frames last time, "eel" 24
        entries, results = pipeline.site_look(FakeRun(), "clip.mp4", self.INF, "s", {"fish"}, 1.0, False)
        self.assertEqual(self.asked, ["hagfish", "eel"])
        self.assertEqual((entries[0]["word"], entries[0]["frames"], entries[0]["source"]), ("eel", 8, "k0"))
        self.assertEqual([t["frames"] for t in entries[0]["tried"]], [0, 8])
        self.assertEqual([r[0] for r in results], ["k0"])
        self.assertEqual(results[0][1], "eel")

    def test_words_the_run_already_tracked_are_skipped(self):
        sitememory.record("s", "r1", "t", "red crab")
        entries, results = pipeline.site_look(FakeRun(), "clip.mp4", self.INF, "s", {"fish", "crab"}, 1.0, False)
        self.assertEqual((entries, results, self.asked), ([], [], []))

    def test_cap_drops_least_confirmed_first(self):
        for r in ("r1", "r2"):
            sitememory.record("s", r, "t", "crab")
        sitememory.record("s", "r3", "t", "snail")
        per = 60 * api.SAM_PER_FRAME            # 60 frames = $0.012 a word
        entries, _ = pipeline.site_look(FakeRun(), "clip.mp4", self.INF, "s", set(), per * 1.5, False)
        self.assertEqual([e["noun"] for e in entries], ["crab"])

    def test_uncached_word_in_free_replay_is_recorded_not_raised(self):
        sitememory.record("s", "r1", "t", "mudskipper")
        entries, results = pipeline.site_look(FakeRun(), "clip.mp4", self.INF, "s", set(), 0.0, True)
        self.assertEqual(results, [])
        self.assertIn("FileNotFoundError", entries[0]["error"])
        self.assertIsNone(entries[0]["word"])


class OffByDefault(Isolated):
    CLIP = os.path.join(ROOT, "tests", "data", "nautilus_s004_0_12.mp4")   # CC BY 4.0, see tests/data/README.md

    def setUp(self):    # runs go to a temp folder, not the repo's runs/ (they would show up in the review screen)
        super().setUp()
        import tempfile
        from fishcount import pipeline
        self._runs, self._tmp = pipeline.RUNS, tempfile.mkdtemp()
        pipeline.RUNS = self._tmp

    def tearDown(self):
        import shutil
        from fishcount import pipeline
        pipeline.RUNS = self._runs
        shutil.rmtree(self._tmp, ignore_errors=True)
        super().tearDown()

    def replay(self, rid, **kw):
        from test_core import replay_or_skip
        return replay_or_skip(self, lambda: pipeline.run_pipeline(self.CLIP, rid, True, False, True, True, ["fish"], 0.0, True, **kw))   # current defaults, as the saved demo run

    def test_site_run_with_nothing_usable_gives_the_saved_counts(self):
        if not os.path.exists(self.CLIP):
            self.skipTest("clip not present (videos are not in git; see README Data)")
        saved = json.load(open(SAVED))
        want = {k: (v["maxn"], v["maxn_frame"], v["first_frame"]) for k, v in saved["metrics"].items()}
        sitememory.record("s", "r1", "t", "uncached-word")      # no saved SAM answer: a free replay cannot try it
        off = self.replay("test_site_off")
        on = self.replay("test_site_on", site="s")
        for r in (off, on):
            self.assertEqual({k: (v["maxn"], v["maxn_frame"], v["first_frame"]) for k, v in r["metrics"].items()}, want)
        self.assertNotIn("site", off)                           # no key at all without --site
        self.assertEqual(on["site"]["name"], "s")
        self.assertEqual(on["site"]["entries"][0]["frames"], 0)
        self.assertIn("error", on["site"]["entries"][0])


if __name__ == "__main__":
    unittest.main()
