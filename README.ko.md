# Riftbound Chronicle

실물 Riftbound 덱을 구성하고, 덱의 운용법을 배우고, 두 덱으로 연습할 수 있도록 설계된 근거 중심 AI Skill입니다.

[English](README.md) · [繁體中文](README.zh-TW.md)

## 왜 이렇게 만들었는가

이 장치들이 전혀 없어도 언어 모델은 카드 상호작용을 "판단"할 수 있습니다. 다만 그것은 그럴듯한 텍스트 이어쓰기에 근거한 판단이며, 합법성과는 다릅니다. 모델은 Reaction 카드의 문면을 읽고 Showdown 마지막에 체인으로 끼워 넣어 Might를 더할 수 있다고 결론지을 수 있습니다. 읽기에는 자연스럽지만, 그것은 합법적인 플레이가 아닙니다.

그래서 기계적인 부분은 프로그램이 소유합니다. 언제 무엇을 낼 수 있는지, 무엇에 대응할 수 있는지, 우선권이 어떻게 넘어가는지, 그리고 현재 점수·비용·Might 같은 수치 —— 이것들은 규칙과 산술의 영역이고, 모델에게 맡기면 흔들립니다. 가장 강력한 모델조차 무언가가 숫자를 검사해 주지 않으면 8.11이 8.9보다 크다고 말합니다.

그다음 모델은 프로그램이 이미 좁혀 놓은 공간 안에서, 실제 규칙과 동일한 외부 제약 아래에서 추론합니다. 이것이 설계의 핵심입니다: **모델이 읽을 수 있도록 규칙을 번역하는 것이 아니라, 모델이 내릴 수 있는 결론의 범위를 제한하는 것.**

현재 프로그램이 소유하는 것은 *타이밍과 권한* 계층입니다. 완전한 합법성은 여전히 사람이 확인하며(아래 P2-A 경계 참조), 자동 규칙 집행은 어차피 현재 Riot 정책상 승인되지 않았습니다. 합법 행동 열거는 계획된 릴리스이며, 대국 기록을 더 모으는 것이 아니라 conformance 커버리지 통과 여부에 달려 있습니다.

## 시스템

| 시스템 | 목적 | 권한 경계 | 실행 가능한 결과물 |
| --- | --- | --- | --- |
| `deck-coach` | 덱 분석, 구축 방향, 8개 섹션 플레이 가이드 | 조언만 제공하며 승률이나 Tier를 만들지 않음 | profile, mask, primer, evaluation, A/B battle |
| `rule-consult` | 날짜와 출처가 있는 규칙／상호작용 설명 | 비공식 상담이며 게임 상태를 변경하거나 심판을 대체하지 않음 | consultation record, evidence ledger |
| `player2-agent` | 두 개의 실물 덱으로 연습할 때 Player 2 전략을 제안 | 숨은 정보, 합법성, 해결 및 상태 갱신은 사람이 담당 | P2-A session ledger |

### 엔진 연결 상태

시스템은 체크리스트의 여섯 조건을 모두 통과해야 연결된 것으로 봅니다: artifact가 봉투를 받아들이고, runner가 생성하며, validator가 과장된 주장을 거부하고, UI가 결과를 표시하며, 회귀 테스트가 지원 사례와 기권 사례를 모두 포함하고, 권한 경계가 유지되어야 합니다. `skill/scripts/check_readme_connection_claims.py`가 artifact에서 이 표를 도출하며, 표가 어느 쪽으로든 어긋나면 실패합니다.

| 시스템 | 상태 | 조건 |
| --- | --- | ---: |
| `rule-consult` → `engine-check.v1` | `connected` | 6 / 6 |
| `player2-agent` → `engine-check.v1` | `connected` | 6 / 6 |
| `deck-coach` → `engine-check.v1` | `connected` | 6 / 6 |
| `match-analyst` → `engine-check.v1` | `planned` | 0 / 6 |

Deck Coach는 이 봉투를 규칙 일관성 증거로만 소비합니다(ADR-0006). 검사를 첨부해도 진단이나 프라이머는 바뀌지 않으며, 스스로 검사를 만들지 않습니다. Match Analyst는 명세와 fixture만 있고 라우팅되지 않았습니다.

