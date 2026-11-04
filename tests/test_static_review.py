"""The static demo (demo/static_review.js, run with node) gives the same counts, ranges, queue order and both CSVs as the
server (web/server.py effective, export_csv; fishcount/maxn_export) for the same review steps, on every demo run.
Skipped without node. No network, $0."""
import glob, json, os, shutil, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "demo"))
import build_static            # noqa: E402  (imports web/server.py)
server = build_static.server
RUNS = sorted(glob.glob(os.path.join(ROOT, "demo", "runs", "cr*_s00*")))
NODE = """const R = require(process.argv[1]); const fs = require("fs");
const inp = JSON.parse(fs.readFileSync(0, "utf8")); let run = R.effective(inp.run, inp.run.review || {}); const out = [];
const snap = (e) => { const j = JSON.parse(JSON.stringify(e)); delete j._static; return [j, R.exportCsv(e), R.globalArchiveCsv(e)]; };
out.push(snap(run));
for (const [t, l] of inp.actions) { run = R.review(run, t, l); out.push(snap(run)); }
console.log(JSON.stringify(out));"""


def snap(rid):
    e = server.effective(rid)
    return [json.loads(json.dumps(e)), server.export_csv(rid), server.maxn_export.to_csv(e, None)]


@unittest.skipUnless(shutil.which("node") and RUNS, "node or demo runs missing")
class StaticReviewMatchesServer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old = server.RUNS
        server.RUNS = self.tmp

    def tearDown(self):
        server.RUNS = self.old
        shutil.rmtree(self.tmp)

    def run_one(self, src):
        rid = os.path.basename(src)
        os.makedirs(os.path.join(self.tmp, rid))
        for f in os.listdir(src):       # result.json and the evidence frames are all effective() reads
            if f == "result.json" or f.startswith("evidence_"):
                shutil.copy(os.path.join(src, f), os.path.join(self.tmp, rid, f))
        e0 = server.effective(rid)
        page = dict(e0, _static=build_static.static_data(rid, e0))
        want, actions = [snap(rid)], []

        def act(t, l):
            actions.append([t, l])
            server._save_review(rid, {t: l})
            want.append(snap(rid))

        open_ = lambda: [q for q in server.effective(rid)["queue"] if not q["reviewed"]]
        steps = [lambda q: (q["track"], q["yes_label"]), lambda q: (q["track"], None),
                 lambda q: (q["track"], "  Red Crabs on sand "), lambda q: (q["track"], "=fish, maybe")]
        for step in steps:
            if open_():
                act(*step(open_()[0]))
        if actions:
            act(actions[0][0], "__undo__")
        for q in open_():               # everything answered: no range left, nothing decisive
            act(q["track"], q["yes_label"])
        for t in list(server.effective(rid)["review"]):
            act(t, "__undo__")
        self.assertGreater(len(actions), 2, rid)
        out = subprocess.run(["node", "-e", NODE, os.path.join(ROOT, "demo", "static_review.js")],
                             input=json.dumps(dict(run=page, actions=actions)), capture_output=True, text=True, check=True).stdout
        got = json.loads(out)
        self.assertEqual(len(got), len(want))
        for i, (g, w) in enumerate(zip(got, want)):
            with self.subTest(run=rid, step=i, action=actions[i - 1] if i else None):
                self.assertEqual(g[0], w[0])
                self.assertEqual(g[1], w[1])
                self.assertEqual(g[2], w[2])
        return actions

    def test_every_demo_run(self):
        for src in RUNS:
            self.run_one(src)


if __name__ == "__main__":
    unittest.main()
