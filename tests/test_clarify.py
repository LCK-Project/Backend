import clova_extract as ce
import pipeline
from clarify import (
    PROMPTS, TEMPLATES, TOPIC_PROMPT_NO_SUBJECT, TOPICS, already_scoped, decide_clarification,
    has_recent_token, has_scope_token, refine_recent_question, scope_options,
)

INTENT_T1 = {"intent": "T1 전략", "keywords": ["T1"], "needs_scope": True, "scope_axis": "tournament", "subject": "T1", "subject_type": "team"}
OPTIONS = ["2026 LCK Cup", "2025 LCK Rounds 1-2"]


def _options(axis, subject=None, subject_type=None):
    return OPTIONS

def _intent(**over):
    return {**INTENT_T1, **over}


# ---------- 토큰 규칙 ----------

def test_scope_token_year():
    assert has_scope_token("2025년 T1 전략") is True

def test_scope_token_korean_and_english_words():
    assert has_scope_token("T1 서머 시즌 성적") is True
    assert has_scope_token("T1 LCK Cup 전략") is True
    assert has_scope_token("젠지 Rounds 1-2 밴픽") is True
    assert has_scope_token("월즈에서 페이커 활약") is True

def test_scope_token_recent_words_count_as_scope():
    for q in ["요즘 메타 어때?", "최근 T1 폼", "현재 젠지 전략", "지금 1위 팀", "올해 우승팀", "이번 시즌 T1"]:
        assert has_scope_token(q) is True, q
        assert has_recent_token(q) is True, q

def test_scope_token_absent():
    assert has_scope_token("T1의 전략이 궁금해") is False
    assert has_recent_token("T1의 전략이 궁금해") is False
    assert has_scope_token("") is False
    assert has_scope_token(None) is False

def test_already_scoped_per_axis():
    assert already_scoped("2025 T1 전략", "tournament") is True
    assert already_scoped("요즘 T1 전략", "season") is True
    assert already_scoped("T1 전략", "tournament") is False
    assert already_scoped("14.21 패치 메타", "patch") is True
    assert already_scoped("요즘 메타", "patch") is True
    assert already_scoped("메타 어때", "patch") is False
    assert already_scoped("2025 LCK Cup T1 플레이오프 성적", "stage") is True
    assert already_scoped("2025 LCK Cup T1 성적", "stage") is False
    # 상대·챔피언·주제는 규칙으로 막지 않는다 (LLM 판단)
    assert already_scoped("2025 T1 vs 젠지 전적", "opponent") is False
    assert already_scoped("2025 페이커 아지르 통계", "champion") is False
    assert already_scoped("T1 어때?", "topic") is False


# ---------- 최근 표현 → 최신 시즌 ----------

def test_refine_recent_appends_latest_season():
    assert refine_recent_question("요즘 메타 어때?", "2026") == "요즘 메타 어때? (2026 시즌 기준)"

def test_refine_recent_leaves_other_questions_alone():
    assert refine_recent_question("T1의 전략이 궁금해", "2026") == "T1의 전략이 궁금해"
    assert refine_recent_question("요즘 2025 메타", "2026") == "요즘 2025 메타"
    assert refine_recent_question("요즘 메타 어때?", None) == "요즘 메타 어때?"


# ---------- decide_clarification ----------

def test_clarify_when_all_conditions_hold():
    result = decide_clarification("T1의 전략이 궁금해", INTENT_T1, _options)
    assert result == {"axis": "tournament", "prompt": PROMPTS["tournament"], "options": OPTIONS, "template": TEMPLATES["tournament"]}

def test_no_clarify_when_question_has_scope_token():
    assert decide_clarification("2025 T1의 전략이 궁금해", INTENT_T1, _options) is None
    assert decide_clarification("요즘 T1의 전략이 궁금해", INTENT_T1, _options) is None

def test_no_clarify_when_llm_says_no_scope_needed():
    assert decide_clarification("T1의 전략이 궁금해", _intent(needs_scope=False), _options) is None

def test_no_clarify_when_axis_unknown():
    assert decide_clarification("T1의 전략이 궁금해", _intent(scope_axis="position"), _options) is None
    assert decide_clarification("T1의 전략이 궁금해", _intent(scope_axis=None), _options) is None