현재 Player 2는 **P2-A**만 구현되어 있습니다. Agent가 행동과 이유를 제안하고, 사람이 합법성을 확인한 뒤 실물 카드로 해결합니다. 자동 시뮬레이터인 P2-S는 문서로만 계획되어 있으며 구현되지 않았습니다.

네 시스템은 **Chronicle이 직접 소유하고 관리하는 규칙 코어**를 공유하며, 이 코어는 conformance 스위트가 실제로 실행하는 것만 주장합니다:

- 타이밍·권한 커널: 네 가지 턴 상태, Action／Reaction, Priority／Focus, HOT／FEPR —— 21개 실행 가능한 케이스(`skill/data/rules_core_cases.json`);
- 제한된 typed effect IR: 15개 연산과 시퀀스, 대상, 연결 효과, 치명 정리, 트리거 방출을 포함하며, 모델링되지 않은 카드 동작을 만나면 추측하지 않고 **fail closed**;
- 둘 사이의 원자적 브리지: 타이밍 판정과 해당 typed effect는 함께 커밋되거나 함께 롤백됩니다.

다른 팬 시뮬레이터에 런타임 의존성이 없으며, 모든 카드 효과를 결산할 수 있다고 주장하지 않습니다 —— `unsupported`는 오류 경로가 아니라 일급 결과입니다. 아키텍처와 흡수 경계는 [주권 규칙 레이어](docs/architecture/SOVEREIGN_RULES_LAYER.md)를, 두 차례의 감사가 규칙 엔진을 만들지 말라고 권고했음에도 만든 이유는 [ADR-0001](docs/decisions/ADR-0001-sovereign-rules-layer.md)을 참조하세요.

네 번째 시스템 `match-analyst`(경기 후 단일 정규화 타임라인 위의 Review와 Commentary 두 가지 투영)는 명세가 완성되었지만 activation gate를 통과할 때까지 **의도적으로 라우팅되지 않습니다** —— [명세](docs/match-analyst/MATCH_ANALYST_PRODUCT_SPEC.md)를 보세요. 위 표는 Skill router가 오늘 실제로 제공하는 것만 나열합니다.

**네 시스템 모두 준비 단계에 있으며, 어느 것도 대신 플레이하지 않습니다.** 구성, 규칙 이해, 연습, 복기 —— 게임 자체는 사람이 이곳 바깥에서 플레이합니다. 그래서 권위 있는 규칙 엔진이, 언젠가 공식 디지털 클라이언트가 나온다 해도, 이 네 시스템을 대체하는 것이 아니라 **강화**합니다. 그런 엔진은 플레이를 위한 것이고, 이것은 준비를 위한 것이기 때문입니다.

이 프로젝트는 플레이어의 대회 준비를 돕는 어시스턴트이며, 연구·교육 목적으로 만들어졌습니다. **대회 진행 중 사용하는 것은 대회 규칙 위반입니다** —— 해당 조문은 [규정 준수 경계](docs/policy/RIOT_COMPLIANCE_BOUNDARY.md)를 참조하세요.

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

## Rift Atlas 덱 핸드오프

저장소에는 사용자가 붙여 넣은 Rift Atlas 덱리스트를 Deck Coach의 input, profile, mask, 8개 섹션 primer scaffold와 brief로 바꾸는 오프라인 bridge가 포함되어 있습니다.

```powershell
python skill/scripts/riftatlas_bridge.py `
  --source-url https://riftatlas.com/decks/community/DECK_ID `
  --deck-file decklist.txt `
  --environment global-vendetta `
  --player-level new `
  --output-dir riftatlas-output
```

URL은 출처 기록으로만 사용됩니다. bridge는 Rift Atlas를 스크랩하거나 private API를 호출하거나 게임을 자동화하지 않습니다. 상대 유지 관리자가 공개에 동의하기 전까지 협력 제안과 번체 중국어 sample은 공개 저장소에 넣지 않습니다.

## Rule Consult와 규칙 PDF

