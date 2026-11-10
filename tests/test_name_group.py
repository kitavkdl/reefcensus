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


NAMES = ("haddock", "pollack / saithe", "lionfish", "needlefish", "damselfish", "whitetip reef shark", "catshark",
         "jellyfish", "box jellyfish", "starfish", "cuttlefish", "crayfish", "shellfish", "painted sweetlips",
         "caridean shrimp", "crab on a starfish", "seaweed", "fish (unidentified)", "barracuda", "union jack",
         "sand lance", "", "sea star", "ocean sunfish")


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
