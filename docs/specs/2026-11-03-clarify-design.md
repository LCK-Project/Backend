# 범위 되묻기(한 번) · 설계 문서

작성일 2026-11-03. 대상 저장소 `Backend`(FastAPI 파이프라인)와 `Frontend`(채팅 모드 `index.html`).
프론트 채팅 모드 설계는 `Frontend/docs/specs/2026-11-03-chat-mode-design.md` 에 있다.

## 1. 의도

"T1의 전략이 궁금해"처럼 시즌·대회 범위가 빠진 질문에 바로 답하면 모든 시즌이 섞인 답이 나온다.
챗봇이 "어느 대회 기준으로 알아볼까요?"라고 **한 번** 되물어 범위를 좁힌 뒤 답한다.

사용자 결정(2026-11-03): 되묻기는 질문 하나당 최대 한 번. 선택을 받으면 더 묻지 않고 답한다.
모호함 판단은 LLM, 선택지는 DB 에 실제 있는 대회·시즌 목록(안 C).

## 2. 목표 · 비범위 · 안티목표

**목표**

- 범위가 빠진 질문에 `/ask` 가 `type: "clarify"` 응답을 돌려주고, 이때 기사·그래프·RDB 검색과
  LLM #2~#5 는 호출하지 않는다.
- 선택지는 `tournament` 또는 `season` 테이블에 실제 있는 이름만이다.
- 프론트 채팅에 되묻는 말풍선과 선택지 칩이 뜨고, 고르면 원래 질문에 범위를 붙인 질문이
  `skip_clarify: true` 로 다시 전송돼 정상 답변이 온다.
- 선택지를 누르지 않고 직접 입력해도 된다(그냥 새 질문으로 처리).
- 목 모드(`?mock=1`)에서 백엔드 없이 되묻기 → 선택 → 답변 흐름이 돈다.

**비범위**

- 여러 번 이어지는 되묻기, 대화 세션 저장, 상대팀·포지션 같은 다른 축.
- 의도 분석 외 프롬프트 변경.

**안티목표**

- 되묻기가 무한히 반복된다(선택 뒤에도 또 묻는다).
- DB 에 없는 대회를 선택지로 보여줘서 골라도 답이 안 나온다.
- LLM 이나 DB 가 실패했을 때 답변 자체가 막힌다. 실패하면 되묻지 말고 평소처럼 답한다.

## 3. 공유 계약

### 3-1. `POST /ask` 요청

```json
{ "question": "T1의 전략이 궁금해", "skip_clarify": false }
```

`skip_clarify` 기본값 `false`. `true` 면 되묻기 판단을 건너뛰고 항상 답한다. 프론트는 선택지를
고른 뒤 보내는 합친 질문에 `true` 를 붙인다. 이것이 "한 번만"을 보장하는 하드 가드다.

### 3-2. `POST /ask` 응답

기존 답변 응답에 `"type": "answer"` 가 추가된다. 되묻기는 아래 형태다.

```json
{
  "type": "clarify",
  "question": "T1의 전략이 궁금해",
  "intent": "T1 의 경기 전략을 알고 싶다",
  "clarify": {
    "axis": "tournament",
    "prompt": "어느 대회 기준으로 알아볼까요?",
    "options": ["2026 LCK Rounds 3-4", "2026 LCK Rounds 1-2", "2026 LCK Cup", "2025 LCK Rounds 3-5", "2025 LCK Rounds 1-2", "2025 LCK Cup", "2024 LCK Summer", "2024 LCK Spring"]
  }
}
```

