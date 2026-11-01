"""Second-round report (11/1 evening): divergent axes, tests F (AI-video permanence) and G (kitchen contact graph).
usage: python3 make_report2.py <out.html>"""
import sys
from make_report import CSS, img

AXES = [  # axis, idea, fate
    ("SAM을 '증인'으로", "F. AI 생성 영상의 물체 영속성 위반 찾기", "<b class=mid>실측</b>"),
    ("SAM의 약점을 신호로 (마스크가 붙음 = 접촉)", "G. 주방 교차오염 추적 (접촉 그래프)", "<b class=ok>실측</b>"),
    ("Meta 모델 셋이 서로 확인", "H. how-to 영상의 '이거·여기'를 실제 물체 이름으로 (Transcribe→Spark→SAM)", "미실측: S1(칠판 강의)과 겹침, 선행 EgoPointVQA·HowToGround1M"),
    ("Meta가 Meta를 채점", "I. SAM이 Muse Image 개수 오류를 잡고 마스크로 재편집", "미실측: Impact 약함, 선행 SLD·Make It Count"),
    ("SAM을 '자'로", "J. 휠체어 눈높이 영상에서 차 폭을 기준으로 보도 통과 폭 재기", "미실측: 'CV 접근성 프로젝트'로 읽힘"),
    ("트랙을 가속도계로", "K. 스톱모션 인형 튐 감지 + 지지대 지우기", "미실측: 선행 없음, 하지만 대상 작음"),
    ("시간 거꾸로", "언제 처음 나타났나", "탈락: SAM 2 역재생, BriefCam"),
    ("출력 매체 바꾸기", "마스크→공간 음향, 마스크+캡션→영상 코덱", "탈락: 큰 문제 없음 / arXiv 2602.05201"),
    ("세기", "벌통·수분 매개·과일·가축·군중", "탈락: 기존 제품·16개 상한"),
]

TESTS = [  # candidate, data, prompts, result, cost
    ("F1 Sora 도쿄 거리 (AI)", "Commons 공공", "person", "트랙 16, 안쪽에서 갑자기 생김 4", "$0.01"),
    ("F4 시부야 거리 (실제, 대조)", "Commons CC BY-SA 4.0 (Basile Morin)", "person", "트랙 12, 안쪽에서 생김 2 → <b class=no>AI와 구별 안 됨</b>", "$0.01"),
    ("F2 Sora 매머드", "Commons 공공", "mammoth", "3마리 끝까지, 위반 0", "$0.01"),
    ("F3 Sora 고양이", "Commons 공공", "cat, paw", "고양이 정상 · paw는 끝부분 앞발 하나 더 생김(유명 결함)을 <b class=mid>잡았지만 내 규칙은 '가림'으로 분류</b>", "$0.02"),
    ("G1 CDC 교육 만화", "Commons 공공 (CDC)", "hand, knife, meat, cutting board", "<b class=ok>4종 모두 검출</b>(만화인데도), 손이 고기 도마를 들었다 내려놓는 접촉 순서 맞음", "$0.04"),
    ("G2 스테이크 썰기 (실제)", "Commons CC BY 3.0 (Serious Eats)", "hand, knife, meat, cutting board", "<b class=ok>4종 모두 검출</b>, 손·칼·고기 마스크 접촉 9쌍. 장면 전환 2번. 오염이 채소로 옮겨 가는 장면은 클립에 없어 <b class=mid>연쇄 전파는 미검증</b>", "$0.04"),
]

SCORES = [  # name, impact, meta, tech, demo, creativity, ambition, works, note
    ("물고기 MaxN (기준선)", 8, 7, 8, 8.5, 6, 7, 8.5, "작동 확인 끝. SAM을 원래 용도로 씀"),
    ("G 주방 교차오염 추적", 7.5, 7.5, 8, 8.5, 7.5, 7.5, 6, "검출 확인, 연쇄 전파·세척 리셋은 미검증. 촬영은 직접(닭+샐러드)"),
    ("F AI 영상 영속성 위반", 8, 7, 7, 7.5, 7, 7, 4, "AI/실제 구별 실패, Skyra(CVPR 2026)가 약 90%"),
]


