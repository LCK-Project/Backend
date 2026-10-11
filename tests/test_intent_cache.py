import clova_extract as ce

def _fake_calls(answers):
    calls = []
    def fake(system, user, *, temperature=0.2, max_tokens=1024):
        calls.append((user, temperature))
        return answers[min(len(calls) - 1, len(answers) - 1)], None
    return fake, calls

def test_same_question_calls_llm_once(monkeypatch):
    fake, calls = _fake_calls(['{"intent": "a", "keywords": ["한화생명"]}', '{"intent": "b", "keywords": ["젠지"]}'])
    monkeypatch.setattr(ce, "_call_clova_chat", fake)
    ce.analyze_question_intent.cache_clear()
    first = ce.analyze_question_intent("한화생명 우승 전략을 알려줘")
    second = ce.analyze_question_intent("  한화생명 우승 전략을 알려줘 ")
    assert first == second == {"intent": "a", "keywords": ["한화생명"]} and len(calls) == 1

def test_intent_uses_zero_temperature(monkeypatch):
    fake, calls = _fake_calls(['{"intent": "a", "keywords": []}'])
    monkeypatch.setattr(ce, "_call_clova_chat", fake)
    ce.analyze_question_intent.cache_clear()
    ce.analyze_question_intent("질문 1")
    assert calls[0][1] == 0.0

def test_error_result_is_not_cached(monkeypatch):
    fake, calls = _fake_calls(['', '{"intent": "a", "keywords": ["x"]}'])
    monkeypatch.setattr(ce, "_call_clova_chat", fake)
    ce.analyze_question_intent.cache_clear()
    assert ce.analyze_question_intent("질문 2")["keywords"] == []
    assert ce.analyze_question_intent("질문 2")["keywords"] == ["x"] and len(calls) == 2
