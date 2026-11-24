"""D-UNID-F1 review-card marks (no network, $0): a queued unidentified track gets "Check needed, may be a real ..." when
the peak check called its box no animal, when Spark said no under 0.7, or when a moving kind hardly moves near the
edge while Spark was unsure; a long video's merged result finds its peak-check tracks; counts, ranges and the queue
are the same as without the marks."""
import json, os, shutil, sys, tempfile, unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "web"))
from fishcount import _pylib  # noqa: F401,E402
from fishcount import pipeline, tracks  # noqa: E402

N, FPS, W, H = 20, 5.0, 1920, 1080
U = "fish (unidentified)"


def moving(i, y):           # crosses the picture, 80 px a frame
    return [100 + 80 * i, y, 180 + 80 * i, y + 60]


def edge_still(i, y):       # sits at the left edge, a pixel of jitter
    return [10 + i % 2, y, 90 + i % 2, y + 60]


# track: (label, verdict, auto label, box(i) or None, frames)
TRACKS = {
    "p0:1": ("fish", dict(is_target=True, confidence=0.6), U, lambda i: moving(i, 100), range(N)),       # A
    "p0:2": ("fish", dict(is_target=True, confidence=0.6), U, lambda i: moving(i, 200), range(N)),       # A, no "said"
    "p0:3": ("fish", dict(is_target=True, confidence=0.6), U, lambda i: moving(i, 300), range(N)),       # rejected as a crab
    "p0:4": ("fish", dict(is_target=True, confidence=0.9), U, lambda i: moving(i, 400), range(N)),       # confident yes, not queued
    "p0:5": ("fish", dict(is_target=False, confidence=0.6), U, lambda i: moving(i, 500), range(N)),      # B
    "m1:1": ("fish", dict(is_target=False, confidence=0.6), None, lambda i: moving(i, 600), range(N)),   # uncounted
    "p0:6": ("fish", dict(is_target=False, confidence=0.6, species="cod"), "cod", lambda i: moving(i, 700), range(N)),  # named
    "p0:7": ("fish", dict(is_target=True, confidence=0.5), U, lambda i: edge_still(i, 100), range(12)),  # C
    "p0:8": ("seaweed", dict(is_target=True, confidence=0.5), "seaweed (unidentified)", lambda i: edge_still(i, 300), range(12)),
    "p0:9": ("fish", dict(is_target=True, confidence=0.5), U, lambda i: edge_still(i, 500), range(13)),  # still only when carried
    "p0:10": ("fish", dict(is_target=True, confidence=0.5), U, lambda i: [900, 500, 980, 560], range(12)),  # still mid-picture
}


def result(prefix="", segment=None):
    frames, trk, verdicts, auto = {}, {}, {}, {}
    for t, (label, vd, al, box, fr) in TRACKS.items():
        T = prefix + t
        trk[T] = dict(label=label, source=prefix + t.split(":")[0])
        verdicts[T] = dict(vd, name=f"T{len(verdicts) + 1}")
        auto[T] = al
        for i in fr:
            k = dict(track=T, box=box(i))
            if t == "p0:9" and i >= 3:
                k["carried"] = True
            frames.setdefault(i, []).append(k)
    seg = dict(segment=segment) if segment else {}
    peak = [dict(label=U, frame=5, checked=4, kept=1, rejected=[dict(track="p0:1", box=[0, 0, 1, 1], said="rock"),
                                                                    dict(track="p0:2", box=[0, 0, 1, 1]),
                                                                    dict(track="p0:3", box=[0, 0, 1, 1], said="crab"),
                                                                    dict(track="p0:4", box=[0, 0, 1, 1], said="empty water")], **seg)]
    video = dict(n_frames=N, fps=FPS, width=W, height=H)
    return dict(id="r", source="x.mp4", video=video, tracks=trk, verdicts=verdicts, auto_labels=auto, peak_checks=peak,
                frames={str(f): ks for f, ks in frames.items()}, metrics=tracks.metrics(frames, trk, N, FPS, auto))


class DoubtMarks(unittest.TestCase):
    def setUp(self):
        import server
        self.server, self.tmp = server, tempfile.mkdtemp()
        self.orig, server.RUNS = server.RUNS, self.tmp

    def tearDown(self):
        self.server.RUNS = self.orig
        shutil.rmtree(self.tmp)

    def put(self, res, rid="r"):
        os.makedirs(os.path.join(self.tmp, rid))
        with open(os.path.join(self.tmp, rid, "result.json"), "w") as f:
            json.dump(res, f)
        return rid

    def test_marks(self):
        kinds = {t: k for t, (k, _) in pipeline.doubt_marks(result()).items()}
        self.assertEqual(kinds, {"p0:1": ["peak"], "p0:2": ["peak"], "p0:5": ["unsure_no"], "p0:7": ["still"]})

    def test_card_text(self):
        q = {x["track"]: x["reason"] for x in self.server.effective(self.put(result()))["queue"]}
        self.assertTrue(q["p0:1"].startswith('Check needed, may be a real fish: in peak frame 5 Spark called this box "rock", not an animal. '))
        self.assertIn("called this box not an animal. ", q["p0:2"])
        self.assertNotIn("None", q["p0:2"])
        self.assertIn("Spark said it is not one, but was unsure (60% sure). ", q["p0:5"])
        self.assertIn("may be a real fish resting: the box hardly moves for 2.2 s near the edge", q["p0:7"])
        for t in ("p0:3", "m1:1", "p0:6", "p0:8", "p0:9", "p0:10"):
            self.assertNotIn("Check needed", q.get(t, ""), t)
        self.assertNotIn("p0:4", q)     # a confident yes stays out of the queue, mark or not

    def test_long_video_segment_prefix(self):
        kinds = {t: k for t, (k, _) in pipeline.doubt_marks(result("S2:", "S2")).items()}
        self.assertEqual(kinds, {"S2:p0:1": ["peak"], "S2:p0:2": ["peak"], "S2:p0:5": ["unsure_no"], "S2:p0:7": ["still"]})

    def test_numbers_unchanged(self):
        rid = self.put(result())
        with_marks = self.server.effective(rid)
        with mock.patch.object(pipeline, "doubt_marks", lambda res: {}):
            without = self.server.effective(rid)
        self.assertTrue(any("Check needed" in q["reason"] for q in with_marks["queue"]))
        for q in with_marks["queue"] + without["queue"]:
            q["reason"] = ""
        self.assertEqual(with_marks, without)


if __name__ == "__main__":
    unittest.main()
