"""Phone page to measure how often the auditor (A1, Muse Spark) agrees with a person. Pool: every A1 verdict in the cr6
runs (30 luderick clips, s001-s004, DH1-DH11), less the 5 tracks whose name a later look changed (relabelled or
name_disagrees: the question would not be the one A1 answered). Three strata by A1's answer: rejected (any confidence),
accepted with confidence < 0.7 (queued), accepted with confidence >= 0.7 (counted). 20 drawn from each with
random.Random(1105), shuffled together. A card shows three crops of the track with our box and the label A1 was asked
about; it does NOT show A1's answer, confidence, note, or whether the track was counted. The person answers
Y "yes, a <label>", O "an animal, but not a <label>", N "not an animal", ? "can't tell".
Scoring is fixed here, before the person sees the sheet (audit_agree_score.py): A1 accept = Y, A1 reject = O or N;
Cohen's kappa and per-stratum agreement over answered cards (? left out, and separately counted as disagreement);
the population estimate weights each stratum by its pool size.

  memcap --max 2G -- python3 report/paper/scripts/audit_agree_sheet.py OUT_DIR
"""
import base64, glob, html, json, os, random, sys
sys.path.insert(0, os.path.expanduser("~/meta-fish"))
from fishcount import video  # noqa: F401  (cv2 path)
from fishcount import gapfind
import cv2

R = os.path.expanduser("~/meta-fish/runs"); OUT = sys.argv[1]; os.makedirs(OUT, exist_ok=True)
SEED, PER = 1105, 20
KO = {"fish": "물고기", "shrimp": "새우", "crab": "게", "nautilus": "앵무조개", "shark": "상어", "worm": "벌레(갯지렁이 등)",
      "coral": "산호", "eel": "장어"}

runs = sorted(glob.glob(f"{R}/cr6_*/result.json") + glob.glob(f"{R}/DH*_cr6/result.json"))
pool = {"rejected": [], "accepted_low": [], "accepted_high": []}
excluded = 0
for f in runs:
    rid = os.path.basename(os.path.dirname(f)); res = json.load(open(f))
    for t, v in sorted(res["verdicts"].items()):
        if not v:
            continue
        if v.get("relabelled") or v.get("name_disagrees"):
            excluded += 1; continue
        conf = v.get("confidence") or 0
        s = "rejected" if not v.get("is_target") else ("accepted_high" if conf >= 0.7 else "accepted_low")
        pool[s].append(dict(run=rid, track=t, label=res["tracks"].get(t, {}).get("label"), stratum=s,
                            a1_is_target=bool(v.get("is_target")), a1_confidence=conf, a1_reason=v.get("reason", "")))
rng = random.Random(SEED)
cards = []
for s in ("rejected", "accepted_low", "accepted_high"):
    cards += rng.sample(pool[s], min(PER, len(pool[s])))
