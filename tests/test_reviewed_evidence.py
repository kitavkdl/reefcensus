"""Evidence frame after a review (no network, $0): when a person's answer moves a label's MaxN, the image beside the
caption is redrawn from the reviewed labels (it used to stay the run's image with the old count); a packed run without
its clip keeps the old image and says so."""
import json, os, shutil, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "web"))
from fishcount import _pylib  # noqa: F401
from fishcount import render

RUN = os.path.join(ROOT, "demo", "runs", "cr11_s004")
CLIP = os.path.join(ROOT, "tests", "data", "nautilus_s004_0_12.mp4")     # the run's clip.mp4, byte for byte
NAME = "caridean shrimp"


class ReviewedEvidence(unittest.TestCase):
    def setUp(self):
        import server
        self.server, self.tmp = server, tempfile.mkdtemp()
        self.d = os.path.join(self.tmp, "r1")
        shutil.copytree(RUN, self.d)
        self.orig, server.RUNS = server.RUNS, self.tmp
        self.res = json.load(open(os.path.join(self.d, "result.json")))

    def tearDown(self):
        self.server.RUNS = self.orig
        shutil.rmtree(self.tmp)

    def reject_one(self):
        f = self.res["metrics"][NAME]["maxn_frame"]
        t = next(k["track"] for k in self.res["frames"][str(f)] if self.res["auto_labels"].get(k["track"]) == NAME)
        json.dump({t: None}, open(os.path.join(self.d, "review.json"), "w"))
        return t

    def test_no_review_keeps_the_run_image(self):
        m = self.server.effective("r1")["metrics"][NAME]
        self.assertEqual(m["evidence"], "evidence_caridean_shrimp.jpg")
        self.assertNotIn("evidence_stale", m)

    def test_redrawn_with_the_new_count(self):
        shutil.copy(CLIP, os.path.join(self.d, "clip.mp4"))
        t = self.reject_one()
        m = self.server.effective("r1")["metrics"][NAME]
        self.assertEqual(m["maxn"], self.res["metrics"][NAME]["maxn"] - 1)
        self.assertEqual(m["evidence"], "evidence_caridean_shrimp_reviewed.jpg")
        self.assertFalse(m["evidence_stale"])
        self.assertTrue(os.path.getsize(os.path.join(self.d, m["evidence"])) > 0)
        mine, _ = render.evidence_split(dict(self.res, auto_labels={**self.res["auto_labels"], t: None}), m["maxn_frame"], NAME)
        self.assertEqual(len(mine), m["maxn"])          # what the redrawn image counts

    def test_packed_run_without_clip_says_so(self):
        self.reject_one()
        m = self.server.effective("r1")["metrics"][NAME]
        self.assertEqual(m["evidence"], "evidence_caridean_shrimp.jpg")
        self.assertTrue(m["evidence_stale"])


if __name__ == "__main__":
    unittest.main()
