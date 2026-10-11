# 그래프 패널 개편 안 1 · 백엔드 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/ask` 응답의 `graph`를 시각화용 필드(`degree, is_seed, match_date, props`, 간선 `evidence`)로 보강하고, Game·ArticleClaim 노드를 그래프에서 빼고 클레임을 엔티티 간 간선으로 펴며, `GET /node` 엔드포인트를 추가한다.

**Architecture:** 변경은 `neo4j_query.py` 한 모듈에 집중한다. Cypher 실행과 결과 변환을 분리해 변환 함수는 neo4j 드라이버 없이 스텁 레코드로 테스트한다. 구조 간선 쿼리와 클레임 간선 쿼리를 따로 실행해 합친다. `pipeline.py`의 반환 키는 그대로 두고 내용만 바뀐다.

**Tech Stack:** Python 3.12, neo4j 드라이버 6.x, FastAPI, pytest(테스트 전용).

**Spec:** `/Users/doo._.hyun/Study/Project/lck/docs/graph-panel-option1-spec.md` (저장소 밖 절대 경로. 0-2 데이터 확인, 4-1 `graph` 계약, 4-3 `/node` 계약, 5절 테스트 목록)

## Global Constraints

- 스펙 4-1·4-3의 키 이름과 규칙을 글자 단위로 지킨다. 키 추가·개명 금지.
- `pipeline.py` 반환 키(`graph, graph_facts, graph_context, kg_keywords` 등)와 `api_server.py`의 `/ask` 응답 키는 바꾸지 않는다.
- 기존 상수 `QUERY_EXCLUDED_LABELS`·`QUERY_EXCLUDED_RELATIONS`는 다른 코드가 쓰므로 그대로 두고 `VISUAL_EXCLUDED_*`를 새로 둔다.
- 테스트는 Aura에 접속하지 않는다. 스텁만 쓴다. Aura 접속은 Task 4·5의 수동 확인 한 번씩.
- `requirements.txt`는 이 계획에서 수정하지 않는다(Docker 계획이 소유). pytest는 venv에 `pip install pytest`로만 설치한다.
- 커밋 메시지·주석은 한국어. 산문에 대시(—) 금지. 각 커밋 끝에 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- `.env`는 루트의 것을 worktree로 복사해서 쓰고 커밋하지 않는다.

## Review Focus

1. Match 노드에 `team_a_key`만 있고 `team_b_key`가 없는 경우: 이름 규칙은 "둘 다 있을 때"만 `A vs B`이므로 `경기 · 날짜`로 떨어져야 한다. (Task 2 `test_match_name_one_team_key_falls_back`)
2. 같은 두 노드 사이에 구조 간선 `MEMBER_OF`와 클레임 간선 `MEMBER_OF`가 둘 다 있는 경우: `(source, target, type)` 중복 규칙으로 하나만 남고, 먼저 들어온 쪽(구조 간선, `evidence: null`)이 남는다. (Task 3 `test_structure_edge_wins_over_same_claim_edge`)
3. 키워드가 Player·Team을 동시에 매칭해 `n`이 여러 개인 경우: 전부 `is_seed: true`. (Task 3 `test_multiple_seeds`)
4. `match_date`가 `"2025-09-06"`처럼 이미 10자이거나 `None`인 경우: 앞 10자 자르기와 null 통과가 둘 다 안전해야 한다. (Task 2 `test_match_date_short_or_none`)
5. `/node`의 `id`에 존재하지 않거나 형식이 다른 문자열(`"abc"`)이 오면 Cypher가 예외 없이 0건을 돌려 404가 된다. (Task 6 수동 확인 `curl .../node?id=abc` → 404)

---

## 실행 모델과 터미널 분할

메인 세션은 오케스트레이터다. Task 1(계획서 커밋)은 오케스트레이터가 Backend `main`에서 하고, Task 2~6은 터미널 B 하나가 worktree에서 순서대로 한다. 같은 Backend 레포에서 Docker 계획(터미널 C)이 동시에 돌므로 **파일 소유권**을 지킨다.

