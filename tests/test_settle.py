"""Which queued tracks can still change a count (fishcount/settle.py). No network, $0.
Run: python3 -m unittest discover -s tests -v"""
import glob, json, os, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "report", "paper", "scripts"))
from fishcount import _pylib  # noqa: F401
from fishcount import pipeline, settle

B = [0, 0, 10, 10]


def toy():
    """fish: A sure (0.9) in frames 2-3; B queued (0.5) and D confidently rejected, both with A in frame 3; G queued,
    alone in frame 0, before A; C queued, alone in frame 5, after A."""
    tracks = {t: dict(label="fish", source="p0", first=0, last=5, n=1) for t in "ABCDG"}
    v = lambda ok, c: dict(is_target=ok, confidence=c, species="unknown", name="T", reason="")
    verdicts = dict(A=v(True, 0.9), B=v(True, 0.5), C=v(True, 0.5), D=v(False, 0.9), G=v(True, 0.5))
    frames = {"0": [dict(track="G", box=B)], "2": [dict(track="A", box=B)],
              "3": [dict(track=t, box=B) for t in "ABD"], "5": [dict(track="C", box=B)]}
    res = dict(tracks=tracks, verdicts=verdicts, frames=frames, video=dict(n_frames=6, fps=5.0, width=10, height=10))
    res["auto_labels"] = pipeline.auto_labels(tracks, verdicts)
    return res


def wide():
    """Twelve queued fish together in frame 1 and nothing sure: every track ties on (upper count, frame)."""
    ids = ["q%02d" % i for i in range(12)]
    tracks = {t: dict(label="fish", source="p0", first=1, last=1, n=1) for t in ids}
    verdicts = {t: dict(is_target=True, confidence=0.5, species="unknown", name="T", reason="") for t in ids}
    res = dict(tracks=tracks, verdicts=verdicts, frames={"1": [dict(track=t, box=B) for t in ids]},
               video=dict(n_frames=2, fps=5.0, width=10, height=10))
    res["auto_labels"] = pipeline.auto_labels(tracks, verdicts)
    return res


class Decisive(unittest.TestCase):
    def test_only_tracks_that_can_move_maxn_or_first_arrival_are_asked(self):
        res = toy()
        self.assertEqual(res["auto_labels"]["D"], None)                    # confidently rejected: not counted
        d = settle.decisive(res)
        self.assertEqual(set(d), {"B", "D", "G"})                          # C can change nothing
        self.assertEqual(sorted(d[t] for t in "BD"), [1, 2])               # frame 3 can reach 3: asked first
        self.assertEqual(d["G"], 3)                                        # first arrival only: after the MaxN ones

    def test_ties_have_a_fixed_order(self):
        """Tracks with the same score are asked earliest first appearance first, then by track id, so the order does
        not depend on Python's per-process string hashing (it did: set iteration order, LONG1 asked 52-55 answers)."""
        self.assertEqual(settle.decisive(toy())["B"], 1)                   # B and D tie in frame 3: id order
        code = ("import sys; sys.path.insert(0, %r); sys.path.insert(0, %r); from fishcount import _pylib; "
                "import test_settle; from fishcount import settle; print(settle.decisive(test_settle.wide()))"
                % (ROOT, os.path.join(ROOT, "tests")))
        import subprocess
        outs = {subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                               env=dict(os.environ, PYTHONHASHSEED=str(s))).stdout for s in range(4)}
        self.assertEqual(len(outs), 1, outs)
        self.assertTrue(next(iter(outs)).startswith("{"))

    def test_answers_close_the_range(self):
        res = toy()
        self.assertEqual(set(settle.decisive(res, dict(B="fish (unidentified)"))), {"D", "G"})
        self.assertEqual(set(settle.decisive(res, dict(B=None, D=None))), {"G"})   # frame 3 now holds only A
        self.assertEqual(settle.decisive(res, dict(B=None, D=None, G=None)), {})

    def test_a_restored_track_joins_the_unidentified_row(self):
        self.assertEqual(settle.accept_label(toy(), "D"), "fish (unidentified)")

    def test_stopping_early_gives_the_numbers_of_answering_everything(self):
        import settle_sim
        runs = sorted(glob.glob(os.path.join(ROOT, "demo", "runs", "cr11_s00?", "result.json")))
        self.assertTrue(runs)
        for p in runs:
            out = settle_sim.run_one(json.load(open(p)))
            for rule in settle_sim.RULES:
                self.assertTrue(out[rule]["same"], (p, rule))
                self.assertLessEqual(out[rule]["asked"], out["queue"])


if __name__ == "__main__":
    unittest.main()
