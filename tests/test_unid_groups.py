"""--unid-groups (D-UNID): the unnamed tracks of a category sorted by look into "fish (unidentified 1)", "(unidentified 2)",
... by one Muse Spark sheet per 12 tracks after every other step. No network, no spend: Spark and the frames are fakes,
except the s004 replays (cache only).
Run: python3 -m unittest discover -s tests -v"""
import csv, io, json, os, re, shutil, subprocess, sys, tempfile, time, unittest
from unittest import mock

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "web"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fishcount import _pylib  # noqa: F401
from fishcount import api, longvideo, maxn_export, pipeline, render, settle, tracks, video

U1, U2, UG, UNID = "fish (unidentified 1)", "fish (unidentified 2)", "fish (unidentified, ungrouped)", "fish (unidentified)"


def fake_frames(clip, idx):
    return {f: np.full((120, 160, 3), (f * 7) % 255, np.uint8) for f in idx}


class Spark:
    """Answers the sort-by-look sheets with `kinds(tile names) -> [[tile, ...], ...]`; logs each call's sheet bytes."""

    def __init__(self, kinds, usd=0.0):
        self.kinds, self.usd, self.calls = kinds, usd, []

    def __call__(self, prompt, images=(), offline=False, check=None, **k):
        assert prompt.startswith("You are sorting animals"), prompt[:60]
        self.calls.append(dict(prompt=prompt, sheet=images[0]))
        if self.usd:
            api._log("spark", self.usd, "fake")
        return json.dumps([{"tiles": g, "looks": "x"} for g in self.kinds(len(self.calls))])


class Regex(unittest.TestCase):
    def test_names(self):
        for n in (UNID, U1, "crab (unidentified 12)", UG):
            self.assertTrue(pipeline.is_unidentified(n), n)
            self.assertEqual(pipeline.unid_base(n), n.split(" (")[0] + " (unidentified)")
        for n in ("fish", "unidentified fish", "fish (unidentified) x", "fish (unidentified one)", "", None):
            self.assertFalse(pipeline.is_unidentified(n), n)
        self.assertEqual(pipeline.unid_base("rockfish"), "rockfish")

    def test_a_peak_check_of_the_unsplit_row_carries_to_the_frame_it_checked(self):
        checked = {(UNID, 6)}
        self.assertTrue(pipeline.peak_checked(U2, 6, checked))
        self.assertFalse(pipeline.peak_checked(U1, 0, checked))       # a frame nobody checked (owner ⑤: not re-checked)
        self.assertFalse(pipeline.peak_checked("rockfish", 6, checked))


