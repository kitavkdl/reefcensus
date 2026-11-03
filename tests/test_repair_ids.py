"""tracks.repair_ids (no network): SAM 3.1 shuffling a frame's ids is undone, and ordinary motion is left alone."""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fishcount import tracks


def box(cx, cy, s=60):
    return (cx - s / 2, cy - s / 2, cx + s / 2, cy + s / 2)


def dets(rows):
    """rows: {frame: [(id, cx, cy)]}"""
    return {f: [dict(id=i, box=box(x, y), conf=0.9) for i, x, y in r] for f, r in rows.items()}


def ids_at(out, f):
    return {(round((d["box"][0] + d["box"][2]) / 2), round((d["box"][1] + d["box"][3]) / 2)): d["id"] for d in out[f]}


class RepairIds(unittest.TestCase):
    def test_shifted_run_is_given_back(self):
        """TF_52 tile r1c1 frame 9: ids 12 and 13 sit on 11's and 12's fish, id 11 on a box seen nowhere near."""
        fish = {11: (1500, 470), 12: (930, 1110), 13: (450, 1130)}
        rows = {f: [(i, x, y) for i, (x, y) in fish.items()] for f in range(0, 9)}
        rows[9] = [(11, 75, 680), (12, 1500, 470), (13, 930, 1110)]
        rows[10] = [(i, x, y) for i, (x, y) in fish.items()]
        out = tracks.repair_ids(dets(rows))
        got = ids_at(out, 9)
        self.assertEqual(got[(1500, 470)], 11)
        self.assertEqual(got[(930, 1110)], 12)
        self.assertGreaterEqual(got[(75, 680)], 1000)           # the stray box is a track of its own
        self.assertEqual(ids_at(out, 10), ids_at(tracks.repair_ids(dets({10: rows[10]})), 10))
        self.assertEqual(sum(len(v) for v in out.values()), sum(len(r) for r in rows.values()))   # boxes untouched

    def test_new_id_on_the_fish_and_old_id_on_a_shadow(self):
        """TF_52 refill segment frame 34: the fish id 14 followed came as a new id 15; id 14 went to a shadow."""
        rows = {f: [(13, 1060, 830), (14, 830 - 4 * f, 705)] for f in range(0, 5)}
        rows[5] = [(13, 1062, 830), (14, 755, 900), (15, 808, 705)]
        rows[6] = [(13, 1064, 830), (14, 804, 705)]
        out = tracks.repair_ids(dets(rows))
        got = ids_at(out, 5)
        self.assertEqual(got[(808, 705)], 14)
        self.assertGreaterEqual(got[(755, 900)], 1000)

    def test_school_swimming_together_is_left_alone(self):
        """Small fish 30 px apart all moving 40 px a frame: nearest-last-position would reshuffle them, prediction does not."""
        rows = {f: [(i, 100 + 30 * i + 40 * f, 200) for i in range(6)] for f in range(10)}
        out = tracks.repair_ids({f: [dict(id=i, box=box(x, y, 25), conf=0.9) for i, x, y in r] for f, r in rows.items()})
        self.assertFalse(any("sam_id" in d for ds in out.values() for d in ds))

    def test_fish_that_stops_is_left_alone(self):
        rows = {f: [(1, 100 + 50 * f, 300)] for f in range(5)}
        rows.update({f: [(1, 300, 300)] for f in range(5, 9)})
        out = tracks.repair_ids(dets(rows))
        self.assertFalse(any("sam_id" in d for ds in out.values() for d in ds))

    def test_two_fish_crossing_keep_their_ids(self):
        rows = {f: [(1, 100 + 30 * f, 300), (2, 400 - 30 * f, 310)] for f in range(11)}
        out = tracks.repair_ids(dets(rows))
        self.assertFalse(any("sam_id" in d for ds in out.values() for d in ds))


if __name__ == "__main__":
    unittest.main()
