"""D-SPLIT: one SAM mask over two animals apart (fishcount/split.py). Backed by another pass -> split into one box
per blob (child track "<track>~2"); not backed -> the box only gets "blobs", which the review screen's upper end
counts. No network, no spend.
Run: python3 -m unittest discover -s tests -v"""
import glob, json, os, shutil, subprocess, sys, tempfile, unittest
from unittest import mock

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "web"))
from fishcount import _pylib  # noqa: F401,E402
from fishcount import longvideo, maxn_export, pipeline, split, tracks  # noqa: E402

W, H = 200, 100
BOX = [10, 10, 110, 50]          # one box over two fish: left x 10-45, right x 80-110


def dump(obj, path):
    with open(path, "w") as f:
        json.dump(obj, f)


def load(path):
    with open(path) as f:
        return json.load(f)


def two_fish():
    m = np.zeros((40, 100), bool)
    m[:, 0:35] = True
    m[:, 70:100] = True
    return m


ONE = [10, 10, 45, 50]           # the left fish alone: the track's box in frames 4 and 6


def scene(support=True, other=None, around=ONE):
    """Frames 4-6 of track p0:1 (counted fish); in frame 5 its mask is two fish. support: a second pass (p0+8 id 0)
    boxed the right fish alone. other: a second counted track p0:2 boxing the right fish (with its mask or without).
    around: the track's box in frames 4 and 6 (ONE: one fish there; BOX: one long fish the frame-5 gap cuts in two)."""
    k = lambda f: dict(track="p0:1", src="p0", label="fish", box=list(BOX if f == 5 else around), conf=0.9)
    frames = {f: [k(f)] for f in (4, 5, 6)}
    trk = {"p0:1": dict(label="fish", source="p0", frames=[4, 5, 6])}
    dec = {"p0": {5: [(BOX, two_fish(), 10, 10)]}}
    sources = [("p0", "fish", {f: [dict(box=list(BOX), id=1)] for f in (4, 5, 6)})]
    if support:
        sources.append(("p0+8", "fish", {5: [dict(box=[80, 10, 110, 50], id=0)]}))
    if other:
        frames[5].append(dict(track="p0:2", src="p0", label="fish", box=[80, 10, 110, 50], conf=0.9))
        trk["p0:2"] = dict(label="fish", source="p0", frames=[5])
        if other == "masked":
            dec["p0"][5].append(([80, 10, 110, 50], np.ones((40, 30), bool), 80, 10))
    labels = {"p0:1": "fish"}
    verdicts = {"p0:1": dict(name="T1", is_target=True, species="unknown", confidence=0.6, reason="a fish")}
    return frames, trk, labels, verdicts, dec, sources


class Blobs(unittest.TestCase):
    def test_two_apart_one_gap_one_small_piece(self):
        self.assertEqual(len(split.blobs(two_fish(), W, H)), 2)
        m = np.zeros((40, 100), bool)
        m[:, 0:40], m[:, 44:100] = True, True          # 4 px gap: closed by the 5 px dilation, one animal
        self.assertEqual(split.blobs(m, W, H), [])
        m = np.zeros((40, 100), bool)
        m[:, 0:80], m[0:10, 90:100] = True, True        # a piece under 25% of the largest: a fin, not an animal
        self.assertEqual(split.blobs(m, W, H), [])
        self.assertEqual(split.blobs(np.ones((40, 100), bool), W, H), [])


