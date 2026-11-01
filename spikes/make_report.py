"""Build the self-contained HTML report (images embedded) for the 11/1 non-camera spikes.
usage: python3 make_report.py <out.html>"""
import base64, os, sys
sys.path.insert(0, os.path.expanduser("~/meta-smoke/pylib"))
import cv2

HERE = os.path.dirname(os.path.abspath(__file__))


def img(path, w=1400, q=72):
    im = cv2.imread(os.path.join(HERE, path))
    if im.shape[1] > w:
        im = cv2.resize(im, (w, int(im.shape[0] * w / im.shape[1])), interpolation=cv2.INTER_AREA)
    b = cv2.imencode(".jpg", im, [cv2.IMWRITE_JPEG_QUALITY, q])[1].tobytes()
    return "data:image/jpeg;base64," + base64.b64encode(b).decode()


ROWS = [  # candidate, data & licence, prompts tried, result, cost, prior art (red team)
    ("대조군 물고기", "IMAS 심해 BRUV (CC BY 4.0)", "fish", "<b class=ok>16개 추적</b>, 58/58프레임", "$0.012",
     "—"),
    ("A 소리→스펙트로그램", "돌고래 CC0 · 혹등고래 CC BY 2.5 · 지빠귀 CC BY-SA 3.0", "line ×3, whistle, curve",
     "<b class=no>5번 모두 0</b>", "$0.05", "이미 있음: SAM-Whistle (Sci. Rep. 2025, Silbido 저자), 고래 호출 zero-shot SAM (2026)"),
    ("B 태양 흑점 (단어)", "NASA SDO HMI (공공)", "sunspot(전체·3배 확대), hole, spot",
     "<b class=no>sunspot·hole 0</b> · spot만 흑점 496개 중 64개(13%)", "$0.04", "부분적: 비SAM 추적기 다수(HARP·SMART)"),
    ("B 태양 흑점 (상자)", "같은 클립", "2개 흑점군에 상자 1번", "<b class=ok>2개 모두 화면 나갈 때까지 추적</b>(35·26프레임), 새 흑점군은 못 찾음", "$0.01", "SAM 2 방식 추적 그 자체"),
    ("C 위성 해빙 (단어)", "NASA Worldview MODIS (공공)", "iceberg, ice, ice(2배 확대), cloud", "<b class=no>4번 모두 0</b>", "$0.04",
     "부분적: Ice Floe Tracker, SatSAM2, SegEarth-OV3"),
    ("C 위성 해빙 (상자)", "같은 클립", "6개 해빙에 상자 1번(25일째)", "<b class=mid>씨앗 날짜 ±3일만 추적</b>, 그 밖 검출 10건은 오인 의심(미검증)", "$0.01", "SAM 2 방식 추적 그 자체"),
    ("D 소나 물고기", "Caltech Fish Counting, ARIS (CaltechDATA 표기 MIT)", "fish", "<b class=no>0</b> (정답 19마리)", "$0.02", "@D"),
    ("E 열화상 드론", "BIRDSAI (CDLA-Permissive 1.0)", "animal, elephant", "<b class=no>2번 모두 0</b> (정답 약 10마리)", "$0.04", "@E"),
]

SCORES = [  # name, impact, meta, tech, demo, creativity, ambition, works, note
    ("물고기 MaxN (기준선, 기존)", 8, 7, 8, 8.5, 6, 7, 8.5, "설계 문서 자체 채점 7.85. SAM을 원래 용도로 씀"),
    ("B 흑점 상자 추적", 4, 5, 5, 7, 5, 4, 7, "과학자가 이미 자동 도구로 하는 일. 상자 줘야 함"),
    ("C 해빙 상자 추적", 5.5, 5, 5.5, 6.5, 6, 5, 4.5, "구름 낀 날 끊김, 3일 넘으면 놓침"),
]


def table():
    rd = {"@D": D_PRIOR, "@E": E_PRIOR}
    h = ["<table><tr><th>후보</th><th>데이터·라이선스</th><th>시도한 프롬프트</th><th>결과</th><th>비용</th><th>선행작(레드팀)</th></tr>"]
    for r in ROWS:
        h.append("<tr>" + "".join(f"<td>{rd.get(c, c)}</td>" for c in r) + "</tr>")
    return "\n".join(h) + "</table>"


def scores():
    h = ["<table><tr><th>작동한 것</th><th>Impact ×0.30</th><th>Meta 도구 ×0.25</th><th>기술 ×0.20</th><th>데모 ×0.25</th>"
         "<th>루브릭 가중</th><th>Indie: 창의 / 야심 / 작동</th><th>메모</th></tr>"]
    for n, i, m, t, d, c, a, w, note in SCORES:
        tot = 0.3 * i + 0.25 * m + 0.2 * t + 0.25 * d
        h.append(f"<tr><td>{n}</td><td>{i}</td><td>{m}</td><td>{t}</td><td>{d}</td><td><b>{tot:.2f}</b></td>"
                 f"<td>{c} / {a} / {w}</td><td>{note}</td></tr>")
    return "\n".join(h) + "</table>"


D_PRIOR = os.environ.get("D_PRIOR", "확인 중")
E_PRIOR = os.environ.get("E_PRIOR", "확인 중")