def test_no_clarify_when_options_empty_or_failing():
    assert decide_clarification("T1의 전략이 궁금해", INTENT_T1, lambda a, s, t: []) is None
    def boom(axis, subject, subject_type):
        raise RuntimeError("db down")
    assert decide_clarification("T1의 전략이 궁금해", INTENT_T1, boom) is None

def test_options_fn_receives_axis_subject_and_type():
    seen = []
    def spy(axis, subject, subject_type):
        seen.append((axis, subject, subject_type))
        return ["x"]
    decide_clarification("페이커 챔피언 통계", _intent(scope_axis="champion", subject="Faker", subject_type="player"), spy)
    assert seen == [("champion", "Faker", "player")]

def test_invalid_subject_type_is_passed_as_none():
    seen = []
    def spy(axis, subject, subject_type):
        seen.append(subject_type)
        return ["x"]
    decide_clarification("T1 어때", _intent(scope_axis="topic", subject_type="org"), spy)
    assert seen == [None]

def test_each_axis_has_prompt_and_template():
    for axis in ("season", "opponent", "stage", "champion", "patch"):
        r = decide_clarification("T1 어쩌고", _intent(scope_axis=axis), _options)
        assert r["axis"] == axis and r["prompt"] == PROMPTS[axis] and r["template"] == TEMPLATES[axis]

def test_topic_prompt_uses_subject():
    r = decide_clarification("T1 어때?", _intent(scope_axis="topic"), _options)
    assert r["prompt"] == "T1의 무엇이 궁금하세요?"
    r = decide_clarification("어때?", _intent(scope_axis="topic", subject=None), _options)
    assert r["prompt"] == TOPIC_PROMPT_NO_SUBJECT

def test_templates_have_both_placeholders():
    for axis, t in TEMPLATES.items():
        assert "{question}" in t and "{option}" in t, axis


# ---------- scope_options ----------

def test_topic_options_are_fixed_and_do_not_touch_db(monkeypatch):
    import clarify
    def boom(*a, **k):
        raise AssertionError("DB 호출 금지")
    monkeypatch.setattr(clarify, "_query", boom)
    assert scope_options("topic", "T1", "team") == TOPICS["team"]
    assert scope_options("topic", "Faker", "player") == TOPICS["player"]
    assert scope_options("topic", None, None) == TOPICS[None]

def test_opponent_options_exclude_subject(monkeypatch):
    import clarify
    def fake(sql, params=()):
        if "entityalias" in sql:
            return []  # 별칭 조회는 못 찾음 → 이름 포함 관계로만 뺀다
        return [{"name": "T1"}, {"name": "젠지 이스포츠"}, {"name": "KT 롤스터"}]
    monkeypatch.setattr(clarify, "_query", fake)
    assert scope_options("opponent", "T1", "team") == ["젠지 이스포츠", "KT 롤스터"]
    assert scope_options("opponent", None, None) == ["T1", "젠지 이스포츠", "KT 롤스터"]

def test_opponent_options_exclude_subject_via_alias(monkeypatch):
    # "T1" 으로 물었는데 DB 팀 이름은 "티원" 인 경우: 별칭 테이블로 같은 팀을 찾아 뺀다
    import clarify
    seen = []
    def fake(sql, params=()):
        if "entityalias" in sql:
            seen.append(params)
            return [{"name": "티원"}]
        return [{"name": "KT 롤스터"}, {"name": "티원"}, {"name": "젠지 이스포츠"}]
    monkeypatch.setattr(clarify, "_query", fake)
    assert scope_options("opponent", "T1", "team") == ["KT 롤스터", "젠지 이스포츠"]
    assert seen == [("%T1%", "%T1%", "%t1%")]

def test_opponent_options_alias_lookup_failure_still_returns_teams(monkeypatch):
    import clarify
    def fake(sql, params=()):
        if "entityalias" in sql:
            raise RuntimeError("alias table down")
        return [{"name": "KT 롤스터"}, {"name": "티원"}]
    monkeypatch.setattr(clarify, "_query", fake)
    assert scope_options("opponent", "T1", "team") == ["KT 롤스터", "티원"]

def test_stage_options_are_korean_labels(monkeypatch):
    import clarify
    monkeypatch.setattr(clarify, "_query", lambda sql, params=(): [{"name": "Regular"}, {"name": "Playoffs"}])
    assert scope_options("stage") == ["정규 시즌", "플레이오프"]