| 소유 | 터미널 B(이 계획) | 터미널 C(Docker 계획) |
|---|---|---|
| 수정 | `neo4j_query.py`, `graph_schema_config.py`, `api_server.py`, `pytest.ini`, `tests/__init__.py`, `tests/stubs.py`, `tests/test_graph_transform.py`, `tests/test_node_detail.py`, `README.md`의 "질의 예시 → 응답 주요 필드" 표와 그 아래 `/node` 절 | `requirements.txt`, `Dockerfile`, `docker-compose.yml`, `entrypoint.sh`, `.dockerignore`, `.gitattributes`, `.env.example`, `chroma_client.py`, `build_vector_db.py`, `rag_answer.py`, `pipeline.py`, `tests/test_vector_build.py`, `README.md`의 맨 위 "빠른 시작" 절과 "설치"·"데이터 준비" 절 |
| 금지 | 오른쪽 열 전부 | 왼쪽 열 전부 |

`README.md`는 둘이 다른 절을 고친다. 머지는 B 먼저, C가 rebase한다.

| 웨이브 | 태스크 | 실행자 | 산출 |
|---|---|---|---|
| W0 | Task 1 계획서 2개 커밋 | 오케스트레이터(main) | 기점 커밋 `<BASE>` |
| W1 | Task 2~6 | 터미널 B (Opus 5.5) · worktree `Backend/.claude/worktrees/lck-graph-api` | 브랜치 `feat/graph-panel-api` |
| W2 | 리뷰 → 수정 → `main` 머지 | 오케스트레이터 + 리뷰어(Opus 5.5) | 머지 커밋 |

사람 사전 조건 2줄: `cd Backend && git log --oneline -1`이 Task 1 커밋인지, `git status --short`가 비어 있는지.

## 파일 구조

| 파일 | 책임 |
|---|---|
| `graph_schema_config.py` | `VISUAL_EXCLUDED_LABELS`, `VISUAL_EXCLUDED_RELATIONS` 추가 |
| `neo4j_query.py` | 이름 생성, 노드·간선 변환, 두 Cypher 실행, `/node` 상세 |
| `api_server.py` | `GET /node` 핸들러(위임만) |
| `tests/stubs.py` | `StubNode`, `StubRel`, 레코드 dict 헬퍼 |
| `tests/test_graph_transform.py`, `tests/test_node_detail.py` | 스펙 5절 테스트 |
| `pytest.ini` | `testpaths = tests` (루트의 `test_*.py`는 DB 접속 스크립트라 수집 제외) |

`neo4j_query.py` 공개 시그니처(Task 2~5에서 정의):

```python
def build_match_name(props: dict) -> str
def node_to_dict(node, is_seed: bool) -> dict                 # 4-1 노드. degree는 0, 뒤에서 채움
def records_to_graph(structure_records: list, claim_records: list, seed_ids: set[str]) -> dict  # {"nodes": [...], "links": [...]}
def records_to_facts(structure_records: list, claim_records: list) -> list[dict]
def search_graph_knowledge(keywords, limit=100) -> dict        # 키 유지: keywords, graph, facts, context
def _run_node_query(node_id: str) -> list                      # Cypher 실행만. 테스트에서 monkeypatch
def get_node_detail(node_id: str) -> dict | None
```

스텁 계약(`tests/stubs.py`):

```python
class StubNode:   # neo4j Node 흉내
    def __init__(self, element_id: str, labels: list[str], props: dict): ...
    element_id: str; labels: frozenset[str]
    def get(self, key, default=None)
class StubRel:    # neo4j Relationship 흉내
    def __init__(self, type: str, start: StubNode, end: StubNode, props: dict | None = None): ...
    type: str
    def get(self, key, default=None)
def structure_record(n, r, m) -> dict        # {"n": n, "r": r, "m": m, "source": r.start, "target": r.end}
def claim_record(n, s, t, relation_type, article_key, evidence_text, confidence) -> dict
```

---

### Task 1: 계획서 커밋 (오케스트레이터, Backend `main`)

**Files:**
- Create: `docs/plans/2026-10-11-graph-panel-option1-backend.md`(이 문서), `docs/plans/2026-10-11-docker-setup.md`(Docker 계획)

- [ ] **Step 1: 두 계획서를 `main`에 커밋**: `구현 계획 추가: 안 1 백엔드 그래프 응답 보강과 Docker 의존성 관리`
- [ ] **Step 2: `git log --oneline -1` 해시를 `<BASE>`로 기록**

---

### Task 2: 스텁, 제외 상수, Match 이름, 노드 변환 (TDD)

**Files:**
- Create: `tests/__init__.py`, `tests/stubs.py`, `tests/test_graph_transform.py`, `pytest.ini`
- Modify: `graph_schema_config.py`(끝에 상수 2개), `neo4j_query.py`(`build_match_name`, `node_to_dict` 추가. 기존 `_node_name`·`_node_label` 유지)

