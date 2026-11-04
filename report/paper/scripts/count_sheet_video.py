"""One-file phone sheet for counting MaxN by hand from short videos (the second held-out hand count, and the NOAA set).

  python3 report/paper/scripts/count_sheet_video.py KEY.json VIDEO_DIR OUT.html [--ext .mp4]

KEY.json has {"key": {"<neutral name>": "<clip id>", ...}} in sheet order; VIDEO_DIR holds <neutral name><ext>.
Videos are embedded (base64) so the page works offline from a messenger attachment. The counter writes the most fish
visible at once (sure) and, separately, shapes that might be fish or moving background (+); answers are kept in the
page (localStorage) and copied back as "name: n (+u) | note" lines, the format recount2_score.py reads."""
import argparse, base64, json, os

TEXT = ("For each video, find the moment with the <b>most fish visible at the same time</b> and write that number. "
        "Use 0.25× and the frame buttons to pause and count. Count only what you would bet is a separate fish "
        "(any kind of fish). If some shapes might be fish or might be moving seagrass or background, do not include "
        "them in the first number; write how many in the \"+\" box instead. Work alone, do not look up the videos, and "
        "do not look at any project output. Your answers are saved in this page as you type. When done, press "
        "<b>Copy answers</b> and send the text back.")


def build(key, vdir, ext, storage):
    items = []
    for v in key:
        b = base64.b64encode(open(os.path.join(vdir, v + ext), "rb").read()).decode()
        items.append(f'''<section><h2>{v}</h2>
<video id="{v}" src="data:video/mp4;base64,{b}" controls muted loop playsinline preload="metadata"></video>
<div class="ctl"><button onclick="sp('{v}',0.25)">0.25×</button><button onclick="sp('{v}',1)">1×</button><button onclick="st('{v}',-1)">◀ frame</button><button onclick="st('{v}',1)">frame ▶</button></div>
<label>Most fish at the same moment (sure): <input inputmode="numeric" data-v="{v}" data-k="n" oninput="sv()"></label>
<label>Extra you can't tell from the background (+): <input inputmode="numeric" data-v="{v}" data-k="u" oninput="sv()"></label>
<label>Note: <input data-v="{v}" data-k="t" oninput="sv()"></label></section>''')
    return f'''<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Fish count sheet</title>
<style>body{{font:16px system-ui,sans-serif;max-width:760px;margin:0 auto;padding:12px;background:#fff;color:#111}}
video{{width:100%;background:#000}}section{{border-top:2px solid #ccc;padding:10px 0 16px}}h2{{margin:4px 0}}
.ctl button{{font-size:15px;margin:4px 6px 4px 0;padding:6px 10px}}label{{display:block;margin:6px 0}}
input{{font-size:17px;width:5em;padding:4px}}input[data-k=t]{{width:60%}}#out{{width:100%;height:14em;font:14px monospace}}
.big{{font-size:18px;padding:10px 16px}}</style>
<h1>Fish count sheet ({len(key)} short videos)</h1>
<p>{TEXT}</p>
{"".join(items)}
<section><button class="big" onclick="cp()">Copy answers</button><p id="msg"></p><textarea id="out" readonly></textarea></section>
<script>
function sp(v,r){{const e=document.getElementById(v);e.playbackRate=r;e.play()}}
function st(v,d){{const e=document.getElementById(v);e.pause();e.currentTime=Math.max(0,e.currentTime+d/30)}}
const K='{storage}';const S=JSON.parse(localStorage.getItem(K)||'{{}}');
document.querySelectorAll('input').forEach(i=>{{const x=S[i.dataset.v+i.dataset.k];if(x)i.value=x}});
function txt(){{let o=[];document.querySelectorAll('section h2').forEach(h=>{{const v=h.textContent;const g=k=>(document.querySelector(`input[data-v="${{v}}"][data-k="${{k}}"]`)||{{}}).value||'';
const n=g('n'),u=g('u'),t=g('t');o.push(v+': '+(n||'?')+(u?' (+'+u+')':'')+(t?' | '+t:''))}});return o.join('\\n')}}
function sv(){{document.querySelectorAll('input').forEach(i=>S[i.dataset.v+i.dataset.k]=i.value);localStorage.setItem(K,JSON.stringify(S));document.getElementById('out').value=txt()}}
function cp(){{const t=txt();document.getElementById('out').value=t;navigator.clipboard.writeText(t).then(()=>msg.textContent='Copied. Paste it into a message.',()=>{{out.select();msg.textContent='Select the text below and copy it.'}})}}
sv();
</script>'''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("key"); ap.add_argument("videos"); ap.add_argument("out")
    ap.add_argument("--ext", default=".mp4")
    a = ap.parse_args()
    key = json.load(open(a.key))["key"]
    storage = "fishcount-" + os.path.splitext(os.path.basename(os.path.dirname(os.path.abspath(a.key))))[0]
    open(a.out, "w").write(build(key, a.videos, a.ext, storage))
    print(f"{a.out}: {len(key)} videos, {os.path.getsize(a.out) / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
