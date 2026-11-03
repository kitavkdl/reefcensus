"""Review-screen rules written in web/app.js, run with node on the real source text (skipped without node). No network, $0."""
import json, os, re, shutil, subprocess, unittest

APP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web", "app.js")


def js(expr, run):
    src = open(APP).read()
    parts = [re.search(r"^const hidden = .*?;\n", src, re.M | re.S).group(0),
             re.search(r"^const groupParts = .*?;\n(?=\n)", src, re.M | re.S).group(0)]
    out = subprocess.run(["node", "-e", "\n".join(parts) + f"\nconst run = {json.dumps(run)};\nconsole.log(JSON.stringify({expr}));"],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


@unittest.skipUnless(shutil.which("node"), "node not installed")
class GroupBlock(unittest.TestCase):
    def test_empty_unidentified_labels_are_left_out_of_the_group_line(self):
        run = dict(metrics={"chambered nautilus": dict(maxn=3, curve=[0, 3]), "nautilus (unidentified)": dict(maxn=0, curve=[0, 0]),
                            "crab (unidentified)": dict(maxn=2, curve=[0, 1]), "fish": dict(maxn=0, curve=[0, 0])})
        m = dict(maxn_frame=1, labels=["chambered nautilus", "nautilus (unidentified)", "crab (unidentified)", "fish", "gone"])
        got = js("groupParts(run, " + json.dumps(m) + ")", run)
        # zero-count "(unidentified)" dropped; a counted "(unidentified)" row, a zero plain label and an unknown label stay
        self.assertEqual(got, ["3 chambered nautilus", "1 crab (unidentified)", "0 fish", "0 gone"])


if __name__ == "__main__":
    unittest.main()
