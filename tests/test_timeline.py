from datetime import datetime

from app import timeline as tl


def _graph(*dates):
    nodes = [{"id": f"m{i}", "label": "Match", "match_date": d} for i, d in enumerate(dates)]
    nodes.append({"id": "t1", "label": "Team", "match_date": None})
    return {"nodes": nodes, "links": []}


def test_span_from_dated_matches():
    assert tl.graph_date_span(_graph("2025-04-20", "2025-01-15", None)) == ("2025-01-15", "2025-04-20")

def test_span_none_without_dated_match():
    assert tl.graph_date_span(_graph(None)) is None
    assert tl.graph_date_span({"nodes": [], "links": []}) is None
    assert tl.graph_date_span(None) is None

def test_timeline_rows_to_bands(monkeypatch):
    rows = [{"name": "2025 LCK Cup", "s": datetime(2025, 1, 15, 17, 0), "e": datetime(2025, 2, 23, 15, 0)}]
    monkeypatch.setattr(tl, "_query", lambda sql, params=(): rows)
    assert tl.build_timeline(_graph("2025-01-15", "2025-04-20")) == {
        "tournaments": [{"name": "2025 LCK Cup", "start": "2025-01-15", "end": "2025-02-23"}]
    }

def test_timeline_query_params(monkeypatch):
    seen = []
    monkeypatch.setattr(tl, "_query", lambda sql, params=(): seen.append((sql, params)) or [])
    tl.build_timeline(_graph("2025-04-20", "2025-01-15"))
    assert seen[0][0] == tl.TOURNAMENT_SPAN_SQL
    assert seen[0][1] == ("2025-04-20 23:59:59", "2025-01-15")

def test_timeline_empty_when_no_match(monkeypatch):
    def boom(sql, params=()):
        raise AssertionError("경기가 없으면 조회하지 않는다")
    monkeypatch.setattr(tl, "_query", boom)
    assert tl.build_timeline(_graph(None)) == {"tournaments": []}

def test_timeline_empty_on_db_error(monkeypatch):
    def boom(sql, params=()):
        raise RuntimeError("connection refused")
    monkeypatch.setattr(tl, "_query", boom)
    assert tl.build_timeline(_graph("2025-01-15")) == {"tournaments": []}
