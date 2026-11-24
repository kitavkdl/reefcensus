"""The static demo (demo/static_review.js, run with node) gives the same counts, ranges, queue order and both CSVs as the
server (web/server.py effective, export_csv; fishcount/maxn_export) for the same review steps, on every demo run.
Its first screen (demo/static_shot.js) shows the same rows, the frame of the clicked row and the queue track the review
screen shows first, at every one of those steps, and the built page redraws it through the drawRun hook.
Skipped without node. No network, $0."""
import contextlib, glob, io, json, os, shutil, subprocess, sys, tempfile, unittest
from urllib.parse import quote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "demo"))
import build_static            # noqa: E402  (imports web/server.py)
server = build_static.server
RUNS = sorted(glob.glob(os.path.join(ROOT, "demo", "runs", "cr*_s00*")))
NODE = """const R = require(process.argv[1]); const S = require(process.argv[2]); const fs = require("fs");
const inp = JSON.parse(fs.readFileSync(0, "utf8")); let run = R.effective(inp.run, inp.run.review || {}); const out = [];
const shot = (e) => { const rs = S.rows(e); return { rows: rs, ask: (S.nextAsk(e) || {}).track || null, input: S.inputLine(e),
  sel: rs.map((r) => S.select(e, r.name, null)), gone: S.select(e, "no such row", null) }; };
const snap = (e) => { const j = JSON.parse(JSON.stringify(e)); delete j._static;
  j.renames = j.renames.map(({ id, at, ...r }) => r); return [j, R.exportCsv(e), R.globalArchiveCsv(e), shot(e)]; };
out.push(snap(run));
for (const [t, l] of inp.actions) {
  if (t !== "__rename__") run = R.review(run, t, l);
  else run = R.renameGroup(run, "undo" in l ? { undo: run.renames[l.undo].id } : l);     // undo by position: ids differ
  out.push(snap(run));
}
console.log(JSON.stringify(out));"""


def snap(rid):
    e = server.effective(rid)
    j = json.loads(json.dumps(e))
    j["renames"] = [{k: v for k, v in r.items() if k not in ("id", "at")} for r in j["renames"]]   # random id, clock
    return [j, server.export_csv(rid), server.maxn_export.to_csv(e, None)]


def shot_want(e):
    """What demo/static_shot.js must show for effective() e, by web/app.js's rules: order() and hidden() for the rows,
    countRow() for the big number and the range, the evidence file of the clicked row, and drawQueue()'s first item
    (open and ranked first, else the first open one; server.effective already sorts the queue that way)."""
    kept = [(n, m) for n, m in e["metrics"].items() if not (m["maxn"] == 0 and n.endswith(" (unidentified)"))]
    kept.sort(key=lambda kv: (e["origin"].get(kv[0]) != "asked", -kv[1]["maxn"], kv[0]))
    rows = []
    for n, m in kept:
        hi = m["maxn_upper"] if m.get("maxn_upper") is not None else m["maxn"]
        lo = m.get("maxn_confirmed")
        rows.append(dict(name=n, origin=e["origin"].get(n), big=("≥" if m.get("lower_bound") else "") + str(m["maxn"]),
                         range=f"{lo}–{hi}" if lo is not None and lo < hi else None, first_time=m["first_time"],
                         maxn_time=m["maxn_time"], maxn_frame=m["maxn_frame"], evidence=m.get("evidence") or None,
                         evidence_stale=bool(m.get("evidence_stale"))))
    sel = [dict(name=r["name"], big=r["big"], time=r["maxn_time"], stale=r["evidence_stale"],
                img=f"runs/{quote(e['id'], safe='')}/{quote(r['evidence'], safe='')}" if r["evidence"] else None,
                noFrame=not r["evidence"], renamed=any(x["to"] == r["name"] for x in e.get("renames") or []),
                playFrame=r["maxn_frame"]) for r in rows]
    q = e["queue"]
    ask = next((x for x in q if not x["reviewed"] and x["rank"] is not None), None) or next((x for x in q if not x["reviewed"]), None)
    v = e.get("video") or {}
    secs = f"a {int(v['n_frames'] / v['fps'] + 0.5)} s " if v.get("fps") else "a "      # Math.round
    words = ", ".join(f"“{w}”" for _, w in e.get("prompts") or [])
    src = f" ({e['source']})" if e.get("source") else ""
    return dict(rows=rows, ask=ask["track"] if ask else None, sel=sel, gone=sel[0] if sel else None,
                input=f"Video in: {secs}deep-sea clip{src} · told to count: {words}")