def tbl(head, rows):
    h = ["<table><tr>" + "".join(f"<th>{c}</th>" for c in head) + "</tr>"]
    h += ["<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows]
    return "\n".join(h) + "</table>"


def scores():
    rows = []
    for n, i, m, t, d, c, a, w, note in SCORES:
        rows.append((n, i, m, t, d, f"<b>{0.3 * i + 0.25 * m + 0.2 * t + 0.25 * d:.2f}</b>", f"{c} / {a} / {w}", note))
    return tbl(["후보", "Impact ×0.30", "Meta ×0.25", "기술 ×0.20", "데모 ×0.25", "루브릭 가중", "Indie 창의/야심/작동", "메모"], rows)


FIGS = [
    ("G/evid_contact_real.jpg", "G2 실제 영상: hand(주황)·knife(파랑)·meat(빨강)·cutting board(초록)를 단어 4개로 동시에 추적. 학습 없음"),
    ("G/timeline_steak.png", "G2 접촉 타임라인: 마스크(박스 아님)가 맞닿은 구간. 이 줄들이 오염 전파 그래프의 간선이 된다"),
    ("G/evid_contact.jpg", "G1 CDC 만화: 사진이 아닌데도 검출됨 → '사진 같은 화면만'이 아니라 '실물을 그린 화면'이면 됨"),
    ("F/evid_cat_paw.jpg", "F3 Sora 고양이: 49번 칸에서 앞발 #2가 #1 자리에 하나 더 생김. 진짜 결함이지만 가림과 구별하는 규칙이 필요"),
    ("F/evid_tokyo.jpg", "F1 Sora 도쿄: 안쪽에서 생긴 사람 트랙. 실제 영상에도 같은 현상이 있어 판별 근거로 약함 (이 그림은 내가 눈으로 확인 안 함)"),
]


def build(out):
    figs = "\n".join(f'<figure><img src="{img(p)}" alt=""><figcaption>{c}</figcaption></figure>' for p, c in FIGS)
    html = f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>새 방향 2차 검사</title><style>{CSS}</style></head><body><main>
<h1>새 방향 2차 검사 — 2026-11-01 저녁</h1>
<div class="lead"><b>한 줄 결론:</b> 참신성 축 7개로 넓혀 약 30개를 떠올리고 5개만 남겨 2개를 실측했다.
<b>G 주방 교차오염 추적</b>이 루브릭 가중 7.85로 물고기 MaxN(7.88)과 사실상 동점이고 창의 점수는 더 높지만, 핵심인 연쇄 전파는 아직 검증 안 됐다.
F(AI 영상 판별)는 실제 영상과 구별이 안 돼 탈락 수준. 이번 SAM 지출 <b>$0.13</b> (F $0.05 · G $0.08), 장부 누계 $0.730.</div>
<h2>1. 어떻게 뻗었나 (축 → 아이디어 → 운명)</h2><div class="wrap">{tbl(["참신성 축", "아이디어", "결과"], AXES)}</div>
<p style="color:var(--mut);font-size:13px">발산은 다른 모델(fable) 서브에이전트가 내 결론 없이 했고, F는 내가 냈다. 선행작 레드팀은 sonnet 서브에이전트 2회.</p>
<h2>2. 실측 (실패 포함 전부)</h2><div class="wrap">{tbl(["클립", "데이터·라이선스", "프롬프트", "결과", "비용"], TESTS)}</div>
<h2>3. 선행작 레드팀</h2><ul>
<li><b>F → 부분적.</b> Skyra(CVPR 2026)가 '비정상 출현·소멸'을 시간·박스로 표시하고 Sora-2 포함 정확도 약 90%. World Consistency Score는 검출기+추적기로 영속성 점수(생성 모델 평가용). 동기는 강함: Meta가 Oversight Board에 "정지 이미지만 자동 판별, 영상은 못 함"이라고 했고, WaPo 시험에서 8개 플랫폼 모두 Content Credentials를 지움.</li>
<li><b>G → 부분적.</b> Intel 특허 US10275659(2017, 소멸): 카메라+센서로 생닭 자른 칼을 표시하고 다른 음식에 닿으면 경고(1단계로 보임, 청구항 미확인). 제품(Wobot·Dragontail·Agrex)은 장갑·헤어넷·손 씻기뿐. 논문 Ego-OMG는 손-물체 접촉 그래프를 행동 예측에만 씀. <b>열린 부분:</b> 학습 없는 단어 추적 + 여러 단계 전파 + 단계마다 증거 프레임 + Spark 설명, 그리고 측정된 정확도를 낸 곳이 없음.</li>
<li>G의 Impact 근거: CDC 연 4,800만 명 식중독. NC State 8개 주방 영상 연구 "직원 1인당 시간당 약 1번 교차오염 행동"(2010). FDA 위험 요인 조사 2008: 오염된 기구 항목 준수율 일반 식당 65%.</li>
<li>G의 약점(레드팀): 2D 맞닿음 ≠ 실제 접촉, 간선 하나 틀리면 연쇄 전체가 오염, 주방 SAM 재식별 52.8% mAP(EPIC-Kitchens), 세척 장면 인식, 직원 감시 우려 → '감시'가 아니라 <b>교육·리플레이 도구</b>로 포장해야 함.</li></ul>
<h2>4. 작동한 것만 채점</h2><p>공식 루브릭 가중 = 0.30·Impact + 0.25·Meta + 0.20·기술 + 0.25·데모. 점수는 내 판단.</p><div class="wrap">{scores()}</div>
<h2>5. 증거 프레임</h2>{figs}
<h2>6. 판단 (결정은 대표님)</h2><ul>
<li><b>F는 접는다.</b> 판별이 안 되고 선행작이 앞서 있다.</li>
<li><b>G는 물고기와 동점</b>이지만 "Meta도 놀랄" 근거(약점을 신호로, 접촉 그래프)가 물고기보다 강하다. 대신 남은 3일 안에 ① 마스크 접촉 정확도 ② 오염 연쇄 ③ 세척 리셋을 직접 찍은 영상(생닭 → 칼 → 샐러드)으로 증명해야 하고, 촬영은 대표님 손이 필요하다.</li>
<li>둘 다 아니면 대표님 지시대로 <b>물고기 MaxN 복귀</b>. 기존 코드(api·tracks·render)는 G에도 그대로 쓰인다.</li></ul>
<p style="color:var(--mut);font-size:13px">코드: ~/meta-fish/spikes/F (lifecycle.py), G (contact.py·maskcontact.py·timeline.py), make_report2.py.</p>
</main></body></html>"""
    open(out, "w").write(html)
    print(out, len(html) // 1024, "KB")


if __name__ == "__main__":
    build(sys.argv[1])