class FindApply(unittest.TestCase):
    def test_backed_blob_is_split_into_a_child_track(self):
        frames, trk, labels, verdicts, dec, sources = scene()
        found = split.find(frames, labels, trk, dec, sources, W, H)
        self.assertEqual(found, [dict(frame=5, track="p0:1", boxes=[[10, 10, 45, 50], [80, 10, 110, 50]], support=[["p0+8", 0]])])
        with tempfile.TemporaryDirectory() as th:
            for s in (".jpg", "_trio.jpg"):
                dump("x", os.path.join(th, f"T1{s}"))
            got = split.apply(frames, trk, labels, verdicts, found, thumbs=th)
            self.assertEqual(sorted(os.listdir(th)), ["T1.jpg", "T1_trio.jpg", "T1b.jpg", "T1b_trio.jpg"])
        self.assertEqual(got, [dict(frame=5, track="p0:1", into=["p0:1", "p0:1~2"], support=[["p0+8", 0]])])
        self.assertEqual([(k["track"], k["box"]) for k in frames[5]], [("p0:1", [10, 10, 45, 50]), ("p0:1~2", [80, 10, 110, 50])])
        self.assertEqual([len(frames[f]) for f in (4, 6)], [1, 1])
        self.assertEqual(trk["p0:1~2"], dict(label="fish", source="p0", frames=[5]))     # its own frames only
        self.assertEqual(trk["p0:1"]["frames"], [4, 5, 6])
        self.assertEqual(labels["p0:1~2"], "fish")
        v = verdicts["p0:1~2"]
        self.assertEqual((v["name"], v["split_from"], v["confidence"]), ("T1b", "p0:1", 0.6))
        self.assertIn("p0+8:0", v["split_reason"])
        m = tracks.metrics(frames, trk, 7, 5.0, labels)
        self.assertEqual(m["fish"]["maxn"], 2)
        self.assertEqual(split.family("p0:1~2"), "p0:1")

    def test_unbacked_blob_only_marks_the_box(self):
        frames, trk, labels, verdicts, dec, sources = scene(support=False)
        before = json.dumps([trk, labels, verdicts])
        found = split.find(frames, labels, trk, dec, sources, W, H)
        self.assertEqual(found[0]["support"], [])
        self.assertEqual(split.apply(frames, trk, labels, verdicts, found), [])
        self.assertEqual(frames[5], [dict(track="p0:1", src="p0", label="fish", box=BOX, conf=0.9, blobs=2)])
        self.assertNotIn("blobs", frames[4][0])
        self.assertEqual(json.dumps([trk, labels, verdicts]), before)      # count, queue, verdicts as they were
        self.assertEqual(tracks.metrics(frames, trk, 7, 5.0, labels)["fish"]["maxn"], 1)

    def test_halves_of_one_fish_are_only_marked(self):
        """A fish cut in two by something in front (11/23 review 2 (1)): a zoom/cell pass boxing one half is no reason
        to split, since each part is far shorter than the track's body elsewhere (here 35 and 30 px of 100)."""
        frames, trk, labels, verdicts, dec, sources = scene(around=BOX)
        found = split.find(frames, labels, trk, dec, sources, W, H)
        self.assertEqual([(h["frame"], h["support"]) for h in found], [(5, [])])
        self.assertEqual(split.apply(frames, trk, labels, verdicts, found), [])
        self.assertEqual(frames[5][0]["blobs"], 2)
        self.assertNotIn("p0:1~2", trk)

    def test_no_body_length_elsewhere_only_marks(self):
        frames, trk, labels, verdicts, dec, sources = scene()
        for f in (4, 6):
            del frames[f]
        self.assertEqual(split.find(frames, labels, trk, dec, sources, W, H)[0]["support"], [])

    def test_body_length_rule_at_the_line(self):
        """BODY of the track's median long side elsewhere: each part's long side is 40 px (its height), at least
        0.6 of 66 px, under 0.6 of 67."""
        for side, split_ in ((66, True), (67, False)):
            frames, trk, labels, verdicts, dec, sources = scene(around=[10, 10, 10 + side, 50])
            self.assertEqual(bool(split.find(frames, labels, trk, dec, sources, W, H)[0]["support"]), split_, side)
        self.assertEqual(split.BODY, 0.6)

    def test_body_leaves_out_the_frames_it_judges(self):
        """The body is the track's frames without a two-part box: frame 5's own box (100 px) is not in it, so with
        frame 4 alone (66 px) it splits; counted in, the median would be 83 and 40 px parts would be under 0.6."""
        frames, trk, labels, verdicts, dec, sources = scene(around=[10, 10, 76, 50])
        del frames[6]
        self.assertTrue(split.find(frames, labels, trk, dec, sources, W, H)[0]["support"])

    def test_the_shorter_part_decides(self):
        """Parts of 40 and 30 px (the right one 30 x 20): against a 60 px body the shorter is under 0.6 (36), so no
        split though the longer is over; against 50 px both are at least 30 and it splits."""
        for side, split_ in ((60, False), (50, True)):
            frames, trk, labels, verdicts, dec, sources = scene(around=[10, 10, 10 + side, 50])
            m = np.zeros((40, 100), bool)
            m[:, 0:35], m[0:20, 70:100] = True, True
            dec["p0"][5] = [(BOX, m, 10, 10)]
            sources[1] = ("p0+8", "fish", {5: [dict(box=[80, 10, 110, 30], id=0)]})
            h = split.find(frames, labels, trk, dec, sources, W, H)[0]
            self.assertEqual(h["boxes"], [[10, 10, 45, 50], [80, 10, 110, 30]])
            self.assertEqual(bool(h["support"]), split_, side)

    def test_a_detection_that_is_a_kept_box_is_no_support(self):
        frames, trk, labels, verdicts, dec, sources = scene(other="unmasked")
        found = split.find(frames, {**labels, "p0:2": "fish"}, trk, dec, sources, W, H)
        self.assertEqual([(h["track"], h["support"]) for h in found], [("p0:1", [])])

    def test_a_blob_another_counted_mask_covers_is_left_out(self):
        frames, trk, labels, verdicts, dec, sources = scene(other="masked")
        self.assertEqual(split.find(frames, {**labels, "p0:2": "fish"}, trk, dec, sources, W, H), [])

    def test_uncounted_box_is_not_looked_at(self):
        frames, trk, labels, verdicts, dec, sources = scene()
        self.assertEqual(split.find(frames, {"p0:1": None}, trk, dec, sources, W, H), [])

    def test_child_leaves_the_queue_with_its_parent(self):
        frames, trk, labels, verdicts, dec, sources = scene()
        split.apply(frames, trk, labels, verdicts, split.find(frames, labels, trk, dec, sources, W, H))
        self.assertEqual(sorted(pipeline.unqueue(trk, verdicts, labels, 0.5)), ["p0:1", "p0:1~2"])
        self.assertFalse(pipeline.needs_review(verdicts["p0:1~2"]))
        frames, trk, labels, verdicts, dec, sources = scene()
        split.apply(frames, trk, labels, verdicts, split.find(frames, labels, trk, dec, sources, W, H))
        self.assertEqual(pipeline.unqueue(trk, verdicts, labels, 0.7), [])          # 0.7: both stay queued
        self.assertTrue(pipeline.needs_review(verdicts["p0:1~2"]))

    def test_parent_and_child_are_not_asked_as_a_nested_pair(self):
        big, small = [10, 10, 110, 50], [20, 20, 40, 40]
        frames = {5: [dict(track="p0:1", box=big), dict(track="p0:1~2", box=small)]}
        trk = {"p0:1": dict(label="fish", source="p0", frames=[5]), "p0:1~2": dict(label="fish", source="p0", frames=[5])}
        dec = {"p0": {5: [(big, np.ones((40, 100), bool), 10, 10), (small, np.ones((20, 20), bool), 20, 20)]}}
        labels = {"p0:1": "fish", "p0:1~2": "fish"}
        self.assertEqual(pipeline.same_animal_pairs(None, "no-clip.mp4", frames, trk, labels, dec, True), [])
        frames[5][1]["track"] = "p0:2"              # two tracks: the same masks are a nested pair (asked, so no clip fails)
        trk["p0:2"], labels["p0:2"] = trk["p0:1~2"], "fish"
        with self.assertRaises(Exception):
            pipeline.same_animal_pairs(None, "no-clip.mp4", frames, trk, labels, dec, True)