**Interfaces:**
- Produces: 위 시그니처의 `build_match_name`, `node_to_dict`, 스텁 계약, 상수
  `VISUAL_EXCLUDED_LABELS = sorted(SOURCE_LABELS | {"Game", "ArticleClaim"})`
  `VISUAL_EXCLUDED_RELATIONS = sorted(LOW_SIGNAL_RELATIONS | {"ASSERTS", "SOURCE_ENTITY", "TARGET_ENTITY", "PLAYED_ON", "PART_OF_MATCH"})`

- [ ] **Step 1: `pytest.ini`에 `[pytest]\ntestpaths = tests`. venv에 `pip install pytest`**
- [ ] **Step 2: `tests/stubs.py` 작성(위 계약)**
- [ ] **Step 3: 실패하는 테스트 작성** (`tests/test_graph_transform.py` 첫 묶음)

```python
from neo4j_query import build_match_name, node_to_dict
from tests.stubs import StubNode

def test_match_name_with_both_teams():
    assert build_match_name({"team_a_key": "TEAM_GEN", "team_b_key": "TEAM_HLE", "match_date": "2025-09-06T06:09:11"}) == "GEN vs HLE · 2025-09-06"
def test_match_name_without_team_keys():
    assert build_match_name({"match_date": "2025-09-06T06:09:11", "match_key": "MATCH_1"}) == "경기 · 2025-09-06"
def test_match_name_one_team_key_falls_back():
    assert build_match_name({"team_a_key": "TEAM_GEN", "match_date": "2025-09-06T06:09:11", "match_key": "MATCH_1"}) == "경기 · 2025-09-06"
def test_match_name_without_date():
    assert build_match_name({"match_key": "MATCH_1"}) == "MATCH_1"
def test_team_node_uses_canonical_name_when_no_name():
    d = node_to_dict(StubNode("4:x:1", ["Entity", "Team"], {"canonical_name": "한화생명 이스포츠"}), is_seed=True)
    assert d == {"id": "4:x:1", "name": "한화생명 이스포츠", "label": "Team", "degree": 0, "is_seed": True, "match_date": None, "props": {}}
def test_match_node_props_exactly_seven_keys():
    props = {"match_key": "MATCH_9", "match_stage": "Playoffs", "score_a": 1, "score_b": 3, "best_of": 5, "team_a_key": "TEAM_GEN", "team_b_key": "TEAM_HLE", "winner_key": "TEAM_HLE", "match_date": "2025-09-06T06:09:11", "dataset": "x"}
    d = node_to_dict(StubNode("4:x:9", ["Match"], props), is_seed=False)
    assert set(d["props"]) == {"match_stage", "score_a", "score_b", "best_of", "team_a_key", "team_b_key", "winner_key"}
    assert d["match_date"] == "2025-09-06" and d["name"] == "GEN vs HLE · 2025-09-06" and d["label"] == "Match"
def test_match_date_short_or_none():
    assert node_to_dict(StubNode("4:x:2", ["Match"], {"match_date": "2025-09-06", "match_key": "M"}), False)["match_date"] == "2025-09-06"
    assert node_to_dict(StubNode("4:x:3", ["Match"], {"match_key": "M"}), False)["match_date"] is None
def test_staff_label_and_name():
    d = node_to_dict(StubNode("4:x:4", ["Entity", "Staff"], {"canonical_name": "김정수", "staff_name": "김정수"}), False)
    assert d["label"] == "Staff" and d["name"] == "김정수"
```

- [ ] **Step 4: `.venv/bin/pytest -q` 실행, ImportError로 FAIL 확인**
- [ ] **Step 5: 구현**
  - `_node_label` 우선순위에 `"Staff", "Coach", "Objective", "Object"`를 `"Match"` 뒤, `"Game"` 앞에 추가(Aura에서 Staff는 `["Entity","Staff"]`로 들어온다).
  - `build_match_name(props)`: `a = props.get("team_a_key")`, `b = props.get("team_b_key")`, `date = (props.get("match_date") or "")[:10]`. 둘 다 있으면 `f"{a.removeprefix('TEAM_')} vs {b.removeprefix('TEAM_')} · {date}"`(date 비면 ` · ` 없이 `A vs B`), 아니면 date 있으면 `f"경기 · {date}"`, 아니면 `props.get("match_key") or "경기"`.
  - `node_to_dict`: Match면 이름은 `build_match_name`, props는 7키 중 존재하는 것만(`{k: node.get(k) for k in MATCH_PROP_KEYS if node.get(k) is not None}`), `match_date`는 앞 10자. 그 외 `_node_name`, `props {}`, `match_date None`.
