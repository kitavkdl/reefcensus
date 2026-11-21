"""--skip-people: a discovery that names people or a boat and no animal is not searched for (no network, no spend).
11/21 night, LONG1_cr9 S1: "human on boat deck" -> 'person' on the whole segment and reversed (5,316 frames, $1.06)
plus 10 audits and 3 duplicate checks, and two rows ("human" MaxN 3, "person (unidentified)" 1) in a fish census."""
import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fishcount import pipeline


class People(unittest.TestCase):
    def test_people_and_boats(self):
        for o in [dict(what="human on boat deck", search_words=["person", "human", "man"]),
                  dict(what="scuba diver", search_words=["diver"]),
                  dict(what="boat hull", search_words=["boat", "hull"]),
                  dict(what="crew member's hand", search_words=["hand", "arm"])]:
            self.assertTrue(pipeline._is_people(o), o)

    def test_animals_stay(self):
        for o in [dict(what="chambered nautilus", search_words=["shell", "snail", "squid"]),
                  dict(what="small shrimp at bait bag", search_words=["shrimp"]),
                  dict(what="crab near diver's hand", search_words=["crab"]),     # the animal comes first
                  dict(what="sea lion", search_words=["seal", "sea lion"]),       # no person word
                  dict(what="dark lump on seabed", search_words=["crab", "shell", "starfish"]),
                  dict(what="unknown", search_words=["person", "fish"])]:          # one animal word is enough
            self.assertFalse(pipeline._is_people(o), o)

    def test_bad_input(self):
        self.assertFalse(pipeline._is_people({}))
        self.assertFalse(pipeline._is_people(dict(what=None, search_words=None)))


class Recover(unittest.TestCase):
    def test_an_unsearched_discovery_gets_no_second_look(self):
        # kept in `others` with no words (so its name still reaches the audit context): no zoom, back-fill or cell
        class Run:
            status = {"billed_usd": 0.0}
            def stage(self, *a): raise AssertionError("no second look expected")
        o = dict(what="human on boat deck", search_words=["person"], frames=[0, 531], approx_max_count=4, cells=["center"])
        log = pipeline.recover(Run(), "/r/clip.mp4", dict(n_frames=2658, width=1920, height=1080), [(o, [])],
                               [dict(what=o["what"], word=None, tried=[], maxn_full=0)], [], [], 5.0, True)
        self.assertEqual(log, [])

    def test_word_ladder_with_no_words_calls_nothing(self):
        self.assertEqual(pipeline.word_ladder(None, "/r/clip.mp4", 2658, [], True), (None, "", []))


if __name__ == "__main__":
    unittest.main()
