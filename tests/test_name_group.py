"""Coarse animal groups of Spark's names (no network, no spend). 11/9 outside data: Spark named fish the old word list
did not have, so they fell out of the "fish" total and out of the peak check's same-group rule:
Exeter G2 haddock 2 (group fish 6 without it), IMR BE10 "pollack / saithe" 5 (no fish row at all), FinPrint
"trevally jack" / "fusilier" / "jack" (no fish row in three of five clips)."""
import json, os, shutil, subprocess, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from fishcount import pipeline


def m(**maxn):
    """Per-label metrics with one curve each: label -> list of per-frame counts."""
    out = {}
    for k, c in maxn.items():
        name = k.replace("_", " ")
        out[name] = dict(curve=c, maxn=max(c), first_frame=0, tracks=max(c))
    return out


class NameGroup(unittest.TestCase):
    def test_outside_data_fish_names(self):
        for n in ("haddock", "pollack / saithe", "trevally jack", "fusilier", "jack", "atlantic cod",
                  "cod-like roundfish", "lionfish", "small demersal reef fish", "whitetip reef shark", "catshark",
                  "plaice", "mackerel", "wobbegong", "stingray"):
            self.assertEqual(pipeline.name_group(n), "fish", n)

    def test_list_words_survive_norm_label(self):
        # name_group compares norm_label(word) with the list, so a list word that norm_label changes never matches
        # ("sweetlips" -> "sweetlip" was listed as "sweetlips" and painted sweetlips stayed outside the fish total)
        for g, ws in pipeline.NAME_GROUPS.items():
            for w in ws:
                self.assertEqual(pipeline.norm_label(w), w, w)
        self.assertEqual(pipeline.name_group("painted sweetlips"), "fish")

    def test_fish_suffix_does_not_take_other_groups(self):
        self.assertEqual(pipeline.name_group("jellyfish"), "cnidarian")
        self.assertEqual(pipeline.name_group("starfish"), "echinoderm")
        self.assertEqual(pipeline.name_group("cuttlefish"), "cephalopod")
        self.assertEqual(pipeline.name_group("crayfish"), "crustacean")
        self.assertIsNone(pipeline.name_group("shellfish"))
        # report/paper/data/sam_agent/s002.json: SAM's agent said "crawfish" (a crayfish, not a fish)
        self.assertEqual(pipeline.name_group("crawfish"), "crustacean")
        self.assertEqual(pipeline.name_group("inkfish"), "cephalopod")
        self.assertIsNone(pipeline.name_group("nonfish debris"))

    def test_old_groups_unchanged(self):
        for n, g in (("caridean shrimp", "crustacean"), ("chambered nautilus", "cephalopod"), ("hagfish", "fish"),
                     ("luderick", "fish"), ("bream", "fish"), ("hermit crab", "crustacean"), ("sea urchin", "echinoderm"),
                     ("small red crab on seabed", "crustacean"), ("white bacterial mat", None), ("seaweed", None),
                     ("rock", None), ("bait", None), ("shell", None)):
            self.assertEqual(pipeline.name_group(n), g, n)

    def test_group_total_takes_haddock(self):
        # Exeter G2: cod 4, cod-like fish 5, haddock 2 named in the same school
        g = pipeline.group_metrics(m(cod=[4, 0], cod_like_fish=[0, 5], haddock=[0, 2]), fps=5)
        self.assertEqual(g["fish"]["maxn"], 7)
        self.assertIn("haddock", g["fish"]["labels"])

    def test_peak_check_keeps_other_fish(self):
        # a "cod" box that the peak check calls a haddock is still a fish: it stays and goes to the queue
        self.assertTrue(pipeline.same_group_answer("young haddock", "fish"))
        self.assertFalse(pipeline.same_group_answer("tail of a haddock", "fish"))

    def test_negated_answer_is_not_another_animal(self):
        # runs/demo_TF52d,g,h,i,j and cr_s004: these peak-check answers were kept as "another animal of the group" and
        # queued, because the head noun is the negated word ("... no fish")
        for said, g in (("blurry water no fish", "fish"), ("pipe structure no fish", "fish"),
                        ("blue pipe no shrimp", "crustacean"), ("seagrass, no fish", "fish"),
                        ("not a fish, kelp", "fish"), ("non-fish debris", "fish")):
            self.assertFalse(pipeline.same_group_answer(said, g), said)
        self.assertTrue(pipeline.same_group_answer("not a cod, other fish", "fish"))
        # outreach Exeter G1, peak check of a flatfish track: another fish, it stays and is queued
        self.assertTrue(pipeline.same_group_answer("elongate non-flatfish fish", "fish"))
        self.assertTrue(pipeline.same_group_answer("other fish", "fish"))
        self.assertEqual(pipeline.name_group("crab, not a shrimp"), "crustacean")
        self.assertIsNone(pipeline.name_group("non-fish debris"))
        self.assertEqual(pipeline.name_group("noaa survey fish"), "fish")      # "no" only as a word
        # 11/10 second review: the negation ends where the answer turns to what it is; "no-" in a hyphenated word
        for n, g in (("not a cod but a haddock", "fish"), ("not a fish but a crab", "crustacean"),
                     ("no-name fish", "fish"), ("not a shrimp, rather a crab", "crustacean"),
                     ("no fish, only a crab", "crustacean"), ("not a fish; instead a squid", "cephalopod"),
                     ("no animals except a crab", "crustacean")):
            self.assertEqual(pipeline.name_group(n), g, n)
        self.assertIsNone(pipeline.name_group("not a fish"))
        self.assertIsNone(pipeline.name_group("not-a-fish"))     # only "no-" makes a compound, not "not-"
        self.assertTrue(pipeline.same_group_answer("not a cod but a haddock", "fish"))
        self.assertFalse(pipeline.same_group_answer("not a fish but a crab", "fish"))
        # 11/10 third review: "no-" before an animal word is a negation ("no-fish zone"); "yet" / "just" turn too
        for n, g in (("no-fish", None), ("no-fish zone", None), ("no-name fish", "fish"), ("not-a-fish", None),
                     ("not a cod yet a haddock", "fish"), ("no fish just a crab", "crustacean"),
                     ("not just a fish", "fish"), ("no fish", None), ("not a fish but a crab", "crustacean")):
            self.assertEqual(pipeline.name_group(n), g, n)
        self.assertFalse(pipeline.same_group_answer("no-fish", "fish"))

    def test_plant_and_remains_answers_leave_the_peak(self):
        for said, g in (("fish skeleton", "fish"), ("shrimp moult", "crustacean"), ("seaweed near fish", "fish"),
                        ("algae on crab", "crustacean"), ("crab moults", "crustacean")):
            self.assertFalse(pipeline.same_group_answer(said, g), said)
        # the plant or the pipe is only where the animal is (runs/eval_fish_20190618_9, fx0_s004, cr10_s004,
        # imr_BE10_RA4_L5_ml)
        for said, g in (("Clear striped fish over seagrass", "fish"), ("Dark striped fish in seagrass", "fish"),
                        ("red crab by blue pipe", "crustacean"), ("shrimp alongside blue pipe structure", "crustacean"),
                        ("crab with eggs", "crustacean"), ("box contains algae urchin above", "echinoderm"),
                        ("kelp and small fish", "fish")):
            self.assertTrue(pipeline.same_group_answer(said, g), said)
        # 11/10 review: the plant rule fired with no place word or one outside the list; a plant named next to an
        # animal is only where the animal is
        for said, g in (("fish next to seagrass", "fish"), ("fish amongst kelp", "fish"), ("fish and seaweed", "fish"),
                        ("small fish among algae", "fish"), ("crab amidst seaweed", "crustacean")):
            self.assertTrue(pipeline.same_group_answer(said, g), said)
        for said, g in (("seaweed next to fish", "fish"), ("kelp frond amongst fish", "fish"),
                        ("skeleton next to fish", "fish")):
            self.assertFalse(pipeline.same_group_answer(said, g), said)
        # 11/10 second review: "with" / "past" put the animal in the box with the plant; remains head an "of"
        for said, g in (("kelp with fish", "fish"), ("seagrass with a fish in it", "fish"),
                        ("seaweed drifting past fish", "fish"), ("algae with a crab", "crustacean")):
            self.assertTrue(pipeline.same_group_answer(said, g), said)
        for said, g in (("skeleton of fish", "fish"), ("moult of a fish", "fish"), ("moult of a shrimp", "crustacean"),
                        ("fish remains", "fish"), ("remains of a crab", "crustacean"), ("seaweed on fish", "fish")):
            self.assertFalse(pipeline.same_group_answer(said, g), said)
        self.assertTrue(pipeline.same_group_answer("school of fish", "fish"))
        # 11/10 third review: remains after an "of" or a "with" are still the last noun of their phrase; "remains"
        # is the noun only at the end or before "of" ("the fish remains still" is the verb)
        for said, g in (("pile of fish skeleton", "fish"), ("bit of fish skeleton", "fish"),
                        ("school of fish skeleton", "fish"), ("kelp with fish skeleton", "fish"),
                        ("pair of crab moult", "crustacean"), ("skeleton of fish", "fish"), ("moult of a fish", "fish"),
                        ("skeleton next to fish", "fish"), ("fish skeleton", "fish"), ("fish remains", "fish"),
                        ("remains of a crab", "crustacean")):
            self.assertFalse(pipeline.same_group_answer(said, g), said)
        for said, g in (("school of fish", "fish"), ("kelp with fish", "fish"), ("fish next to seagrass", "fish"),
                        ("the fish remains still", "fish"), ("fish remains in place", "fish"),
                        # an animal before "with" / "past" is what the box is; the remains after it are only beside it
                        ("fish with skeleton", "fish"), ("fish with remains of food", "fish"),
                        ("crab with a moult next to it", "crustacean"), ("school of fish with skeleton", "fish"),
                        ("school of fish past skeleton", "fish")):
            self.assertTrue(pipeline.same_group_answer(said, g), said)

    def test_more_names(self):
        for n, g in (("nephrops", "crustacean"), ("norway lobster", "crustacean"), ("langoustine", "crustacean"),
                     ("hammerhead", "fish"), ("seastar", "echinoderm"), ("sandeel", "fish"), ("megrim", "fish"),
                     ("tarpon", "fish"), ("snook", "fish"), ("porgy", "fish"), ("octopuses", "cephalopod"),
                     ("octopi", "cephalopod"), ("nautiluses", "cephalopod")):
            self.assertEqual(pipeline.name_group(n), g, n)
        self.assertEqual(pipeline.norm_label("octopuses"), "octopus")
        self.assertEqual(pipeline.norm_label("nautiluses"), "nautilus")
        self.assertEqual(pipeline.norm_label("walruses"), "walrus")
        for w, want in (("houses", "house"), ("causes", "cause"), ("blouses", "blouse")):   # 11/10 review: "hous"
            self.assertEqual(pipeline.norm_label(w), want, w)
        # 51c7363's new list words become SAM's word for a name that holds one (it was the last word): on purpose,
        # short_name's rule is "known animal word first"; no saved discover name or site label changes (11/10)
        self.assertEqual(pipeline.short_name("haddock shoal"), "haddock")