def test_champion_options_fall_back_to_overall_when_player_unknown(monkeypatch):
    import clarify
    calls = []
    def fake(sql, params=()):
        calls.append(sql)
        if "FROM player" in sql:
            return []
        return [{"name": "아지르", "n": 9}, {"name": "오리아나", "n": 4}]
    monkeypatch.setattr(clarify, "_query", fake)
    assert scope_options("champion", "모르는선수", "player") == ["아지르", "오리아나"]
    assert any("FROM player" in c for c in calls)
    assert not any("gp.player_id IN" in c for c in calls)

def test_champion_options_use_player_ids_when_found(monkeypatch):
    import clarify
    calls = []
    def fake(sql, params=()):
        calls.append((sql, params))
        if "FROM player" in sql:
            return [{"player_id": 7}]
        return [{"name": "아지르", "n": 9}]
    monkeypatch.setattr(clarify, "_query", fake)
    assert scope_options("champion", "Faker", "player") == ["아지르"]
    assert any("gp.player_id IN" in s and p == (7,) for s, p in calls)

def test_db_failure_returns_empty(monkeypatch):
    import clarify
    def boom(sql, params=()):
        raise RuntimeError("db down")
    monkeypatch.setattr(clarify, "_query", boom)
    for axis in ("tournament", "season", "opponent", "stage", "champion", "patch"):
        assert scope_options(axis) == []

def test_unknown_axis_returns_empty():
    assert scope_options("position") == []


# ---------- 의도 분석 JSON 정규화 ----------

def _fake(answer):
    def fake(system, user, *, temperature=0.2, max_tokens=1024):
        return answer, None
    return fake

def test_intent_normalizes_scope_keys(monkeypatch):
    monkeypatch.setattr(ce, "_call_clova_chat", _fake('{"intent": "a", "keywords": ["T1"], "needs_scope": true, "scope_axis": "opponent", "subject": " T1 ", "subject_type": "team"}'))
    ce.analyze_question_intent.cache_clear()
    r = ce.analyze_question_intent("질문 A")
    assert r["needs_scope"] is True and r["scope_axis"] == "opponent" and r["subject"] == "T1" and r["subject_type"] == "team"

def test_intent_defaults_scope_keys_when_missing_or_invalid(monkeypatch):
    monkeypatch.setattr(ce, "_call_clova_chat", _fake('{"intent": "a", "keywords": [], "needs_scope": "yes", "scope_axis": "position", "subject": "", "subject_type": "org"}'))
    ce.analyze_question_intent.cache_clear()
    r = ce.analyze_question_intent("질문 B")
    assert r["needs_scope"] is False and r["scope_axis"] is None and r["subject"] is None and r["subject_type"] is None
    monkeypatch.setattr(ce, "_call_clova_chat", _fake('{"intent": "a", "keywords": []}'))
    ce.analyze_question_intent.cache_clear()
    r = ce.analyze_question_intent("질문 C")
    assert r["needs_scope"] is False and r["scope_axis"] is None and r["subject"] is None and r["subject_type"] is None

def test_intent_empty_content_is_error(monkeypatch):
    monkeypatch.setattr(ce, "_call_clova_chat", _fake(""))
    ce.analyze_question_intent.cache_clear()
    r = ce.analyze_question_intent("질문 D")
    assert r["error"] and r["needs_scope"] is False


# ---------- 파이프라인 분기 ----------

def _no_search(*args, **kwargs):
    raise AssertionError("되묻기 응답에서는 검색이 호출되면 안 된다")

def _stub_full_pipeline(monkeypatch, seen):
    monkeypatch.setattr(pipeline, "scope_options", _options)
    monkeypatch.setattr(pipeline, "_search_articles_safe", lambda q, top_k=3, date_range=None: seen.append(("articles", q)) or [])
    monkeypatch.setattr(pipeline, "search_graph_knowledge", lambda kw, limit=100, date_range=None: {"facts": [], "context": "", "keywords": kw, "graph": {"nodes": [], "links": []}})
    monkeypatch.setattr(pipeline, "_search_rdb_safe", lambda q, kw, graph_limit=40, date_range=None: seen.append(("rdb", q)) or {"keywords": [], "entities": {"players": [], "teams": []}, "facts": [], "context": "", "sql": None})
    monkeypatch.setattr(pipeline, "call_hyperclova_kg_answer", lambda q, c: seen.append(("kg", q)) or "kg")
    monkeypatch.setattr(pipeline, "call_hyperclova_rdb_answer", lambda q, c: "rdb")
    monkeypatch.setattr(pipeline, "call_hyperclova_merge", lambda q, a, g, r: seen.append(("merge", q)) or "final")

