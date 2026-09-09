# Tierwork 개발 계획

## 문서 상태

- 기준 리비전: `9fa807a` (`9fa807a8f5d7cfd324600b4b63bc9d0b2f3881c3`)
- 기준 날짜: 2026-09-09
- 상태: **제안됨(Proposed) / 미구현(Unimplemented)**
- 목적: Tierwork 자체의 결함과 검증 공백을 실행 가능한 작업 패키지로 전환한다. 다른 저장소와의 연동은 범위에 넣지 않는다.
- 이 문서의 테스트는 모두 **제안된 검증 절차**이며 실행 결과가 아니다.

## 추진 원칙

1. 아래 작업 패키지는 모두 Tierwork 내부 개선이며, 기능별 완료 기준을 구분한다.
2. 각 패키지는 자체 문제 정의, 변경 범위, 테스트, 승인 기준, 커밋 경계를 가진다.
3. 패키지 간 공통 파일이 있으면 병합 순서만 조정하고 성공 지표는 합치지 않는다.
4. 로그에 없는 assignment generation이나 하네스가 제공하지 않는 식별자를 합성하지 않는다.
5. 관측값은 프로세스 생존, 결과 회수, 주 에이전트 통합의 증거로 확대 해석하지 않는다.
6. 상태를 판정할 증거가 부족한 경우의 기본값은 `unknown`이다.

## 범위

- 검증기 신뢰도 경계와 주 통합 정책의 모순 제거
- 대시보드와 상태 도구의 이벤트 병합 의미 정렬
- SSE 증분 읽기의 레코드 경계 보존
- `bench/status.py`의 회귀 테스트 확장
- A/B 벤치의 반복성, 비용 측정, 품질 채점 개선
- 관련 사용자 문서와 정적 템플릿의 동기화

## 비범위

- 새로운 에이전트 역할이나 모델 티어 설계
- Claude/Codex가 노출하지 않는 assignment generation 생성
- 기록된 hook 상태로 실제 프로세스 생존 여부 판정
- 외부 데이터베이스, 원격 관측 서비스, 프런트엔드 프레임워크 도입
- 이번 계획 단계에서 코드, README, 테스트 또는 릴리스 버전 변경
- 단일 벤치 결과로 효율성 또는 품질 우월성 선언

## 근거와 확실성 분류

### 확인된 정책/구현 사실

- 결정적 검사가 없으면 신뢰도를 70 이하로 제한한다.
  [검증기 지침](agents/bug-validator.md) 65–84행.
- `needs_primary_review`는 신뢰도 70 미만일 때만 `yes`가 된다.
  [검증기 지침](agents/bug-validator.md) 88–89행.
- 주 에이전트는 확정 및 신뢰도 70 이상인 결과를 다시 열지 않는다.
  [세션 정책](hooks/policy.md) 53–56행.
- 따라서 검사 없음·신뢰도 정확히 70인 결과는 추가 검토 없이 수용될 수 있다.
- 대시보드는 같은 `(session_id, agent_id)`에서 오래된 완료도 최신 실행보다 우선한다.
  [대시보드](bench/dashboard.py) 116–125행.
- 상태 도구는 최신 타임스탬프를 우선하고 동시각일 때 완료를 우선한다.
  [상태 도구](bench/status.py) 63–84행.
- assignment generation은 현재 제공되지 않는다.
  [벤치 문서](bench/README.md) 44–52행.
- 상태 테스트는 현재 네 가지 사례만 포함한다.
  [상태 테스트](bench/test_status.py) 10–69행.
- 벤치 실행은 고정 프롬프트로 finder와 validator 사용을 강제한다.
  [실행기](bench/run.sh) 46–53행.
- 채점기는 정규화한 `path:line`의 정확 일치만 인정한다.
  [채점기](bench/score.py) 9–13행 및 71–76행.
- 현재 구성별 표본은 `n=1`이므로 통계적 결론을 낼 수 없다.
  [벤치 문서](bench/README.md) 191–195행.