- [ ] **Step 6: `.venv/bin/pytest -q` 전부 PASS**
- [ ] **Step 7: 커밋**: `그래프 노드 변환 추가: Match 표시명 규칙, 시각화 제외 라벨·관계 상수, 테스트 스텁`

---

### Task 3: 그래프·사실 변환(클레임 간선화, degree, is_seed) (TDD)

**Files:**
- Modify: `neo4j_query.py`(`records_to_graph`, `records_to_facts` 신설. 기존 `_records_to_graph`·`_records_to_facts`는 삭제), `tests/test_graph_transform.py`(둘째 묶음 추가)

**Interfaces:**
- Consumes: Task 2의 `node_to_dict`, 스텁
- Produces: `records_to_graph(structure_records, claim_records, seed_ids) -> {"nodes": [...], "links": [...]}`, `records_to_facts(structure_records, claim_records) -> list[dict]`. 간선 dict `{"source","target","type","evidence"}`. fact dict `{"source","source_label","relation","target","target_label","evidence"}`.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
from neo4j_query import records_to_graph, records_to_facts, format_graph_facts
from tests.stubs import StubNode, StubRel, structure_record, claim_record

HLE = StubNode("4:x:1", ["Entity", "Team"], {"canonical_name": "한화생명 이스포츠"})
ZEKA = StubNode("4:x:3", ["Entity", "Player"], {"canonical_name": "제카"})
M9 = StubNode("4:x:9", ["Match"], {"team_a_key": "TEAM_GEN", "team_b_key": "TEAM_HLE", "match_date": "2025-09-06T06:09:11", "match_stage": "Playoffs", "score_a": 1, "score_b": 3, "best_of": 5, "winner_key": "TEAM_HLE"})
AZIR = StubNode("4:x:13", ["Entity", "Champion"], {"canonical_name": "아지르"})

def test_degree_counts_both_ends():
    recs = [structure_record(HLE, StubRel("MEMBER_OF", ZEKA, HLE), ZEKA), structure_record(HLE, StubRel("WON_MATCH", HLE, M9), M9), structure_record(HLE, StubRel("PLAYED_MATCH", HLE, M9), M9)]
    g = records_to_graph(recs, [], seed_ids={"4:x:1"})
    deg = {n["id"]: n["degree"] for n in g["nodes"]}
    assert deg == {"4:x:1": 3, "4:x:3": 1, "4:x:9": 2}
def test_is_seed_true_when_node_is_n():
    g = records_to_graph([structure_record(HLE, StubRel("MEMBER_OF", ZEKA, HLE), ZEKA)], [], seed_ids={"4:x:1"})
    seeds = {n["id"]: n["is_seed"] for n in g["nodes"]}
    assert seeds == {"4:x:1": True, "4:x:3": False}
def test_multiple_seeds():
    g = records_to_graph([structure_record(HLE, StubRel("MEMBER_OF", ZEKA, HLE), ZEKA)], [], seed_ids={"4:x:1", "4:x:3"})
    assert all(n["is_seed"] for n in g["nodes"])
def test_structure_edge_has_null_evidence():
    g = records_to_graph([structure_record(HLE, StubRel("WON_MATCH", HLE, M9), M9)], [], set())
    assert g["links"] == [{"source": "4:x:1", "target": "4:x:9", "type": "WON_MATCH", "evidence": None}]
def test_claim_record_becomes_edge_with_evidence():
    g = records_to_graph([], [claim_record(HLE, ZEKA, AZIR, "PICKED_CHAMPION", "ARTICLE_1", "제카가 아지르를 꺼냈다.", 1.0)], {"4:x:1"})
    assert g["links"] == [{"source": "4:x:3", "target": "4:x:13", "type": "PICKED_CHAMPION", "evidence": {"article_key": "ARTICLE_1", "text": "제카가 아지르를 꺼냈다.", "confidence": 1.0}}]
    assert {n["id"] for n in g["nodes"]} == {"4:x:3", "4:x:13"}
def test_duplicate_claim_keeps_first_evidence():
    claims = [claim_record(HLE, ZEKA, AZIR, "PICKED_CHAMPION", "ARTICLE_1", "첫 문장", 1.0), claim_record(HLE, ZEKA, AZIR, "PICKED_CHAMPION", "ARTICLE_2", "둘째 문장", 0.8)]
    g = records_to_graph([], claims, set())
    assert len(g["links"]) == 1 and g["links"][0]["evidence"]["article_key"] == "ARTICLE_1"