def test_pipeline_returns_clarify_without_searching(monkeypatch):
    monkeypatch.setattr(pipeline, "analyze_question_intent", lambda q: dict(INTENT_T1))
    monkeypatch.setattr(pipeline, "scope_options", _options)
    monkeypatch.setattr(pipeline, "search_graph_knowledge", _no_search)
    monkeypatch.setattr(pipeline, "_search_articles_safe", _no_search)
    monkeypatch.setattr(pipeline, "_search_rdb_safe", _no_search)
    r = pipeline.run_pipeline("T1의 전략이 궁금해")
    assert r == {
        "type": "clarify",
        "question": "T1의 전략이 궁금해",
        "intent": "T1 전략",
        "clarify": {"axis": "tournament", "prompt": PROMPTS["tournament"], "options": OPTIONS, "template": TEMPLATES["tournament"]},
    }

def test_pipeline_skip_clarify_runs_full_answer(monkeypatch):
    seen = []
    monkeypatch.setattr(pipeline, "analyze_question_intent", lambda q: dict(INTENT_T1))
    _stub_full_pipeline(monkeypatch, seen)
    r = pipeline.run_pipeline("T1의 전략이 궁금해 (2025 LCK Cup 기준)", skip_clarify=True)
    assert r["type"] == "answer" and r["answer"] == "final"

def test_pipeline_skip_clarify_flag_alone_prevents_clarify(monkeypatch):
    # 범위 토큰이 없어도 skip_clarify=True 면 되묻지 않는다 (한 번만 되묻기의 하드 가드)
    seen = []
    monkeypatch.setattr(pipeline, "analyze_question_intent", lambda q: dict(INTENT_T1))
    _stub_full_pipeline(monkeypatch, seen)
    assert pipeline.run_pipeline("T1의 전략이 궁금해", skip_clarify=True)["type"] == "answer"

def test_pipeline_recent_question_uses_latest_season_downstream(monkeypatch):
    seen = []
    monkeypatch.setattr(pipeline, "analyze_question_intent", lambda q: {**INTENT_T1, "needs_scope": False, "scope_axis": None})
    monkeypatch.setattr(pipeline, "latest_season", lambda: "2026")
    _stub_full_pipeline(monkeypatch, seen)
    r = pipeline.run_pipeline("요즘 메타 어때?")
    refined = "요즘 메타 어때? (2026 시즌 기준)"
    assert r["type"] == "answer" and r["question"] == refined
    assert dict(seen)["articles"] == refined and dict(seen)["kg"] == refined and dict(seen)["merge"] == refined

def test_pipeline_recent_question_is_not_clarified_even_if_llm_asks(monkeypatch):
    seen = []
    monkeypatch.setattr(pipeline, "analyze_question_intent", lambda q: {**INTENT_T1, "scope_axis": "season"})
    monkeypatch.setattr(pipeline, "latest_season", lambda: "2026")
    _stub_full_pipeline(monkeypatch, seen)
    assert pipeline.run_pipeline("요즘 메타 어때?")["type"] == "answer"

def test_pipeline_scope_passes_date_range_and_keywords(monkeypatch):
    import clarify
    seen = {}
    monkeypatch.setattr(pipeline, "analyze_question_intent", lambda q: {**INTENT_T1, "needs_scope": False, "scope_axis": None})
    monkeypatch.setattr(pipeline, "scope_date_range", lambda scope: ("2024-01-01", "2024-12-31") if scope == {"axis": "season", "value": "2024"} else None)
    def articles(q, top_k=3, date_range=None):
        seen["articles"] = date_range
        return []
    def graph(kw, limit=100, date_range=None):
        seen["graph"] = (kw, date_range)
        return {"facts": [], "context": "", "keywords": kw, "graph": {"nodes": [], "links": []}}
    monkeypatch.setattr(pipeline, "_search_articles_safe", articles)
    monkeypatch.setattr(pipeline, "search_graph_knowledge", graph)
    monkeypatch.setattr(pipeline, "_search_rdb_safe", lambda q, kw, graph_limit=40, date_range=None: {"keywords": [], "entities": {"players": [], "teams": []}, "facts": [], "context": "", "sql": None})
    monkeypatch.setattr(pipeline, "call_hyperclova_kg_answer", lambda q, c: "kg")
    monkeypatch.setattr(pipeline, "call_hyperclova_rdb_answer", lambda q, c: "rdb")
    monkeypatch.setattr(pipeline, "call_hyperclova_merge", lambda q, a, g, r: "final")
    pipeline.run_pipeline("T1의 전략이 궁금해 (2024 시즌 기준)", skip_clarify=True, scope={"axis": "season", "value": "2024"})
    assert seen["articles"] == ("2024-01-01", "2024-12-31")
    assert seen["graph"] == (["T1"], ("2024-01-01", "2024-12-31"))