rng.shuffle(cards)
for i, c in enumerate(cards, 1):
    c["n"] = i
    res = json.load(open(f"{R}/{c['run']}/result.json"))
    fb = [(int(fr), k["box"]) for fr, ks in sorted(res["frames"].items(), key=lambda x: int(x[0])) for k in ks
          if k["track"] == c["track"]]
    c["show"] = gapfind.spread(fb)
    fr = video.frames(f"{R}/{c['run']}/clip.mp4", [x for x, _ in c["show"]])
    c["crops"] = [cv2.imencode(".jpg", gapfind._crop(fr[x], b, []), [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()
                  for x, b in c["show"] if x in fr]

GUIDE = """<h3>무엇을 재나</h3><p>우리 프로그램 안에는 <b>컴퓨터 검사관</b>(Muse Spark)이 있어서, 영상에서 따라간 물체마다
"이게 정말 ○○인가?"를 판정합니다. 심사 AI가 "검사관이 사람과 얼마나 같은 판단을 하는지 재지 않았다"고 지적했습니다.
이 페이지가 그걸 잽니다. <b>대표님 답 = 정답</b>으로 놓고, 검사관 답과 몇 장이나 같은지 셉니다(결과는 논문 표 하나).</p>
<p>카드마다 검사관이 무엇이라 답했는지는 <b>일부러 숨겼습니다</b>. 일부는 검사관이 "맞다", 일부는 "아니다"라고 한 것을 섞었습니다.</p>
<h3>할 일</h3><ol><li>카드 60장마다 버튼 하나씩 누릅니다(평소 판단 속도면 됩니다).</li>
<li>다 끝나면 맨 아래 <b>답 복사</b>를 누르고 채팅에 붙여 넣어 주세요.</li></ol>
<h3>카드 보는 법</h3><ul><li>카드 한 장 = 컴퓨터가 영상에서 따라간 물체 하나. 사진(최대 3장, 옆으로 넘기기)은 같은 물체의 처음·중간·끝입니다.</li>
<li><span class="y">노란 상자</span> = 그 물체. 위 제목의 <b>질문 단어</b>(예: 새우)가 검사관이 받은 질문입니다.</li></ul>
<h3>선택지 — 무엇을 누르면 어떻게 되나</h3><dl>
<dt>맞다</dt><dd>노란 상자 안이 그 동물이다(종류가 대충 맞으면 맞다. 예: "물고기"인데 어떤 물고기든 물고기면 맞다).</dd>
<dt>다른 동물</dt><dd>동물은 맞는데 질문 단어와 다르다(예: "새우"라고 물었는데 게).</dd>
<dt>동물 아님</dt><dd>물·모래·바위·해초·그림자·미끼 덩어리·화면 글자 등.</dd>
<dt>모르겠음</dt><dd>사진만으로 판단이 안 된다. 억지로 고르지 않으셔도 됩니다(결과에 그대로 "모르겠음"으로 적습니다).</dd></dl>
<p>이 답은 프로그램 숫자를 바꾸지 않습니다. 검사관이 사람과 얼마나 맞는지 적는 데만 씁니다.</p>"""

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
.q{font-size:17px;font-weight:700}.im{display:flex;gap:6px;overflow-x:auto}.im img{height:150px;border-radius:6px}
.b{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-top:8px}.b button,#done{padding:12px 0;font-size:16px;border:1px solid var(--line);
border-radius:8px;background:var(--bg);color:var(--fg)}.b button.on{background:var(--on);color:#fff}
#done{width:100%;margin:0 0 14px}button:focus-visible{outline:2px solid var(--on);outline-offset:2px}textarea{width:100%;height:110px}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}"""

parts = []
for c in cards:
    ko = KO.get(c["label"], c["label"])
    imgs = "".join(f'<img alt="사진" src="data:image/jpeg;base64,{base64.b64encode(j).decode()}">' for j in c["crops"])
    btns = "".join(f'<button data-a="{a}">{t}</button>' for a, t in (("Y", "맞다"), ("O", "다른 동물"), ("N", "동물 아님"), ("?", "모르겠음")))
    parts.append(f'<div class="c" data-n="{c["n"]}"><h2>#{c["n"]} <span class="q">이게 {html.escape(ko)}인가?</span> '
                 f'<small>({html.escape(c["label"])})</small></h2><div class="im">{imgs}</div><div class="b">{btns}</div></div>')
JS = """const N=%d,K="auditagree-1105";let A={},T0=null;try{const s=JSON.parse(localStorage.getItem(K)||"{}");A=s.a||{};T0=s.t0||null}catch(e){}
const save=()=>{try{localStorage.setItem(K,JSON.stringify({a:A,t0:T0}))}catch(e){}};
function draw(){document.querySelectorAll(".c").forEach(c=>c.querySelectorAll("button").forEach(b=>b.classList.toggle("on",A[c.dataset.n]===b.dataset.a)));
document.getElementById("prog").textContent=Object.keys(A).length+" / "+N}
document.querySelectorAll(".b button").forEach(b=>b.onclick=()=>{if(!T0)T0=Date.now();const n=b.closest(".c").dataset.n;
A[n]=A[n]===b.dataset.a?undefined:b.dataset.a;if(A[n]===undefined)delete A[n];save();draw()});
document.getElementById("done").onclick=()=>{const t=JSON.stringify({sheet:K,answers:A,seconds:T0?Math.round((Date.now()-T0)/1000):null,n_answered:Object.keys(A).length});
const o=document.getElementById("out");o.value=t;o.select();try{navigator.clipboard.writeText(t).then(()=>{document.getElementById("done").textContent="복사됨 — 채팅에 붙여 넣어 주세요"},()=>{})}catch(e){}};draw();""" % len(cards)
body = (f'<style>{CSS}</style><header><b>검사관 일치도 — 이게 그 동물인가요?</b> <span id="prog"></span></header>'
        f'<main><section class="g">{GUIDE}</section>{"".join(parts)}'
        f'<button id="done">답 복사</button><textarea id="out" readonly aria-label="답"></textarea></main><script>{JS}</script>')
head = '<title>Auditor agreement</title>\n<meta name="claude:viewport-fit-sides" content="cover">'
open(os.path.join(OUT, "sheet_artifact.html"), "w").write(head + body)
open(os.path.join(OUT, "sheet.html"), "w").write('<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" '
     'content="width=device-width,initial-scale=1,viewport-fit=cover">' + head + '</head><body>' + body + '</body></html>')
json.dump(dict(sheet="auditagree-1105", protocol=__doc__.split("\n\n")[0].replace("\n", " "),
               pool_sizes={k: len(v) for k, v in pool.items()}, excluded_renamed=excluded, seed=SEED, per_stratum=PER,
               cards=[{k: v for k, v in c.items() if k != "crops"} for c in cards]),
          open(os.path.join(OUT, "key.json"), "w"), indent=1)
print(len(cards), "cards ->", OUT, {k: len(v) for k, v in pool.items()}, "excluded", excluded)
