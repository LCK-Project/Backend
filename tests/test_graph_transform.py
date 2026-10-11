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
