"""Group rename on the review screen (no network, $0): a person renames a whole table row ("fish (unidentified)" are
all rockfish). Every track of the row takes the new name, queued or not, and MaxN is counted again frame by frame
(not the two MaxNs added). The rule lives in the run folder's renames.json; Undo removes it by id. A check box also
marks the row's still-queued tracks reviewed; Undo takes that back too."""
import csv, io, json, os, shutil, sys, tempfile, threading, time, unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "web"))
from fishcount import _pylib  # noqa: F401
from fishcount import maxn_export, settle, tracks

UNID, ROCK = "fish (unidentified)", "rockfish"
S004 = os.path.join(ROOT, "demo", "runs", "cr11_s004")
CLIP = os.path.join(ROOT, "tests", "data", "nautilus_s004_0_12.mp4")

# synthetic run, 8 frames at 1 fps. rockfish r1-r5 (5 in frame 0); unidentified u2, u3 sure, u1 / u5 queued but counted;
# u4 queued and not counted (Spark said no), its "Yes" name is "fish (unidentified)"; c1 a crab.
PRESENT = {"r1": [0, 1, 2], "r2": [0, 1, 2], "r3": [0, 1, 2], "r4": [0], "r5": [0],
           "u1": [0], "u2": [0, 1, 5, 6], "u3": [5, 6], "u5": [6], "u4": [1], "c1": [3]}
AUTO = {**{t: ROCK for t in ("r1", "r2", "r3", "r4", "r5")}, **{t: UNID for t in ("u1", "u2", "u3", "u5")}, "u4": None, "c1": "crab"}
SURE, OPEN = {"confidence": 0.9, "is_target": True}, {"confidence": 0.5, "is_target": True}


def synthetic():
    frames = {}
    for t, fs in PRESENT.items():
        for f in fs:
            frames.setdefault(f, []).append({"track": t, "box": [10, 10, 20, 20]})
    trk = {t: {"label": "fish", "source": "p0"} for t in PRESENT}
    verdicts = {t: dict(SURE, name=t) for t in PRESENT}
    verdicts.update(u1=dict(OPEN, name="u1"), u5=dict(OPEN, name="u5"),
                    u4={"confidence": 0.4, "is_target": False, "species": "unknown", "name": "u4"})
    m = tracks.metrics(frames, trk, 8, 1.0, AUTO)
    return {"source": "syn.mp4", "video": {"n_frames": 8, "fps": 1.0}, "frames": {str(f): ks for f, ks in frames.items()},
            "tracks": trk, "auto_labels": AUTO, "verdicts": verdicts, "metrics": m, "jobs": [{"name": "p0"}],
            "peak_checks": [],
            "crowd_checks": [{"row": "fish", "labels": [UNID, ROCK], "frame": 0, "maxn": 7, "total": 20, "lower_bound": True}]}


class Base(unittest.TestCase):
    def setUp(self):
        import server
        self.server, self.tmp = server, tempfile.mkdtemp()
        self.orig, server.RUNS = server.RUNS, self.tmp
        self.d = os.path.join(self.tmp, "r1")

    def tearDown(self):
        self.server.RUNS = self.orig
        shutil.rmtree(self.tmp)

    def rename(self, frm, to, accept=False):
        return self.server.rename_group("r1", {"from": frm, "to": to, "accept": accept})

    def undo(self, rid):
        return self.server.rename_group("r1", {"undo": rid})

    def rules(self):
        with open(os.path.join(self.d, "renames.json")) as f:
            return json.load(f)

    def write(self, name, obj):
        with open(os.path.join(self.d, name), "w") as f:
            json.dump(obj, f)


