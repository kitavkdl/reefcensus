"""Build a static copy of the review screen for the precomputed demo runs (demo/runs), for a static host.
No server, no model calls: the API answers are written as JSON files next to the page, the run folders are copied,
and the page is told it is static (live runs and saving reviews are switched off, with a note saying so).
  python3 demo/build_static.py [out_dir]     (default demo/site; test with: python3 -m http.server -d demo/site)"""
import json, os, re, shutil, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "web"))
import server   # noqa: E402  (web/server.py: run_list, effective, export_csv read server.RUNS at call time)

SRC = os.path.join(ROOT, "demo", "runs")
OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "demo", "site"))
REPO = "https://github.com/kitavkdl/reefcensus"
SITE = "https://kitavkdl.github.io/reefcensus/"
TITLE = "reefcensus counts what you asked for & finds what you didn't"
DESC = ("Baited-camera video in; MaxN for each animal, its first arrival & the frame behind each count out. "
        "Tracks it is unsure of go to a person. Four real deep-sea clips, every answer precomputed; review them in your browser.")
# link previews (Slack, X, iMessage) need absolute URLs; the favicon is an inline SVG so it needs no file
HEAD = (f'<meta name="description" content="{DESC}">\n'
        f'<meta property="og:type" content="website">\n<meta property="og:url" content="{SITE}">\n'
        f'<meta property="og:title" content="{TITLE}">\n<meta property="og:description" content="{DESC}">\n'
        f'<meta property="og:image" content="{SITE}static/og.png">\n'
        f'<meta property="og:image:width" content="1280">\n<meta property="og:image:height" content="640">\n'
        f'<meta name="twitter:card" content="summary_large_image">\n<meta name="twitter:title" content="{TITLE}">\n'
        f'<meta name="twitter:description" content="{DESC}">\n<meta name="twitter:image" content="{SITE}static/og.png">\n'
        '<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22%3E'
        '%3Ctext y=%22.9em%22 font-size=%2290%22%3E%F0%9F%90%9F%3C/text%3E%3C/svg%3E">\n')


# Landing block for judges: the claim in one line, then one card per run (asked vs. found, with its evidence frame).
# Captions are the measured facts from README "Discovery" (development clips, Barord et al. 2014).
# s002 first: the one clip where SAM tracked the requested word "fish", so a fish researcher does not open on "nothing"
ORDER = ["cr11_s002", "cr11_s004", "cr11_s003", "cr11_s001"]
CAPTION = {
    "cr11_s004": "A shrimp swarm & a hagfish & a nautilus at the bait. SAM found nothing for “hagfish”; Spark tried “eel” and it locked on.",
    "cr11_s003": "Three nautiluses (one partly behind another) counted as three.",
    "cr11_s002": "A nautilus and a small red crab nobody asked for.",
    "cr11_s001": "Night behind a wire trap. No word found them; moving pixels did. 4 counted; a paler 5th Spark was not sure of goes to a person. Its evidence frame is the first with 4 where three are distant shapes on the floor; near the end of the clip all four are plain.",
}
SHOW = {"cr11_s004": "caridean shrimp", "cr11_s003": "chambered nautilus",
        "cr11_s002": "small red crab", "cr11_s001": "chambered nautilus"}
