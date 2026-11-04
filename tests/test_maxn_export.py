"""GlobalArchive-layout MaxN export: honest columns, human review applied exactly as in the plain CSV. No network, $0."""
import csv, io, json, os, shutil, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "web"))
from fishcount import _pylib  # noqa: F401
from fishcount import maxn_export

SAVED = os.path.join(ROOT, "demo", "runs", "mg2_s004", "result.json")


class GlobalArchiveExport(unittest.TestCase):
    def setUp(self):
        import server
        self.server = server
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "r1"))
        shutil.copy(SAVED, os.path.join(self.tmp, "r1", "result.json"))
        self.orig, server.RUNS = server.RUNS, self.tmp

    def tearDown(self):
        self.server.RUNS = self.orig
        shutil.rmtree(self.tmp)

    def table(self, opcode=None):
        return list(csv.DictReader(io.StringIO(maxn_export.to_csv(self.server.effective("r1"), opcode))))

    def test_layout_and_blank_taxonomy(self):
        t = self.table("SITE1_B_1_60")
        self.assertEqual(list(t[0]), maxn_export.COLUMNS)
        self.assertEqual(maxn_export.COLUMNS[:7], ["OpCode", "Family", "Genus", "Species", "MaxN", "Frame", "Time_mins"])
        e = self.server.effective("r1")
        self.assertEqual({r["spark_common_name"]: int(r["MaxN"]) for r in t}, {k: v["maxn"] for k, v in e["metrics"].items() if v["maxn"] > 0})
        for r in t:     # never invented taxonomy
            self.assertEqual((r["Family"], r["Genus"], r["Species"]), ("", "", ""))
            self.assertEqual(r["OpCode"], "SITE1_B_1_60")
            self.assertIn("not verified", r["taxonomy_status"])
        self.assertTrue(all(not r["spark_common_name"].startswith("all ") for r in t))     # no group rows
        top = max(t, key=lambda r: int(r["MaxN"]))
        m = e["metrics"][top["spark_common_name"]]
        self.assertEqual(int(top["Frame"]), m["maxn_frame"])
        self.assertAlmostEqual(float(top["Time_mins"]), m["maxn_time"] / 60, places=3)

    def test_default_opcode_is_the_video_name(self):
        self.assertEqual(self.table()[0]["OpCode"], "nautilus_s004_0_12")

    def test_human_review_is_applied_like_the_plain_csv(self):
        before = {r["spark_common_name"]: r["MaxN"] for r in self.table()}
        # a person renames a queued unidentified shrimp to a new name and removes another from the counts
        with open(os.path.join(self.tmp, "r1", "review.json"), "w") as f:
            json.dump({"d1z-center:8": "banded coral shrimp", "d1z-center:11": None}, f)
        after = {r["spark_common_name"]: r["MaxN"] for r in self.table()}
        self.assertIn("banded coral shrimp", after)
        self.assertNotIn("banded coral shrimp", before)
        plain = {r["label"]: r["maxn"] for r in csv.DictReader(io.StringIO(self.server.export_csv("r1")))
                 if not r["label"].startswith("all ") and r["maxn"] != "0"}
        self.assertEqual(after, plain)

    def test_model_text_cannot_start_a_formula(self):
        e = dict(id="x", source="a.mp4", n_reviewed=0, origin={}, metrics={
            "=cmd()": dict(maxn=1, maxn_confirmed=1, maxn_time=1.0, maxn_frame=5)})
        self.assertEqual(list(csv.reader(io.StringIO(maxn_export.to_csv(e))))[1][7], "'=cmd()")


if __name__ == "__main__":
    unittest.main()


class CrowdLowerBound(unittest.TestCase):
    def test_group_lower_bound_reaches_every_label_row(self):
        from fishcount import maxn_export
        m = {"maxn": 9, "maxn_frame": 29, "maxn_time": 5.8}
        e = {"metrics": {"fish (unidentified)": dict(m), "thresher shark": dict(m, maxn=1)},
             "group_metrics": {"fish": {"labels": ["fish (unidentified)", "thresher shark"], "maxn": 16,
                                        "lower_bound": True, "crowd_total": 35, "crowd_frame": 29}}}
        rows = maxn_export.rows(e, "DH8")
        col = maxn_export.COLUMNS.index("maxn_lower_bound")
        self.assertTrue(all(r[col].startswith("yes (fish): Spark counts about 35 in frame 29") for r in rows))
        e["group_metrics"]["fish"]["lower_bound"] = False
        self.assertTrue(all(r[col] == "" for r in maxn_export.rows(e, "DH8")))