def result_json(frames, trk, labels, verdicts):
    m = tracks.metrics(frames, trk, 7, 5.0, labels)
    return dict(id="r", source="c.mp4", video=dict(n_frames=7, fps=5.0, width=W, height=H), prompts=[["fish", "fish"]], jobs=[],
                tracks={t: dict(v, n=len(v["frames"]), first=min(v["frames"]), last=max(v["frames"]), frames=None) for t, v in trk.items()},
                verdicts=verdicts, auto_labels=labels, metrics=m, group_metrics=pipeline.group_metrics(m, 5.0),
                frames={str(f): ks for f, ks in frames.items()})


class Screen(unittest.TestCase):
    def run_dir(self, res):
        import server
        runs = self.enterContext(tempfile.TemporaryDirectory())
        os.makedirs(os.path.join(runs, "r"))
        dump(res, os.path.join(runs, "r", "result.json"))
        self.enterContext(mock.patch.object(server, "RUNS", runs))
        return server, runs

    def test_upper_end_counts_blobs_lower_end_stays(self):
        frames, trk, labels, verdicts, dec, sources = scene(support=False)
        split.apply(frames, trk, labels, verdicts, split.find(frames, labels, trk, dec, sources, W, H))
        verdicts["p0:1"]["confidence"] = 0.9            # not queued
        server, _ = self.run_dir(result_json(frames, trk, labels, verdicts))
        e = server.effective("r")
        self.assertEqual([e["metrics"]["fish"][k] for k in ("maxn", "maxn_confirmed", "maxn_upper")], [1, 1, 2])
        row = maxn_export.rows(e)[0]
        self.assertEqual((row[4], row[8], row[-1]), (1, 1, 2))

    def test_no_blobs_no_change(self):
        frames, trk, labels, verdicts, dec, sources = scene(support=False)
        verdicts["p0:1"]["confidence"] = 0.9
        server, _ = self.run_dir(result_json(frames, trk, labels, verdicts))
        e = server.effective("r")
        self.assertEqual([e["metrics"]["fish"][k] for k in ("maxn", "maxn_confirmed", "maxn_upper")], [1, 1, 1])

    def test_a_parents_review_carries_to_its_child(self):
        frames, trk, labels, verdicts, dec, sources = scene()
        split.apply(frames, trk, labels, verdicts, split.find(frames, labels, trk, dec, sources, W, H))
        server, runs = self.run_dir(result_json(frames, trk, labels, verdicts))
        e = server.save_review("r", {"p0:1": "rockfish"})
        self.assertEqual(load(os.path.join(runs, "r", "review.json")), {"p0:1": "rockfish", "p0:1~2": "rockfish"})
        self.assertEqual(e["metrics"]["rockfish"]["maxn"], 2)
        server.save_review("r", {"p0:1~2": None})       # the child alone: the parent stays
        self.assertEqual(load(os.path.join(runs, "r", "review.json")), {"p0:1": "rockfish", "p0:1~2": None})
        server.save_review("r", {"p0:1": "__undo__"})
        self.assertEqual(load(os.path.join(runs, "r", "review.json")), {"p0:1~2": None})

    def test_a_child_reviewed_itself_keeps_its_review(self):
        """11/23 review 2 (2): a later review of the parent (rename, removal, Undo) no longer overwrites a child the
        person reviewed on its own; a child still following its parent goes on following it."""
        frames, trk, labels, verdicts, dec, sources = scene()
        split.apply(frames, trk, labels, verdicts, split.find(frames, labels, trk, dec, sources, W, H))
        server, runs = self.run_dir(result_json(frames, trk, labels, verdicts))
        rv = lambda: load(os.path.join(runs, "r", "review.json"))
        server.save_review("r", {"p0:1~2": "kelp bass"})
        server.save_review("r", {"p0:1": "rockfish"})
        self.assertEqual(rv(), {"p0:1": "rockfish", "p0:1~2": "kelp bass"})
        for l in ("vermilion rockfish", None, "__undo__"):
            server.save_review("r", {"p0:1": l})
            self.assertEqual(rv()["p0:1~2"], "kelp bass", l)
        server.save_review("r", {"p0:1~2": "__undo__"})      # the child's own Undo: it follows its parent again
        server.save_review("r", {"p0:1": "rockfish"})
        self.assertEqual(rv(), {"p0:1": "rockfish", "p0:1~2": "rockfish"})
        server.save_review("r", {"p0:1": "blue rockfish", "p0:1~2": "kelp bass"})      # both in one save: each its own
        self.assertEqual(rv(), {"p0:1": "blue rockfish", "p0:1~2": "kelp bass"})