HERO_CSS = """
.hero { background: var(--board); color: var(--graphite); padding: 24px 24px 24px; border-top: 1px solid var(--rule); }
.hero h2 { margin: 0 0 6px; font-size: clamp(20px, 2.4vw, 28px); line-height: 1.1; font-weight: 800; font-variation-settings: "wdth" 72; }
.hero .tag { margin: 0 0 8px; font-size: 17px; font-weight: 700; font-variation-settings: "wdth" 80; }
.hero .a { color: var(--asked); } .hero .f { color: var(--found); }
.hero .sub { margin: 0 0 18px; max-width: 70ch; color: var(--ink-2); font-size: 15px; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }
.card { display: flex; flex-direction: column; justify-content: flex-start; align-items: stretch; text-align: left; background: #fff; border: 1px solid var(--rule); border-radius: 6px; padding: 0; color: inherit; cursor: pointer; overflow: hidden; }
.hero .proof { margin: 16px 0 0; max-width: 90ch; color: var(--graphite); font-size: 14px; border-left: 3px solid var(--asked); padding-left: 10px; }
.card:hover, .card:focus-visible { border-color: var(--found); }
.card img { display: block; width: 100%; aspect-ratio: 16/9; object-fit: cover; background: #111; }
.card .body { padding: 10px 12px 12px; }
.card .ask { font-size: 12px; color: var(--asked); margin: 0 0 4px; }
.card ul { list-style: none; margin: 0 0 6px; padding: 0; }
.card li { font-size: 15px; font-weight: 600; }
.card li .n { font-family: var(--narrow); font-variation-settings: "wdth" 68; font-size: 22px; margin-right: 6px; }
.card li.found { color: var(--found); } .card li.asked { color: var(--asked); }
.card li small { font-weight: 400; color: var(--ink-2); font-size: 12px; }
.card p.lab { margin: 6px 0 2px; font-size: 11px; text-transform: uppercase; letter-spacing: .06em; }
.card p.lab.f { color: var(--found); } .card p.lab.a { color: var(--asked); }
.card p.cap { margin: 0; font-size: 13px; color: var(--ink-2); }
.hero .more { margin: 14px 0 0; font-size: 13px; color: var(--ink-2); }
.hero .more a { color: var(--asked); }
.hero .how { margin: -8px 0 14px; max-width: 70ch; color: var(--ink-2); font-size: 13px; }
.hero .legend { margin: 0 0 10px; font-size: 13px; }
.hero .legend .n { font-family: var(--narrow); font-variation-settings: "wdth" 68; font-size: 17px; }
.hero .proof details { margin-top: 6px; color: var(--ink-2); }
.hero .proof summary, details.made > summary { cursor: pointer; }
details.made > summary { font-size: 15px; font-weight: 600; color: var(--ink-2); padding: var(--s3) 0; }
@media (max-width: 520px) { .hero { padding: 20px 16px; } }
"""