### 아직 검증되지 않은 런타임 가설

- SSE 감시기는 읽은 바이트 전체를 즉시 offset에 반영하고 `splitlines()` 후 JSON 파싱에
  실패한 조각을 버린다. append가 JSONL 한 줄 중간에서 관측되면 해당 레코드가 영구 손실될
  가능성이 있다. [대시보드](bench/dashboard.py) 329–350행.
- 멀티바이트 UTF-8 문자 중간에서 read 경계가 생기는 경우도 같은 계열의 손실 후보이다.
- `(session_id, agent_id)` 재사용이 실제 하네스에서 얼마나 자주 일어나는지는 측정되지 않았다.
- 반복 실행 전에는 고정된 고비용 리뷰 정책의 품질 대비 비용 이점을 알 수 없다.

## 우선순위 요약

| 우선순위 | 독립 프로젝트 | 목표 | 완료 판단 |
|---|---|---|---|
| P0 | A. 검증 경계 폐쇄 | 검사 없는 결과의 자동 수용 차단 | 모든 정책 사본과 계약 테스트 일치 |
| P0 | B. 상태 병합 의미 정렬 | 최신 assignment 이벤트 보존 | 대시보드·상태 도구 경계 행렬 통과 |
| P0 | C. SSE 레코드 보존 | 부분 append 손실 방지 | 분할 쓰기 테스트에서 정확히 1회 전달 |
| P1 | D. 상태 테스트 확장 | 현재 네 사례의 사각지대 제거 | 오류·필터·시간·상태 행렬 통과 |
| P1 | E. 벤치 증거 강화 | 비용/품질 판단을 반복 가능하게 함 | 반복 실행과 불확실성 포함 보고서 생성 |

## 프로젝트 A — 검증 경계 폐쇄

### 문제와 결정

- 현재 `cap 70`, `review if < 70`, `accept if >= 70`의 닫힌 경계가 안전 불변식을 깨뜨린다.
- 권장 결정은 신뢰도와 검증 상태를 분리하는 것이다. `check_status: passed|failed|unavailable`을 추가한다.
- 자동 수용은 `confirmed`, `check_status: passed`, 신뢰도 70 이상을 모두 만족할 때만 가능하다. 숫자 상한 조정만으로 검증 여부를 추론하지 않는다.
- `verdict`가 `confirmed|refuted`만 허용하므로 “inconclusive” 표현도 명시적으로 정리한다.
  스키마를 늘리지 않는다면 불충분한 증거는 `needs_primary_review: yes`로 표현한다.

### 변경 대상

- `agents/bug-validator.md`
- `codex/agents/bug-validator.toml`
- `hooks/policy.md`
- `skills/subagent-delegation/SKILL.md`에서 동일 임계값을 언급하는 부분
- 벤치 fixture에 복제된 정책/에이전트 파일은 fixture 의도가 “기준 스냅샷”인지 확인 후 별도 커밋
- 새 정적 계약 테스트(예: `bench/test_policy_contract.py`)

### 구현 항목

1. 실제 실행 결과에 따라 `check_status`를 기록한다. 실패한 검사를 높은 신뢰도로 상쇄할 수 없다.
2. `needs_primary_review`를 검사 없음, 증거 불충분, confidence 70 미만에 대해 `yes`로 명시한다. 기존 출력에 상태 필드가 없으면 `unavailable`로 취급한다.
3. 주 정책에 “결정적 검사 없음은 자동 수용 금지” 불변식을 직접 쓴다.
4. Claude 지침, Codex 템플릿, 주입 정책의 숫자와 조건을 정적 테스트로 비교한다.

### 제안 테스트 및 승인 게이트

