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


# Landing block for judges: the claim in one line, then one card per run (asked vs. found, with its evidence frame).
# Captions are the measured facts from README "Discovery" (development clips, Barord et al. 2014).
ORDER = ["mg2_s004", "mg2_s003", "mg2_s002", "cr9_s001"]
CAPTION = {
    "mg2_s004": "A shrimp swarm, a hagfish and a nautilus at the bait. SAM found nothing for “hagfish”; Spark tried “eel” and it locked on.",
    "mg2_s003": "Three nautiluses, one partly behind another, counted as three.",
    "mg2_s002": "A nautilus and a small red crab nobody asked for.",
    "cr9_s001": "Night, behind a wire trap. No word found them; moving pixels did. 4 counted; a paler 5th Spark was not sure of goes to a person.",
}
SHOW = {"mg2_s004": "caridean shrimp", "mg2_s003": "chambered nautilus",
        "mg2_s002": "small red crab", "cr9_s001": "chambered nautilus"}
HERO_CSS = """
.hero { background: var(--graphite); color: var(--slate); padding: 28px 24px 24px; }
.hero h2 { margin: 0 0 6px; font-size: clamp(26px, 4.4vw, 46px); line-height: 1.05; font-weight: 800; font-variation-settings: "wdth" 70; max-width: 30ch; }
.hero h2 .a { color: #8FB5EE; } .hero h2 .f { color: #FF8A5C; }
.hero .sub { margin: 0 0 18px; max-width: 70ch; color: #B9C4CC; font-size: 15px; }
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }
.card { display: flex; flex-direction: column; justify-content: flex-start; align-items: stretch; text-align: left; background: #2E363C; border: 1px solid #47525B; border-radius: 6px; padding: 0; color: inherit; cursor: pointer; overflow: hidden; }
.hero .proof { margin: 16px 0 0; max-width: 90ch; color: #D7DEE3; font-size: 14px; border-left: 3px solid #8FB5EE; padding-left: 10px; }
.card:hover, .card:focus-visible { border-color: #FF8A5C; }
.card img { display: block; width: 100%; aspect-ratio: 16/9; object-fit: cover; background: #111; }
.card .body { padding: 10px 12px 12px; }
.card .ask { font-size: 12px; color: #8FB5EE; margin: 0 0 4px; }
.card ul { list-style: none; margin: 0 0 6px; padding: 0; }
.card li { font-size: 15px; font-weight: 600; }
.card li .n { font-family: var(--narrow); font-variation-settings: "wdth" 68; font-size: 22px; margin-right: 6px; }
.card li.found { color: #FF8A5C; } .card li.asked { color: #8FB5EE; }
.card li small { font-weight: 400; color: #B9C4CC; font-size: 12px; }
.card p.lab { margin: 6px 0 2px; font-size: 11px; text-transform: uppercase; letter-spacing: .06em; }
.card p.lab.f { color: #FF8A5C; } .card p.lab.a { color: #8FB5EE; }
.card p.cap { margin: 0; font-size: 13px; color: #B9C4CC; }
.hero .more { margin: 14px 0 0; font-size: 13px; color: #B9C4CC; }
.hero .more a { color: #FFFFFF; }
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
            items.append((kind, f'<li class="{kind}"><span class="n">{n}</span>{H.escape(name)}</li>'))
        q = len(eff.get("queue", []))
        show = SHOW.get(rid)
        ev = (metrics.get(show) or {}).get("evidence") if show else None
        ev = ev or next((m.get("evidence") for m in metrics.values() if m.get("evidence")), None)
        img = f'<img src="runs/{rid}/{H.escape(ev)}" alt="Evidence frame for {H.escape(show or rid)}" loading="lazy">' if ev else ""
        cards.append(
            f'<button class="card" type="button" data-run="{rid}">{img}<div class="body">'
            f'<p class="ask">Asked for: “fish” · clip {H.escape(by[rid].get("source", ""))}</p>'
            + (f'<p class="lab f">Not asked for, found and counted</p><ul>{"".join(h for k, h in items if k == "found")}</ul>'
               if any(k == "found" for k, _ in items) else "")
            + (f'<p class="lab a">Asked for</p><ul>{"".join(h for k, h in items if k == "asked")}</ul>'
               if any(k == "asked" for k, _ in items) else "")
            + f'<p class="cap">{H.escape(CAPTION.get(rid, ""))} {q} track{"s" if q != 1 else ""} in the review queue.</p>'
            + '</div></button>')
    js = ("<script>document.querySelectorAll('.card[data-run]').forEach(function(b){b.onclick=function(){"
          "var s=document.getElementById('runSel');s.value=b.dataset.run;s.dispatchEvent(new Event('change'));"
          "var m=document.getElementById('main');m.scrollIntoView({behavior:'smooth'});m.focus({preventScroll:true});};});</script>")
    return (f'<style>{HERO_CSS}</style><section class="hero" aria-labelledby="heroTitle">'
            f'<h2 id="heroTitle">Asked to count <span class="a">fish</span>. '
            f'It also found the <span class="f">animals nobody asked for</span>.</h2>'
            f'<p class="sub">SAM 3.1 only sees what it is told to look for. Muse Spark looks first, names what is there in words '
            f'SAM can act on, and checks SAM’s work frame by frame. Four 12-second clips of deep-sea baited-camera video, '
            f'every model answer computed beforehand. Click a clip to see the counts, the evidence and the review queue.</p>'
            f'<div class="cards">{"".join(cards)}</div>'
            f'<p class="proof"><b>On another dataset (24 held-out luderick fish videos, not used in development)</b>, hand-counted '
            f'separately by two people: the pipeline’s MaxN is closer to the hand count than the human reference boxes are, '
            f'summed error 6 against 16 for the first count (21 of 24 counted blind) and 2 against 14 for a second person who '
            f'never saw the project’s output (exact on 22 of 24); within one fish on all 24. Of 40 randomly drawn boxes the reference called false, none was judged not a fish. '
            f'Reviewing the pipeline’s extra tracks on a phone, one person added 145 missing fish boxes to the reference in 9 min 39 s.</p>'
            f'<p class="more">Code, paper and how to run it live: <a href="{REPO}">{REPO}</a></p></section>{js}')


def main():
    server.RUNS = SRC
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(os.path.join(OUT, "static"))
    os.makedirs(os.path.join(OUT, "api", "runs"))
    runs = [r for r in server.run_list() if r.get("stage") == "done"]
    json.dump(dict(runs=runs, running=None), open(os.path.join(OUT, "api", "runs.json"), "w"))
    for r in runs:
        rid = r["id"]
        json.dump(server.effective(rid), open(os.path.join(OUT, "api", "runs", f"{rid}.json"), "w"))
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
            ("api(`/api/runs/${encodeURIComponent(id)}`)", "api(`api/runs/${encodeURIComponent(id)}.json`)"),
            ("`/runs/", "`runs/")]
    for a, b in subs:
        if a not in js:
            raise SystemExit(f"app.js changed, update build_static.py: {a!r} not found")
        js = js.replace(a, b)
    # saving a review needs the server: keep the change on screen only and say so
    js = re.sub(r"async function review\(track, label\) \{.*?\n\}\n",
                "async function review(track, label) {\n  const n = document.getElementById(\"staticNote\");\n"
                "  if (n) n.textContent = \"Static demo: reviews are not saved. Run the server from the repository to review and export.\";\n}\n",
                js, count=1, flags=re.S)
    # no upload form in the static copy (it needs the server); without it there is nothing to wire
    if "\nwireForm();\n" not in js:
        raise SystemExit("app.js changed, update build_static.py: wireForm() call not found")
    js = js.replace("\nwireForm();\n", "\n", 1)
    open(os.path.join(OUT, "static", "app.js"), "w").write(js)
    shutil.copy(os.path.join(ROOT, "web", "style.css"), os.path.join(OUT, "static", "style.css"))
    html = open(os.path.join(ROOT, "web", "index.html")).read()
    html = html.replace('href="/static/', 'href="static/').replace('src="/static/', 'src="static/')
    note = (f'<p id="staticNote" style="margin:0;padding:6px 16px;font-size:13px;background:#fff6e5;color:#5a4300">'
            f'Interactive replay of four real runs — click a clip. Every model answer is saved, so nothing here calls a model. '
            f'To run your own video: <a href="{REPO}">{REPO}</a></p>')
    html = html.replace("<body>", "<body>\n" + note + "\n" + hero(runs), 1)
    # IMAS footage is no longer used anywhere (licence not specified at the source); credit only what is shown
    html = re.sub(r'<footer class="credits">.*?</footer>',
                  '<footer class="credits">Nautilus video: Barord et al. 2014, PLOS ONE 9(6): e100799, S1–S4, CC BY 4.0. '
                  'SAM 3.1 and Muse Spark by Meta, through the Meta Model API.</footer>', html, count=1, flags=re.S)
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
    if 'id="staticNote"' not in html or "newBtn\" hidden" not in html:
        raise SystemExit("index.html changed, update build_static.py")
    open(os.path.join(OUT, "index.html"), "w").write(html)
    n, size = 0, 0
    for d, _, fs in os.walk(OUT):
        for f in fs:
            n += 1
            size += os.path.getsize(os.path.join(d, f))
    print(f"{OUT}: {len(runs)} runs, {n} files, {size / 1e6:.1f} MB")


main()