def hero(runs):
    import html as H
    by = {r["id"]: r for r in runs}
    cards = []
    for rid in [i for i in ORDER if i in by] + [r["id"] for r in runs if r["id"] not in ORDER]:
        eff = server.effective(rid)
        origin = eff.get("origin", {})
        metrics = eff.get("metrics", {})
        items = []
        for name, n in sorted(by[rid].get("maxn", {}).items(), key=lambda kv: (origin.get(kv[0]) != "found", -kv[1])):
            kind = "found" if origin.get(name) == "found" else "asked"
            m = metrics.get(name) or {}
            lo, hi = m.get("maxn_confirmed", n), m.get("maxn_upper", n)
            shown = f"{lo} to {hi}" if lo != hi else n   # the review screen's range while queued tracks are open (§4.7)
            items.append((kind, f'<li class="{kind}"><span class="n">{shown}</span>{H.escape(name)}</li>'))
        q = len(eff.get("queue", []))
        show = SHOW.get(rid)
        ev = (metrics.get(show) or {}).get("evidence") if show else None
        ev = ev or next((m.get("evidence") for m in metrics.values() if m.get("evidence")), None)
        img = f'<img src="runs/{rid}/{H.escape(ev)}" alt="Evidence frame for {H.escape(show or rid)}" loading="lazy">' if ev else ""
        cards.append(
            f'<button class="card" type="button" data-run="{rid}">{img}<div class="body">'
            f'<p class="ask">Asked for: “fish” · clip {H.escape(by[rid].get("source", ""))}</p>'
            + (f'<p class="lab a">Asked for</p><ul>{"".join(h for k, h in items if k == "asked")}</ul>'
               if any(k == "asked" for k, _ in items) else "")
            + (f'<p class="lab f">Not asked for, found and counted</p><ul>{"".join(h for k, h in items if k == "found")}</ul>'
               if any(k == "found" for k, _ in items) else "")
            + f'<p class="cap">{H.escape(CAPTION.get(rid, ""))} {q} track{"s" if q != 1 else ""} in the review queue.</p>'
            + '</div></button>')
    js = ("<script>document.querySelectorAll('.card[data-run]').forEach(function(b){b.onclick=function(){"
          "var s=document.getElementById('runSel');s.value=b.dataset.run;s.dispatchEvent(new Event('change'));"
          "var m=document.getElementById('main');m.scrollIntoView({behavior:'smooth'});m.focus({preventScroll:true});};});</script>")
    # below the review screen since W-DEMO2 (the first screen is shot()); the text and numbers are unchanged
    return (f'<style>{HERO_CSS}</style><section class="hero" aria-labelledby="heroTitle">'
            f'<h2 id="heroTitle">About these four clips</h2>'
            f'<p class="tag">Asked to count <span class="a">fish</span>. '
            f'It also found the <span class="f">animals nobody asked for</span>.</p>'
            f'<p class="sub">Give it baited-camera video and it gives back MaxN for each animal, when each first arrived, and the frame '
            f'behind every count. Anything it is not sure of waits in a short queue for a person to answer (Yes, Rename, Not an animal). '
            f'The table downloads as CSV, also in GlobalArchive layout. Below are four 12-second deep-sea clips with every answer '
            f'already computed, so nothing runs here. Click a clip.</p>'
            f'<p class="how">How: Muse Spark looks first and names what is there; SAM 3.1, which only sees what it is told to look for, '
            f'then tracks each named animal frame by frame, and Spark checks its work.</p>'
            f'<p class="legend">A count like <span class="n">4 to 6</span> is not settled yet: 4 counts only the tracks it was sure of, '
            f'6 if every track waiting in the queue is real. Answering the queue closes the range.</p>'
            f'<div class="cards">{"".join(cards)}</div>'
            f'<div class="proof"><b>Tested on 24 luderick seagrass clips of 1 to 12 s (remote underwater video, not baited camera) '
            f'not used in development:</b> MaxN was within one fish of two separate hand counts on all 24 (the author, not a marine '
            f'biologist, and a second person who never saw the output), and closer to them than the dataset’s reference boxes.'
            f'<details><summary>Details</summary>'
            f'Summed MaxN error against the hand counts: '
            f'6 against the reference boxes’ 16 for the first count (21 of 24 counted blind) and 2 against 14 for the second person '
            f'(exact on 22 of 24). The reference boxes were drawn to train a luderick detector, not to count MaxN. '
            f'Of 40 randomly drawn boxes the reference called false none was judged not a fish (29 fish, 2 part of a fish, 9 unsure). '
            f'Reviewing the pipeline’s extra tracks on a phone, one person added 145 missing fish boxes to the reference in 9 min 39 s.</details></div>'
            f'<p class="more">Every model answer is precomputed so there is nothing to install; answer the review queue right here. '
            f'Run your own clips & read the paper: <a href="{REPO}">GitHub</a> · <a href="https://youtu.be/XjFA1MOeVdA">3-minute video</a></p></section>{js}')


# First screen (W-DEMO2): the real boxed frame and the MaxN table side by side, one queue track to answer. demo/static_shot.js
# fills it from state.run after every drawRun (HOOK), so it always matches the review screen under it.
CHIP = {"cr11_s002": "Nautilus & a red crab", "cr11_s004": "Shrimp swarm, hagfish",
        "cr11_s003": "Three nautiluses", "cr11_s001": "Night, behind a trap"}
