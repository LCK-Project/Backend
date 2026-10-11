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


from neo4j_query import records_to_graph, records_to_facts, format_graph_facts
from tests.stubs import StubRel, structure_record, claim_record

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
