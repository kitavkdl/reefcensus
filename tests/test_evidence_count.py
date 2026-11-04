"""render.evidence_split (no network): the count burned into a label's evidence frame is that label's MaxN, with the
same label rule as tracks.metrics (11/4: it printed every label's boxes summed, s004 nautilus "count 11" beside
"chambered nautilus: 1")."""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fishcount import render, tracks


class EvidenceCount(unittest.TestCase):
    def test_count_is_the_labels_maxn(self):
        trk = {"T1": {"label": "fish", "frames": [0]}, "T2": {"label": "fish", "frames": [0]},
               "T3": {"label": "nautilus", "frames": [0]}, "T4": {"label": "fish", "frames": [0]},
               "T5": {"label": "fish", "frames": [0]}}
        labels = {"T1": "luderick", "T2": "fish (unidentified)", "T4": None}     # T3, T5: no verdict, own label
        box = [0, 0, 10, 10]
        frames = {0: [dict(track=t, box=box) for t in trk]}
        result = dict(tracks=trk, auto_labels=labels, frames={"0": frames[0]})
        m = tracks.metrics(frames, trk, 1, 5, labels)
        for name, mm in m.items():
            mine, others = render.evidence_split(result, 0, name)
            self.assertEqual(len(mine), mm["maxn"], name)
            self.assertEqual(len(mine) + len(others), 4)        # T4 (rejected) is in neither
        self.assertEqual({k["track"] for k in render.evidence_split(result, 0, "fish")[0]}, {"T5"})


if __name__ == "__main__":
    unittest.main()
