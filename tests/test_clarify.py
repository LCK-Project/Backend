import clova_extract as ce
import pipeline
from clarify import PROMPTS, decide_clarification, has_scope_token

INTENT_NEEDS_TOURNAMENT = {"intent": "T1 전략", "keywords": ["T1"], "needs_scope": True, "scope_axis": "tournament"}
OPTIONS = ["2026 LCK Cup", "2025 LCK Rounds 1-2"]


def _options(axis):
    return OPTIONS


# ---------- has_scope_token ----------

def test_scope_token_year():
    assert has_scope_token("2025년 T1 전략") is True

def test_scope_token_korean_and_english_words():
    assert has_scope_token("T1 서머 시즌 성적") is True
    assert has_scope_token("T1 LCK Cup 전략") is True
    assert has_scope_token("젠지 Rounds 1-2 밴픽") is True
    assert has_scope_token("월즈에서 페이커 활약") is True

def test_scope_token_absent():
    assert has_scope_token("T1의 전략이 궁금해") is False
    assert has_scope_token("") is False
    assert has_scope_token(None) is False


# ---------- decide_clarification ----------

def test_clarify_when_all_conditions_hold():
    result = decide_clarification("T1의 전략이 궁금해", INTENT_NEEDS_TOURNAMENT, _options)
    assert result == {"axis": "tournament", "prompt": PROMPTS["tournament"], "options": OPTIONS}

def test_no_clarify_when_question_has_scope_token():
    assert decide_clarification("2025 T1의 전략이 궁금해", INTENT_NEEDS_TOURNAMENT, _options) is None

def test_no_clarify_when_llm_says_no_scope_needed():
    intent = {**INTENT_NEEDS_TOURNAMENT, "needs_scope": False}
    assert decide_clarification("T1의 전략이 궁금해", intent, _options) is None

def test_no_clarify_when_axis_unknown():
    intent = {**INTENT_NEEDS_TOURNAMENT, "scope_axis": "opponent"}
    assert decide_clarification("T1의 전략이 궁금해", intent, _options) is None
    intent = {**INTENT_NEEDS_TOURNAMENT, "scope_axis": None}
    assert decide_clarification("T1의 전략이 궁금해", intent, _options) is None

def test_no_clarify_when_options_empty_or_failing():
    assert decide_clarification("T1의 전략이 궁금해", INTENT_NEEDS_TOURNAMENT, lambda axis: []) is None
    def boom(axis):
        raise RuntimeError("db down")
    assert decide_clarification("T1의 전략이 궁금해", INTENT_NEEDS_TOURNAMENT, boom) is None

def test_season_axis_uses_season_prompt():
    intent = {**INTENT_NEEDS_TOURNAMENT, "scope_axis": "season"}
    result = decide_clarification("T1의 전략이 궁금해", intent, lambda axis: ["2026", "2025"])
    assert result["axis"] == "season" and result["prompt"] == PROMPTS["season"] and result["options"] == ["2026", "2025"]


# ---------- 의도 분석 JSON 정규화 ----------

def _fake(answer):
    def fake(system, user, *, temperature=0.2, max_tokens=1024):
        return answer, None
    return fake

def test_intent_normalizes_scope_keys(monkeypatch):
    monkeypatch.setattr(ce, "_call_clova_chat", _fake('{"intent": "a", "keywords": ["T1"], "needs_scope": true, "scope_axis": "tournament"}'))
    ce.analyze_question_intent.cache_clear()
    r = ce.analyze_question_intent("질문 A")
    assert r["needs_scope"] is True and r["scope_axis"] == "tournament"

def test_intent_defaults_scope_keys_when_missing_or_invalid(monkeypatch):
    monkeypatch.setattr(ce, "_call_clova_chat", _fake('{"intent": "a", "keywords": [], "needs_scope": "yes", "scope_axis": "opponent"}'))
    ce.analyze_question_intent.cache_clear()
    r = ce.analyze_question_intent("질문 B")
    assert r["needs_scope"] is False and r["scope_axis"] is None
    monkeypatch.setattr(ce, "_call_clova_chat", _fake('{"intent": "a", "keywords": []}'))
    ce.analyze_question_intent.cache_clear()
    r = ce.analyze_question_intent("질문 C")
    assert r["needs_scope"] is False and r["scope_axis"] is None