SHOT_CSS = """
.shot { background: var(--board); border-bottom: 1px solid var(--rule); padding: 18px 24px 20px; }
.shot h2 { margin: 0 0 4px; font-size: clamp(24px, 3.2vw, 38px); line-height: 1.05; font-weight: 800; font-variation-settings: "wdth" 70; }
.shot .sub2 { margin: 0 0 8px; color: var(--ink-2); font-size: 15px; max-width: 80ch; }
.shot .sub2 b { color: var(--graphite); font-weight: 600; }
.shot .input { margin: 0 0 8px; font-size: 13px; font-variation-settings: "wdth" 85; }
.chips { display: flex; gap: 8px; overflow-x: auto; padding-bottom: 2px; scrollbar-width: thin; }
.chip { flex: 0 0 auto; display: flex; align-items: center; gap: 8px; padding: 4px 10px 4px 4px; border-radius: 6px; cursor: pointer;
        border: 1px solid var(--rule); background: #fff; color: var(--graphite); font-size: 13px; font-weight: 600; }
.chip img { width: 56px; height: 32px; object-fit: cover; border-radius: 3px; display: block; background: #111; }
.chip[aria-pressed=true] { border-color: var(--graphite); box-shadow: inset 0 0 0 1px var(--graphite); }
.pair { display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(0, 1fr); gap: 20px; margin-top: 12px; align-items: start; }
.pair figure { margin: 0; }
.pair .frame { aspect-ratio: 16/9; background: #0E1215; border-radius: 4px; overflow: hidden; display: grid; place-items: center; }
.pair .frame img { width: 100%; height: 100%; object-fit: contain; display: block; cursor: zoom-in; }
.pair .frame p { color: var(--slate); padding: 16px; text-align: center; margin: 0; font-size: 14px; }
.pair figcaption { display: flex; flex-wrap: wrap; gap: 4px 12px; align-items: center; font-size: 13px; margin-top: 6px; }
.tablebox { background: #fff; border-radius: 4px; border-left: 6px solid var(--rule); padding: 10px 12px; }
table.maxn { width: 100%; border-collapse: collapse; font-size: 15px; }
table.maxn th { text-align: left; font-size: 11px; font-weight: 600; color: var(--ink-2); text-transform: uppercase; letter-spacing: .05em; padding: 0 8px 6px 0; border-bottom: 1px solid var(--rule); }
table.maxn td { padding: 7px 8px 7px 0; border-bottom: 1px solid var(--slate); vertical-align: middle; }
table.maxn td small { display: block; font-size: 12px; color: var(--ink-2); }
table.maxn tr[aria-selected] { cursor: pointer; } table.maxn tr[aria-selected=true] td { background: var(--asked-tint); }
table.maxn td.n button { background: none; border: 0; padding: 0; cursor: pointer; font-family: var(--narrow); font-variation-settings: "wdth" 68;
                         font-size: 28px; font-weight: 800; line-height: 1; }
table.maxn tr.asked td.n button { color: var(--asked); } table.maxn tr.found td.n button { color: var(--found); }
table.maxn td.t { font-family: var(--narrow); font-variation-settings: "wdth" 80; white-space: nowrap; }
.tablebox .dl { margin: 6px 0 0; font-size: 13px; }
.shot .ask { margin-top: 10px; border-top: 1px solid var(--rule); padding-top: 8px; }
.shot .askhead { margin: 0 0 6px; font-size: 14px; font-weight: 600; }
.shot .qline { display: grid; grid-template-columns: 56px 1fr; gap: 10px; align-items: start; }
.shot .qline img { width: 56px; height: 56px; object-fit: cover; border-radius: 3px; background: #0E1215; cursor: zoom-in; }
.shot .qline .said { font-size: 14px; }
.shot .qline .acts { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 4px; }
.shot .rename { display: flex; gap: 4px; margin-top: 6px; }
.shot .rename input { flex: 1; padding: 3px 6px; border: 1px solid var(--rule); border-radius: 3px; min-width: 0; }
@media (max-width: 1000px) { .rail { display: none; } }    /* nothing runs in the static copy: the rail would always read "done" */
@media (max-width: 760px) {
  .shot { padding: 14px 16px 16px; } .pair { grid-template-columns: minmax(0, 1fr); gap: 10px; }
  .meter { display: none; }       /* always "Replayed from saved answers, $0" here; a phone needs the room for the table */
  table.maxn td { padding: 4px 8px 4px 0; }
}
"""
# one line, so tests/test_static_review.py can lift it out of the built app.js and run it
HOOK = "/* static-shot hook */ { const drawApp = drawRun; drawRun = function (w) { drawApp(w); StaticShot.draw(state.run); }; }\n"
SHOT_JS = """StaticShot.show = %s;
$("runSel").addEventListener("change", () => { if (!state.run) StaticShot.draw(null); });   // a new clip is loading
document.querySelectorAll(".chip[data-run]").forEach((c) => c.addEventListener("click", () => {
  $("runSel").value = c.dataset.run; $("runSel").dispatchEvent(new Event("change")); }));
$("shotCsv").addEventListener("click", () => $("exportBtn").click());
$("shotGa").addEventListener("click", () => $("exportGaBtn").click());
"""


