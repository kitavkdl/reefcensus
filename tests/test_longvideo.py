"""Long videos: segment plan and the merge of segment runs (no network, no spend).
Run: python3 -m unittest discover -s tests -v"""
import glob, json, os, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fishcount import _pylib  # noqa: F401
from fishcount import longvideo

DEMO = sorted(glob.glob(os.path.join(ROOT, "demo", "runs", "mg2_s00?")))
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


if __name__ == "__main__":
    unittest.main()