def test_pipeline_opponent_scope_adds_keyword(monkeypatch):
    seen = {}
    monkeypatch.setattr(pipeline, "analyze_question_intent", lambda q: {**INTENT_T1, "needs_scope": False, "scope_axis": None})
    monkeypatch.setattr(pipeline, "_search_articles_safe", lambda q, top_k=3, date_range=None: [])
    def graph(kw, limit=100, date_range=None):
        seen["graph"] = (kw, date_range)
        return {"facts": [], "context": "", "keywords": kw, "graph": {"nodes": [], "links": []}}
    monkeypatch.setattr(pipeline, "search_graph_knowledge", graph)
    monkeypatch.setattr(pipeline, "_search_rdb_safe", lambda q, kw, graph_limit=40, date_range=None: {"keywords": [], "entities": {"players": [], "teams": []}, "facts": [], "context": "", "sql": None})
    monkeypatch.setattr(pipeline, "call_hyperclova_kg_answer", lambda q, c: "kg")
    monkeypatch.setattr(pipeline, "call_hyperclova_rdb_answer", lambda q, c: "rdb")
    monkeypatch.setattr(pipeline, "call_hyperclova_merge", lambda q, a, g, r: "final")
    pipeline.run_pipeline("T1 전적 (젠지 이스포츠 상대 기준)", skip_clarify=True, scope={"axis": "opponent", "value": "젠지 이스포츠"})
    assert seen["graph"] == (["T1", "젠지 이스포츠"], None)


# ---------- 범위 → 날짜·키워드 ----------

def test_scope_date_range_season():
    from clarify import scope_date_range
    assert scope_date_range({"axis": "season", "value": "2024"}) == ("2024-01-01", "2024-12-31")
    assert scope_date_range({"axis": "season", "value": "abc"}) is None
    assert scope_date_range(None) is None
    assert scope_date_range({"axis": "opponent", "value": "젠지"}) is None

def test_scope_date_range_tournament_from_db(monkeypatch):
    import clarify
    monkeypatch.setattr(clarify, "_query", lambda sql, params=(): [{"s": "2025-01-15", "e": "2025-02-28"}])
    assert clarify.scope_date_range({"axis": "tournament", "value": "2025 LCK Cup"}) == ("2025-01-15", "2025-02-28")

def test_scope_date_range_tournament_falls_back_to_year(monkeypatch):
    import clarify
    monkeypatch.setattr(clarify, "_query", lambda sql, params=(): [{"s": None, "e": None}])
    assert clarify.scope_date_range({"axis": "tournament", "value": "2025 LCK Cup"}) == ("2025-01-01", "2025-12-31")
    def boom(sql, params=()):
        raise RuntimeError("db")
    monkeypatch.setattr(clarify, "_query", boom)
    assert clarify.scope_date_range({"axis": "tournament", "value": "2025 LCK Cup"}) == ("2025-01-01", "2025-12-31")
    assert clarify.scope_date_range({"axis": "tournament", "value": "LCK Cup"}) is None

def test_scope_date_range_patch(monkeypatch):
    import clarify
    monkeypatch.setattr(clarify, "_query", lambda sql, params=(): [{"season_year": 2025}])
    assert clarify.scope_date_range({"axis": "patch", "value": "25.24"}) == ("2025-01-01", "2025-12-31")
    monkeypatch.setattr(clarify, "_query", lambda sql, params=(): [])
    assert clarify.scope_date_range({"axis": "patch", "value": "99.99"}) is None

def test_scope_keywords():
    from clarify import scope_keywords
    assert scope_keywords({"axis": "opponent", "value": "젠지 이스포츠"}) == ["젠지 이스포츠"]
    assert scope_keywords({"axis": "champion", "value": "아지르"}) == ["아지르"]
    assert scope_keywords({"axis": "season", "value": "2024"}) == []
    assert scope_keywords(None) == []