- 경계표: 검사 없음 70 → review, 검사 통과 69 → review, 검사 통과 70 → 정책상 수용 가능, 검사 실패 100 → 수용 금지.
- `confirmed`라도 검사 없음이면 자동 수용되지 않는다는 문구 검사.
- 세 정책 사본과 벤치 결과 파서가 동일한 상태·신뢰도 규약을 적용함.
- fixture 갱신 여부가 명시적으로 결정되고, 무심코 기준 데이터가 바뀌지 않음.

### 기능 커밋 경계

1. `fix(policy): close validator no-check confidence boundary`
2. `test(policy): lock validator and primary-review thresholds`
3. 필요 시 `test(fixtures): refresh policy snapshot intentionally`

## 프로젝트 B — 상태 병합 의미 정렬

### 문제와 결정

- 대시보드의 “완료 영구 우선”은 같은 키로 재시작된 최신 실행을 숨긴다.
- 권장 계약은 상태 도구와 동일하게 **최신 유효 timestamp 우선, 동시각 완료 우선**이다.
- 이 결과는 “latest recorded event”일 뿐 현재 프로세스 상태의 보증이 아니다.
- generation 필드가 하네스에서 실제 제공되는 경우에만 키에 포함한다. 없으면 만들지 않는다.
- 알 수 없는 상태, 무효 timestamp, 키 결손의 fallback은 완료가 아니라 `unknown`이다.

### 변경 대상

- `bench/dashboard.py`
- `bench/merge.py`
- `bench/status.py`의 공유 가능 경계만 검토하되 CLI 출력 계약은 보존
- 새 대시보드 병합 테스트(예: `bench/test_dashboard.py`)
- `bench/README.md`, 주 `README.md`

### 구현 항목

1. 병합 비교자를 timestamp, 동시각 status tie-rank, 입력 순서 순으로 단일화한다.
2. unknown/future status를 done 계층으로 승격하지 않고 그대로 노출한다.
3. API rows, export, SSE 갱신, merge CLI가 같은 비교 함수를 사용하게 한다.
4. UI 문구를 “recorded running/done/unknown”으로 제한하고 liveness 주장을 금지한다.

### 제안 테스트 및 승인 게이트

- 오래된 done + 최신 running → running.
- 오래된 running + 최신 done → done.
- 동시각 running + done → done.
- 같은 agent ID라도 session이 다르면 별도 행.
- 무효 키/시간/상태 → unknown 또는 진단 집계, 완료 KPI에 미포함.
- generation 미제공 입력에 synthetic ID가 추가되지 않음.
- `/api/rows`, JSON/CSV export, `bench/merge.py` 결과가 동일함.

### 기능 커밋 경계

1. `fix(status): prefer latest recorded assignment event`
2. `test(status): cover dashboard merge state matrix`
3. `docs(status): define recorded-state and unknown semantics`

## 프로젝트 C — SSE 레코드 보존

### 문제와 설계

- 부분 줄 손실은 코드 검토로 발견한 후보이며 재현 테스트 전에는 확정 결함으로 부르지 않는다.
- 파일별로 아직 개행이 끝나지 않은 **바이트 조각**을 보관한다.
- 새 chunk와 조각을 합친 뒤 완성된 `\n` 레코드만 UTF-8 decode/JSON parse한다.
- truncate/rotate 시 offset과 조각을 함께 초기화한다.
- malformed인 완성 레코드는 건너뛰되 진단 가능하게 계수한다.

### 변경 대상

- `bench/dashboard.py`의 file watcher
- `bench/test_dashboard.py` 또는 watcher 전용 `bench/test_dashboard_sse.py`
- 동작 계약이 바뀌는 경우에만 `bench/README.md`

### 제안 테스트 및 승인 게이트

- 한 JSON 행을 2회, 3회 append해도 마지막 개행 뒤 정확히 한 번 전달.
- 두 완성 행과 다음 부분 행을 한 chunk로 읽어 완성 행만 즉시 전달.
- UTF-8 멀티바이트 경계 분할에도 replacement 문자나 레코드 손실 없음.
- CRLF 입력, 빈 줄, malformed 완성 줄 뒤 정상 줄 처리.
- truncate/rotate 뒤 이전 조각이 새 파일 첫 레코드에 붙지 않음.
- 기존 hello, ping, polling fallback 계약 유지.

