"""Phone page to time the person queue: every queued track of the four qtime_* development runs, as the review screen
shows it (three crops of the track with our box, the auditor's note), answered Accept / Reject / Unsure, timed from a
Start button to Copy answers. Writes sheet.html (local), sheet_artifact.html (no document skeleton) and key.json.

  memcap --max 2G -- env FISH_PYLIB=... python3 report/paper/scripts/qtime_sheet.py OUT_DIR
"""
import base64, html, json, os, random, sys
sys.path.insert(0, os.path.expanduser("~/meta-fish"))
from fishcount import video  # noqa: F401  (cv2 path)
from fishcount import pipeline, gapfind
import cv2

R = os.path.expanduser("~/meta-fish/runs"); OUT = sys.argv[1]; os.makedirs(OUT, exist_ok=True)
cards = []
for rid in sorted(d for d in os.listdir(R) if d.startswith("qtime_")):
    res = json.load(open(f"{R}/{rid}/result.json"))
    for t, v in res["verdicts"].items():
        if not pipeline.needs_review(v):
            continue
        fb = [(int(f), k["box"]) for f, ks in sorted(res["frames"].items(), key=lambda x: int(x[0])) for k in ks if k["track"] == t]
        cards.append(dict(run=rid, track=t, label=res["tracks"].get(t, {}).get("label"), reason=v.get("reason", ""),
                          is_target=v.get("is_target"), confidence=v.get("confidence"), show=gapfind.spread(fb)))
