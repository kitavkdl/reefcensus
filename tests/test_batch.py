"""fishcount/batch.py: many videos, one line each (zero-count and failed ones too), kept on rerun, stopped cleanly.
Each video runs a fake pipeline.py (a small script) in its own process exactly as the batch runs the real one, so
the subprocess, the tables and the rerun logic are the batch's own. No network, $0."""
import csv, json, os, shutil, signal, subprocess, sys, tempfile, time, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "web"))
from fishcount import _pylib  # noqa: F401
from fishcount import api, batch, maxn_export, pipeline

SAVED = os.path.join(ROOT, "demo", "runs", "cr11_s004", "result.json")

# argv: <video> --id <rid> [options...]. Behaviour by the video's file name: "bad" fails like a crashed run (status
# error, exit 1), "zero" finishes with nothing counted, "slow" sleeps first (pid in <runs>/<rid>.pid), else the
# saved s004 result. Every call is appended to <runs>/calls.jsonl; a paid call is written to the ledger, tagged.
FAKE = r'''
import json, os, sys, time
runs, saved, ledger = os.environ["FAKE_RUNS"], os.environ["FAKE_SAVED"], os.environ["FAKE_LEDGER"]
video, rid, opts = sys.argv[1], sys.argv[3], sys.argv[4:]
with open(os.path.join(runs, "calls.jsonl"), "a") as f:
    f.write(json.dumps(dict(video=video, rid=rid, opts=opts)) + "\n")
d = os.path.join(runs, rid)
os.makedirs(d, exist_ok=True)
name = os.path.basename(video)
st = dict(id=rid, stage="track", log=["started"], live_calls=2, cached_calls=5, billed_usd=0.25)
json.dump(st, open(os.path.join(d, "status.json"), "w"))
with open(ledger, "a") as f:
    f.write(json.dumps(dict(t=time.time(), kind="sam", usd=0.25, note="x", run=rid, stage="run_pipeline")) + "\n")
if name.startswith("slow"):
    open(os.path.join(runs, rid + ".pid"), "w").write(str(os.getpid()))
    time.sleep(60)
if name.startswith("bad"):
    st.update(stage="error", error="FileNotFoundError: not cached: spark call")
    json.dump(st, open(os.path.join(d, "status.json"), "w"))
    print("Traceback ... FileNotFoundError")
    sys.exit(1)
res = json.load(open(saved))
res.update(id=rid, source=name)
if name.startswith("zero"):
    res.update(tracks={}, verdicts={}, auto_labels={}, metrics={}, group_metrics={}, frames={}, peak_checks=[],
               crowd_checks=[], duplicates=[], recovered=[])
json.dump(res, open(os.path.join(d, "result.json"), "w"))
st.update(stage="done")
json.dump(st, open(os.path.join(d, "status.json"), "w"))
'''


class BatchCase(unittest.TestCase):
    def setUp(self):
        import server
        self.server = server
        self.tmp = tempfile.mkdtemp()
        self.runs = os.path.join(self.tmp, "runs")
        self.vids = os.path.join(self.tmp, "videos")
        self.out = os.path.join(self.tmp, "out")
        os.makedirs(self.runs)
        os.makedirs(self.vids)
        self.fake = os.path.join(self.tmp, "fake_pipeline.py")
        with open(self.fake, "w") as f:
            f.write(FAKE)
        self.ledger = os.path.join(self.tmp, "ledger.jsonl")
        self.saved = (pipeline.RUNS, server.RUNS, api.LEDGER, batch.command)
        pipeline.RUNS = server.RUNS = self.runs
        api.LEDGER = self.ledger
        real_command = batch.command
        batch.command = lambda path, rid, opts: [sys.executable, self.fake] + real_command(path, rid, opts)[2:]
        self.env = {k: os.environ.get(k) for k in ("FAKE_RUNS", "FAKE_SAVED", "FAKE_LEDGER")}
        os.environ.update(FAKE_RUNS=self.runs, FAKE_SAVED=SAVED, FAKE_LEDGER=self.ledger)

    def tearDown(self):
        pipeline.RUNS, self.server.RUNS, api.LEDGER, batch.command = self.saved
        for k, v in self.env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp)

    def video(self, name, folder=None):
        d = os.path.join(self.vids, folder) if folder else self.vids
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, name)
        with open(p, "wb") as f:
            f.write(name.encode())
        return p

    def calls(self):
        try:
            return [json.loads(l) for l in open(os.path.join(self.runs, "calls.jsonl"))]
        except OSError:
            return []

    def table(self, name="videos.csv"):
        with open(os.path.join(self.out, name)) as f:
            return list(csv.DictReader(f))