# ---------- 파이프라인 분기 ----------

def _no_search(*args, **kwargs):
    raise AssertionError("되묻기 응답에서는 검색이 호출되면 안 된다")

def test_pipeline_returns_clarify_without_searching(monkeypatch):
    monkeypatch.setattr(pipeline, "analyze_question_intent", lambda q: dict(INTENT_NEEDS_TOURNAMENT))
    monkeypatch.setattr(pipeline, "scope_options", _options)
    monkeypatch.setattr(pipeline, "search_graph_knowledge", _no_search)
    monkeypatch.setattr(pipeline, "_search_articles_safe", _no_search)
    monkeypatch.setattr(pipeline, "_search_rdb_safe", _no_search)
    r = pipeline.run_pipeline("T1의 전략이 궁금해")
    assert r == {
        "type": "clarify",
        "question": "T1의 전략이 궁금해",
        "intent": "T1 전략",
        "clarify": {"axis": "tournament", "prompt": PROMPTS["tournament"], "options": OPTIONS},
    }

def test_pipeline_skip_clarify_runs_full_answer(monkeypatch):
    monkeypatch.setattr(pipeline, "analyze_question_intent", lambda q: dict(INTENT_NEEDS_TOURNAMENT))
    monkeypatch.setattr(pipeline, "scope_options", _options)
    monkeypatch.setattr(pipeline, "_search_articles_safe", lambda q, top_k=3: [])
    monkeypatch.setattr(pipeline, "search_graph_knowledge", lambda kw, limit=100: {"facts": [], "context": "", "keywords": kw, "graph": {"nodes": [], "links": []}})
    monkeypatch.setattr(pipeline, "_search_rdb_safe", lambda q, kw, graph_limit=40: {"keywords": [], "entities": {"players": [], "teams": []}, "facts": [], "context": "", "sql": None})
    monkeypatch.setattr(pipeline, "call_hyperclova_kg_answer", lambda q, c: "kg")
    monkeypatch.setattr(pipeline, "call_hyperclova_rdb_answer", lambda q, c: "rdb")
    monkeypatch.setattr(pipeline, "call_hyperclova_merge", lambda q, a, g, r: "final")
    r = pipeline.run_pipeline("T1의 전략이 궁금해 (2025 LCK Cup 기준)", skip_clarify=True)
    assert r["type"] == "answer" and r["answer"] == "final"

def test_pipeline_skip_clarify_flag_alone_prevents_clarify(monkeypatch):
    # 범위 토큰이 없어도 skip_clarify=True 면 되묻지 않는다 (한 번만 되묻기의 하드 가드)
    monkeypatch.setattr(pipeline, "analyze_question_intent", lambda q: dict(INTENT_NEEDS_TOURNAMENT))
    monkeypatch.setattr(pipeline, "scope_options", _options)
    monkeypatch.setattr(pipeline, "_search_articles_safe", lambda q, top_k=3: [])
    monkeypatch.setattr(pipeline, "search_graph_knowledge", lambda kw, limit=100: {"facts": [], "context": "", "keywords": kw, "graph": {"nodes": [], "links": []}})
    monkeypatch.setattr(pipeline, "_search_rdb_safe", lambda q, kw, graph_limit=40: {"keywords": [], "entities": {"players": [], "teams": []}, "facts": [], "context": "", "sql": None})
    monkeypatch.setattr(pipeline, "call_hyperclova_kg_answer", lambda q, c: "kg")
    monkeypatch.setattr(pipeline, "call_hyperclova_rdb_answer", lambda q, c: "rdb")
    monkeypatch.setattr(pipeline, "call_hyperclova_merge", lambda q, a, g, r: "final")
    assert pipeline.run_pipeline("T1의 전략이 궁금해", skip_clarify=True)["type"] == "answer"