def test_structure_edge_wins_over_same_claim_edge():
    recs = [structure_record(HLE, StubRel("MEMBER_OF", ZEKA, HLE), ZEKA)]
    claims = [claim_record(HLE, ZEKA, HLE, "MEMBER_OF", "ARTICLE_3", "제카는 한화생명 소속이다.", 1.0)]
    g = records_to_graph(recs, claims, set())
    assert len(g["links"]) == 1 and g["links"][0]["evidence"] is None
def test_facts_include_evidence_key():
    facts = records_to_facts([structure_record(HLE, StubRel("WON_MATCH", HLE, M9), M9)], [claim_record(HLE, ZEKA, AZIR, "PICKED_CHAMPION", "ARTICLE_1", "t", 1.0)])
    assert facts[0] == {"source": "한화생명 이스포츠", "source_label": "Team", "relation": "WON_MATCH", "target": "GEN vs HLE · 2025-09-06", "target_label": "Match", "evidence": None}
    assert facts[1]["evidence"]["article_key"] == "ARTICLE_1"
def test_format_graph_facts_unchanged_format():
    facts = records_to_facts([structure_record(HLE, StubRel("WON_MATCH", HLE, M9), M9)], [])
    assert format_graph_facts(facts) == "1. (Team) 한화생명 이스포츠 -[WON_MATCH]-> (Match) GEN vs HLE · 2025-09-06"
```

- [ ] **Step 2: `pytest -q` 실행, FAIL 확인**
- [ ] **Step 3: 구현**: 구조 레코드 먼저, 클레임 레코드 다음 순서로 `seen_links` 키 `(source_id, target_id, type)` 검사. 노드는 `node_to_dict(node, node.element_id in seed_ids)`로 넣고 마지막에 링크 양끝 등장 횟수를 `degree`에 기록. facts는 같은 순서, 같은 중복 규칙에 `evidence` 추가.
- [ ] **Step 4: `pytest -q` 전부 PASS**
- [ ] **Step 5: 커밋**: `그래프 변환 보강: 클레임을 간선으로 펴기, degree·is_seed·evidence 추가`

---

### Task 4: 두 Cypher 실행과 `search_graph_knowledge` 교체

**Files:**
- Modify: `neo4j_query.py`(`KEYWORD_CYPHER` 교체, `CLAIM_CYPHER` 추가, `search_graph_knowledge` 본문, `EXCLUDED_*` 상수를 `VISUAL_EXCLUDED_*`로)

**Interfaces:**
- Consumes: Task 3 함수
- Produces: `search_graph_knowledge(keywords, limit=100)` 반환 키 유지. `seed_ids`는 두 쿼리의 `n` element_id 합집합.

- [ ] **Step 1: Cypher 두 개를 스펙 4-1 그대로 넣는다.** `n` 매칭 WHERE는 문자열 상수 `SEED_WHERE`로 한 번만 쓰고 두 쿼리에 f-string으로 끼운다(두 쿼리가 어긋나지 않게). `aliases` 조건 `any(a IN coalesce(n.aliases, []) WHERE toLower(a) CONTAINS kw)` 포함.
- [ ] **Step 2: `search_graph_knowledge`**: 세션 하나에서 두 쿼리 실행 → `records_to_graph(structure, claims, seed_ids)`, `records_to_facts(...)`, `format_graph_facts`. 빈 결과 처리는 기존 `_empty_graph_result` 유지. DEBUG print는 노드·링크·사실 수만 남긴다.
- [ ] **Step 3: `pytest -q` 전부 PASS(변환 테스트가 깨지지 않았는지)**
- [ ] **Step 4: 수동 확인(Aura, 한 번)**:
  `.venv/bin/python -c "from neo4j_query import search_graph_knowledge as s; g=s('한화생명')['graph']; import collections; print(len(g['nodes']), collections.Counter(n['label'] for n in g['nodes']), sum(1 for n in g['nodes'] if n['name']=='unknown'), collections.Counter(l['type'] for l in g['links']), sum(1 for l in g['links'] if l['evidence']))"`
  통과 기준: 라벨에 `Game`·`ArticleClaim` 없음, unknown 0, 간선 타입에 `MEMBER_OF`와 `WON_MATCH` 또는 `PLAYED_MATCH`가 함께 있음, evidence 있는 간선 1개 이상. 출력 원문을 보고서에 붙인다.
- [ ] **Step 5: 커밋**: `그래프 검색 교체: 구조·클레임 두 쿼리, 별칭 매칭, Game 제외`

---

### Task 5: `get_node_detail` (TDD)

**Files:**
- Modify: `neo4j_query.py`(`NODE_CYPHER`, `_run_node_query`, `get_node_detail`)
- Create: `tests/test_node_detail.py`

**Interfaces:**
- Produces: `get_node_detail(node_id) -> dict | None`(스펙 4-3). `_run_node_query(node_id) -> list[dict]`는 레코드 `{"n", "r", "m", "source"}`를 돌려주며 `r`·`m`·`source`는 None일 수 있다(OPTIONAL MATCH).

- [ ] **Step 1: 실패하는 테스트 작성**

```python
import neo4j_query as q
from tests.stubs import StubNode, StubRel