FIGS = [
    ("fail_sheet.jpg", "실패 7종: 사진이 아닌 화면에선 단어 프롬프트가 아무것도 못 찾음 (각 칸 제목에 시도한 단어)"),
    ("control/evid_fish.jpg", "대조군: 같은 날 같은 API·코드로 물고기 영상에 'fish' → 16마리. 0검출이 API 고장 탓이 아님을 확인"),
    ("B/evid_B2_spot.jpg", "B 단어 'spot': 흑점 일부만 잡음. 2번째 칸의 큰 흑점군도 1개만"),
    ("B/evid_B2_box.jpg", "B 상자 모드: 2번 프레임에 상자 2개 → 약 3일 자전을 따라 마스크 유지. 24번 칸의 새 큰 흑점들은 상자를 안 줬으니 못 찾음"),
    ("C/evid_C1_box.jpg", "C 상자 모드: 25일째 해빙 6개 → 22~28일 따라감(구름 사이). 7일째 #5·33일째는 다른 것을 잡은 것으로 보임"),
]

CSS = """
:root{--bg:#fbfaf7;--fg:#1d1d1b;--mut:#6b6a66;--line:#e2dfd8;--ok:#1f7a3a;--no:#b3261e;--mid:#9a6700;--card:#fff}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#161615;--fg:#ecebe7;--mut:#a3a19b;--line:#33322f;--ok:#5fc17a;--no:#ff8a80;--mid:#e0b04a;--card:#1e1e1c}}
body{background:var(--bg);color:var(--fg);font:15px/1.6 system-ui,-apple-system,"Apple SD Gothic Neo","Noto Sans KR",sans-serif;margin:0;padding:24px 16px}
main{max-width:1100px;margin:0 auto}h1{font-size:22px}h2{font-size:18px;margin-top:36px}
.lead{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 18px}
table{border-collapse:collapse;width:100%;font-size:13.5px;background:var(--card)}th,td{border:1px solid var(--line);padding:7px 9px;vertical-align:top;text-align:left}
th{color:var(--mut);font-weight:600}.ok{color:var(--ok)}.no{color:var(--no)}.mid{color:var(--mid)}
.wrap{overflow-x:auto}figure{margin:18px 0}figure img{width:100%;border-radius:8px;border:1px solid var(--line)}figcaption{color:var(--mut);font-size:13.5px;margin-top:6px}
li{margin:4px 0}
"""


def build(out):
    figs = "\n".join(f'<figure><img src="{img(p)}" alt=""><figcaption>{c}</figcaption></figure>' for p, c in FIGS)
    html = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>비카메라 SAM 검사</title><style>{CSS}</style></head><body><main>
<h1>SAM 3.1 비카메라 데이터 검사 — 2026-11-01</h1>
<div class="lead"><b>한 줄 결론:</b> SAM 3.1의 <b>단어 프롬프트는 사진처럼 생긴 화면에서만 작동</b>했다.
스펙트로그램·태양·위성·소나·열화상 5종, 단어 15번 중 14번이 0검출, 1번(흑점 'spot')은 13%만.
같은 시각 대조군(물고기)은 정상이라 API 고장은 아니다. <b>상자를 직접 찍어 주는 모드</b>는 태양·해빙에서 추적이 되지만, 이건 SAM 2부터 있던 기능이라 "Meta도 놀랄" 근거로는 약하다.
<br>이번 세션 SAM 지출 <b>$0.221</b> (A $0.05 · B $0.05 · C $0.05 · D $0.02 · E $0.04 · 대조군 $0.012), 상한 $0.30 안.</div>
<h2>1. 비교표 (실패 포함 전부)</h2><div class="wrap">{table()}</div>
<h2>2. 작동한 것만 채점</h2>
<p>공식 루브릭 가중 = 0.30·Impact + 0.25·Meta 도구 + 0.20·기술 깊이 + 0.25·데모. 점수는 내 판단(10점 만점)이다. 비교를 위해 기존 물고기 MaxN을 기준선으로 넣었다.</p>
<div class="wrap">{scores()}</div>
<h2>3. 증거 프레임</h2>{figs}
<h2>4. 읽는 법과 남은 선택지 (결정은 대표님)</h2><ul>
<li><b>원리 자체가 막힘:</b> "영상이 아닌 것을 영상으로 만들어 SAM 단어 추적"은 이번 API에선 성립하지 않는다. 학습 데이터(사진)와 닮은 화면일 때만 단어가 먹는다.</li>
<li><b>작동하는 구조는 '씨앗 + 추적':</b> 고전적 방법(밝기 문턱 등)이나 Spark가 상자를 찍고 SAM이 따라가는 방식. 이번 B·C 상자도 내가 문턱으로 고른 것이다. 다만 이건 SAM 2 시절부터 가능한 조합이라 참신성은 낮다.</li>
<li><b>시험 안 한 변수:</b> A의 색 지도(흑백·반전), C의 더 촘촘한 영상(GOES 10분 간격), D·E의 상자 모드. 각 $0.01–0.02. 같은 실패일 가능성이 높다고 본다.</li>
<li>기존 물고기 MaxN은 여전히 가장 높다. 참신성 축은 약하다.</li></ul>
<p style="color:var(--mut);font-size:13px">코드·원자료: ~/meta-fish/spikes (A·B·C·D·E·control 폴더, run.py·evid.py). 선행작 원문: ops/sessions/meta-hackathon/ideation/redteam-nonvideo.md, redteam-sensor.md.</p>
</main></body></html>"""
    open(out, "w").write(html)
    print(out, len(html) // 1024, "KB")


if __name__ == "__main__":
    build(sys.argv[1])
