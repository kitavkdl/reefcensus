"""Second pass of the auditor-agreement sheet (audit_agree_sheet.py). After answering the first sheet, the person said
that a fair number of "yes" answers were given when unsure. Same 60 cards, same crops (cut out of the first sheet's
html), new order (random.Random(1106)), A1's answer still hidden, first-pass answers not shown. Five buttons:
S "sure: yes, a <label>", A "unsure, could be a <label>", O "an animal, but not a <label>", N "not an animal",
? "can't tell at all". Scoring is fixed here, before the person sees the sheet (audit_agree_score.py --recheck):
only S counts as yes; A is scored like ? (left out, and separately counted as disagreement with A1).
The first pass stays on record as answered; both are reported.

  python3 report/paper/scripts/audit_agree_recheck.py
"""
import json, os, random, re

D = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "audit_agree")
first = open(os.path.join(D, "sheet.html")).read()
css = re.search(r"<style>(.*?)</style>", first, re.S).group(1)
cards = {}
for m in re.finditer(r'<div class="c" data-n="(\d+)"><h2>#\d+ (<span class="q">.*?</small>)</h2><div class="im">(.*?)</div>',
                     first, re.S):
    cards[int(m.group(1))] = (m.group(2), m.group(3))
assert len(cards) == 60, len(cards)
order = sorted(cards); random.Random(1106).shuffle(order)

GUIDE = """<h3>왜 다시 하나</h3><p>아까 시트에서 애매한데 "맞다"를 누른 카드가 꽤 있다고 하셔서, <b>같은 사진 60장</b>을 순서만 바꿔 다시 묻습니다.
아까 답은 그대로 기록에 남고, 이번 답과 함께 논문에 적습니다. 검사관 답은 이번에도 숨겼습니다.</p>
<h3>선택지</h3><dl>
<dt>확실히 맞다</dt><dd>노란 상자 안이 그 동물이라고 <b>자신 있게</b> 말할 수 있을 때만. (논문에서 '맞다'로 세는 건 이것뿐입니다.)</dd>
<dt>애매함</dt><dd>그럴 수도 있는데 확신이 없다. 조금이라도 망설여지면 이것.</dd>
<dt>다른 동물</dt><dd>동물은 맞는데 질문 단어와 다르다(예: "새우"라고 물었는데 게).</dd>
<dt>동물 아님</dt><dd>물·모래·바위·해초·그림자·미끼 덩어리·화면 글자 등.</dd>
<dt>모르겠음</dt><dd>사진만으로 전혀 판단이 안 된다.</dd></dl>
<p>다 끝나면 맨 아래 <b>답 복사</b> → 채팅에 붙여 넣어 주세요. 이 답은 프로그램 숫자를 바꾸지 않습니다.</p>"""
CSS = css + ".b{grid-template-columns:1fr 1fr 1fr}"
BT = (("S", "확실히 맞다"), ("A", "애매함"), ("O", "다른 동물"), ("N", "동물 아님"), ("?", "모르겠음"))
parts = []
for i, n in enumerate(order, 1):
    q, imgs = cards[n]
    btns = "".join(f'<button data-a="{a}">{t}</button>' for a, t in BT)
    parts.append(f'<div class="c" data-n="{n}"><h2>{i}/60 {q}</h2><div class="im">{imgs}</div><div class="b">{btns}</div></div>')
JS = """const N=60,K="auditagree-1106";let A={},T0=null;try{const s=JSON.parse(localStorage.getItem(K)||"{}");A=s.a||{};T0=s.t0||null}catch(e){}
const save=()=>{try{localStorage.setItem(K,JSON.stringify({a:A,t0:T0}))}catch(e){}};
function draw(){document.querySelectorAll(".c").forEach(c=>c.querySelectorAll("button").forEach(b=>b.classList.toggle("on",A[c.dataset.n]===b.dataset.a)));
document.getElementById("prog").textContent=Object.keys(A).length+" / "+N}
document.querySelectorAll(".b button").forEach(b=>b.onclick=()=>{if(!T0)T0=Date.now();const n=b.closest(".c").dataset.n;
A[n]=A[n]===b.dataset.a?undefined:b.dataset.a;if(A[n]===undefined)delete A[n];save();draw()});
document.getElementById("done").onclick=()=>{const t=JSON.stringify({sheet:K,answers:A,seconds:T0?Math.round((Date.now()-T0)/1000):null,n_answered:Object.keys(A).length});
const o=document.getElementById("out");o.value=t;o.select();try{navigator.clipboard.writeText(t).then(()=>{document.getElementById("done").textContent="복사됨 — 채팅에 붙여 넣어 주세요"},()=>{})}catch(e){}};draw();"""
body = (f'<style>{CSS}</style><header><b>검사관 일치도 — 다시 보기(확신 나눠서)</b> <span id="prog"></span></header>'
        f'<main><section class="g">{GUIDE}</section>{"".join(parts)}'
        f'<button id="done">답 복사</button><textarea id="out" readonly aria-label="답"></textarea></main><script>{JS}</script>')
open(os.path.join(D, "recheck.html"), "w").write(
    '<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" '
    'content="width=device-width,initial-scale=1,viewport-fit=cover"><title>Auditor agreement, recheck</title></head><body>'
    + body + '</body></html>')
json.dump(dict(sheet="auditagree-1106", protocol=__doc__.split("\n\n")[0].replace("\n", " "), order=order),
          open(os.path.join(D, "recheck_key.json"), "w"), indent=1)
print("60 cards ->", os.path.join(D, "recheck.html"))
