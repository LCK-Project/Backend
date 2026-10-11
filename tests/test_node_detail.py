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