HLE = StubNode("4:x:1", ["Entity", "Team"], {"canonical_name": "한화생명 이스포츠"})
M9 = StubNode("4:x:9", ["Match"], {"team_a_key": "TEAM_GEN", "team_b_key": "TEAM_HLE", "match_date": "2025-09-06T06:09:11", "match_stage": "Playoffs", "score_a": 1, "score_b": 3, "best_of": 5, "winner_key": "TEAM_HLE"})
def P(i, name): return StubNode(f"4:x:{i}", ["Entity", "Player"], {"canonical_name": name})
def rec(n, r, m): return {"n": n, "r": r, "m": m, "source": r.start if r else None}
def patch(monkeypatch, recs): monkeypatch.setattr(q, "_run_node_query", lambda node_id: recs)

def test_not_found_returns_none(monkeypatch):
    patch(monkeypatch, []); assert q.get_node_detail("4:x:404") is None
def test_isolated_node_has_empty_groups(monkeypatch):
    patch(monkeypatch, [rec(HLE, None, None)])
    d = q.get_node_detail("4:x:1"); assert d["groups"] == [] and d["degree"] == 0 and d["record"] == {"wins": 0, "losses": 0}
def test_team_record_counts_won_and_lost(monkeypatch):
    m10, m12 = StubNode("4:x:10", ["Match"], {"match_key": "M10"}), StubNode("4:x:12", ["Match"], {"match_key": "M12"})
    patch(monkeypatch, [rec(HLE, StubRel("WON_MATCH", HLE, M9), M9), rec(HLE, StubRel("WON_MATCH", HLE, m10), m10), rec(HLE, StubRel("LOST_MATCH", HLE, m12), m12)])
    d = q.get_node_detail("4:x:1"); assert d["record"] == {"wins": 2, "losses": 1} and d["match"] is None and d["degree"] == 3
def test_groups_sorted_by_size_then_neighbors_by_name(monkeypatch):
    patch(monkeypatch, [rec(HLE, StubRel("MEMBER_OF", P(3, "제카"), HLE), P(3, "제카")), rec(HLE, StubRel("MEMBER_OF", P(4, "바이퍼"), HLE), P(4, "바이퍼")), rec(HLE, StubRel("MEMBER_OF", P(5, "딜라이트"), HLE), P(5, "딜라이트")), rec(HLE, StubRel("WON_MATCH", HLE, M9), M9)])
    d = q.get_node_detail("4:x:1")
    assert [g["relation"] for g in d["groups"]] == ["MEMBER_OF", "WON_MATCH"]
    assert [n["name"] for n in d["groups"][0]["neighbors"]] == ["딜라이트", "바이퍼", "제카"]
def test_member_of_role_from_edge_property(monkeypatch):
    patch(monkeypatch, [rec(HLE, StubRel("MEMBER_OF", P(3, "제카"), HLE, {"role": "MID"}), P(3, "제카")), rec(HLE, StubRel("WON_MATCH", HLE, M9), M9)])
    d = q.get_node_detail("4:x:1")
    assert d["groups"][0]["neighbors"][0]["role"] == "MID" and d["groups"][1]["neighbors"][0]["role"] is None
def test_direction_out_when_selected_is_start(monkeypatch):
    patch(monkeypatch, [rec(HLE, StubRel("MEMBER_OF", P(3, "제카"), HLE), P(3, "제카")), rec(HLE, StubRel("WON_MATCH", HLE, M9), M9)])
    d = q.get_node_detail("4:x:1"); dirs = {g["relation"]: g["direction"] for g in d["groups"]}
    assert dirs == {"MEMBER_OF": "in", "WON_MATCH": "out"}
