"""pipeline.shadow_pairs (no network): a dark track moving rigidly under a counted fish is its shadow; a dark fish
swimming beside another fish, or one not moving in step, is not."""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fishcount import pipeline


def box(cx, cy, w=50, h=78):
    return [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2]


def frames(rows):
    """rows: {frame: [(track, cx, cy)]}"""
    return {f: [dict(track=t, box=box(x, y)) for t, x, y in r] for f, r in rows.items()}


class ShadowPairs(unittest.TestCase):
    def test_tf52_t50(self):
        """TF_52 f34, f37: the shadow and the fish above-right keep offset (+70, -35) +- a few pixels."""
        fr = frames({34: [("T50", 755, 732), ("F", 825, 697)], 37: [("T50", 742, 718), ("F", 813, 680)]})
        got = pipeline.shadow_pairs(fr, ["T50"], ["T50", "F"])
        self.assertEqual(got["T50"][0], "F")

    def test_fish_side_by_side_not_shadow(self):
        """Two fish at the same height in step (a school): the companion is not above, so no pair."""
        fr = frames({f: [("D", 500 + 10 * f, 400), ("F", 580 + 10 * f, 402)] for f in range(5)})
        self.assertEqual(pipeline.shadow_pairs(fr, ["D"], ["D", "F"]), {})

    def test_loose_companion_not_shadow(self):
        """A fish above whose offset wanders (luderick 20190618_9: spread 0.21) is not a shadow caster."""
        fr = frames({f: [("D", 500 + 10 * f, 400), ("F", 560 + 10 * f + (25 if f % 2 else -25), 330)] for f in range(6)})
        self.assertEqual(pipeline.shadow_pairs(fr, ["D"], ["D", "F"]), {})

    def test_companion_must_be_counted_and_bright(self):
        fr = frames({34: [("D", 755, 732), ("E", 825, 697)], 37: [("D", 742, 718), ("E", 813, 680)]})
        self.assertEqual(pipeline.shadow_pairs(fr, ["D"], ["D"]), {})            # E not counted
        self.assertEqual(pipeline.shadow_pairs(fr, ["D", "E"], ["D", "E"]), {})  # E dark too

    def test_one_shared_frame_is_not_enough(self):
        fr = frames({34: [("D", 755, 732), ("F", 825, 697)], 37: [("D", 742, 718)]})
        self.assertEqual(pipeline.shadow_pairs(fr, ["D"], ["D", "F"]), {})


if __name__ == "__main__":
    unittest.main()