class Inputs(BatchCase):
    def test_folders_lists_and_files_in_order(self):
        b, a = self.video("b.mp4"), self.video("A.MOV")
        self.video("notes.txt")
        os.makedirs(os.path.join(self.vids, "sub"))
        self.video("c.mp4", "sub")      # sub-folders are not entered
        lst = os.path.join(self.tmp, "list.txt")
        with open(lst, "w") as f:
            f.write("# survey 2026\nvideos/sub/c.mp4\n\n" + b + "\n")
        self.assertEqual(batch.videos([self.vids, lst]), [a, b, os.path.join(self.vids, "sub", "c.mp4"), b])

    def test_run_ids_safe_unique_prefixed(self):
        paths = ["/x/st 1.mp4", "/y/st 1.mp4", "/z/ok-2.b.mov", "/w/st 1.mp4"]
        self.assertEqual(batch.run_ids(paths, "y26_"), ["y26_st_1", "y26_st_1_2", "y26_ok-2.b", "y26_st_1_3"])

    def test_command_adds_resume_but_not_with_skip_empty(self):
        cmd = self.saved[3]     # the real batch.command
        self.assertEqual(cmd("/v.mp4", "r", ["--zoom"])[2:], ["/v.mp4", "--id", "r", "--zoom", "--resume"])
        self.assertNotIn("--resume", cmd("/v.mp4", "r", ["--skip-empty"]))
        self.assertEqual(cmd("/v.mp4", "r", ["--resume"]).count("--resume"), 1)

    def test_id_option_is_refused(self):
        self.video("a.mp4")
        with self.assertRaises(SystemExit):
            batch.main([self.vids, "--out", self.out, "--", "--id", "x"])


class Tables(BatchCase):
    def test_every_video_has_a_line_and_maxn_all_is_the_per_video_export(self):
        ok, zero, bad = self.video("s004.mp4"), self.video("zero_empty.mp4"), self.video("bad_cut.mp4")
        rc = batch.main([ok, zero, bad, "--out", self.out, "--", "--zoom"])
        self.assertEqual(rc, 1)        # a failed video: non-zero exit, but the batch went on
        t = self.table()
        self.assertEqual([r["source_file"] for r in t], [ok, zero, bad])
        self.assertEqual([r["status"] for r in t], ["done", "done", "error"])
        self.assertEqual(t[1]["labels_counted"], "0")
        self.assertEqual(t[1]["maxn_by_label"], "")
        self.assertEqual(t[2]["error"], "FileNotFoundError: not cached: spark call")
        self.assertEqual(t[2]["labels_counted"], "")
        e = self.server.effective("s004")
        counted = {n: m["maxn"] for n, m in e["metrics"].items() if m["maxn"] > 0}
        self.assertEqual(int(t[0]["labels_counted"]), len(counted))
        self.assertTrue(t[0]["maxn_by_label"].startswith("caridean shrimp 14"))
        self.assertEqual(t[0]["analysed_s"], "12.0")
        for r in t:     # each run's status numbers; ledger rows tagged with the run id
            self.assertEqual((r["live_calls"], r["billed_usd"], r["ledger_usd"]), ("2", "0.25", "0.25"))
        with open(os.path.join(self.out, "maxn_all.csv")) as f:
            want = maxn_export.to_csv(e)
            self.assertEqual(f.read(), want)       # only s004 counted anything; same rows as its own export
        self.assertTrue(os.path.exists(os.path.join(self.out, "logs", "bad_cut.log")))
        with open(os.path.join(self.out, "logs", "bad_cut.log")) as f:
            self.assertIn("FileNotFoundError", f.read())

    def test_human_review_reaches_the_tables(self):
        ok = self.video("s004.mp4")
        batch.main([ok, "--out", self.out])
        with open(os.path.join(self.runs, "s004", "review.json"), "w") as f:
            json.dump({"d1z-center:8": "banded coral shrimp"}, f)
        batch.main([ok, "--out", self.out])     # kept, tables rebuilt from the reviewed run
        self.assertIn("banded coral shrimp", self.table()[0]["maxn_by_label"])
        self.assertIn("banded coral shrimp", {r["spark_common_name"] for r in self.table("maxn_all.csv")})

    def test_clashing_file_names_get_their_run_id_as_opcode(self):
        a, b = self.video("st.mp4", "a"), self.video("st.mp4", "b")
        c = self.video("other.mp4")
        batch.main([a, b, c, "--out", self.out])
        self.assertEqual([r["run_id"] for r in self.table()], ["st", "st_2", "other"])
        self.assertEqual({r["OpCode"] for r in self.table("maxn_all.csv")}, {"st", "st_2", "other"})

    def test_segments_and_earlier_tries_add_to_the_ledger_column(self):
        with open(self.ledger, "w") as f:
            # every try of a video counts here (t is not filtered: the video's budget, longvideo.video_spent, is)
            for rid, usd in (("v__S1", 0.5), ("v__P2", 0.25), ("v", 0.125), ("vv", 9.0), (None, 7.0)):
                f.write(json.dumps(dict(t=1, kind="sam", usd=usd, note="", **({"run": rid} if rid else {}))) + "\n")
            f.write("not json\n")
        self.assertEqual(batch.ledger_by_run(self.ledger), {"v": 0.875, "vv": 9.0})

    def test_a_video_not_reached_shows_no_old_numbers(self):
        p = self.video("s004.mp4")
        os.makedirs(os.path.join(self.runs, "s004"))
        json.dump(dict(stage="audit", live_calls=40, billed_usd=1.5), open(os.path.join(self.runs, "s004", "status.json"), "w"))
        os.makedirs(self.out)
        r = batch.write_tables(self.out, [p], ["s004"], {})[0]
        self.assertEqual((r["status"], r["live_calls"], r["billed_usd"], r["error"]), ("pending", "", "", ""))