`axis` 는 `"tournament" | "season"`. `prompt` 는 축별 고정 문구(tournament: "어느 대회 기준으로
알아볼까요?", season: "어느 시즌이 궁금하세요?"). `options` 는 최신순이며 비어 있으면 되묻지 않는다.

### 3-3. 의도 분석 JSON (LLM #1)

기존 `intent`, `keywords` 에 두 키를 추가한다.

```json
{
  "intent": "...",
  "keywords": ["T1", "전략"],
  "needs_scope": true,
  "scope_axis": "tournament"
}
```

`needs_scope`: 시즌·대회에 따라 답이 달라지는 질문인데 범위가 없으면 true. 소속 선수, 설립 연도처럼
범위와 무관하면 false. `scope_axis`: `"tournament" | "season" | null`. 파싱 시 `needs_scope` 는
bool 이 아니면 false, `scope_axis` 는 두 값 외면 null 로 정규화한다.

### 3-4. 되묻기 판정 (Backend `clarify.py`)

```python
SCOPE_TOKEN = re.compile(
    r"(20\d{2}|스프링|서머|spring|summer|cup|컵|라운드|rounds?|월즈|worlds|msi|플레이오프|playoffs?)",
    re.IGNORECASE,
)

def has_scope_token(question: str) -> bool:
    """질문 안에 연도·시즌·대회를 가리키는 토큰이 있으면 True."""
    return bool(SCOPE_TOKEN.search(question))

def decide_clarification(question: str, intent_result: dict, options_fn) -> dict | None:
    """
    되묻기가 필요하면 {"axis", "prompt", "options"} 를, 아니면 None 을 돌려준다.
    조건 네 개가 모두 참일 때만 되묻는다:
      1. 질문에 범위 토큰이 없다 (has_scope_token 이 False)
      2. intent_result["needs_scope"] 가 True
      3. intent_result["scope_axis"] 가 "tournament" 또는 "season"
      4. options_fn(axis) 가 비어 있지 않은 리스트를 돌려준다 (예외가 나면 None 취급)
    """
```

`scope_options(axis)` 는 MySQL 에서 읽는다. tournament: `SELECT tournament_name FROM tournament
ORDER BY tournament_id DESC`. season: `SELECT season_name FROM season ORDER BY season_year DESC`.
연결·조회 실패는 `[]` 로 돌려준다.

### 3-5. 파이프라인 분기

`run_pipeline(question, top_k=3, graph_limit=100, skip_clarify=False)`.
의도 분석 직후, `skip_clarify` 가 False 이고 `decide_clarification` 이 값을 돌려주면
`{"type": "clarify", "question": question, "intent": ..., "clarify": {...}}` 를 즉시 반환한다.
그 외엔 기존 결과에 `"type": "answer"` 를 더해 돌려준다. `api_server.py` 는 `type` 으로 분기한다.

### 3-6. Frontend `chat-store.js` 변경

- `Turn` 에 `skipClarify: bool`, `choice: string|null` 추가. `status` 에 `"clarify"` 추가.
- `ask(question, { skipClarify = false } = {})`.
- `resolve(id, data)`: `data.type === "clarify"` 면 status 를 `"clarify"` 로 두고 `activeId` 는
  바꾸지 않는다. 그 외는 기존대로 `"done"` + 활성.
- `choose(id, option)`: status 가 `"clarify"` 이고 아직 `choice` 가 없을 때만 `choice` 를 기록하고
  합친 질문 문자열을 돌려준다. 아니면 `null`. 합치기는 `composeRefinedQuestion(original, option)`
  = `` `${original} (${option} 기준)` ``.
- `activate` 는 여전히 `"done"` 만 받는다.

테스트(`tests/chat-store.test.js` 에 추가):

| 이름 | 단언 |
|---|---|
| `ask_records_skipClarify` | `ask("q", {skipClarify:true})` 턴의 `skipClarify === true`, 기본은 `false` |
| `resolve_clarify_keeps_active` | 턴1 done 뒤 턴2 를 clarify 데이터로 resolve → 턴2 `status === "clarify"`, `activeId === "turn-1"` |
| `choose_returns_composed_question_once` | `choose("turn-2","2025 LCK Cup")` 가 `"q2 (2025 LCK Cup 기준)"`, 턴2 `choice` 기록, 두 번째 `choose` 는 `null` |
| `choose_rejects_non_clarify` | done 턴·loading 턴에 `choose` 가 `null` |
| `activate_rejects_clarify` | clarify 턴에 `activate` 가 `false` |
| `composeRefinedQuestion` | `composeRefinedQuestion("T1의 전략이 궁금해","2025 LCK Cup") === "T1의 전략이 궁금해 (2025 LCK Cup 기준)"` |

### 3-7. 목 모드

`fixtures/clarify_sample.json` 을 추가한다(3-2 형태). 목 모드에서 `skipClarify` 가 아니고 질문에
`20\d\d` 가 없으면 이 픽스처를, 아니면 기존 `ask_sample.json` 을 돌려준다.

## 4. 화면 요구사항 (배치·문구·클래스는 실행자 재량)

1. clarify 턴은 봇 말풍선에 `prompt` 와 `options` 칩을 보여준다. "분석 보기"는 없다.
2. 칩을 누르면 `choose` 로 합친 질문을 받아 `skipClarify: true` 로 새 턴을 보낸다. 합친 질문은
   사용자 말풍선으로 보인다.
3. 고른 뒤에는 그 턴의 칩이 비활성이 되고 고른 것이 표시된다.
4. 칩을 누르지 않고 입력창에 새 질문을 보내도 된다(기존 ask 그대로).
5. `/ask` 요청 본문에 `skip_clarify` 를 보낸다.

## 5. 실행 모델

리뷰·검토 없이 이 세션이 직접 구현한다(사용자 지시, 2026-11-03). Backend 와 Frontend 각각
`feat/clarify` 브랜치에서 작업해 `main` 에 ff 머지한다. 테스트는 Backend `pytest`, Frontend
`node --test "tests/*.test.js"`, 화면은 목 모드 Playwright 로 확인한다.