class Sort(unittest.TestCase):
    """pipeline.unid_groups on a synthetic run: fish a-f first seen on frames 0-5 (a-e counted unidentified, f queued
    and uncounted, Spark said no species), rk a rockfish, c1 one unidentified crab."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        for p in (mock.patch.object(pipeline, "RUNS", self.tmp), mock.patch.object(video, "frames", fake_frames),
                  mock.patch.object(api, "LEDGER", os.path.join(self.tmp, "ledger.jsonl"))):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_(self, n_fish=6):
        names = [chr(97 + i) for i in range(n_fish)]
        frames = {}
        for i, t in enumerate(names + ["rk", "c1"]):
            for f in (i, i + 1, i + 2):
                frames.setdefault(f, []).append(dict(track=t, box=[10 + i, 10, 40 + i, 30]))
        trk = {t: dict(label="fish", source="p0") for t in names + ["rk"]}
        trk["c1"] = dict(label="crab", source="p1")
        verdicts = {t: dict(is_target=True, confidence=0.9, species="unknown") for t in trk}
        verdicts[names[-1]] = dict(is_target=False, confidence=0.4, species="unknown")      # queued, not counted
        verdicts["rk"]["species"] = "rockfish"
        labels = {t: UNID for t in names[:-1]}
        labels.update({names[-1]: None, "rk": "rockfish", "c1": "crab (unidentified)"})
        return pipeline.Run("r"), frames, trk, verdicts, labels

    def sort(self, spark, n_fish=6, offline=False, max_usd=1.0, run=None):
        r, frames, trk, verdicts, labels = self.run_(n_fish)
        with mock.patch.object(api, "spark", spark):
            return pipeline.unid_groups(run or r, "clip.mp4", frames, trk, verdicts, labels, offline, max_usd), r

    def test_two_kinds_are_numbered_by_first_box_and_a_queued_track_gets_its_kind(self):
        sp = Spark(lambda k: [["U2", "U5"], ["U1", "U3", "U4", "U6"]])
        got, run = self.sort(sp)
        self.assertEqual(got, dict(a=U1, c=U1, d=U1, f=U1, b=U2, e=U2))      # f: queued, its "Yes" name
        self.assertEqual(len(sp.calls), 1)          # the crab row has one track: not asked; the rockfish is named
        self.assertTrue(os.path.exists(run.path("unid_fish_1.jpg")))
        self.assertIn('"fish"', sp.calls[0]["prompt"])
        self.assertNotIn("R1", sp.calls[0]["prompt"])

    def test_one_kind_keeps_the_name(self):
        got, _ = self.sort(Spark(lambda k: [["U1", "U2", "U3", "U4", "U5", "U6"]]))
        self.assertEqual(got, {})

    def test_a_tile_left_out_named_twice_or_unknown_is_ungrouped(self):
        got, _ = self.sort(Spark(lambda k: [["U1", "U2", "U9"], ["U3", "U2"], ["U4"]]))
        self.assertEqual(got, dict(a=U1, c=U2, d="fish (unidentified 3)", b=UG, e=UG, f=UG))

    def test_a_second_sheet_shows_one_example_per_kind_and_the_same_bytes_again(self):
        def kinds(k):
            if k == 1:      # sheet 1: U1-U12 = a-l, two kinds
                return [[f"U{i}" for i in range(1, 13, 2)], [f"U{i}" for i in range(2, 13, 2)]]
            return [["R2", "U1"], ["U2"], ["R1", "R2", "U3"]]        # m -> kind 2, n new kind, o with two kinds: ungrouped
        sp = Spark(kinds)
        got, _ = self.sort(sp, n_fish=16)       # a-o counted, p queued: 16 candidates, two sheets
        self.assertEqual(len(sp.calls), 2)
        self.assertIn("R1, R2", sp.calls[1]["prompt"])
        self.assertEqual((got["a"], got["b"], got["m"], got["n"], got["o"], got["p"]),
                         (U1, U2, U2, "fish (unidentified 3)", UG, UG))     # p: on sheet 2 as U4, not in the answer
        sp2 = Spark(kinds)
        self.sort(sp2, n_fish=16)
        self.assertEqual([c["sheet"] for c in sp2.calls], [c["sheet"] for c in sp.calls])   # cache key: same bytes

    def test_an_offline_replay_without_the_answer_leaves_the_category_as_it_was(self):
        def miss(*a, **k):
            raise FileNotFoundError("not cached: spark_x.json")
        got, run = self.sort(miss, offline=True)
        self.assertEqual(got, {})
        self.assertIn("not sorted by look", run.status["log"][-1])
        self.assertEqual(run.capped, [])        # not a cap skip: result["capped"] unchanged

    def test_a_sheet_past_the_cap_is_skipped_and_a_replay_skips_it_too(self):
        sp = Spark(lambda k: [["U1"], ["U2"]])
        got, run = self.sort(sp, max_usd=0.01)
        self.assertEqual((got, sp.calls), ({}, []))
        self.assertEqual([c["item"] for c in run.capped], ["unid:fish:1"])
        replay = pipeline.Run("r2")
        replay.live_capped = {c["item"]: c["msg"] for c in run.capped}
        got2, _ = self.sort(sp, offline=True, run=replay)
        self.assertEqual((got2, sp.calls, [c["item"] for c in replay.capped]), ({}, [], ["unid:fish:1"]))

    def test_past_the_sheet_limit_tracks_are_ungrouped(self):
        with mock.patch.object(pipeline, "UNID_MAX_SHEETS", 1):
            got, _ = self.sort(Spark(lambda k: [[f"U{i}" for i in range(1, 7)], [f"U{i}" for i in range(7, 13)]]), n_fish=16)
        self.assertEqual((got["a"], got["l"], got["m"], got["p"]), (U1, U2, UG, UG))

    def test_accept_label_gives_the_kind(self):
        res = dict(tracks=dict(f=dict(label="fish")), auto_labels=dict(f=None),
                   verdicts=dict(f=dict(species="unknown")), unid_names=dict(f=U2))
        self.assertEqual(settle.accept_label(res, "f"), U2)
        res["verdicts"]["f"]["species"] = "Cod"
        self.assertEqual(settle.accept_label(res, "f"), "cod")      # a species still wins
        del res["unid_names"]
        res["verdicts"]["f"]["species"] = "unknown"
        self.assertEqual(settle.accept_label(res, "f"), UNID)


def split_run():
    """tests/test_group_rename.py's synthetic run sorted by look: u1 u2 kind 1, u3 u5 kind 2, u4 (queued, uncounted)
    kind 2. The unsplit row peaked at frame 6 (u2 u3 u5) and was peak-checked there."""
    import test_group_rename as g
    res = g.synthetic()
    res["peak_checks"] = [dict(label=UNID, frame=6, n=3, kept=3)]
    names = dict(u1=U1, u2=U1, u3=U2, u5=U2, u4=U2)
    res["unid_names"] = names
    res["auto_labels"] = {t: (names[t] if l == UNID else l) for t, l in res["auto_labels"].items()}
    frames = {int(f): ks for f, ks in res["frames"].items()}
    res["metrics"] = tracks.metrics(frames, res["tracks"], 8, 1.0, res["auto_labels"])
    return res


class Server(unittest.TestCase):
    def setUp(self):
        import server
        self.server, self.tmp = server, tempfile.mkdtemp()
        self.orig, server.RUNS = server.RUNS, self.tmp
        self.addCleanup(setattr, server, "RUNS", self.orig)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def put(self, rid, res):
        os.makedirs(os.path.join(self.tmp, rid))
        json.dump(res, open(os.path.join(self.tmp, rid, "result.json"), "w"))
        return self.server.effective(rid)

    def test_split_rows_on_the_review_screen_and_in_both_csvs(self):
        import test_group_rename as g
        e0, e = self.put("whole", g.synthetic()), self.put("split", split_run())
        m = e["metrics"]
        self.assertEqual((m[U1]["maxn"], m[U1]["maxn_frame"], m[U2]["maxn"], m[U2]["maxn_frame"]), (2, 0, 2, 6))
        self.assertEqual((m[U1]["peak_checked"], m[U2]["peak_checked"]), (False, True))
        self.assertEqual({k: (v["maxn"], v["curve"]) for k, v in e["group_metrics"].items()},
                         {k: (v["maxn"], v["curve"]) for k, v in e0["group_metrics"].items()})   # all fish: the same
        self.assertTrue(e["group_metrics"]["fish"].get("lower_bound"))      # the crowd check on "fish" still holds
        self.assertEqual(next(q for q in e["queue"] if q["track"] == "u4")["yes_label"], U2)
        rows = {r["label"]: r for r in csv.DictReader(io.StringIO(self.server.export_csv("split")))}
        self.assertTrue(rows[U1]["origin"].endswith("; grouped by appearance (Muse Spark, not verified)"))
        self.assertNotIn("grouped", rows["rockfish"]["origin"])
        ga = {r["spark_common_name"]: r for r in csv.DictReader(io.StringIO(maxn_export.to_csv(e)))}
        self.assertEqual(ga[U2]["taxonomy_status"], "not verified: unidentified, grouped by appearance by Muse Spark")
        self.assertEqual(ga["rockfish"]["taxonomy_status"], "not verified: common name from Muse Spark or a reviewer")

    def test_renaming_a_split_row_moves_its_maxn(self):
        self.put("split", split_run())
        e = self.server.rename_group("split", {"from": U2, "to": "cod", "accept": False})
        self.assertNotIn(U2, e["metrics"])
        self.assertEqual((e["metrics"]["cod"]["maxn"], e["metrics"]["cod"]["maxn_frame"]), (2, 6))
        self.assertEqual(next(q for q in e["queue"] if q["track"] == "u4")["yes_label"], "cod")
        e = self.server.rename_group("split", {"from": U1, "to": "cod", "accept": False})     # join: frame by frame
        self.assertEqual(e["metrics"]["cod"]["maxn"], 3)

    def test_a_split_row_outside_the_animal_groups_loses_the_crowd_mark(self):
        self.assertIsNone(pipeline.name_group("blob (unidentified)"))
        res = split_run()
        ren = lambda l: l.replace("fish (", "blob (") if l else l
        res["auto_labels"] = {t: ren(l) for t, l in res["auto_labels"].items()}
        res["unid_names"] = {t: ren(l) for t, l in res["unid_names"].items()}
        res["crowd_checks"] = [dict(row="blob (unidentified)", labels=["blob (unidentified)"], frame=6, maxn=3, total=9, lower_bound=True)]
        e = self.put("blob", res)
        self.assertFalse(any(v.get("lower_bound") for v in e["metrics"].values()))     # Spark counted the sum, not a kind


def long_seg(d, start, kinds, n=2):
    """A segment run: one unidentified fish per entry of kinds (track t<i> on its frames), peak-checked at frame 0."""
    trk = {f"t{i}": dict(label="fish", source="p0", first=0, last=1, n=2) for i in range(len(kinds))}
    fr = {"0": [dict(track=t, box=[10, 10, 30, 30]) for t in trk], "1": [dict(track=t, box=[10, 10, 30, 30]) for t in trk]}
    res = dict(source="v.mp4", video=dict(n_frames=n, fps=5, width=160, height=120), tracks=trk, frames=fr,
               verdicts={t: dict(is_target=True, confidence=0.9, species="unknown", name=t.upper()) for t in trk},
               auto_labels={t: UNID for t in trk}, metrics={UNID: dict(maxn=len(trk))},
               peak_checks=[dict(label=UNID, frame=0)])
    os.makedirs(d, exist_ok=True)
    json.dump(res, open(os.path.join(d, "result.json"), "w"))


class Long(unittest.TestCase):
    def test_reserve_is_taken_before_the_shares(self):
        floors = [0.3, 0.3]
        self.assertEqual(longvideo.unid_reserve(2.0, floors), 0.2)
        self.assertEqual(longvideo.unid_reserve(0.65, floors), 0.05)
        self.assertEqual(longvideo.unid_reserve(0.6, floors), 0.0)          # the first passes first

    def test_the_merge_sorts_the_whole_video_and_the_spend_is_the_videos(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(api, "LEDGER", os.path.join(tmp, "ledger.jsonl")), \
                mock.patch.object(video, "frames", fake_frames), mock.patch.object(pipeline, "RUNS", tmp):
            a, b, out = os.path.join(tmp, "a"), os.path.join(tmp, "b"), os.path.join(tmp, "vid")
            long_seg(a, 0, [1, 2])
            long_seg(b, 2, [1])
            os.makedirs(out)
            t0 = time.time()
            logs = []
            step, vr = longvideo._unid_step("vid", out, "full.mp4", {}, 0.2, False, logs.append)
            sp = Spark(lambda k: [["U1", "U3"], ["U2"]], usd=0.01)     # S1:t0 + S2:t0 one kind, S1:t1 another
            with mock.patch.object(api, "spark", sp):
                R = longvideo.merge("vid", "v.mp4", [(a, 0, 2), (b, 2, 2)], 5, out_dir=out, unid=step, videos=False)
            self.assertEqual(R["unid_names"], {"S1:t0": U1, "S2:t0": U1, "S1:t1": U2})
            self.assertEqual(R["auto_labels"]["S2:t0"], U1)
            self.assertEqual((R["metrics"][U1]["maxn"], R["metrics"][U2]["maxn"]), (1, 1))
            self.assertTrue(R["metrics"][U1]["peak_checked"])        # frame 0 was checked as the unsplit row
            self.assertTrue(any("sorted by look into 2 kinds" in l for l in logs))
            spent, _ = longvideo.video_spent("vid", t0, os.path.join(tmp, "ledger.jsonl"))
            self.assertAlmostEqual(spent, 0.01)     # in the ledger under the video's id: _budget counts it
            self.assertAlmostEqual(vr.status["billed_usd"], 0.01)

    def test_run_long_gives_the_segments_the_cap_minus_the_reserve(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        got, cuts, drawn = [], {}, []

        def ingest(src, dst, **k):
            open(dst, "w").close()

        def cut(clip, dst, start, n):
            cuts[dst] = (start, n)
            open(dst, "w").close()

        def run_pipeline(sp, srid, **kw):
            got.append(kw)
            start, n = cuts[sp]
            long_seg(os.path.join(tmp, srid), start, [1, 2], n)
            json.dump(dict(live_calls=1, cached_calls=0, billed_usd=0.0), open(os.path.join(tmp, srid, "status.json"), "w"))

        with mock.patch.object(pipeline, "RUNS", tmp), mock.patch.object(video, "ingest", ingest), \
                mock.patch.object(api, "LEDGER", os.path.join(tmp, "ledger.jsonl")), \
                mock.patch.object(video, "info", lambda p: dict(n_frames=3000, fps=5.0, width=160, height=120)), \
                mock.patch.object(video, "light_stats", lambda p: dict(median_l=100, mean_l=100)), \
                mock.patch.object(video, "frames", fake_frames), mock.patch.object(longvideo, "cut", cut), \
                mock.patch.object(render, "evidence", lambda clip, raw, R, f, out, name: drawn.append(name)), \
                mock.patch.object(pipeline, "run_pipeline", run_pipeline), \
                mock.patch.object(api, "spark", Spark(lambda k: [["U1", "U3", "U5", "U7"], ["U2", "U4", "U6", "U8"]])):
            R = longvideo.run_long("v.mp4", "vid", seg_s=150, max_usd_video=2.0, unid=True)
        self.assertTrue(all("unid" not in kw for kw in got))         # not each segment's
        self.assertAlmostEqual(sum(kw["max_usd"] for kw in got), 2.0 - 0.2, places=3)
        self.assertEqual(sorted(set(R["unid_names"].values())), [U1, U2])
        self.assertEqual(sorted(drawn), [U1, U2])        # the split rows' evidence frames, drawn from the whole clip


@unittest.skipUnless(shutil.which("node"), "node missing")
class Screen(unittest.TestCase):
    """web/app.js groupTotal(): "All fish together" over the split rows and the named ones, run in node."""

    def total(self, rows, name):
        js = open(os.path.join(ROOT, "web", "app.js")).read()
        head = re.search(r"^const UNID_RE = .*\n^const isUnid = .*$", js, re.M).group(0)
        fn = re.search(r"^function groupTotal\(rows, name\) \{.*?^\}$", js, re.M | re.S).group(0)
        rows = [[n, dict(curve=c)] for n, c in rows]
        prog = f"{head}\n{fn}\nconsole.log(JSON.stringify(groupTotal({json.dumps(rows)}, {json.dumps(name)})));"
        return json.loads(subprocess.run(["node", "-e", prog], capture_output=True, text=True, check=True).stdout)

    def test_split_rows_add_up_with_the_named_ones(self):
        rows = [("reef fish", [3, 1]), (U1, [1, 0]), (U2, [2, 1]), (UG, [0, 1]), ("crab (unidentified 1)", [5, 5])]
        g = self.total(rows, U2)
        self.assertEqual((g["head"], g["maxn"], g["frame"]), ("fish", 6, 0))
        self.assertEqual(g["parts"], ["3 reef", "1 unidentified 1", "2 unidentified 2", "0 unidentified, ungrouped"])

    def test_the_unsplit_row_reads_as_before(self):
        g = self.total([("caridean shrimp", [12, 2]), ("shrimp (unidentified)", [3, 1])], "shrimp (unidentified)")
        self.assertEqual((g["maxn"], g["parts"]), (15, ["12 caridean", "3 unidentified"]))


class Replay(unittest.TestCase):
    """The saved s004 clip replayed from cache/ with --unid-groups: three counted 'shrimp (unidentified)' tracks."""
    CLIP = os.path.join(ROOT, "tests", "data", "nautilus_s004_0_12.mp4")

    def setUp(self):
        if not os.path.exists(self.CLIP):
            self.skipTest("clip not present (videos are not in git; see README Data)")
        self._runs, self.tmp = pipeline.RUNS, tempfile.mkdtemp()
        pipeline.RUNS = self.tmp
        self.addCleanup(setattr, pipeline, "RUNS", self._runs)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def replay(self, rid, **kw):
        from test_core import replay_or_skip
        return replay_or_skip(self, lambda: pipeline.run_pipeline(self.CLIP, rid, True, False, True, True, ["fish"], 0.0, True, **kw))

    def test_off_and_on_without_answers_are_the_same_bytes_and_with_answers_the_rows_split(self):
        strip = lambda r: json.dumps({k: v for k, v in r.items() if k != "id"}, sort_keys=True)
        off = self.replay("off")
        self.assertEqual(strip(self.replay("miss", unid=True)), strip(off))     # no cached sheet: as before
        real = api.spark

        def spark(prompt, images=(), **k):      # only the sort sheet is answered here; every other call is the cache
            if prompt.startswith("You are sorting animals"):
                return json.dumps([{"tiles": ["U1"]}, {"tiles": [f"U{i}" for i in range(2, 13)]}])
            return real(prompt, images, **k)
        with mock.patch.object(api, "spark", spark):
            on = self.replay("on", unid=True)
        seen = {k["track"] for ks in off["frames"].values() for k in ks}
        bycat = {}
        for t, c in pipeline.unid_candidates(off["tracks"], off["verdicts"], off["auto_labels"]).items():
            if t in seen:
                bycat.setdefault(c, set()).add(t)
        self.assertGreaterEqual(len(bycat.get("shrimp", ())), 2)
        self.assertEqual(set(on["unid_names"]), set().union(*(ts for ts in bycat.values() if len(ts) >= 2)))
        self.assertNotIn("shrimp (unidentified)", on["metrics"])
        self.assertIn("shrimp (unidentified 1)", on["metrics"])
        self.assertEqual({g: v["curve"] for g, v in on["group_metrics"].items()}, {g: v["curve"] for g, v in off["group_metrics"].items()})
        for k in ("tracks", "verdicts", "frames", "peak_checks", "crowd_checks"):
            self.assertEqual(on[k], off[k], k)
        for name in set(on["unid_names"].values()) & set(on["metrics"]):
            self.assertTrue(os.path.exists(os.path.join(self.tmp, "on", f"evidence_{pipeline.api_safe(name)}.jpg")), name)


if __name__ == "__main__":
    unittest.main()