class StaticDemoBlobs(unittest.TestCase):
    """11/23 review 2 (4): demo/static_review.js counts "blobs" in the upper end as web/server.py effective() does.
    Every demo run with blobs 2 on the first box of every frame goes through test_static_review's server = JS
    comparison (every review step, both CSVs). The demo runs themselves have no blobs, so what they show is unchanged."""

    def setUp(self):
        sys.path.insert(0, os.path.join(ROOT, "tests"))
        import test_static_review as tsr
        if not (shutil.which("node") and tsr.RUNS):
            self.skipTest("node or demo runs missing")
        self.tsr, self.server = tsr, tsr.server
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())
        self.enterContext(mock.patch.object(tsr.server, "RUNS", self.tmp))

    def test_server_and_static_demo_agree_with_blobs(self):
        widened = 0
        for src in self.tsr.RUNS:
            self.assertFalse(any("blobs" in k for ks in load(os.path.join(src, "result.json"))["frames"].values() for k in ks), src)
            res = load(os.path.join(src, "result.json"))
            for ks in res["frames"].values():
                if ks:
                    ks[0]["blobs"] = 2
            d = os.path.join(self.enterContext(tempfile.TemporaryDirectory()), os.path.basename(src))
            shutil.copytree(src, d)
            dump(res, os.path.join(d, "result.json"))
            self.tsr.StaticReviewMatchesServer.run_one(self, d)
            e = self.server.effective(os.path.basename(src))
            widened += any(m["maxn_upper"] > m["maxn"] for m in e["metrics"].values())
        self.assertGreater(widened, 0)


