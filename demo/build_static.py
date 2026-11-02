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
        shutil.copytree(os.path.join(SRC, rid), os.path.join(OUT, "runs", rid))
    js = open(os.path.join(ROOT, "web", "app.js")).read()
    subs = [('api("/api/runs")', 'api("api/runs.json")'),
            ("`/api/runs/${encodeURIComponent(id)}/export.csv`", "`api/runs/${encodeURIComponent(id)}/export.csv`"),
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
    open(os.path.join(OUT, "static", "app.js"), "w").write(js)
    shutil.copy(os.path.join(ROOT, "web", "style.css"), os.path.join(OUT, "static", "style.css"))
    html = open(os.path.join(ROOT, "web", "index.html")).read()
    html = html.replace('href="/static/', 'href="static/').replace('src="/static/', 'src="static/')
    note = (f'<p id="staticNote" style="margin:0;padding:6px 16px;font-size:13px;background:#fff6e5;color:#5a4300">'
            f'Static demo of four precomputed runs (every model answer was computed beforehand). '
            f'Live runs and reviews need the local server: <a href="{REPO}">{REPO}</a></p>')
    html = html.replace("<body>", "<body>\n" + note, 1)
    html = html.replace('<button class="btn ghost" id="newBtn"', '<button class="btn ghost" id="newBtn" hidden style="display:none"', 1)
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