### 기능 커밋 경계

1. `fix(sse): retain incomplete jsonl byte fragments`
2. `test(sse): cover split writes unicode and rotation`

## 프로젝트 D — 상태 도구 회귀 테스트 확장

### 변경 대상과 사례

- `bench/test_status.py`
- 필요 시 테스트 용이성을 위한 최소한의 `bench/status.py` 순수 함수 분리
- hook 로그 파서에 대한 별도 fixture 테스트: Claude/Codex 형식, 필드 누락, 잘못된 transcript 연결, 동시 append, Python/jq fallback을 포함한다.
- timestamp timezone/naive/invalid, 동일각 tie, 입력 순서 tie, unknown status를 표로 검증한다.
- session/agent 필터가 dedup 이후 적용되는지 두 방향으로 검증한다.
- missing, unreadable, malformed, non-object, invalid identity 진단의 복합/개별 사례를 검증한다.
- recent window의 정확 경계, 미래 timestamp, 빈 로그, 여러 로그 source를 검증한다.
- `--json` 스키마와 사람용 출력의 핵심 경고를 subprocess 수준에서 검증한다.
- fixture 테스트와 실제 플랫폼 smoke를 구분한다. 실제 smoke에는 호스트 버전·세션/에이전트 ID·시작/종료/결과 회수 관측을 기록한다.

### 승인 게이트와 커밋 경계

- 단위 테스트가 파일 시스템과 현재 시각에 비결정적으로 의존하지 않음.
- 지원 Python 버전에서 stdlib만으로 전체 테스트 통과.
- 커밋: `test(status): expand recorded-state diagnostic coverage`.

## 프로젝트 E — 벤치 증거 강화

### 문제와 목표

- `n=1` 결과는 효율성 근거가 아니며 고정된 고비용 review fan-out의 이점을 증명하지 못한다.
- 정확 `path:line` 채점은 올바른 버그를 인접 줄로 보고한 경우를 false negative/extra로 이중 계산한다.
- 목표는 “우월성 선언”이 아니라 반복 가능한 원자료와 불확실성을 남기는 것이다.

### 변경 대상

- `bench/run.sh`
- `bench/score.py`
- `bench/report.py` 또는 별도 집계기
- `bench/fixtures/*/ANSWER.md`의 허용 위치 범위 표현
- 채점/집계 단위 테스트와 `bench/README.md`

### 구현 항목

1. fixture, 조건, 반복 번호, 모델, 정책 버전을 실행 메타데이터로 기록한다.
2. enabled/disabled를 같은 fixture에서 짝지어 여러 번 실행하도록 하되 반복 수는 CLI 인자로 받는다.
3. 비용, duration, turns, 모델별 token과 발견 품질을 원자료와 함께 보존한다.
4. 사람이 사전에 고정한 정답 결함 ID, 발생 조건, 기대 동작, 허용 위치 범위를 answer key에 기록한다. 위치 겹침은 의미 검토의 후보 선정에만 사용한다.
5. 같은 줄의 잘못된 주장도 오탐으로 판정할 수 있도록 독립 의미 검토를 수행한다. 중복 보고는 한 결함으로 묶고 모호한 매칭은 `unknown`으로 남긴다.
6. 평가용 정답 ID와 하네스 실행 ID를 구분한다. 하네스가 제공하지 않은 assignment ID를 관측한 것처럼 기록하지 않는다.
7. recall, precision 후보, 평균/중앙값, 분산 또는 신뢰구간과 표본 수를 함께 출력한다.
8. 현재 고정 정책과 대안 정책은 별도 실험군으로 실행하며 결과를 합산하지 않는다.

### 제안 테스트 및 승인 게이트