class Rerun(BatchCase):
    def test_finished_videos_are_kept_and_the_rest_run_again(self):
        ok, zero, bad = self.video("s004.mp4"), self.video("zero_empty.mp4"), self.video("bad_cut.mp4")
        batch.main([ok, zero, bad, "--out", self.out, "--", "--zoom"])
        first = self.table()
        n = len(self.calls())
        batch.main([ok, zero, bad, "--out", self.out, "--", "--zoom"])
        self.assertEqual([c["rid"] for c in self.calls()[n:]], ["bad_cut"])     # no call for the finished ones
        t = self.table()
        self.assertEqual([r["status"] for r in t], ["kept", "kept", "error"])
        for a, b in zip(first[:2], t[:2]):
            self.assertEqual({k: v for k, v in a.items() if k not in ("status", "wall_s")},
                             {k: v for k, v in b.items() if k not in ("status", "wall_s")})
        self.assertEqual(t[2]["ledger_usd"], "0.5")     # both tries of the failed video

    def test_other_options_or_a_changed_source_run_again(self):
        ok = self.video("s004.mp4")
        batch.main([ok, "--out", self.out, "--", "--zoom"])
        batch.main([ok, "--out", self.out, "--", "--zoom", "--discover"])
        self.assertEqual(len(self.calls()), 2)
        with open(ok, "ab") as f:
            f.write(b"more")
        batch.main([ok, "--out", self.out, "--", "--zoom", "--discover"])
        self.assertEqual(len(self.calls()), 3)
        batch.main([ok, "--out", self.out, "--", "--zoom", "--discover"])
        self.assertEqual(len(self.calls()), 3)
        self.assertEqual(self.calls()[-1]["opts"], ["--zoom", "--discover", "--resume"])

    def test_a_run_finished_outside_the_batch_is_run_again_from_its_cache(self):
        ok = self.video("s004.mp4")
        os.makedirs(os.path.join(self.runs, "s004"))
        shutil.copy(SAVED, os.path.join(self.runs, "s004", "result.json"))
        json.dump(dict(stage="done"), open(os.path.join(self.runs, "s004", "status.json"), "w"))
        batch.main([ok, "--out", self.out])         # no batch.json: options unknown, so not trusted
        self.assertEqual(len(self.calls()), 1)


class Stop(BatchCase):
    def test_sigterm_stops_the_running_video_and_keeps_the_tables(self):
        ok, slow = self.video("s004.mp4"), self.video("slow.mp4")
        script = os.path.join(self.tmp, "run_batch.py")
        with open(script, "w") as f:
            f.write("import sys\nsys.path.insert(0, %r)\nsys.path.insert(0, %r)\n" % (ROOT, os.path.join(ROOT, "web"))
                    + "from fishcount import _pylib, api, batch, pipeline\nimport server\n"
                    + "pipeline.RUNS = server.RUNS = %r\napi.LEDGER = %r\n" % (self.runs, self.ledger)
                    + "real = batch.command\nbatch.command = lambda p, r, o: [sys.executable, %r] + real(p, r, o)[2:]\n" % self.fake
                    + "sys.exit(batch.main(sys.argv[1:]))\n")
        p = subprocess.Popen([sys.executable, script, ok, slow, "--out", self.out], stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True)
        pid_file = os.path.join(self.runs, "slow.pid")
        t = time.time()
        while not os.path.exists(pid_file) and time.time() - t < 60:
            time.sleep(0.1)
        time.sleep(0.2)
        child = int(open(pid_file).read())
        p.send_signal(signal.SIGTERM)
        out = p.communicate(timeout=60)[0]
        self.assertEqual(p.returncode, 130, out)
        self.assertIn("batch stopped", out)
        time.sleep(0.2)
        self.assertFalse(os.path.exists(f"/proc/{child}") and open(f"/proc/{child}/stat").read().split()[2] != "Z",
                         "the video's process outlived the batch")
        self.assertEqual([r["status"] for r in self.table()], ["done", "pending"])


if __name__ == "__main__":
    unittest.main()