def test_match_node_returns_match_props_and_null_record(monkeypatch):
    patch(monkeypatch, [rec(M9, StubRel("WON_MATCH", HLE, M9), HLE)])
    d = q.get_node_detail("4:x:9")
    assert d["record"] is None and set(d["match"]) == {"match_stage", "score_a", "score_b", "best_of", "team_a_key", "team_b_key", "winner_key"} and d["name"] == "GEN vs HLE · 2025-09-06"
def test_neighbors_capped_at_twenty(monkeypatch):
    patch(monkeypatch, [rec(HLE, StubRel("MEMBER_OF", P(100 + i, f"선수{i:02d}"), HLE), P(100 + i, f"선수{i:02d}")) for i in range(25)])
    d = q.get_node_detail("4:x:1"); assert len(d["groups"][0]["neighbors"]) == 20 and d["degree"] == 25
```

- [ ] **Step 2: `pytest -q` FAIL 확인**
- [ ] **Step 3: 구현**: `NODE_CYPHER`는 스펙 4-3 그대로(`elementId(n) = $id`, `$excluded_relations`·`$excluded_labels`에 `VISUAL_EXCLUDED_*`). `get_node_detail`: 레코드 0개 → None. 첫 레코드의 `n`으로 `node_to_dict`(id, name, label, match는 Match면 props 아니면 None). `r`이 None이 아닌 레코드만 묶어 `(type, direction)`별 그룹. 정렬: `neighbors` 수 내림차순, 동수는 relation 오름차순. neighbors 이름 오름차순(`sorted(..., key=lambda x: x["name"])`), 20개 제한은 **정렬 뒤**. `degree`는 제한 전 전체 수. `record`는 Team·Player일 때 `{"wins": WON_MATCH 수, "losses": LOST_MATCH 수}`(방향 무관).
- [ ] **Step 4: `pytest -q` 전부 PASS**
- [ ] **Step 5: 수동 확인(Aura, 한 번)**: Task 4 출력의 Team 노드 id 하나로 `.venv/bin/python -c "from neo4j_query import get_node_detail as g; import json; print(json.dumps(g('<id>'), ensure_ascii=False)[:600])"` → `groups`에 `MEMBER_OF`가 있고 `record.wins > 0`.
- [ ] **Step 6: 커밋**: `노드 상세 조회 추가: 관계 그룹, 승패 집계, MEMBER_OF 역할`

---

### Task 6: `GET /node` 엔드포인트와 README

**Files:**
- Modify: `api_server.py`, `README.md`("응답 주요 필드" 표 갱신 + `/node` 절 추가. 다른 절은 건드리지 않는다)

**Interfaces:**
- Consumes: `get_node_detail`
- Produces: `GET /node?id=<element_id>` → 200 dict 또는 `404 {"detail": "node not found"}`. `id` 없으면 FastAPI 기본 422.

- [ ] **Step 1: `@app.get("/node") def node(id: str)`**: `get_node_detail(id)`가 None이면 `raise HTTPException(status_code=404, detail="node not found")`.
- [ ] **Step 2: README**: 응답 필드 표의 `graph` 행을 "`nodes`(id, name, label, degree, is_seed, match_date, props) / `links`(source, target, type, evidence)"로, `graph_facts` 행에 `evidence` 추가. 새 절 "노드 상세 조회"에 `curl "localhost:8000/node?id=<graph.nodes[].id>"`와 응답 키 목록.
- [ ] **Step 3: 수동 확인**: `uvicorn api_server:app --port 8001` 띄우고 `curl -s "localhost:8001/node?id=abc" -w " %{http_code}"` → `{"detail":"node not found"} 404`. Task 5의 Team id로 → 200과 `groups`. 끝나면 서버 종료.
- [ ] **Step 4: 커밋**: `node 엔드포인트 추가와 README 응답 필드 갱신`

---

## 실행 프롬프트 (터미널 B)

권장 실행 설정: 모델 Opus 5.5, 추론 수준 high, 에이전트 종류 general-purpose. 프로젝트 루트 `/Users/doo._.hyun/Study/Project/lck/Backend`에서 Claude Code를 열고 붙여 넣는다. Task 1이 `main`에 커밋된 뒤에만 유효하다.

```
[1단계: 작업 공간 만들기] 다른 무엇보다 먼저 이것부터 해라.
루트 /Users/doo._.hyun/Study/Project/lck/Backend 에서 `git log --oneline -1` 을 실행해 기점 커밋 해시를 기록해라. 그 커밋 메시지가 "구현 계획 추가: 안 1 백엔드 그래프 응답 보강과 Docker 의존성 관리" 가 아니면 중단하고 BLOCKED 로 보고해라. 그 해시를 <BASE> 라 부른다.
  git worktree add -b feat/graph-panel-api /Users/doo._.hyun/Study/Project/lck/Backend/.claude/worktrees/lck-graph-api <BASE>
