from app.search.neo4j_query import build_match_name, node_to_dict
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


from app.search.neo4j_query import format_graph_facts, records_to_facts, records_to_graph
from tests.stubs import StubRel, claim_record, structure_record

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
    assert g["links"] == [{"source": "4:x:1", "target": "4:x:9", "type": "WON_MATCH", "evidence": None, "when": [["2025-09-06", "2025-09-06"]]}]
def test_claim_record_becomes_edge_with_evidence():
    g = records_to_graph([], [claim_record(HLE, ZEKA, AZIR, "PICKED_CHAMPION", "ARTICLE_1", "제카가 아지르를 꺼냈다.", 1.0)], {"4:x:1"})
    assert g["links"] == [{"source": "4:x:3", "target": "4:x:13", "type": "PICKED_CHAMPION", "evidence": {"article_key": "ARTICLE_1", "text": "제카가 아지르를 꺼냈다.", "confidence": 1.0}, "when": None}]
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


# ---------- 간선의 when (날짜 스트립 기간 선택용) ----------
from app.search.neo4j_query import claim_when, structure_when

def _rec(n, rel, m, spans=None, game_keys=None):
    return {**structure_record(n, rel, m), "spans": spans or [], "game_keys": game_keys or []}

def _link(g):
    assert len(g["links"]) == 1
    return g["links"][0]

def test_when_member_of_collects_every_interval_sorted():
    rec = _rec(HLE, StubRel("MEMBER_OF", ZEKA, HLE), ZEKA, spans=[["2025-07-23", "2025-09-10"], ["2025-04-01", "2025-07-23"], ["2025-04-01", "2025-07-23"]])
    assert structure_when(rec) == [["2025-04-01", "2025-07-23"], ["2025-07-23", "2025-09-10"]]

def test_when_open_ended_interval_keeps_none():
    rec = _rec(HLE, StubRel("MEMBER_OF", ZEKA, HLE), ZEKA, spans=[["2026-04-01", ""], [None, None]])
    assert structure_when(rec) == [["2026-04-01", None]]

def test_when_pick_uses_game_dates_and_skips_unknown_game():
    rec = _rec(ZEKA, StubRel("PICKED_CHAMPION", ZEKA, AZIR), AZIR, spans=[[None, None], [None, None]], game_keys=["G2", "G1", "G_없음"])
    dates = {"G1": "2025-01-15T17:00:00", "G2": "2025-08-30T15:00:00"}
    assert structure_when(rec, dates) == [["2025-01-15", "2025-01-15"], ["2025-08-30", "2025-08-30"]]

def test_when_match_edge_uses_match_date():
    assert structure_when(_rec(HLE, StubRel("WON_MATCH", HLE, M9), M9)) == [["2025-09-06", "2025-09-06"]]

def test_when_fan_comment_edge_uses_published_date():
    video = StubNode("4:x:50", ["FanVideo"], {"video_published_at": "2025-08-02T13:00:10"})
    comment = StubNode("4:x:51", ["FanComment"], {"comment_published_at": "2026-07-05T04:42:09"})
    rec = _rec(video, StubRel("HAS_COMMENT", video, comment), comment)
    assert structure_when(rec) == [["2025-08-02", "2025-08-02"], ["2026-07-05", "2026-07-05"]]

def test_when_none_for_undated_edge():
    league = StubNode("4:x:60", ["League"], {"name": "LCK"})
    assert structure_when(_rec(HLE, StubRel("COMPETES_IN", HLE, league), league)) is None
    # 스텁처럼 spans·game_keys 키가 아예 없는 레코드도 받는다.
    assert structure_when(structure_record(HLE, StubRel("COMPETES_IN", HLE, league), league)) is None

def test_claim_when_prefers_published_at_then_article_key():
    base = claim_record(HLE, ZEKA, AZIR, "PICKED_CHAMPION", "ARTICLE_01100201.20250306154350001", "t", 1.0)
    assert claim_when({**base, "published_at": "2025-03-07T00:00:00"}) == [["2025-03-07", "2025-03-07"]]
    assert claim_when(base) == [["2025-03-06", "2025-03-06"]]
    assert claim_when({**base, "article_key": "ARTICLE_1"}) is None

def test_graph_duplicate_claims_merge_when_and_keep_first_evidence():
    claims = [
        {**claim_record(HLE, ZEKA, AZIR, "PICKED_CHAMPION", "ARTICLE_2", "둘째 날", 1.0), "published_at": "2025-08-30T00:00:00"},
        {**claim_record(HLE, ZEKA, AZIR, "PICKED_CHAMPION", "ARTICLE_1", "첫째 날", 0.8), "published_at": "2025-03-06T00:00:00"},
    ]
    link = _link(records_to_graph([], claims, set()))
    assert link["evidence"]["article_key"] == "ARTICLE_2"
    assert link["when"] == [["2025-03-06", "2025-03-06"], ["2025-08-30", "2025-08-30"]]

