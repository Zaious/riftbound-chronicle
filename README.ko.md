# Riftbound Chronicle

실물 Riftbound 덱을 구성하고, 덱의 운용법을 배우고, 두 덱으로 연습할 수 있도록 설계된 근거 중심 AI Skill입니다.

[English](README.md) · [繁體中文](README.zh-TW.md)

## 세 가지 시스템

| 시스템 | 목적 | 권한 경계 | 실행 가능한 결과물 |
| --- | --- | --- | --- |
| `deck-coach` | 덱 분석, 구축 방향, 8개 섹션 플레이 가이드 | 조언만 제공하며 승률이나 Tier를 만들지 않음 | profile, mask, primer, evaluation, A/B battle |
| `rule-consult` | 날짜와 출처가 있는 규칙／상호작용 설명 | 비공식 상담이며 게임 상태를 변경하거나 심판을 대체하지 않음 | consultation record, evidence ledger |
| `player2-agent` | 두 개의 실물 덱으로 연습할 때 Player 2 전략을 제안 | 숨은 정보, 합법성, 해결 및 상태 갱신은 사람이 담당 | P2-A session ledger |

현재 Player 2는 **P2-A**만 구현되어 있습니다. Agent가 행동과 이유를 제안하고, 사람이 합법성을 확인한 뒤 실물 카드로 해결합니다. 자동 시뮬레이터인 P2-S는 문서로만 계획되어 있으며 구현되지 않았습니다.

## 빠른 시작

필요 조건은 Git과 Python 3.10 이상입니다. 정적 데모에는 패키지 설치나 빌드가 필요하지 않습니다.

```powershell
git clone https://github.com/Zaious/riftbound-chronicle.git
cd riftbound-chronicle
python skill/scripts/deck_coach_pipeline.py run `
  --case-id DC-RNG-GLOBAL-001 `
  --output-dir deck-coach-output
```

브라우저에서 다음 데모를 직접 열 수 있습니다.

- [Deck Coach](prototype/deck-coach/index.html)
- [Rule Consult](prototype/rule-consult/index.html)
- [P2-A](prototype/p2a/index.html)

세 페이지는 Ember & Aged Gold 색상, 동일한 브랜드 헤더, 페이지 프레임, 폰트와 컨트롤 스타일을 공유합니다. 기본 언어는 번체 중국어이며 오른쪽 위의 `EN` 버튼으로 영어로 전환할 수 있습니다. 데모는 모델을 호출하지 않고 브라우저 저장소를 사용하지 않으며 게임 규칙을 자동 실행하지 않습니다.

## Deck Coach 폐쇄 루프

```text
decklist + environment + player level
  → structured deck profile
  → recommendation mask
  → eight-section primer
  → seven-dimension evaluation
  → optional blind A/B primer battle
```

프로필에는 Legend, 포맷, 지역 카드 풀, Energy 곡선, Domain, Power, 카드 유형, 8가지 역할, 상호작용／드로우／재귀／이동 밀도, 엔진 후보, 출처와 신뢰도가 기록됩니다.

mask는 선택한 환경에서 출시되지 않은 카드, 금지 카드, Legend의 Domain 정체성과 맞지 않는 카드, 보유하지 않은 카드, 오래된 errata를 사용하는 카드, 다른 환경의 대회 자료를 제외합니다. 실제 대회용 추천은 현재 공식 합법성 자료를 다시 확인해야 합니다.

## Rule Consult와 규칙 PDF

Rule Consult는 사용자가 제공한 사실, 가정, 규칙 근거, 분석, 신뢰도와 escalation을 분리해 기록합니다. 결과에는 항상 `official_status: unofficial`, `state_effect: none`이 유지됩니다.

공개 저장소에는 Riot의 규칙 PDF를 넣지 않습니다. 정확한 조항이 필요할 때 한 번만 다음 명령을 실행하세요.

```powershell
python skill/scripts/bootstrap_rules.py --yes
```

Core Rules와 Tournament Rules가 Git에서 무시되는 `skill/.local/rules/`에 저장되고, 로컬 SHA-256 lock 파일이 생성됩니다. `RIFTBOUND_RULES_DIR` 또는 `--rules-dir`로 다른 경로를 지정할 수도 있습니다. Skill은 질문을 받을 때 몰래 다운로드하지 않습니다. 파일이 없으면 bootstrap 또는 최신 공식 출처를 요청합니다.

대회 절차 우선순위는 다음과 같습니다.

```text
event addendum > Tournament Rules > 수정되지 않은 Core Rules > 현장 Head Judge
```

## P2-A 경계

```text
사람이 공개 상태를 확인
  → Agent가 행동과 이유를 제안
  → 사람이 합법성을 확인
  → 사람이 실물 카드로 해결하고 새 상태를 확인
```

P2-A는 상대의 숨은 정보를 보지 않고, 행동이 합법이라고 주장하지 않으며, 해결 후 상태를 추론하지 않습니다. 셔플, 드로우, 단계 진행, 전투／효과 해결, 점수 계산, 승자 판정도 수행하지 않습니다.

## 출처, 데이터와 검증

출처 우선순위는 현재 공식 규칙／대회 문서／errata／금지 목록, 공식 카드 텍스트, 신뢰할 수 있는 커뮤니티 자료, 명시된 추론, 그리고 알 수 없음입니다. 포함된 카드 snapshot은 비공식 RiftCodex API에서 가져온 것으로 1,451개 row와 1,304개의 unique card ID를 포함합니다. 자세한 내용은 [데이터 출처와 제한](skill/data/README.md)을 확인하세요.

```powershell
python skill/scripts/check_data_integrity.py
python skill/scripts/check_links.py
python skill/scripts/check_deck_coach.py
python skill/scripts/check_deck_coach_prototype.py
python skill/scripts/check_rule_consult.py
python skill/scripts/check_rule_consult_prototype.py
python skill/scripts/check_p2a_protocol.py
python skill/scripts/check_p2a_prototype.py
python skill/scripts/check_prototype_ui.py
python skill/scripts/check_rules_bootstrap.py
```

## 규정 준수와 라이선스

이 프로젝트는 승률, 사용률, 매치업 비율 또는 Tier 순위를 게시하거나 저장하지 않습니다. 공식 심판 권한을 주장하지 않으며 Riftbound 경기를 자동화하지 않습니다. Riot product registration과 공식 API 카드 출처는 아직 해결되지 않은 문제입니다.

원본 코드와 방법론은 [MIT](LICENSE) 라이선스입니다. 카드 이름, 규칙 텍스트 및 기타 Riot 소유 자료는 이 라이선스에 포함되지 않습니다.

> Riftbound Chronicle was created under Riot Games' “Legal Jibber Jabber” policy using assets owned by Riot Games. Riot Games does not endorse or sponsor this project.

Riftbound Chronicle은 Riot Games와 제휴하지 않은 비공식 fan project입니다.
