from app.search import rdb_query as r


class FakeCursor:
    """execute 로 받은 SQL·파라미터를 기록하고, 미리 정한 행을 돌려준다."""
    def __init__(self, rows_by_call):
        self.rows_by_call = list(rows_by_call)
        self.calls = []

    def execute(self, sql, params=()):
        self.calls.append((sql, params))

    def fetchall(self):
        return self.rows_by_call.pop(0) if self.rows_by_call else []


def test_module_no_longer_references_dropped_alias_tables():
    src = open(r.__file__, encoding="utf-8").read()
    assert "playeralias" not in src and "teamalias" not in src

def test_normalize_alias_matches_db_rule():
    assert r.normalize_alias("Gen.G") == "geng"
    assert r.normalize_alias("'페이커' 이상혁") == "페이커이상혁"
    assert r.normalize_alias("SKT T1") == "sktt1"
    assert r.normalize_alias("한화생명 e스포츠") == "한화생명e스포츠"

def test_resolve_teams_uses_entityalias_and_name_history():
    cur = FakeCursor([[{"team_id": 20, "team_name": "티원"}]])
    teams = r._resolve_teams(cur, ["T1"])
    sql, params = cur.calls[0]
    assert "entityalias" in sql and "teamnamehistory" in sql
    assert params == ("%T1%", "T1", "t1", "T1", "T1")
    assert teams == [{"team_id": 20, "team_name": "티원"}]

def test_resolve_players_alias_is_exact_match_only():
    cur = FakeCursor([[{"player_id": 83, "player_name": "페이커", "position": "mid"}]])
    players = r._resolve_players(cur, ["Faker"])
    sql, params = cur.calls[0]
    assert "entityalias" in sql
    assert "ea.alias_name = %s" in sql and "ea.normalized_alias = %s" in sql
    assert "ea.alias_name LIKE" not in sql
    assert params == ("%Faker%", "%Faker%", "Faker", "faker")
    assert players[0]["position"] == "mid"

def test_resolve_dedupes_across_keywords():
    row = {"team_id": 20, "team_name": "티원"}
    cur = FakeCursor([[row], [row]])
    assert r._resolve_teams(cur, ["T1", "티원"]) == [row]

def test_team_roster_facts_latest_year():
    cur = FakeCursor([[
        {"player_name": "도란", "position": "top", "games": 109, "yr": 2026},
        {"player_name": "페이커", "position": "mid", "games": 109, "yr": 2026},
    ]])
    facts = r._team_roster_facts(cur, {"team_id": 20, "team_name": "티원"})
    assert facts == ["(Team) 티원 2026년 출전 선수: 도란(top, 109게임), 페이커(mid, 109게임)"]
    assert cur.calls[0][1] == (20, 20, 20)

def test_team_roster_facts_empty():
    assert r._team_roster_facts(FakeCursor([[]]), {"team_id": 1, "team_name": "x"}) == []

def test_schema_prompt_describes_new_tables():
    for table in ("entityalias", "season", "tournamentstage", "teamnamehistory", "gameparticipant", "gamedraft", "teamroster"):
        assert table in r.RDB_SCHEMA_PROMPT, table


# ---------- 기간 ----------

def test_question_date_range_uses_shared_rule():
    assert r.question_date_range("2025년 페이커 평균 KDA") == ("2025-01-01", "2025-12-31")
    # 연도가 여러 개면 가장 이른 해부터 가장 늦은 해까지다(그래프·기사 검색과 같은 규칙).
    assert r.question_date_range("2024 vs 2025 비교") == ("2024-01-01", "2025-12-31")
    assert r.question_date_range("페이커 KDA") is None

def test_range_label():
    assert r._range_label(("2025-01-01", "2025-12-31")) == "2025년 "
    assert r._range_label(("2025-01-15", "2025-02-28")) == "2025-01-15~2025-02-28 "
    assert r._range_label(None) == ""

def test_team_record_applies_date_range():
    cur = FakeCursor([])
    cur.fetchone = lambda: {"matches": 10, "wins": 7}
    facts = r._team_record_facts(cur, {"team_id": 20, "team_name": "티원"}, ("2025-01-01", "2025-12-31"))
    sql, params = cur.calls[0]
    assert "match_date BETWEEN %s AND %s" in sql
    assert params == (20, 20, 20, "2025-01-01", "2025-12-31 23:59:59")
    assert facts == ["(Team) 2025년 티원 — 매치 10전 7승 3패"]

def test_player_overall_without_range_has_no_date_filter():
    cur = FakeCursor([])
    cur.fetchone = lambda: {"games": 0}
    r._player_overall_facts(cur, {"player_id": 83, "player_name": "페이커"})
    sql, params = cur.calls[0]
    assert "BETWEEN" not in sql and params == (83,)


# ---------- 맞대결 ----------

T1 = {"team_id": 20, "team_name": "티원"}
GEN = {"team_id": 16, "team_name": "젠지 이스포츠"}

def test_head_to_head_summary_and_recent():
    rows = [
        {"d": "2026-07-01", "winner_team_id": 16, "a_sets": 1, "b_sets": 2},
        {"d": "2026-04-10", "winner_team_id": 20, "a_sets": 2, "b_sets": 0},
        {"d": "2025-09-01", "winner_team_id": 16, "a_sets": 0, "b_sets": 3},
    ]
    cur = FakeCursor([rows])
    facts = r._head_to_head_facts(cur, T1, GEN, recent=2)
    assert facts == [
        "(H2H) 티원 vs 젠지 이스포츠 — 맞대결 3매치, 티원 1승 / 젠지 이스포츠 2승, 세트 3:5",
        "(H2H) 2026-07-01 티원 1:2 젠지 이스포츠 (승: 젠지 이스포츠)",
        "(H2H) 2026-04-10 티원 2:0 젠지 이스포츠 (승: 티원)",
    ]
    assert cur.calls[0][1] == (20, 20, 20, 16, 16, 20)

def test_head_to_head_none():
    assert r._head_to_head_facts(FakeCursor([[]]), T1, GEN) == []

def test_run_templates_puts_head_to_head_first_when_two_teams(monkeypatch):
    order = []
    monkeypatch.setattr(r, "_head_to_head_facts", lambda cur, a, b, dr=None: order.append(("h2h", a["team_id"], b["team_id"], dr)) or ["h2h"])
    monkeypatch.setattr(r, "_team_record_facts", lambda cur, t, dr=None: order.append(("rec", t["team_id"], dr)) or [])
    monkeypatch.setattr(r, "_team_roster_facts", lambda cur, t, dr=None: [])
    facts = r._run_templates(None, [], [T1, GEN], ("2025-01-01", "2025-12-31"))
    assert facts[0] == "h2h"
    assert order[0] == ("h2h", 20, 16, ("2025-01-01", "2025-12-31"))
    assert ("rec", 20, ("2025-01-01", "2025-12-31")) in order

def test_schema_prompt_spells_out_season_join():
    assert "tournament.season_id = season.season_id" in r.RDB_SCHEMA_PROMPT
    assert "`match` 에는 season_id 가 없다" in r.RDB_SCHEMA_PROMPT
