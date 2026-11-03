import os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fishcount import gapfind as g


def run(frames, labels):
    return dict(tracks={t: dict(label=l) for t, l in labels.items()}, auto_labels={}, verdicts={},
                frames={str(f): [dict(track=t, box=b) for t, b in v] for f, v in frames.items()})


class GapFind(unittest.TestCase):
    def setUp(self):
        # two annotated frames; the human boxed fish A only; the run also tracks fish B (track p:1) and a rejected track
        self.gt = {0: [(0, 0, 100, 100, "luderick")], 1: [(10, 0, 110, 100, "luderick")]}
        self.res = run({0: [("p:0", [2, 2, 98, 98]), ("p:1", [300, 300, 380, 360]), ("p:2", [600, 0, 650, 40])],
                        1: [("p:0", [12, 0, 108, 100]), ("p:1", [310, 300, 390, 360])],
                        2: [("p:1", [320, 300, 400, 360])]},              # frame 2 is not annotated: ignored
                       {"p:0": "luderick", "p:1": "fish (unidentified)", "p:2": None})

    def test_find_gaps(self):
        gaps = g.find_gaps(self.res, self.gt)
        self.assertNotIn("p:2", gaps)                                     # not counted -> never on the sheet
        self.assertEqual(gaps["p:0"]["unmatched"], [])
        self.assertEqual(gaps["p:0"]["matched"], 2)
        self.assertEqual([f for f, _ in gaps["p:1"]["unmatched"]], [0, 1])
        self.assertEqual(gaps["p:1"]["raises"], 2)

    def test_one_to_one_matching(self):
        # two run boxes on one human box: only one can match, the other is a gap
        res = run({0: [("a", [0, 0, 100, 100]), ("b", [5, 5, 100, 100])]}, {"a": "fish", "b": "fish"})
        gaps = g.find_gaps(res, {0: [(0, 0, 100, 100, "fish")]})
        self.assertEqual(sum(len(e["unmatched"]) for e in gaps.values()), 1)

    def test_spread(self):
        self.assertEqual(g.spread([1, 2]), [1, 2])
        self.assertEqual(g.spread(list(range(10))), [0, 4, 9])           # middle index 4.5 rounds to even

    def test_apply(self):
        key = dict(cards=[dict(n=1, kind="gap", clip="c", track="p:1", label="fish (unidentified)",
                               boxes=[(0, [300, 300, 380, 360]), (1, [310, 300, 390, 360])]),
                          dict(n=2, kind="gap", clip="c", track="p:9", label="fish", boxes=[(1, [500, 0, 540, 30])]),
                          dict(n=3, kind="gap", clip="c", track="p:8", label="fish", boxes=[(0, [700, 0, 740, 30])]),
                          dict(n=4, kind="control", clip="c", track="p:0", label="luderick", boxes=[])])
        fixed, s = g.apply(key, {"1": "O", "2": "D", "3": "P", "4": "O"}, {"c": self.gt})
        self.assertEqual(s["added_boxes"], 2)
        self.assertEqual(len(fixed["c"][1]), 2)
        self.assertTrue(fixed["c"][1][1][4].endswith(g.ADDED))
        self.assertEqual(s["clips"]["c"], dict(maxn_before=1, maxn_after=2))
        self.assertEqual([r["n"] for r in s["redraw"]], [3])
        self.assertEqual(s["controls"], {"4": "O"})
        self.assertEqual(len(self.gt[1]), 1)                               # the input is not modified

    def test_roundtrip_format(self):
        import json, tempfile
        d = tempfile.mkdtemp()
        p = os.path.join(d, "gt.json")
        json.dump(dict(frames={"0": [[1, 2, 3, 4, "x"]]}, n_frames=5), open(p, "w"))
        gt = g.load_gt(p)
        self.assertEqual(gt, {0: [(1, 2, 4, 6, "x")]})
        g.dump_gt(gt, 5, os.path.join(d, "o.json"))
        self.assertEqual(json.load(open(os.path.join(d, "o.json"))), json.load(open(p)))


if __name__ == "__main__":
    unittest.main()