def test_graph_structure_edge_ignores_claim_dates_of_same_edge():
    structure = [_rec(HLE, StubRel("MEMBER_OF", ZEKA, HLE), ZEKA, spans=[["2025-04-01", "2025-07-23"]])]
    claims = [{**claim_record(HLE, ZEKA, HLE, "MEMBER_OF", "ARTICLE_3", "제카는 한화생명 소속이다.", 1.0), "published_at": "2026-01-01T00:00:00"}]
    link = _link(records_to_graph(structure, claims, set()))
    assert link["evidence"] is None
    assert link["when"] == [["2025-04-01", "2025-07-23"]]

def test_graph_same_structure_edge_from_two_seeds_merges_when():
    a = _rec(ZEKA, StubRel("PICKED_CHAMPION", ZEKA, AZIR), AZIR, game_keys=["G1"])
    b = _rec(AZIR, StubRel("PICKED_CHAMPION", ZEKA, AZIR), ZEKA, game_keys=["G2"])
    link = _link(records_to_graph([a, b], [], set(), {"G1": "2025-01-15", "G2": "2025-08-30"}))
    assert link["when"] == [["2025-01-15", "2025-01-15"], ["2025-08-30", "2025-08-30"]]


# ---------- 그래프 검색 키워드 ----------
from app.search.neo4j_query import _extract_keywords

def test_keywords_drop_numeric_only_tokens():
    assert _extract_keywords(["2024", "T1", "전략"]) == ["t1", "전략"]
    assert _extract_keywords(["2024년", "5월", "페이커"]) == ["페이커"]
    assert _extract_keywords("2024 T1 전략") == ["2024 t1 전략", "t1", "전략"]

def test_keywords_keep_names_containing_digits():
    assert _extract_keywords(["T1", "100 Thieves"]) == ["t1", "100 thieves", "thieves"]


# ---------- 시드 찾기 ----------
from app.search import neo4j_query as nq

class _Session:
    """run 으로 받은 쿼리를 기록하고, 쿼리별로 정해 둔 행을 돌려준다."""
    def __init__(self, exact, contains):
        self.rows = {nq.SEED_EXACT_CYPHER: exact, nq.SEED_CONTAINS_CYPHER: contains}
        self.calls = []
    def run(self, query, **params):
        self.calls.append((query, params))
        return [{"id": i} for i in self.rows[query]]

def test_seed_keys_strip_spaces_and_dedupe():
    assert nq.seed_keys(["한화생명 이스포츠", "t1", "t 1", " "]) == ["한화생명이스포츠", "t1"]

def test_find_seed_ids_exact_hit_skips_contains():
    session = _Session(exact=["4:x:1"], contains=["4:x:1", "4:x:99"])
    assert nq.find_seed_ids(session, ["kt", "전략"]) == ["4:x:1"]
    assert [q for q, _ in session.calls] == [nq.SEED_EXACT_CYPHER]
    assert session.calls[0][1]["keys"] == ["kt", "전략"]

def test_find_seed_ids_falls_back_to_contains_only_without_exact_hit():
    session = _Session(exact=[], contains=["4:x:7"])
    assert nq.find_seed_ids(session, ["페이"]) == ["4:x:7"]
    assert [q for q, _ in session.calls] == [nq.SEED_EXACT_CYPHER, nq.SEED_CONTAINS_CYPHER]

def test_find_seed_ids_no_keywords_runs_nothing():
    session = _Session(exact=["4:x:1"], contains=[])
    assert nq.find_seed_ids(session, [" "]) == []
    assert session.calls == []

def test_seed_queries_only_consider_entity_nodes():
    assert "MATCH (n:Entity)" in nq.SEED_EXACT_CYPHER and "MATCH (n:Entity)" in nq.SEED_CONTAINS_CYPHER
    assert " IN $keys" in nq.SEED_EXACT_CYPHER and "CONTAINS" not in nq.SEED_EXACT_CYPHER


# ---------- 질문 종류별 그래프 구성 ----------
def test_graph_focus_strategy_words():
    for q in ("티원 전략 알려줘", "젠지 밴픽 경향", "요즘 메타 어때", "페이커 챔피언 폭", "한화 조합"):
        assert nq.graph_focus(q) == "strategy", q

def test_graph_focus_default():
    for q in ("티원 성적 알려줘", "젠지 로스터", "", None):
        assert nq.graph_focus(q) == "default", q

def test_graph_focus_profiles():
    assert nq.GRAPH_FOCUS["default"] == {"per_match": nq.STRUCTURE_PER_TYPE_LIMIT, "team_picks": 8}
    assert nq.GRAPH_FOCUS["strategy"] == {"per_match": 8, "team_picks": 20}
    assert nq.MATCH_REL_TYPES == ["WON_MATCH", "LOST_MATCH", "PLAYED_MATCH"]