class Synthetic(Base):
    def setUp(self):
        super().setUp()
        os.makedirs(self.d)
        self.res = synthetic()
        self.write("result.json", self.res)
        self.before = self.server.effective("r1")

    def q(self, e, t):
        return next(x for x in e["queue"] if x["track"] == t)

    def test_counted_again_frame_by_frame_without_any_review(self):
        self.assertEqual((self.before["metrics"][ROCK]["maxn"], self.before["metrics"][UNID]["maxn"]), (5, 3))
        e = self.rename(UNID, ROCK)
        self.assertFalse(os.path.exists(os.path.join(self.d, "review.json")))
        m = e["metrics"][ROCK]
        self.assertEqual((m["maxn"], m["maxn_frame"], m["tracks"]), (7, 0, 9))   # frame 0: 5 + 2, not 5 + 3
        self.assertNotIn(UNID, e["metrics"])
        self.assertEqual(e["origin"][ROCK], "asked")
        self.assertEqual((e["n_renames"], e["n_reviewed"]), (1, 0))

    def test_new_name_that_differs_only_in_case_joins_the_row(self):
        e = self.rename(UNID, "  Rockfish ")
        self.assertEqual(e["metrics"][ROCK]["maxn"], 7)
        self.assertEqual(self.rules()[0]["to"], ROCK)

    def test_checks(self):
        for body in ({"from": "shark", "to": ROCK}, {"from": UNID, "to": " "}, {"from": UNID, "to": "Fish (Unidentified)"},
                     {"undo": "nope"}, {}, [], {"from": [UNID], "to": ROCK}, {"undo": 0}):
            with self.assertRaises(ValueError, msg=body):
                self.server.rename_group("r1", body)

    def test_queued_tracks_stay_queued_by_default(self):
        e = self.rename(UNID, ROCK)
        for t in ("u1", "u5"):
            q = self.q(e, t)
            self.assertEqual((q["reviewed"], q["label"], q["yes_label"]), (False, ROCK, ROCK))
        self.assertEqual(self.q(e, "u4")["yes_label"], ROCK)      # not counted, its Yes now joins the new row
        self.assertIsNone(self.q(e, "u4")["label"])
        m = e["metrics"][ROCK]
        self.assertEqual((m["maxn_confirmed"], m["maxn_upper"]), (6, 7))       # u1 left out of frame 0 / accepted
        self.assertEqual(self.rules()[0]["accept"], [])

    def test_check_box_marks_the_rows_queued_tracks_reviewed_and_undo_takes_it_back(self):
        e = self.rename(UNID, ROCK, accept=True)
        self.assertEqual(sorted(self.rules()[0]["accept"]), ["u1", "u5"])       # not u4: not in the row
        self.assertTrue(self.q(e, "u1")["reviewed"] and self.q(e, "u5")["reviewed"])
        self.assertFalse(self.q(e, "u4")["reviewed"])
        self.assertEqual(e["metrics"][ROCK]["maxn_confirmed"], 7)
        self.assertEqual(e["n_flagged"], 1)
        self.assertEqual(e["n_reviewed"], 0)
        rows = list(csv.DictReader(io.StringIO(self.server.export_csv("r1"))))
        self.assertEqual({r["human_edits"] for r in rows}, {"1"})               # one rename = one edit, not 1 + 2 tracks
        e = self.undo(self.rules()[0]["id"])
        self.assertFalse(self.q(e, "u1")["reviewed"])
        self.assertEqual(e["metrics"], self.before["metrics"])

    def test_a_track_review_wins_over_the_check_box_and_a_review_to_the_old_name_is_renamed(self):
        self.rename(UNID, ROCK, accept=True)
        e = self.server.save_review("r1", {"u1": "lingcod"})
        self.assertEqual(self.q(e, "u1")["label"], "lingcod")
        e = self.server.save_review("r1", {"u1": UNID})
        self.assertEqual(self.q(e, "u1")["label"], ROCK)

    def test_undo_by_id_any_rule(self):
        self.server.save_review("r1", {"u2": None})          # a track edit before the rules
        reviewed = self.server.effective("r1")
        a = self.rename(UNID, ROCK)["renames"][0]["id"]
        self.rename("crab", "red crab")
        e = self.undo(a)                                       # the first rule; the later one stays
        self.assertEqual([r["to"] for r in e["renames"]], ["red crab"])
        self.assertEqual(e["metrics"][UNID], reviewed["metrics"][UNID])
        self.assertIn("red crab", e["metrics"])
        e = self.undo(e["renames"][0]["id"])
        self.assertEqual(e["metrics"], reviewed["metrics"])
        self.assertEqual(self.q(e, "u2")["label"], None)       # the track edit is still there

    def test_chain_and_reverse_rule(self):
        self.rename(UNID, ROCK)
        e = self.rename(ROCK, UNID)          # not an Undo: both rows end up "fish (unidentified)", two rules stay
        self.assertEqual(sorted(e["metrics"]), ["crab", UNID])
        self.assertEqual(e["metrics"][UNID]["maxn"], 7)
        self.assertEqual(e["n_renames"], 2)

    def test_three_exits_agree(self):
        e = self.rename(UNID, ROCK)
        plain = {r["label"]: r for r in csv.DictReader(io.StringIO(self.server.export_csv("r1")))}
        ga = {r["spark_common_name"]: r for r in csv.DictReader(io.StringIO(maxn_export.to_csv(self.server.effective("r1"))))}
        for name, m in e["metrics"].items():
            self.assertEqual((int(plain[name]["maxn"]), int(plain[name]["maxn_frame"]), int(plain[name]["tracks"])),
                             (m["maxn"], m["maxn_frame"], m["tracks"]))
            self.assertEqual(int(ga[name]["MaxN"]), m["maxn"])
            self.assertEqual((plain[name]["human_edits"], ga[name]["human_edits"]), ("1", "1"))

    def test_decisive_ranks_under_the_renamed_names(self):
        self.assertEqual(set(settle.decisive(self.res, {})), {"u5"})
        self.assertEqual(settle.decisive(self.res, {}, None), settle.decisive(self.res, {}))
        rules = [{"from": UNID, "to": ROCK}]
        self.assertEqual(set(settle.decisive(self.res, {}, rules)), {"u1"})
        self.assertEqual(self.rename(UNID, ROCK)["n_decisive"], 1)
        self.assertEqual(self.q(self.server.effective("r1"), "u1")["rank"], 1)

    def test_crowd_lower_bound_kept_when_only_the_name_changed(self):
        self.assertTrue(self.before["group_metrics"]["fish"]["lower_bound"])
        e = self.rename(UNID, ROCK)            # one fish row left: no group row, the label row carries the mark
        self.assertTrue(e["metrics"][ROCK].get("lower_bound"))
        self.assertEqual(e["metrics"][ROCK]["crowd_total"], 20)

    def test_site_rows_and_no_remembered_from_a_rename(self):
        self.res["site"] = {"name": None, "entries": [{"source": "p0", "word": "fish", "label": UNID}]}
        self.write("result.json", self.res)
        self.write("review.json", {"u1": UNID})     # confirmed as the automatic name
        e = self.rename(UNID, ROCK)
        self.assertIn(ROCK, e["site_rows"])
        self.assertNotIn(UNID, e["site_rows"])
        self.assertNotIn("remembered", self.q(e, "u1"))

    def test_concurrent_renames_both_kept(self):
        real = os.replace

        def slow(*a):           # both threads would read the rules before either writes, without the lock
            time.sleep(0.3)
            real(*a)
        with mock.patch("os.replace", slow):
            ts = [threading.Thread(target=self.rename, args=a) for a in ((UNID, ROCK), ("crab", "red crab"))]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
        self.assertEqual(sorted(r["to"] for r in self.rules()), ["red crab", ROCK])

    def test_each_rule_says_how_many_tracks_it_renamed(self):
        e = self.rename(UNID, ROCK)
        self.assertEqual(e["renames"][0]["tracks"], 4)          # u1 u2 u3 u5; u4 has no name, c1 is a crab
        self.assertNotIn("tracks", self.rules()[0])            # worked out on every read, not stored
        e = self.rename(ROCK, "fish")
        self.assertEqual([r["tracks"] for r in e["renames"]], [4, 9])

    def test_crowd_lower_bound_dropped_when_the_merge_changed_maxn(self):
        self.res["crowd_checks"] = [{"row": UNID, "labels": [UNID], "frame": 6, "maxn": 3, "total": 9, "lower_bound": True}]
        self.write("result.json", self.res)
        self.assertTrue(self.server.effective("r1")["metrics"][UNID].get("lower_bound"))
        e = self.rename(UNID, ROCK)            # 7 now, not the 3 Spark checked
        self.assertFalse(e["metrics"][ROCK].get("lower_bound"))

    def test_a_checked_track_ranks_under_the_name_it_is_counted_as(self):
        # u1 has no automatic label, so it counts under its category "fish" and its "Yes" would name it lingcod. The check
        # box marks it reviewed as the row's name: it counts as rockfish, so u4 (its "Yes" is lingcod) is still the only
        # lingcod and decides that row
        self.res["auto_labels"] = {t: l for t, l in AUTO.items() if t != "u1"}
        self.res["verdicts"]["u1"]["species"] = "Lingcod"
        self.res["verdicts"]["u4"]["species"] = "Lingcod"
        self.write("result.json", self.res)
        self.rename("crab", "red crab")        # with a rule on, the queue shows u1 in the "fish" row too
        e = self.rename("fish", ROCK, accept=True)
        self.assertIn("u1", self.rules()[1]["accept"])
        self.assertNotIn("lingcod", e["metrics"])
        self.assertIsNotNone(self.q(e, "u4")["rank"])

    def test_a_rule_without_from_is_skipped(self):
        self.write("renames.json", [{"id": "x", "to": ROCK}])
        self.assertEqual(self.server.effective("r1")["metrics"], self.before["metrics"])

    def test_no_rules_is_the_run_as_before(self):
        e = self.server.effective("r1")
        self.assertEqual((e["renames"], e["n_renames"]), ([], 0))
        self.assertEqual(e["metrics"], self.before["metrics"])
        self.undo(self.rename(UNID, ROCK)["renames"][0]["id"])
        self.assertEqual(self.rules(), [])
        self.assertEqual(self.server.effective("r1")["metrics"], self.before["metrics"])