class MissLabel(unittest.TestCase):
    def test_one_label_request(self):
        self.assertEqual(pipeline._miss_label("luderick", ["fish"]), "fish")
        self.assertEqual(pipeline._miss_label("crab", ["fish"]), "crab")
        # neither name in a group: they are not "the same group" (None == None relabelled anything)
        self.assertEqual(pipeline._miss_label("kelp", ["sole"]), "kelp")
        self.assertEqual(pipeline._miss_label("fish", ["fish", "crab"]), "fish")
        self.assertEqual(pipeline._miss_label("bream", ["fish", "crab"]), "bream")


NAMES = ("haddock", "pollack / saithe", "lionfish", "needlefish", "damselfish", "whitetip reef shark", "catshark",
         "jellyfish", "box jellyfish", "starfish", "cuttlefish", "crayfish", "shellfish", "painted sweetlips",
         "caridean shrimp", "crab on a starfish", "seaweed", "fish (unidentified)", "barracuda", "union jack",
         "sand lance", "", "sea star", "ocean sunfish", "crawfish", "nonfish debris", "non-fish debris",
         "blurry water no fish", "seagrass, no fish", "not a cod, other fish", "crab, not a shrimp", "octopuses",
         "nephrops", "noaa survey fish", "Not a fish (kelp)", "elongate non-flatfish fish", "pipe not fish",
         "not a cod but a haddock", "not a fish but a crab", "no-name fish", "not a shrimp, rather a crab",
         "no fish, only a crab", "not a fish; instead a squid", "no animals except a crab", "not only fish",
         "no fish however a crab", "not crab though maybe shrimp", "no fish although a crab", "not-a-fish",
         "no-fish", "no-fish zone", "not a cod yet a haddock", "no fish just a crab", "not just a fish", "no fish",
         "no-name fish zone", "no-crab", "éno fish", "ßnon-fish", "café no fish")


@unittest.skipUnless(shutil.which("node"), "node missing")
class StaticDemoNameGroup(unittest.TestCase):
    def test_js_matches_python(self):
        # demo/static_review.js recomputes group totals in the browser from pipeline._GROUP_OF; the "...fish" /
        # "...shark" rule lives in code, not in that table, so the JS has to carry it too
        js = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "demo", "static_review.js")
        prog = ("const R = require(process.argv[1]); const inp = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
                "console.log(JSON.stringify(inp.names.map((n) => R.nameGroup(n, inp.group_of))));")
        out = subprocess.run(["node", "-e", prog, js], input=json.dumps(dict(names=NAMES, group_of=pipeline._GROUP_OF)),
                             capture_output=True, text=True, check=True).stdout
        self.assertEqual(dict(zip(NAMES, json.loads(out))), {n: pipeline.name_group(n) for n in NAMES})


if __name__ == "__main__":
    unittest.main()