class LongMerge(unittest.TestCase):
    def test_merge_keeps_blobs_and_child_tracks(self):
        d = sorted(glob.glob(os.path.join(ROOT, "demo", "runs", "cr11_s003")))
        if not d:
            self.skipTest("no demo run")
        res = load(os.path.join(d[0], "result.json"))
        f, ks = next((f, ks) for f, ks in res["frames"].items() if ks)
        t = ks[0]["track"]
        ks[0]["blobs"] = 2
        res["tracks"][t + "~2"] = dict(res["tracks"][t])
        ks.append(dict(ks[0], track=t + "~2"))
        n, fps = res["video"]["n_frames"], res["video"]["fps"]
        with tempfile.TemporaryDirectory() as tmp:
            s = os.path.join(tmp, "seg")
            shutil.copytree(d[0], s)
            dump(res, os.path.join(s, "result.json"))
            R = longvideo.merge("t", res["source"], [(s, 0, n)], fps, out_dir=os.path.join(tmp, "out"))
        got = {k["track"]: k for k in R["frames"][next(x for x in R["frames"] if int(x) == int(f))]}
        self.assertEqual(got["S1:" + t]["blobs"], 2)
        self.assertIn("S1:" + t + "~2", got)
        self.assertIn("S1:" + t + "~2", R["tracks"])


