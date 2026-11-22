"""A run that dies says so in its status.json (round 3, graduate-student and data-manager views): before, an
exception in the CLI or a batch left the last stage ("audit", "segments") in status.json, so a crashed run looked
like one still going and nobody (or no batch script) could tell which videos to run again. No network."""
import json, os, sys, tempfile, unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fishcount import longvideo, pipeline


def status(d):
    with open(os.path.join(d, "status.json")) as fh:
        return json.load(fh)


class ErrorStatus(unittest.TestCase):
    def setUp(self):
        self.runs = tempfile.mkdtemp()
        p = mock.patch.object(pipeline, "RUNS", self.runs)
        p.start()
        self.addCleanup(p.stop)

    def test_run_pipeline_failure_is_written(self):
        def boom(src, rid, *a, **k):
            pipeline.Run(rid).stage("audit", "auditing")
            raise ConnectionError("DNS failure")
        with mock.patch.object(pipeline, "_run_pipeline", boom):
            with self.assertRaises(ConnectionError):
                pipeline.run_pipeline("x.mp4", "r1")
        st = status(os.path.join(self.runs, "r1"))
        self.assertEqual(st["stage"], "error")
        self.assertEqual(st["error"], "ConnectionError: DNS failure")
        self.assertTrue(st["log"][-1].endswith("stopped: ConnectionError: DNS failure"))
        self.assertEqual(st["log"][0].split(" ", 1)[1], "auditing")      # what was there is kept
        self.assertIn("billed_usd", st)

    def test_failure_before_the_run_folder_exists(self):
        with mock.patch.object(pipeline, "_run_pipeline", mock.Mock(side_effect=ValueError("no frames"))):
            with self.assertRaises(ValueError):
                pipeline.run_pipeline("x.mp4", "r2")
        self.assertEqual(status(os.path.join(self.runs, "r2"))["error"], "ValueError: no frames")

    def test_success_is_unchanged(self):
        def ok(src, rid, *a, **k):
            pipeline.Run(rid).stage("done", "finished")
            return {"metrics": {}}
        with mock.patch.object(pipeline, "_run_pipeline", ok):
            self.assertEqual(pipeline.run_pipeline("x.mp4", "r3"), {"metrics": {}})
        st = status(os.path.join(self.runs, "r3"))
        self.assertEqual(st["stage"], "done")
        self.assertNotIn("error", st)

    def test_inner_failure_is_written_once(self):
        # the crowd-peak second pass calls run_pipeline inside run_pipeline: one "stopped" line, not two
        def inner(src, rid, *a, **k):
            pipeline.Run(rid).stage("crowd", "tiling")
            raise RuntimeError("SAM status response.failed")
        def outer(src, rid, *a, **k):
            with mock.patch.object(pipeline, "_run_pipeline", inner):
                return pipeline.run_pipeline(src, rid)
        with mock.patch.object(pipeline, "_run_pipeline", outer):
            with self.assertRaises(RuntimeError):
                pipeline.run_pipeline("x.mp4", "r4")
        st = status(os.path.join(self.runs, "r4"))
        self.assertEqual(sum("stopped:" in l for l in st["log"]), 1)

    def test_run_long_failure_is_written_to_the_video_folder(self):
        def boom(src, rid=None, *a, **k):
            os.makedirs(os.path.join(self.runs, rid))
            longvideo._status(os.path.join(self.runs, rid), id=rid, stage="segments", log=["10:00:00 segment S1 done"])
            raise MemoryError()
        with mock.patch.object(longvideo, "_run_long", boom):
            with self.assertRaises(MemoryError):
                longvideo.run_long("long.mp4", "v1")
        st = status(os.path.join(self.runs, "v1"))
        self.assertEqual((st["stage"], st["error"]), ("error", "MemoryError"))
        self.assertEqual(st["log"][0], "10:00:00 segment S1 done")

    def test_an_unreadable_status_is_replaced(self):
        d = os.path.join(self.runs, "r5")
        os.makedirs(d)
        with open(os.path.join(d, "status.json"), "w") as fh:
            fh.write('{"stage": "aud')
        with mock.patch.object(pipeline, "_run_pipeline", mock.Mock(side_effect=OSError("disk full"))):
            with self.assertRaises(OSError):
                pipeline.run_pipeline("x.mp4", "r5")
        self.assertEqual(status(d)["stage"], "error")


if __name__ == "__main__":
    unittest.main()