Rule Consult는 사용자가 제공한 사실, 가정, 규칙 근거, 분석, 신뢰도와 escalation을 분리해 기록합니다. 결과에는 항상 `official_status: unofficial`, `state_effect: none`이 유지됩니다.

공개 저장소에는 Riot의 규칙 PDF를 넣지 않습니다. 정확한 조항이 필요할 때 한 번만 다음 명령을 실행하세요.

```powershell
python skill/scripts/bootstrap_rules.py --yes
python skill/scripts/bootstrap_rules.py --include-supplemental-en --yes
python skill/scripts/bootstrap_rules.py --include-zh-cn --yes
python skill/scripts/rules_index.py build
python skill/scripts/rules_index.py search "chain resolution"
```

기본 설치는 영어 Core Rules와 Tournament Rules이며, `--include-supplemental-en`은 영어 정오표와 역사 자료로 표시된 Origins FAQ HTML 스냅샷을 추가합니다. `--include-zh-cn`은 중국어 규칙·금지 목록·FAQ·정오표·별도 등급의 심판 자료를 추가합니다. 다운로드 파일, SHA-256 lock, 검색 인덱스는 Git에서 무시되는 `skill/.local/rules/`에 남습니다. 검색 결과는 자동 판정이 아니며 번역 충돌 시 영어가 우선하고 대체된 출처는 기본 검색에서 제외됩니다.

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

규칙 계층을 변경하기 전에 읽어 볼 설계 근거: [ADR-0001](docs/decisions/ADR-0001-sovereign-rules-layer.md)(두 차례 감사가 규칙 엔진을 만들지 말라고 권고했음에도 만든 이유와, 이 결정이 주장하지 **않는** 것), [RELATED_WORK](docs/architecture/RELATED_WORK.md)(발표된 연구 대비 위치), [ITERATION_INPUTS](docs/research/ITERATION_INPUTS.md)(다음에 무엇을 만들지 바꿔야 할 연구).

출처 우선순위는 현재 공식 규칙／대회 문서／errata／금지 목록, 공식 카드 텍스트, 신뢰할 수 있는 커뮤니티 자료, 명시된 추론, 그리고 알 수 없음입니다. 포함된 카드 snapshot은 비공식 RiftCodex API에서 가져온 것으로 1,451개 row와 1,304개의 unique card ID를 포함합니다. 자세한 내용은 [데이터 출처와 제한](skill/data/README.md)을 확인하세요.

CI와 동일하게 모든 결정적 검사를 실행합니다. 이 루프는 디스크의 검사 스크립트를 직접 찾기 때문에, 손으로 옮겨 적은 목록처럼 낡을 수 없습니다(이전 목록은 규칙 코어 검사를 포함해 네 개를 빠뜨리고 있었습니다):

```powershell
Get-ChildItem skill/scripts/check_*.py | ForEach-Object {
  python $_.FullName
  if ($LASTEXITCODE -ne 0) { Write-Error "FAILED: $($_.Name)" }
}
```

푸시 시 실제로 실행되는 항목은 `.github/workflows/ci.yml`이 기준입니다. CI는 저장소 바깥 디렉터리에서 한 번 더 실행해 스크립트가 작업 디렉터리에 의존하지 않음을 확인합니다.

## 규정 준수와 라이선스

이 프로젝트는 승률, 사용률, 매치업 비율 또는 Tier 순위를 게시하거나 저장하지 않습니다. 공식 심판 권한을 주장하지 않으며 Riftbound 경기를 자동화하지 않습니다. Riot product registration과 공식 API 카드 출처는 아직 해결되지 않은 문제입니다.

원본 코드와 방법론은 [MIT](LICENSE) 라이선스입니다. 카드 이름, 규칙 텍스트 및 기타 Riot 소유 자료는 이 라이선스에 포함되지 않습니다.

> Riftbound Chronicle was created under Riot Games' “Legal Jibber Jabber” policy using assets owned by Riot Games. Riot Games does not endorse or sponsor this project.

Riftbound Chronicle은 Riot Games와 제휴하지 않은 비공식 fan project입니다.