def shot(runs):
    import html as H
    chips = []
    for r in runs:
        rid = r["id"]
        ev = (server.effective(rid)["metrics"].get(SHOW.get(rid)) or {}).get("evidence")
        img = f'<img src="runs/{rid}/{H.escape(ev)}" alt="" loading="lazy">' if ev else ""
        chips.append(f'<button class="chip" type="button" data-run="{rid}" aria-pressed="false">{img}'
                     f'<span>{H.escape(CHIP.get(rid, rid))}</span></button>')
    return (f'<style>{SHOT_CSS}</style><section class="shot" aria-labelledby="shotTitle">'
            f'<h2 id="shotTitle">Baited-camera video in. A MaxN table out.</h2>'
            f'<p class="sub2">For each animal: the most seen in one frame, when it first arrived, and the frame it was counted in. '
            f'<b>Anything it is unsure of waits for a person to confirm.</b></p>'
            f'<p class="input" id="shotInput"></p>'
            f'<div class="chips" role="group" aria-label="Choose a clip">{"".join(chips)}</div>'
            f'<div class="pair"><figure><div class="frame"><img id="shotImg" alt="" hidden>'
            f'<p id="shotNoFrame" hidden>No saved frame for this row.</p></div>'
            f'<figcaption><span id="shotCap"></span><button class="btn ghost small" id="shotPlay" type="button" hidden>'
            f'&#9654; Play the clip from this frame</button></figcaption></figure>'
            f'<div class="tablebox"><table class="maxn"><thead><tr><th scope="col">MaxN</th><th scope="col">Animal</th>'
            f'<th scope="col">First seen</th><th scope="col">Peak</th></tr></thead>'
            f'<tbody id="shotRows"><tr><td colspan="4">Loading…</td></tr></tbody></table>'
            f'<p class="dl">Download: <button class="link" type="button" id="shotCsv">MaxN table (CSV)</button> · '
            f'<button class="link" type="button" id="shotGa">GlobalArchive layout (CSV)</button></p>'
            f'<div class="ask" id="shotAsk"></div></div></div></section>')


def static_data(rid, eff):
    """What demo/static_review.js needs to recompute server.effective() and both CSVs in the browser after an edit."""
    res = server._json(os.path.join(server.RUNS, rid, "result.json"))
    if res.get("site"):
        raise SystemExit(f"{rid}: static review does not handle site memory")
    v = res["video"]
    times = [round(i / v["fps"], 2) for i in range(v["n_frames"])]       # as tracks.metrics rounds them
    queued = [t for t, vd in res.get("verdicts", {}).items() if server.pipeline.needs_review(vd)]
    card = ("track", "name", "thumb", "trio", "has_trio", "species", "confidence", "is_target", "reason", "category", "auto",
            "yes_label", "from_site")
    return dict(frames=res["frames"], base_metrics=res["metrics"], n_frames=v["n_frames"], times=times,
                times_str=[str(t) for t in times], mins_str=[str(round(t / 60, 3)) for t in times],   # Python's float text
                queued=queued, verdict_order=list(res.get("verdicts", {})),
                accept={t: server.settle.accept_label(res, t) for t in dict.fromkeys(queued + [q["track"] for q in eff["queue"]])},
                cards={q["track"]: {k: q[k] for k in card} for q in eff["queue"]},
                group_of=server.pipeline._GROUP_OF, opcode=server.maxn_export.default_opcode(eff), ga_columns=server.maxn_export.COLUMNS,
                evidence=sorted(f for f in os.listdir(os.path.join(server.RUNS, rid)) if f.startswith("evidence_")))