class PipelineWiring(unittest.TestCase):
    """11/23 review 2 (3): the pipeline's two D-SPLIT hooks (split.apply on split.find's hits; "blobs" written into
    result.json) without the s004 clip or any cache: a 7-frame drawn clip, SAM's reply and the Spark stages faked,
    split.find faked to one hit on the one counted track. RealCache below does the same on real data where it can."""

    def run(self, result=None):
        with tempfile.TemporaryDirectory() as tmp:
            self.tmp = tmp
            super().run(result)

    def pipe(self, support, **kw):
        import cv2
        clip = os.path.join(self.tmp, "c.mp4")
        w = cv2.VideoWriter(clip, cv2.VideoWriter_fourcc(*"mp4v"), 5.0, (W, H))
        for _ in range(7):
            w.write(np.full((H, W, 3), 90, np.uint8))
        w.release()
        sam = "\n".join(f"<{f}f>1<|box;x1=10;y1=10;x2=109;y2=49;c=0.9|>" for f in range(7))
        seen = []

        def find(frames, labels, trk, dec, sources, W_, H_):
            seen.append(sorted(trk))
            return [dict(frame=3, track=sorted(trk)[0], boxes=[[10, 10, 45, 50], [80, 10, 110, 50]], support=support)]

        def audit(run, clip, frames, trk, label, *a, **k):
            return {t: dict(name=f"T{i + 1}", is_target=True, species="fish", confidence=0.9, reason="a fish")
                    for i, t in enumerate(sorted(t for t in trk if trk[t]["label"] == label))}

        with mock.patch.object(pipeline, "RUNS", self.tmp), mock.patch.object(pipeline.api, "sam_video", lambda *a, **k: sam), \
                mock.patch.object(pipeline, "audit", audit), mock.patch.object(pipeline, "dark_tracks", lambda *a, **k: []), \
                mock.patch.object(pipeline, "same_animal_pairs", lambda *a, **k: []), \
                mock.patch.object(pipeline, "verify_peaks", lambda *a, **k: []), \
                mock.patch.object(pipeline.render, "evidence", lambda *a, **k: None), \
                mock.patch.object(pipeline.render, "annotate", lambda *a, **k: None), mock.patch.object(split, "find", find):
            pipeline.run_pipeline(clip, "w", do_scout=False, prompts=["fish"], refill=False, crowd_look=False, lowlight="off", **kw)
        return load(os.path.join(self.tmp, "w", "result.json")), seen

    def test_marked_box_reaches_result_json(self):
        res, seen = self.pipe([])
        self.assertEqual(len(seen), 1)
        self.assertEqual([k.get("blobs") for k in res["frames"]["3"]], [2])
        self.assertEqual(sum("blobs" in k for ks in res["frames"].values() for k in ks), 1)
        self.assertNotIn("splits", res)

    def test_backed_box_is_split_in_result_json(self):
        res, seen = self.pipe([["zoom-x", 0]])
        t = seen[0][0]
        self.assertEqual(res["splits"], [dict(frame=3, track=t, into=[t, t + "~2"], support=[["zoom-x", 0]])])
        self.assertEqual(sorted(k["track"] for k in res["frames"]["3"]), [t, t + "~2"])
        self.assertIn(t + "~2", res["tracks"])
        self.assertEqual(res["verdicts"][t + "~2"]["split_from"], t)
        self.assertEqual(res["metrics"]["fish"]["maxn"], 2)

    def test_no_audit_never_looks(self):
        res, seen = self.pipe([["zoom-x", 0]], do_audit=False)
        self.assertEqual(seen, [])
        self.assertFalse(any("blobs" in k for ks in res["frames"].values() for k in ks))
        self.assertNotIn("splits", res)


def _main_checkout():
    """The main checkout (a worktree has no untracked clips or cache of its own)."""
    try:
        g = subprocess.run(["git", "-C", ROOT, "rev-parse", "--path-format=absolute", "--git-common-dir"],
                           capture_output=True, text=True, timeout=10).stdout.strip()
    except OSError:
        return ROOT
    return os.path.dirname(g) if g else ROOT