rng = random.Random(1104); rng.shuffle(cards)
for i, c in enumerate(cards, 1):
    c["n"] = i
    fr = video.frames(f"{R}/{c['run']}/clip.mp4", [f for f, _ in c["show"]])
    c["crops"] = [cv2.imencode(".jpg", gapfind._crop(fr[f], b, []), [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()
                  for f, b in c["show"] if f in fr]

GUIDE = """<h3>무엇을 재나</h3><p>우리 프로그램은 확신이 없는 물체를 바로 세지 않고 <b>사람 확인 대기열</b>에 보냅니다.
이 페이지는 그 확인에 사람이 몇 분 쓰는지 잽니다. 결과는 "기계 + 사람 확인 몇 분"이라는 숫자로 영상·제출 폼에 들어갑니다.
빨리 할 필요는 없고, 평소 판단하시는 속도면 됩니다.</p>
<h3>할 일</h3><ol><li>아래 <b>시작</b>을 누르면 시간이 잽니다.</li><li>카드 9장마다 버튼 하나씩 누릅니다.</li>
<li>다 끝나면 맨 아래 <b>답 복사</b>를 누르고 채팅에 붙여 넣어 주세요(이때 시간이 멈춥니다).</li></ol>
<h3>카드 보는 법</h3><ul><li>카드 한 장 = 컴퓨터가 영상에서 따라간 물체 하나. 사진(최대 3장, 옆으로 넘기기)은 같은 물체의 처음·중간·끝입니다.</li>
<li><span class="y">노란 상자</span> = 컴퓨터가 "물고기"로 찾은 것.</li>
<li><b>컴퓨터 메모</b> = 컴퓨터(Muse Spark)가 이 물체를 보고 남긴 한 줄(영어). 이 메모 때문에 대기열에 왔습니다.
참고만 하시고 판단은 사진으로 해 주세요.</li></ul>
<h3>선택지 — 무엇을 누르면 어떻게 되나</h3><dl>
<dt>넣기</dt><dd>노란 상자 안이 물고기다(희미해도 물고기로 보이면 넣기). → 이 물체가 물고기 수(MaxN)에 <b>들어갑니다</b>.</dd>
<dt>빼기</dt><dd>물고기가 아니다(물·해초·그림자·화면 글자 등). → 물고기 수에서 <b>빠집니다</b>.</dd>
<dt>모르겠음</dt><dd>사진만으로 판단이 안 된다. → 물고기 수에서 빠진 채로 "다시 볼 것"으로 남습니다. 억지로 고르지 않으셔도 됩니다.</dd></dl>"""

CSS = """:root{--bg:#fff;--fg:#111;--mut:#5f6368;--card:#f2f4f5;--on:#0a7a5c;--line:#d6d9dc;--y:#b38f00}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#111314;--fg:#eceeef;--mut:#9aa0a6;--card:#1d2023;--line:#33383c;--y:#e0c040;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#111314;--fg:#eceeef;--mut:#9aa0a6;--card:#1d2023;--line:#33383c;--y:#e0c040;color-scheme:dark}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.45 system-ui,sans-serif}
header{position:sticky;top:env(safe-area-inset-top,0px);background:var(--bg);border-bottom:1px solid var(--line);padding-block:10px;z-index:2}
body::before{content:"";position:fixed;inset:0 0 auto;height:env(safe-area-inset-top,0px);z-index:10;background:var(--bg)}
header,main{padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}
main{padding-block:12px 80px;max-width:760px;margin:auto}.g{background:var(--card);border-radius:10px;padding:4px 14px 10px;margin:0 0 16px}
.g h3{font-size:16px;margin:12px 0 4px}.g dt{font-weight:700;margin-top:8px}.g dd{margin:2px 0 0}.g ol,.g ul{padding-left:20px;margin:4px 0}
.y{color:var(--y);font-weight:700}.c{background:var(--card);border-radius:10px;padding:10px;margin:0 0 14px}.c h2{font-size:15px;margin:0 0 6px}
.im{display:flex;gap:6px;overflow-x:auto}.im img{height:150px;border-radius:6px}.why{color:var(--mut);font-size:14px;margin:6px 0 0}
.b{display:flex;gap:6px;margin-top:8px}.b button,#start,#done{flex:1;padding:12px 0;font-size:16px;border:1px solid var(--line);
border-radius:8px;background:var(--bg);color:var(--fg)}.b button.on,#start.on{background:var(--on);color:#fff}
#start,#done{width:100%;margin:0 0 14px}button:focus-visible{outline:2px solid var(--on);outline-offset:2px}textarea{width:100%;height:110px}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}"""

parts = []
for c in cards:
    imgs = "".join(f'<img alt="사진" src="data:image/jpeg;base64,{base64.b64encode(j).decode()}">' for j in c["crops"])
    btns = "".join(f'<button data-a="{a}">{t}</button>' for a, t in (("A", "넣기"), ("R", "빼기"), ("?", "모르겠음")))
    parts.append(f'<div class="c" data-n="{c["n"]}"><h2>#{c["n"]}</h2><div class="im">{imgs}</div>'
                 f'<p class="why">컴퓨터 메모: “{html.escape(c["reason"])}”</p><div class="b">{btns}</div></div>')
JS = """const N=%d,K="qtime-1104";let A={},T0=null;try{const s=JSON.parse(localStorage.getItem(K)||"{}");A=s.a||{};T0=s.t0||null}catch(e){}
const save=()=>{try{localStorage.setItem(K,JSON.stringify({a:A,t0:T0}))}catch(e){}};
function draw(){document.querySelectorAll(".c").forEach(c=>c.querySelectorAll("button").forEach(b=>b.classList.toggle("on",A[c.dataset.n]===b.dataset.a)));
document.getElementById("prog").textContent=Object.keys(A).length+" / "+N;const s=document.getElementById("start");
s.classList.toggle("on",!!T0);s.textContent=T0?"시간 재는 중 (시작함)":"시작 — 누르면 시간을 잽니다"}
document.getElementById("start").onclick=()=>{if(!T0){T0=Date.now();save();draw()}};
document.querySelectorAll(".b button").forEach(b=>b.onclick=()=>{if(!T0)T0=Date.now();const n=b.closest(".c").dataset.n;
A[n]=A[n]===b.dataset.a?undefined:b.dataset.a;if(A[n]===undefined)delete A[n];save();draw()});
document.getElementById("done").onclick=()=>{const t=JSON.stringify({sheet:K,answers:A,seconds:T0?Math.round((Date.now()-T0)/1000):null,n_answered:Object.keys(A).length});
const o=document.getElementById("out");o.value=t;o.select();try{navigator.clipboard.writeText(t).then(()=>{document.getElementById("done").textContent="복사됨 — 채팅에 붙여 넣어 주세요"},()=>{})}catch(e){}};draw();""" % len(cards)
body = (f'<style>{CSS}</style><header><b>이 물체를 물고기 수에 넣을까요?</b> <span id="prog"></span></header>'
        f'<main><section class="g">{GUIDE}</section><button id="start">시작</button>{"".join(parts)}'
        f'<button id="done">답 복사</button><textarea id="out" readonly aria-label="답"></textarea></main><script>{JS}</script>')
head = '<title>Queue review timer</title>\n<meta name="claude:viewport-fit-sides" content="cover">'
open(os.path.join(OUT, "sheet_artifact.html"), "w").write(head + body)
open(os.path.join(OUT, "sheet.html"), "w").write('<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" '
     'content="width=device-width,initial-scale=1,viewport-fit=cover">' + head + '</head><body>' + body + '</body></html>')
json.dump(dict(protocol="11/4: every queued track (pipeline.needs_review) of runs/qtime_* (4 development luderick clips), "
               "shuffled with random.Random(1104); three crops (spread over the track) with our box and the auditor's reason, "
               "as the review screen shows them; answers A accept / R reject / ? unsure; seconds from Start (or first tap) to Copy.",
               cards=[{k: v for k, v in c.items() if k != "crops"} for c in cards]), open(os.path.join(OUT, "key.json"), "w"), indent=1)
print(len(cards), "cards ->", OUT)