# ---------- 그래프·기사 날짜 필터 ----------

def _graph():
    nodes = [
        {"id": "t1", "name": "티원", "label": "Team", "degree": 3, "is_seed": True, "match_date": None},
        {"id": "m24", "name": "KT vs T1 · 2024-01-26", "label": "Match", "degree": 1, "is_seed": False, "match_date": "2024-01-26"},
        {"id": "m25", "name": "HLE vs T1 · 2025-04-12", "label": "Match", "degree": 2, "is_seed": False, "match_date": "2025-04-12"},
        {"id": "mnd", "name": "경기 · 날짜 없음", "label": "Match", "degree": 1, "is_seed": False, "match_date": None},
        {"id": "p1", "name": "페이커", "label": "Player", "degree": 1, "is_seed": False, "match_date": None},
    ]
    links = [
        {"source": "t1", "target": "m24", "type": "WON_MATCH", "evidence": None},
        {"source": "t1", "target": "m25", "type": "LOST_MATCH", "evidence": None},
        {"source": "p1", "target": "m25", "type": "PLAYED_MATCH", "evidence": None},
        {"source": "t1", "target": "mnd", "type": "PLAYED_MATCH", "evidence": None},
    ]
    facts = [
        {"source": "티원", "source_label": "Team", "relation": "WON_MATCH", "target": "KT vs T1 · 2024-01-26", "target_label": "Match", "evidence": None},
        {"source": "티원", "source_label": "Team", "relation": "LOST_MATCH", "target": "HLE vs T1 · 2025-04-12", "target_label": "Match", "evidence": None},
        {"source": "페이커", "source_label": "Player", "relation": "PLAYED_MATCH", "target": "HLE vs T1 · 2025-04-12", "target_label": "Match", "evidence": None},
    ]
    return {"nodes": nodes, "links": links}, facts

def test_filter_graph_by_date_keeps_only_matches_in_range():
    from neo4j_query import filter_graph_by_date
    graph, facts = _graph()
    g, f = filter_graph_by_date(graph, facts, "2024-01-01", "2024-12-31")
    ids = {n["id"] for n in g["nodes"]}
    assert ids == {"t1", "m24", "mnd"}            # 2025 경기와, 그 경기에만 닿던 페이커가 빠진다
    assert len(g["links"]) == 2
    assert {n["id"]: n["degree"] for n in g["nodes"]} == {"t1": 2, "m24": 1, "mnd": 1}
    assert [x["target"] for x in f] == ["KT vs T1 · 2024-01-26"]

def test_filter_graph_by_date_keeps_seed_even_if_isolated():
    from neo4j_query import filter_graph_by_date
    graph, facts = _graph()
    g, _ = filter_graph_by_date(graph, facts, "2030-01-01", "2030-12-31")
    assert {n["id"] for n in g["nodes"]} == {"t1", "mnd"} and g["links"][0]["target"] == "mnd"

def test_filter_graph_by_date_noop_when_all_inside():
    from neo4j_query import filter_graph_by_date
    graph, facts = _graph()
    g, f = filter_graph_by_date(graph, facts, "2020-01-01", "2030-12-31")
    assert g is graph and f is facts

def test_filter_articles_by_date():
    from rag_answer import filter_by_date
    items = [{"published_at": "2025-03-01T00:00:00"}, {"published_at": "2024-06-01"}, {"published_at": ""}, {"published_at": "2024-12-31"}]
    assert filter_by_date(items, "2024-01-01", "2024-12-31", 5) == [{"published_at": "2024-06-01"}, {"published_at": "2024-12-31"}]
    assert filter_by_date(items, "2024-01-01", "2024-12-31", 1) == [{"published_at": "2024-06-01"}]


def test_pipeline_recent_without_db_keeps_question(monkeypatch):
    seen = []
    monkeypatch.setattr(pipeline, "analyze_question_intent", lambda q: {**INTENT_T1, "needs_scope": False, "scope_axis": None})
    monkeypatch.setattr(pipeline, "latest_season", lambda: None)
    _stub_full_pipeline(monkeypatch, seen)
    assert pipeline.run_pipeline("요즘 메타 어때?")["question"] == "요즘 메타 어때?"