@unittest.skipUnless(shutil.which("node") and RUNS, "node or demo runs missing")
class StaticReviewMatchesServer(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old = server.RUNS
        server.RUNS = self.tmp

    def tearDown(self):
        server.RUNS = self.old
        shutil.rmtree(self.tmp)

    def compare(self, rid, page, actions, want):
        out = subprocess.run(["node", "-e", NODE, os.path.join(ROOT, "demo", "static_review.js"), os.path.join(ROOT, "demo", "static_shot.js")],
                             input=json.dumps(dict(run=page, actions=actions)), capture_output=True, text=True, check=True).stdout
        got = json.loads(out)
        self.assertEqual(len(got), len(want))
        for i, (g, w) in enumerate(zip(got, want)):
            with self.subTest(run=rid, step=i, action=actions[i - 1] if i else None):
                self.assertEqual(g[0], w[0])
                self.assertEqual(g[1], w[1])
                self.assertEqual(g[2], w[2])
                self.assertEqual(g[3], shot_want(w[0]))     # the first screen: rows, clicked-row frames, queue track

    def copy(self, src):
        rid = os.path.basename(src)
        os.makedirs(os.path.join(self.tmp, rid))
        for f in os.listdir(src):       # result.json and the evidence frames are all effective() reads
            if f == "result.json" or f.startswith("evidence_"):
                shutil.copy(os.path.join(src, f), os.path.join(self.tmp, rid, f))
        return rid

    def test_group_renames(self):
        """Rename all (web/server.py rename_group) on every demo run: merge a row into another with and without the
        check box, a track review in between, a reverse rule, Undo of any rule by position, a page packed with a rule."""
        for src in RUNS:
            rid = self.copy(src)
            e0 = server.effective(rid)
            rows = sorted(e0["metrics"], key=lambda n: (e0["metrics"][n]["maxn"], n))
            if len(rows) < 2:
                continue
            small, big = rows[0], rows[-1]
            server.rename_group(rid, {"from": small, "to": "Packed Name "})        # in the page from the start (pack_runs)
            e1 = server.effective(rid)
            page = dict(e1, _static=build_static.static_data(rid, e1))
            want, actions = [snap(rid)], []

            def act(t, l):
                actions.append([t, l])
                if t == "__rename__":
                    server.rename_group(rid, {"undo": server.effective(rid)["renames"][l["undo"]]["id"]} if "undo" in l else l)
                else:
                    server._save_review(rid, {t: l})
                want.append(snap(rid))

            act("__rename__", {"from": big, "to": "packed name", "accept": False})
            q = [x for x in server.effective(rid)["queue"] if not x["reviewed"]]
            if q:
                act(q[0]["track"], q[0]["yes_label"])
            mid = sorted(server.effective(rid)["metrics"])[0]
            act("__rename__", {"from": mid, "to": "  Red Crabs ", "accept": True})
            act("__rename__", {"from": "red crabs", "to": mid, "accept": False})     # reverse rule, not an Undo
            act("__rename__", {"undo": 1})
            while server.effective(rid)["renames"]:
                act("__rename__", {"undo": 0})
            self.compare(rid, page, actions, want)

    def test_group_renames_on_the_synthetic_run(self):
        """tests/test_group_rename.py's run: a crowd lower bound kept by a rename, and a queue order the rename changes
        (no demo run has either)."""
        sys.path.insert(0, os.path.join(ROOT, "tests"))
        import test_group_rename as g
        rid = "syn"
        os.makedirs(os.path.join(self.tmp, rid))
        with open(os.path.join(self.tmp, rid, "result.json"), "w") as f:
            json.dump(g.synthetic(), f)
        e0 = server.effective(rid)
        page = dict(e0, _static=build_static.static_data(rid, e0))
        want, actions = [snap(rid)], []
        for body in ({"from": g.UNID, "to": g.ROCK, "accept": False}, {"undo": 0}, {"from": g.UNID, "to": g.ROCK, "accept": True}, {"undo": 0}):
            actions.append(["__rename__", body])
            server.rename_group(rid, {"undo": server.effective(rid)["renames"][0]["id"]} if "undo" in body else body)
            want.append(snap(rid))
        self.assertTrue(want[1][0]["metrics"][g.ROCK].get("lower_bound"))
        self.compare(rid, page, actions, want)

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
        StaticReviewMatchesServer.compare(self, rid, page, actions, want)     # test_split borrows run_one with its own self
        return actions

    def test_every_demo_run(self):
        for src in RUNS:
            self.run_one(src)

    def test_one_yes_stays_inside_the_range(self):
        """A "Yes" on any one open queued track lands inside the range shown before it (s004 T6: caridean 14 -> 15 <= 16)."""
        for src in RUNS:
            rid = os.path.basename(src)
            os.makedirs(os.path.join(self.tmp, rid))
            shutil.copy(os.path.join(src, "result.json"), os.path.join(self.tmp, rid))
            before = server.effective(rid)
            for q in [q for q in before["queue"] if not q["reviewed"]]:
                server._save_review(rid, {q["track"]: q["yes_label"]})
                for name, m in server.effective(rid)["metrics"].items():
                    if name in before["metrics"]:
                        b = before["metrics"][name]
                        self.assertTrue(b["maxn_confirmed"] <= m["maxn"] <= b["maxn_upper"], (rid, q["track"], name))
                server._save_review(rid, {q["track"]: "__undo__"})


@unittest.skipUnless(RUNS, "demo runs missing")
class StaticShotBuild(unittest.TestCase):
    """The built page: the first screen sits between the top bar and the review screen, its script loads between
    review.js and app.js, and the drawRun hook is there once and really calls StaticShot.draw with state.run."""
    @classmethod
    def setUpClass(cls):
        cls.out = tempfile.mkdtemp()
        old = build_static.OUT, server.RUNS
        build_static.OUT = cls.out
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                build_static.main()
        finally:
            build_static.OUT, server.RUNS = old

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.out)

    def read(self, *p):
        with open(os.path.join(self.out, *p)) as f:
            return f.read()

    def test_page(self):
        h = self.read("index.html")
        self.assertEqual(h.count('<section class="shot"'), 1)
        self.assertLess(h.index('<header class="bar"'), h.index('<section class="shot"'))
        self.assertLess(h.index('<section class="shot"'), h.index('<main class="grid"'))
        self.assertLess(h.index("</main>"), h.index('id="heroTitle"'))          # the old landing text, under the review screen
        self.assertLess(h.index("static/review.js"), h.index("static/shot.js"))
        self.assertLess(h.index("static/shot.js"), h.index("static/app.js"))
        self.assertTrue(os.path.isfile(os.path.join(self.out, "static", "shot.js")))
        paths = [os.path.join(d, f).lower() for d, _, fs in os.walk(self.out) for f in fs]
        self.assertFalse([p for p in paths if "tnc" in p])                         # a partner's shared footage never goes public

    @unittest.skipUnless(shutil.which("node"), "node missing")
    def test_hook_redraws_the_first_screen(self):
        hooks = [l for l in self.read("static", "app.js").splitlines() if l.startswith("/* static-shot hook */")]
        self.assertEqual(len(hooks), 1)
        code = ('const calls = [], drawn = []; var state = { run: { id: "R" } }; var StaticShot = { draw: (r) => drawn.push(r) };\n'
                'function drawRun(w) { calls.push(w); }\n' + hooks[0] + '\ndrawRun(false); state.run = { id: "S" }; drawRun(true);\n'
                'console.log(JSON.stringify([calls, drawn]));')
        out = subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True).stdout
        self.assertEqual(json.loads(out), [[False, True], [{"id": "R"}, {"id": "S"}]])


if __name__ == "__main__":
    unittest.main()