를 실행한 뒤 EnterWorktree 도구에 path=/Users/doo._.hyun/Study/Project/lck/Backend/.claude/worktrees/lck-graph-api 를 넘겨 세션을 옮겨라.
진입 후 아래를 확인하고, 하나라도 어긋나면 중단하고 BLOCKED 로 보고해라:
  - pwd 가 /Users/doo._.hyun/Study/Project/lck/Backend/.claude/worktrees/lck-graph-api 인지
  - git log --oneline -1 이 <BASE> 인지
  - docs/plans/2026-10-11-graph-panel-option1-backend.md 가 존재하는지
  - 스펙 /Users/doo._.hyun/Study/Project/lck/docs/graph-panel-option1-spec.md 가 존재하는지(저장소 밖 절대 경로다)
  - git status --short 가 비어 있는지
  - cp /Users/doo._.hyun/Study/Project/lck/Backend/.env ./.env 로 환경 파일을 복사했는지(gitignore 대상이다. 커밋하지 않는다)
  - python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest 가 성공하고 .venv/bin/python -c "import neo4j, fastapi, pytest" 가 되는지

[2단계: 실행] 계획서 docs/plans/2026-10-11-graph-panel-option1-backend.md 의 Task 2 부터 Task 6 까지 순서대로 수행한다. 역할: 백엔드 구현자. 각 태스크의 Step 을 체크박스 순서대로 하고, 테스트 스텝은 실제로 실행해 출력으로 확인한다. 스펙 문서는 계획서가 가리키는 절만 읽는다.
허용 Files: neo4j_query.py, graph_schema_config.py, api_server.py, pytest.ini, tests/__init__.py, tests/stubs.py, tests/test_graph_transform.py, tests/test_node_detail.py, README.md 의 "응답 주요 필드" 표와 새 "노드 상세 조회" 절.
수정 금지: requirements.txt, pipeline.py, clova_extract.py, rdb_query.py, rag_answer.py, Dockerfile 등 Docker 계획 소유 파일, README.md 의 다른 절, docs/ 아래, 그 외 모든 파일. 같은 레포에서 다른 터미널이 Docker 계획을 동시에 진행 중이다.
공유 계약: 스펙 4-1(graph 노드·간선), 4-3(/node 응답)과 계획서 "파일 구조" 절의 시그니처를 글자 단위로 지킨다. 테스트 코드는 계획서의 것을 그대로 쓰고 단언을 약화하지 않는다. 테스트가 틀렸다고 판단되면 고치지 말고 BLOCKED 로 보고한다.
검증: 각 태스크의 pytest 스텝과 Task 4·5·6 의 수동 확인(실제 Aura 접속은 Task 4 와 5 에서 각 한 번)을 수행하고 출력 원문을 보고서에 붙인다.
커밋: 계획서의 각 태스크 마지막 Step 메시지로 태스크 단위 원자 커밋. 마지막 줄에 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` 를 넣는다. 산문에 대시(—) 를 쓰지 않는다.
보고서: /Users/doo._.hyun/Study/Project/lck/Backend/.claude/reports/t1-report.md 에 태스크별 커밋 해시, 최종 `pytest -q` 출력 원문, 수동 확인 출력 원문, 계획과 달리 한 결정(있다면)을 적는다.
완료 형식: 마지막 메시지는 `DONE T1 feat/graph-panel-api <HEAD 해시>` 한 줄과 보고서 경로. 실패나 막힘은 `BLOCKED T1 <사유>`.
```

## 통합 게이트 (오케스트레이터)

1. 각 태스크 커밋 뒤 diff 리뷰: 허용 파일 밖 변경 없음, 스펙 4-1·4-3 키 일치, 테스트 단언 미변경.
2. Task 6 뒤 Opus 5.5 리뷰어가 브랜치 전체를 Review Focus 5항목 중심으로 본다.
3. `main`에 머지(Docker 브랜치보다 먼저). 머지 뒤 실제 서버로 `/ask`를 한 번 호출해 스펙 완료 조건 4(Game·ArticleClaim 0, unknown 0)를 확인한다.