class RealRun(Base):
    """s004 from the demo, no review.json: rename "shrimp (unidentified)" into "caridean shrimp"."""
    def setUp(self):
        super().setUp()
        shutil.copytree(S004, self.d)
        self.assertFalse(os.path.exists(os.path.join(self.d, "review.json")))

    def test_evidence_redrawn_from_a_rename_alone(self):
        shutil.copy(CLIP, os.path.join(self.d, "clip.mp4"))
        before = self.server.effective("r1")["metrics"]
        e = self.rename("shrimp (unidentified)", "caridean shrimp")
        m = e["metrics"]["caridean shrimp"]
        self.assertNotIn("shrimp (unidentified)", e["metrics"])
        self.assertGreater(m["maxn"], before["caridean shrimp"]["maxn"])
        self.assertLess(m["maxn"], before["caridean shrimp"]["maxn"] + before["shrimp (unidentified)"]["maxn"] + 1)
        self.assertEqual(m["evidence"], "evidence_caridean_shrimp_reviewed.jpg")
        self.assertFalse(m["evidence_stale"])

    def test_three_exits_agree(self):
        e = self.rename("shrimp (unidentified)", "caridean shrimp")
        plain = {r["label"]: r for r in csv.DictReader(io.StringIO(self.server.export_csv("r1")))}
        ga = {r["spark_common_name"]: r for r in csv.DictReader(io.StringIO(maxn_export.to_csv(e)))}
        for name, m in e["metrics"].items():
            self.assertEqual((int(plain[name]["maxn"]), int(ga[name]["MaxN"]), plain[name]["human_edits"]), (m["maxn"], m["maxn"], "1"))
            self.assertEqual(int(plain[name]["maxn_upper"]), m["maxn_upper"])


if __name__ == "__main__":
    unittest.main()