def _replay(test, clip, cache, rid, *args):
    """An offline replay with the command line's own defaults, the run folder under a temp dir (pipeline.RUNS has no
    flag); the result.json."""
    tmp = test.enterContext(tempfile.TemporaryDirectory())
    env = dict(os.environ, FISH_CACHE_DIR=cache, FISH_LEDGER=os.path.join(tmp, "ledger.jsonl"))
    code = ("import sys; from fishcount import pipeline; pipeline.RUNS = sys.argv[1]; sys.argv = ['pipeline.py'] + sys.argv[2:]; "
            "main = open('fishcount/pipeline.py').read().split('if __name__ == \"__main__\":')[1].replace('\\n    ', '\\n'); "
            "exec(compile(main, 'main', 'exec'), vars(pipeline))")
    r = subprocess.run([sys.executable, "-c", code, tmp, clip, "--id", rid, "--offline", *args],
                       cwd=ROOT, env=env, capture_output=True, text=True, timeout=900)
    test.assertEqual(r.returncode, 0, r.stderr[-800:])
    return load(os.path.join(tmp, rid, "result.json"))


class RealPartnerClip(unittest.TestCase):
    """The case D-SPLIT is for, a partner's clip that cannot be shared: an offline replay from its cache still splits
    the same boxes and keeps the same MaxN. Everything about the clip stays outside git: FISH_PARTNER_SPLIT names a
    JSON file {"clip", "cache", "id", "args": [...], "splits": [[frame, track, [parts]], ...],
    "metrics": {label: [maxn, maxn_frame]}}; skipped without it or its clip, as RealCache is without s004."""

    def test_still_split(self):
        p = os.environ.get("FISH_PARTNER_SPLIT")
        want = load(p) if p and os.path.exists(p) else None
        if not (want and os.path.exists(want["clip"]) and os.path.isdir(want["cache"])):
            self.skipTest("no partner clip (FISH_PARTNER_SPLIT)")
        res = _replay(self, want["clip"], want["cache"], want["id"], *want.get("args", []))
        self.assertEqual([[s["frame"], s["track"], s["into"]] for s in res["splits"]], want["splits"])
        for label, (maxn, frame) in want["metrics"].items():
            self.assertEqual((res["metrics"][label]["maxn"], res["metrics"][label]["maxn_frame"]), (maxn, frame), label)


class RealCache(unittest.TestCase):
    """Offline replay of demo clip s004 from the demo cache: 12 boxes marked, none split, hagfish still 1; with
    --no-audit nothing is looked at. Skipped without the clip and its cache (both outside git)."""

    def replay(self, *extra):
        base = next((b for b in (ROOT, _main_checkout()) if os.path.exists(os.path.join(b, "spikes/L1/clips/nautilus_s004_0_12.mp4"))
                     and os.path.isdir(os.path.join(b, "cache"))), None)
        if base is None:
            self.skipTest("no s004 clip / demo cache")
        return _replay(self, os.path.join(base, "spikes/L1/clips/nautilus_s004_0_12.mp4"), os.path.join(base, "cache"), "s004",
                       "--no-scout", "--discover", "--zoom", "--prompts", "fish", "--max-usd", "1", *extra)

    def test_s004_marked_not_split(self):
        res = self.replay()
        self.assertEqual(sum("blobs" in k for ks in res["frames"].values() for k in ks), 12)
        self.assertNotIn("splits", res)
        self.assertFalse(any("~" in t for t in res["tracks"]))
        self.assertEqual(res["metrics"]["hagfish"]["maxn"], 1)

    def test_no_audit_no_split(self):
        res = self.replay("--no-audit")
        self.assertFalse(any("blobs" in k for ks in res["frames"].values() for k in ks))
        self.assertNotIn("splits", res)


if __name__ == "__main__":
    unittest.main()