def main():
    server.RUNS = SRC
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(os.path.join(OUT, "static"))
    os.makedirs(os.path.join(OUT, "api", "runs"))
    runs = [r for r in server.run_list() if r.get("stage") == "done"]
    runs.sort(key=lambda r: ORDER.index(r["id"]) if r["id"] in ORDER else len(ORDER))   # the page opens runs[0]
    json.dump(dict(runs=runs, running=None), open(os.path.join(OUT, "api", "runs.json"), "w"))
    for r in runs:
        rid = r["id"]
        eff = server.effective(rid)
        json.dump(dict(eff, _static=static_data(rid, eff)), open(os.path.join(OUT, "api", "runs", f"{rid}.json"), "w"))
        os.makedirs(os.path.join(OUT, "api", "runs", rid))
        open(os.path.join(OUT, "api", "runs", rid, "export.csv"), "w").write(server.export_csv(rid))
        open(os.path.join(OUT, "api", "runs", rid, "export_globalarchive.csv"), "w").write(
            server.maxn_export.to_csv(server.effective(rid), None))
        shutil.copytree(os.path.join(SRC, rid), os.path.join(OUT, "runs", rid))
    js = open(os.path.join(ROOT, "web", "app.js")).read()
    subs = [('api("/api/runs")', 'api("api/runs.json")'),
            ("`/api/runs/${encodeURIComponent(id)}/export.csv`", "`api/runs/${encodeURIComponent(id)}/export.csv`"),
            ("`/api/runs/${encodeURIComponent(id)}/export_globalarchive.csv`",
             "`api/runs/${encodeURIComponent(id)}/export_globalarchive.csv`"),
            ("await api(`/api/runs/${encodeURIComponent(id)}`)", "StaticReview.open(await api(`api/runs/${encodeURIComponent(id)}.json`))"),
            ("`/runs/", "`runs/")]
    for a, b in subs:
        if a not in js:
            raise SystemExit(f"app.js changed, update build_static.py: {a!r} not found")
        js = js.replace(a, b)
    # no server to save to: static/review.js recomputes the counts, the queue order and both CSVs in the page (memory only)
    js, k = re.subn(r"async function review\(track, label\) \{.*?\n\}\n",
                    "async function review(track, label) {\n  state.run = StaticReview.review(state.run, track, label);\n  drawRun(false);\n}\n",
                    js, count=1, flags=re.S)
    if not k:
        raise SystemExit("app.js changed, update build_static.py: review() not found")
    js, k = re.subn(r"async function renameGroup\(body\) \{.*?\n\}\n",
                    "async function renameGroup(body) {\n  try { state.run = StaticReview.renameGroup(state.run, body); drawRun(false); }\n"
                    "  catch (e) { alert(`Could not rename: ${e.message}`); }\n}\n", js, count=1, flags=re.S)
    if not k:
        raise SystemExit("app.js changed, update build_static.py: renameGroup() not found")
    js += ('for (const [b, f, n] of [["exportBtn", StaticReview.exportCsv, "_maxn.csv"], '
           '["exportGaBtn", StaticReview.globalArchiveCsv, "_globalarchive_maxn.csv"]])\n'
           '  $(b).addEventListener("click", (e) => { if (!state.run) return; e.preventDefault(); '
           'StaticReview.download(state.id + n, f(state.run)); });\n')
    # no upload form in the static copy (it needs the server); without it there is nothing to wire
    if "\nwireForm();\n" not in js:
        raise SystemExit("app.js changed, update build_static.py: wireForm() call not found")
    js = js.replace("\nwireForm();\n", "\n", 1)
    # "No fish in this clip." read as "there is nothing here" to a fish researcher; say what SAM did and where the rest is
    empty = '[el("p", { class: "empty" }, `No ${words.join(" or ")} in this clip.`)]'
    if empty not in js:
        raise SystemExit("app.js changed, update build_static.py: drawAsked empty line not found")
    js = js.replace(empty, '[el("p", { class: "empty" }, `SAM tracked nothing as ${words.map((w) => `“${w}”`).join(" or ")} in this clip.`'
                    ' + (Object.values(run.origin || {}).includes("found") ? " What it did find is under Found without being asked." : ""))]', 1)
    # the first screen redraws with the review screen: every clip change, queue answer and group rename goes through drawRun
    if "\nfunction drawRun(withVideo) {" not in js:
        raise SystemExit("app.js changed, update build_static.py: drawRun() not found")
    js += HOOK + SHOT_JS % json.dumps({r["id"]: SHOW.get(r["id"]) for r in runs})
    open(os.path.join(OUT, "static", "app.js"), "w").write(js)
    shutil.copy(os.path.join(ROOT, "web", "style.css"), os.path.join(OUT, "static", "style.css"))
    shutil.copy(os.path.join(ROOT, "demo", "static_review.js"), os.path.join(OUT, "static", "review.js"))
    shutil.copy(os.path.join(ROOT, "demo", "static_shot.js"), os.path.join(OUT, "static", "shot.js"))
    html = open(os.path.join(ROOT, "web", "index.html")).read()
    html = html.replace('href="/static/', 'href="static/').replace('src="/static/', 'src="static/')
    if '<script src="static/app.js"></script>' not in html:
        raise SystemExit("index.html changed, update build_static.py: app.js script tag not found")
    html = html.replace('<script src="static/app.js"></script>', '<script src="static/review.js"></script>\n<script src="static/shot.js"></script>\n<script src="static/app.js"></script>', 1)
    shutil.copy(os.path.join(ROOT, "demo", "og.png"), os.path.join(OUT, "static", "og.png"))
    if html.count("<title>reefcensus</title>") != 1:
        raise SystemExit("index.html changed, update build_static.py: <title> not found")
    html = html.replace("<title>reefcensus</title>", f"<title>{TITLE}</title>\n{HEAD}", 1)
    if "</header>\n" not in html:
        raise SystemExit("index.html changed, update build_static.py: </header> not found")
    html = html.replace("</header>\n", "</header>\n" + shot(runs) + "\n", 1)
    # IMAS footage is no longer used anywhere (licence not specified at the source); credit only what is shown
    about = hero(runs)    # the old landing text, under the review screen (a function: re.sub must not read its text as a template)
    html = re.sub(r'<footer class="credits">.*?</footer>',
                  lambda m: about + '\n<footer class="credits">Nautilus video: Barord et al. 2014, PLOS ONE 9(6): e100799, S1 to S4, CC BY 4.0. '
                  'SAM 3.1 and Muse Spark by Meta, through the Meta Model API.</footer>', html, count=1, flags=re.S)
    # results first: the second-look steps and the log move under the downloads, folded (on a phone they came before the counts)
    how = ('<section class="panel second" id="secondPanel"></section>\n'
           '    <details class="log" id="logBox"><summary>Pipeline log</summary><ol id="log"></ol></details>\n')
    if how not in html:
        raise SystemExit("index.html changed, update build_static.py: secondPanel / logBox not found")
    html = html.replace("    " + how, "", 1)
    html, k = re.subn(r'(id="exportGaBtn"[^\n]*\n)', lambda m: m.group(1) + '    <details class="made"><summary>How the count was made '
                      '(second looks, pipeline log)</summary>\n    ' + how + '    </details>\n', html, count=1)
    if not k:
        raise SystemExit("index.html changed, update build_static.py: exportGaBtn not found")
    html = html.replace('<main class="grid" id="main">', '<main class="grid" id="main" tabindex="-1">', 1)
    html = html.replace('<button class="btn ghost" id="newBtn"', '<button class="btn ghost" id="newBtn" hidden style="display:none"', 1)
    # a reader without JavaScript sees the raw HTML: drop the server-only form and point the export links at a real file
    html, k = re.subn(r'<section class="drawer" id="newRun" hidden>.*?</section>\n?', '', html, count=1, flags=re.S)
    if not k:
        raise SystemExit("index.html changed, update build_static.py: newRun drawer not found")
    if runs:
        first = runs[0]["id"]
        html = html.replace('id="exportBtn" href="#"', f'id="exportBtn" href="api/runs/{first}/export.csv"', 1)
        html = html.replace('id="exportGaBtn" href="#"', f'id="exportGaBtn" href="api/runs/{first}/export_globalarchive.csv"', 1)
    if 'og:image' not in html or "newBtn\" hidden" not in html:
        raise SystemExit("index.html changed, update build_static.py")
    open(os.path.join(OUT, "index.html"), "w").write(html)
    n, size = 0, 0
    for d, _, fs in os.walk(OUT):
        for f in fs:
            n += 1
            size += os.path.getsize(os.path.join(d, f))
    print(f"{OUT}: {len(runs)} runs, {n} files, {size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