- exact 위치, 허용 범위 내 인접 위치, 범위 밖 위치, 중복 보고, 모호한 다중 match, 같은 줄을 인용한 거짓 주장 fixture.
- 중단/실패 실행은 성공 표본에서 누락하지 않고 별도 상태로 집계.
- 최소 표본 기준은 비용 예산 결정 후 사전 등록하며, 미달이면 결론을 `inconclusive`로 표시.
- 원 JSON에서 집계 수치까지 재현 가능한 명령과 설정을 보고서에 포함.
- 효율성 주장은 품질 비열등 기준과 비용/토큰 개선 기준을 모두 만족할 때만 허용.

### 기능 커밋 경계

1. `feat(bench): record paired repeat metadata`
2. `fix(score): support answer ranges and ambiguous matches`
3. `test(bench): cover scorer and incomplete runs`
4. `docs(bench): define evidence and claim thresholds`

## 의존 순서

- 프로젝트 A, B, C, D, E는 각각 독립 착수할 수 있다.
- B와 C가 동시에 `bench/dashboard.py`를 수정하면 B를 먼저 병합하고 C를 rebase하여 watcher 부분만 검증한다.
- D는 B의 구현을 기다리지 않는다. 다만 공유 비교 함수를 도입하기로 결정하면 B의 계약 확정 후 추가 커밋한다.
- E는 A의 새 임계값을 실험 메타데이터에 기록할 수 있지만 A 완료를 전제로 하지 않는다.
- README 변경은 각 프로젝트의 마지막 문서 커밋으로 제한하고 독립적으로 검토한다.

## 위험과 완화

- **정책 사본 드리프트:** 정적 계약 테스트로 Claude/Codex/주입 정책을 함께 검사한다.
- **fixture 의미 훼손:** 제품 정책과 과거 기준 스냅샷을 구분하고 갱신을 별도 커밋한다.
- **상태 과신:** UI/API에 recorded-state 한계를 유지하고 unknown을 숨기지 않는다.
- **ID 재사용:** generation이 없다는 사실을 보존하며 synthetic 세대 번호를 만들지 않는다.
- **SSE 중복/누락:** 바이트 조각, offset, rotation을 결정적 단위 테스트로 고정한다.
- **벤치 비용 증가:** 반복 수와 예산 상한을 실행 전 지정하고 실패도 기록한다.
- **채점 관대화:** line range는 answer key에 사전 명시된 범위만 허용하고 모호성은 unknown 처리한다.
- **성급한 성능 주장:** 표본 수와 불확실성을 모든 요약에 강제한다.

## 열린 결정

1. fixture의 복제 정책 파일은 현재 제품 정책을 따라갈 것인가, 과거 기준 스냅샷으로 고정할 것인가?
2. unknown status 행을 대시보드의 별도 lane/chip으로 표시할 것인가, 진단 패널에만 둘 것인가?
3. 하네스가 향후 generation을 제공하면 기존 `(session_id, agent_id)` 로그와 어떻게 호환할 것인가?
4. 벤치의 비용 예산, 최소 반복 수, 품질 비열등 허용폭은 얼마로 사전 등록할 것인가?
5. 허용 line range를 수동 answer key로 관리할 것인가, diff hunk에서 보조 후보만 계산할 것인가?
6. fixed fan-out 대안 실험군을 축소 fan-out, 조건부 validator, 또는 둘 다로 둘 것인가?

## 전체 종료 조건

- 각 프로젝트가 자체 승인 게이트와 독립 커밋 이력을 가진다.
- 확인된 정책 사실과 런타임 가설이 구현/릴리스 문서에서도 구분된다.
- 자동화 테스트가 통과하더라도 live harness 검증 전에는 런타임 가설을 “확인됨”으로 승격하지 않는다.
- 벤치 표본이 기준에 미달하면 결과는 명시적으로 `inconclusive`이며 효율성 주장을 게시하지 않는다.
