"""
RDB(espo) 기반 정형 데이터 검색 - 하이브리드 방식.

흐름:
  키워드
   └→ 1) 엔티티 확정: player/team + 별칭(entityalias, teamnamehistory) 매칭
        ├→ 2) 정형 질문: 미리 정의한 고정 통계 쿼리 실행 (안전·결정적)
        └→ 3) 그 외/집계 질문: HyperCLOVA Text-to-SQL 폴백 (SELECT 전용 검증)
             └→ facts(사실 문자열) + context(LLM 답변용 텍스트) 반환

정형 데이터는 그래프/기사가 답하기 어려운 수치·집계 질문
(평균 KDA, 팀 전적, 최다 킬 등)의 근거가 된다.
"""

import re

from mysql_connect import get_connection

# =========================
# 키워드 정리
# =========================

# 엔티티(선수/팀)명이 아닌 통계·질의 어휘. LIKE 부분매칭 노이즈를 막는다.
# (예: 'KDA' 가 'deokdam' 에, '전적' 이 엉뚱한 이름에 substring 매칭되는 것 방지)
_RESOLVE_STOPWORDS = {
    "평균", "kda", "전적", "우승", "경기", "게임", "통계", "선수", "정보", "기록",
    "성적", "승률", "순위", "랭킹", "스탯", "최다", "가장", "비교", "관련",
    "챔피언", "대회", "리그", "포지션", "알려줘", "보여줘", "분석",
}


def _as_keyword_list(keywords):
    if isinstance(keywords, str):
        items = [keywords]
    elif isinstance(keywords, list):
        items = keywords
    else:
        items = []

    # 구절 키워드("T1 전적")는 팀/선수명("T1")과 LIKE 매칭이 안 되므로
    # 구절 자체 + 공백 단위 토큰을 모두 후보로 풀어준다.
    expanded = []
    for kw in items:
        kw = str(kw).strip()
        if len(kw) >= 2 and kw.lower() not in _RESOLVE_STOPWORDS:
            expanded.append(kw)
        for tok in kw.split():
            tok = tok.strip()
            if len(tok) >= 2 and tok.lower() not in _RESOLVE_STOPWORDS:
                expanded.append(tok)

    # 중복 제거(순서 유지)
    return list(dict.fromkeys(expanded))


# =========================
# 1) 엔티티 확정 (별칭 해소)
# =========================

def normalize_alias(text):
    """
    entityalias.normalized_alias 와 같은 규칙으로 정규화한다: 소문자, 공백·따옴표·마침표·가운뎃점·하이픈 제거.
    예: "Gen.G" → "geng", "'페이커' 이상혁" → "페이커이상혁"
    """
    return re.sub(r"[\s'\"‘’“”.·\-_]", "", str(text).lower())


# 선수 포지션은 player.position 이 비어 있어 실제 출전 기록에서 가장 많이 나온 값을 쓴다.
_PLAYER_POSITION_SQL = """
    (SELECT s.position FROM playergamestat s
     WHERE s.player_id = p.player_id AND s.position IS NOT NULL
     GROUP BY s.position ORDER BY COUNT(*) DESC LIMIT 1)
"""


def _resolve_players(cur, keywords):
    """
    키워드를 선수로 확정한다. 별칭은 정확히 일치할 때만 받는다(팀 이름이 선수 별칭에 부분 일치해
    엉뚱한 선수가 잡히는 것을 막는다). 선수 이름·본명은 부분 일치도 받는다.
    """
    found = {}
    for kw in keywords:
        like = f"%{kw}%"
        cur.execute(
            f"""
            SELECT DISTINCT p.player_id, p.player_name, {_PLAYER_POSITION_SQL} AS position
            FROM player p
            LEFT JOIN entityalias ea ON ea.entity_id = p.entity_id
            WHERE p.player_name LIKE %s
               OR p.real_name LIKE %s
               OR ea.alias_name = %s
               OR ea.normalized_alias = %s
            LIMIT 5
            """,
            (like, like, kw, normalize_alias(kw)),
        )
        for row in cur.fetchall():
            found[row["player_id"]] = row
    return list(found.values())


def _resolve_teams(cur, keywords):
    """
    키워드를 팀으로 확정한다. 현재 이름은 부분 일치, 별칭(entityalias)과 옛 이름·약칭
    (teamnamehistory)은 정확히 일치할 때 받는다. 예: "T1" → 티원, "Gen.G" → 젠지 이스포츠.
    """
    found = {}
    for kw in keywords:
        like = f"%{kw}%"
        norm = normalize_alias(kw)
        cur.execute(
            """
            SELECT DISTINCT t.team_id, t.team_name
            FROM team t
            LEFT JOIN entityalias ea ON ea.entity_id = t.entity_id
            LEFT JOIN teamnamehistory th ON th.team_id = t.team_id
            WHERE t.team_name LIKE %s
               OR ea.alias_name = %s
               OR ea.normalized_alias = %s
               OR th.team_name = %s
               OR th.short_name = %s
            LIMIT 5
            """,
            (like, kw, norm, kw, kw),
        )
        for row in cur.fetchall():
            found[row["team_id"]] = row
    return list(found.values())


# =========================
# 2) 고정 통계 쿼리 (정형 질문)
# =========================

_YEAR = re.compile(r"(20\d{2})")


def question_date_range(question):
    """질문에 연도가 정확히 하나 있으면 그 해 전체 ("YYYY-01-01", "YYYY-12-31"), 아니면 None."""
    years = set(_YEAR.findall(str(question or "")))
    if len(years) != 1:
        return None
    y = years.pop()
    return (f"{y}-01-01", f"{y}-12-31")


def _date_clause(date_range, alias="m"):
    """`match` 별칭 기준 날짜 조건과 파라미터. 범위가 없으면 빈 조건."""
    if not date_range:
        return "", ()
    return f" AND {alias}.match_date BETWEEN %s AND %s", (date_range[0], f"{date_range[1]} 23:59:59")


def _range_label(date_range):
    """사실 문장 앞에 붙일 기간 표시. 한 해 전체면 "2025년", 아니면 "시작~끝"."""
    if not date_range:
        return ""
    s, e = date_range
    if s[:4] == e[:4] and s[5:] == "01-01" and e[5:] == "12-31":
        return f"{s[:4]}년 "
    return f"{s}~{e} "


def _player_overall_facts(cur, player, date_range=None):
    clause, params = _date_clause(date_range)
    cur.execute(
        f"""
        SELECT COUNT(*) AS games,
               ROUND(AVG(s.kills), 1)   AS avg_k,
               ROUND(AVG(s.deaths), 1)  AS avg_d,
               ROUND(AVG(s.assists), 1) AS avg_a,
               ROUND(AVG((s.kills + s.assists) / NULLIF(s.deaths, 0)), 2) AS kda,
               ROUND(AVG(s.cs), 0)   AS avg_cs,
               ROUND(AVG(s.gold), 0) AS avg_gold
        FROM playergamestat s
        JOIN game g ON g.game_id = s.game_id
        JOIN `match` m ON m.match_id = g.match_id
        WHERE s.player_id = %s{clause}
        """,
        (player["player_id"], *params),
    )
    row = cur.fetchone()
    if not row or not row["games"]:
        return []

    name = player["player_name"]
    pos = player.get("position") or "-"
    return [
        (
            f"(Player) {_range_label(date_range)}{name}[{pos}] — {row['games']}게임, 평균 KDA {row['kda']} "
            f"(K {row['avg_k']} / D {row['avg_d']} / A {row['avg_a']}), "
            f"평균 CS {row['avg_cs']}, 평균 골드 {row['avg_gold']}"
        )
    ]


def _player_recent_games_facts(cur, player, limit=5, date_range=None):
    clause, params = _date_clause(date_range)
    cur.execute(
        f"""
        SELECT c.champion_name, s.kills, s.deaths, s.assists, DATE(m.match_date) AS d,
               CASE WHEN g.winner_team_id = s.team_id THEN '승' ELSE '패' END AS result
        FROM playergamestat s
        JOIN game g ON g.game_id = s.game_id
        JOIN `match` m ON m.match_id = g.match_id
        LEFT JOIN champion c ON c.champion_id = s.champion_id
        WHERE s.player_id = %s{clause}
        ORDER BY m.match_date DESC, g.game_no DESC
        LIMIT %s
        """,
        (player["player_id"], *params, limit),
    )
    facts = []
    name = player["player_name"]
    for row in cur.fetchall():
        champ = row["champion_name"] or "?"
        facts.append(
            f"(Game) {row['d']} {name} — {champ} {row['kills']}/{row['deaths']}/{row['assists']} {row['result']}"
        )
    return facts


def _team_record_facts(cur, team, date_range=None):
    clause, params = _date_clause(date_range)
    cur.execute(
        f"""
        SELECT COUNT(*) AS matches,
               SUM(CASE WHEN m.winner_team_id = %s THEN 1 ELSE 0 END) AS wins
        FROM `match` m
        WHERE (m.team_a_id = %s OR m.team_b_id = %s){clause}
        """,
        (team["team_id"], team["team_id"], team["team_id"], *params),
    )
    row = cur.fetchone()
    if not row or not row["matches"]:
        return []

    wins = int(row["wins"] or 0)
    losses = int(row["matches"]) - wins
    return [
        f"(Team) {_range_label(date_range)}{team['team_name']} — 매치 {row['matches']}전 {wins}승 {losses}패"
    ]


_POSITION_ORDER = "FIELD(s.position, 'top', 'jng', 'mid', 'bot', 'sup')"


def _team_roster_facts(cur, team, date_range=None):
    """
    그 팀이 가장 최근에 경기한 해(범위가 있으면 범위 안의 마지막 해)에 실제로 출전한 선수 목록.
    여러 해를 합치면 이적한 선수까지 섞여 로스터처럼 읽히지 않는다.
    """
    clause2, params2 = _date_clause(date_range, alias="m2")
    cur.execute(
        f"""
        SELECT p.player_name, s.position, COUNT(*) AS games, y.yr
        FROM playergamestat s
        JOIN player p ON p.player_id = s.player_id
        JOIN game g ON g.game_id = s.game_id
        JOIN `match` m ON m.match_id = g.match_id
        JOIN (
            SELECT MAX(YEAR(m2.match_date)) AS yr
            FROM `match` m2 WHERE (m2.team_a_id = %s OR m2.team_b_id = %s){clause2}
        ) y ON YEAR(m.match_date) = y.yr
        WHERE s.team_id = %s
        GROUP BY p.player_name, s.position, y.yr
        ORDER BY {_POSITION_ORDER}, games DESC
        """,
        (team["team_id"], team["team_id"], *params2, team["team_id"]),
    )
    rows = cur.fetchall()
    if not rows:
        return []
    year = rows[0]["yr"]
    members = [f"{row['player_name']}({row['position'] or '-'}, {row['games']}게임)" for row in rows]
    return [f"(Team) {team['team_name']} {year}년 출전 선수: {', '.join(members)}"]


def _head_to_head_facts(cur, team_a, team_b, date_range=None, recent=5):
    """두 팀의 맞대결 매치 전적과 최근 맞대결 결과."""
    a, b = team_a["team_id"], team_b["team_id"]
    clause, params = _date_clause(date_range)
    cur.execute(
        f"""
        SELECT DATE(m.match_date) AS d, m.winner_team_id,
               CASE WHEN m.team_a_id = %s THEN m.score_a ELSE m.score_b END AS a_sets,
               CASE WHEN m.team_a_id = %s THEN m.score_b ELSE m.score_a END AS b_sets
        FROM `match` m
        WHERE ((m.team_a_id = %s AND m.team_b_id = %s) OR (m.team_a_id = %s AND m.team_b_id = %s)){clause}
        ORDER BY m.match_date DESC
        """,
        (a, a, a, b, b, a, *params),
    )
    rows = cur.fetchall()
    if not rows:
        return []
    a_name, b_name = team_a["team_name"], team_b["team_name"]
    a_wins = sum(1 for r in rows if r["winner_team_id"] == a)
    b_wins = sum(1 for r in rows if r["winner_team_id"] == b)
    a_sets = sum(int(r["a_sets"] or 0) for r in rows)
    b_sets = sum(int(r["b_sets"] or 0) for r in rows)
    facts = [
        f"(H2H) {_range_label(date_range)}{a_name} vs {b_name} — 맞대결 {len(rows)}매치, "
        f"{a_name} {a_wins}승 / {b_name} {b_wins}승, 세트 {a_sets}:{b_sets}"
    ]
    for r in rows[:recent]:
        winner = a_name if r["winner_team_id"] == a else b_name if r["winner_team_id"] == b else "?"
        facts.append(f"(H2H) {r['d']} {a_name} {r['a_sets']}:{r['b_sets']} {b_name} (승: {winner})")
    return facts


def _run_templates(cur, players, teams, date_range=None):
    facts = []
    if len(teams) >= 2:
        facts += _head_to_head_facts(cur, teams[0], teams[1], date_range)
    for player in players:
        facts += _player_overall_facts(cur, player, date_range)
        facts += _player_recent_games_facts(cur, player, date_range=date_range)
    for team in teams:
        facts += _team_record_facts(cur, team, date_range)
        facts += _team_roster_facts(cur, team, date_range)
    return facts


# =========================
# 3) Text-to-SQL 폴백
# =========================

RDB_SCHEMA_PROMPT = """
[espo 데이터베이스 스키마] (MySQL, LCK e스포츠 2024~2026)

league(league_id, league_name, region, description)
season(season_id, season_year, season_name, start_date, end_date)   -- season_year 예: 2024, 2025, 2026
tournament(tournament_id, league_id, tournament_name, season_id, split, start_date, end_date)
  - tournament_name 예: '2025 LCK Cup', '2025 LCK Rounds 1-2', '2024 LCK Summer'
tournamentstage(stage_id, tournament_id, stage_name, stage_order, start_date, end_date)
  - stage_name 은 'Regular' 또는 'Playoffs'
team(team_id, team_name, region, founded_year, description, is_active, entity_id)
  - team_name 은 한글 이름 (예: '티원', '젠지 이스포츠', '한화생명 이스포츠', 'KT 롤스터')
teamnamehistory(team_name_history_id, team_id, team_name, short_name, valid_from, valid_to)  -- 옛 이름·약칭
player(player_id, player_name, real_name, position, nationality, birth_date, is_active, entity_id)
  - player_name 은 한글 표기 (예: '페이커'). position 은 비어 있으니 playergamestat.position 을 써라
entityalias(alias_id, entity_id, alias_name, normalized_alias, language_code, alias_type, valid_from, valid_to)
  - 팀·선수·챔피언 별칭. team.entity_id / player.entity_id / champion.entity_id 와 조인
  - 예: 'T1'·'SKT T1' → 티원, 'Faker' → 페이커, 'Gen.G' → 젠지 이스포츠
teamroster(roster_id, team_id, player_id, start_date, end_date, role, roster_status, source_url)
  - roster_status 예: 'ACTIVE', 'CALLED_UP', 'LOAN'
staff(staff_id, staff_name, real_name, nationality, is_active, entity_id)
teamstafftenure(team_staff_tenure_id, team_id, staff_id, staff_role, start_date, end_date, source_url)
champion(champion_id, champion_name, role_type, description, entity_id, riot_champion_key, champion_name_en, release_patch_id)
  - champion_name 은 한글 (예: '아지르'), champion_name_en 은 영문
patch(patch_id, canonical_version, official_label, season_year, patch_order, released_at, notes_url, lifecycle_status)
`match`(match_id, tournament_id, stage_id, match_date, team_a_id, team_b_id, match_format, best_of,
        match_stage, winner_team_id, score_a, score_b)
  -- 주의: match 는 예약어이므로 반드시 백틱 `match` 로 표기
  -- team_a_id/team_b_id = 참가팀, winner_team_id = 승리팀, score_a/score_b = 세트 스코어
game(game_id, match_id, game_no, blue_team_id, red_team_id, winner_team_id, duration_seconds, patch_id, patch)
  -- 한 세트. 시즌 필터는 game → `match` → tournament → season 으로 조인
gameparticipant(participant_id, game_id, player_id, team_id, champion_id, side, position)
gamedraft(draft_id, game_id, team_id, champion_id, action_type, action_order)  -- action_type: 'PICK' 또는 'BAN'
playergamestat(player_game_stat_id, game_id, player_id, team_id, champion_id, position, side, result,
     kills, deaths, assists, cs, gold, damage_to_champions, damage_per_minute, damage_share,
     vision_score, wards_placed, wards_killed, cs_per_minute, earned_gold_per_minute,
     gold_at_15, xp_at_15, cs_at_15, gold_diff_at_15, xp_diff_at_15, cs_diff_at_15,
     first_blood_kill, double_kills, triple_kills, quadra_kills, penta_kills)
  -- 세트당 선수 1행. result 1=승, 0=패. position: 'top','jng','mid','bot','sup'
  -- KDA = (kills + assists) / NULLIF(deaths, 0)
teamgamestat(team_game_stat_id, game_id, team_id, side, result, total_kills, total_deaths,
     dragons, barons, towers, heralds, void_grubs, atakhans, inhibitors,
     first_dragon, first_baron, first_tower, first_blood, gspd, total_gold)
  -- 세트당 팀 1행. result 1=승, 0=패

[조인 경로] (이 외의 외래키는 없다)
- `match`.tournament_id = tournament.tournament_id, tournament.season_id = season.season_id
  (`match` 에는 season_id 가 없다. 시즌으로 거르려면 반드시 tournament 를 거쳐라.
   또는 YEAR(`match`.match_date) 로 연도를 거른다)
- `match`.stage_id = tournamentstage.stage_id
- game.match_id = `match`.match_id
- playergamestat.game_id / gameparticipant.game_id / gamedraft.game_id / teamgamestat.game_id = game.game_id
- player.entity_id / team.entity_id / champion.entity_id = entityalias.entity_id

[규칙]
- 팀·선수 이름은 영문·약칭으로 들어올 수 있다. team_name/player_name 만으로 찾지 말고
  entityalias.alias_name 또는 normalized_alias(소문자, 공백·마침표 제거)로도 찾아라.
- team.region 으로 팀을 거르지 마라.
- [질문에서 확인된 엔티티]로 team_id/player_id 가 주어지면 그 id 를 그대로 써라.
- 질문에 연도·대회가 있으면 tournament.tournament_name 이나 season.season_year 로 범위를 좁혀라.
- deaths 가 0일 수 있으니 KDA 계산 시 NULLIF(deaths,0) 사용.
- 반드시 단일 SELECT 문 하나만, MySQL 문법으로 작성.
"""

_FORBIDDEN_SQL = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|create|grant|"
    r"into\s+outfile|load_file)\b",
    re.IGNORECASE,
)


def _sanitize_sql(raw):
    """LLM이 만든 SQL을 SELECT 전용으로 검증·정리. 부적합하면 None."""
    if not raw:
        return None

    sql = re.sub(r"```(?:sql)?", "", raw, flags=re.IGNORECASE).strip()

    # 첫 번째 문장만 사용 (다중 쿼리 차단)
    sql = sql.split(";")[0].strip()

    if not re.match(r"^(select|with)\b", sql, re.IGNORECASE):
        return None

    if _FORBIDDEN_SQL.search(sql):
        return None

    if not re.search(r"\blimit\b", sql, re.IGNORECASE):
        sql += " LIMIT 50"

    return sql


def _format_rows(rows):
    facts = []
    for row in rows:
        parts = [f"{k}={v}" for k, v in row.items() if v is not None]
        if parts:
            facts.append("(RDB) " + ", ".join(parts))
    return facts


def _text_to_sql_facts(cur, question, entity_hint):
    # 순환 import 방지를 위해 함수 안에서 import
    from clova_extract import generate_sql_with_clova

    sql = generate_sql_with_clova(question, RDB_SCHEMA_PROMPT, entity_hint)
    safe_sql = _sanitize_sql(sql)

    print("DEBUG text-to-sql raw:", repr(sql))
    print("DEBUG text-to-sql safe:", repr(safe_sql))

    if not safe_sql:
        return [], None

    try:
        cur.execute(safe_sql)
        rows = cur.fetchmany(50)
    except Exception as e:  # noqa: BLE001
        print("DEBUG text-to-sql 실행 실패:", e)
        return [], safe_sql

    return _format_rows(rows), safe_sql


# =========================
# 집계형 질문 감지
# =========================

_AGGREGATE_HINTS = (
    "평균", "최다", "가장", "최고", "최소", "최저", "순위", "랭킹",
    "몇", "총", "합계", "비교", "누가", "제일", "top", "most", "best",
)


def _looks_aggregate(question):
    q = str(question).lower()
    return any(hint in q for hint in _AGGREGATE_HINTS)


# =========================
# 메인 함수
# =========================

def _empty_rdb_result(keywords=None):
    return {
        "keywords": keywords or [],
        "entities": {"players": [], "teams": []},
        "facts": [],
        "context": "",
        "sql": None,
    }


def search_rdb_knowledge(question, keywords, max_facts=40, date_range=None):
    """
    질문/키워드 기반으로 espo RDB에서 정형 사실을 조회한다.
    date_range 가 없으면 질문 속 연도(하나일 때)로 기간을 정한다. 고정 통계 쿼리에 적용된다.
    반환: {keywords, entities, facts(list[str]), context(str), sql}
    """
    kw_list = _as_keyword_list(keywords)
    date_range = date_range or question_date_range(question)
    print("DEBUG rdb keywords:", kw_list)
    print("DEBUG rdb date_range:", date_range)

    try:
        conn = get_connection()
    except Exception as e:  # noqa: BLE001
        print("DEBUG RDB 연결 실패:", e)
        return _empty_rdb_result(kw_list)

    facts = []
    sql_used = None
    players = []
    teams = []

    try:
        with conn.cursor() as cur:
            players = _resolve_players(cur, kw_list) if kw_list else []
            teams = _resolve_teams(cur, kw_list) if kw_list else []
            print("DEBUG rdb players:", [p["player_name"] for p in players])
            print("DEBUG rdb teams:", [t["team_name"] for t in teams])

            # 2) 엔티티가 잡히면 고정 통계 쿼리 실행
            if players or teams:
                facts += _run_templates(cur, players, teams, date_range)

            # 3) 폴백: 고정 쿼리로 못 채웠거나 집계형 질문이면 Text-to-SQL
            entity_hint = _build_entity_hint(players, teams)
            if not facts or _looks_aggregate(question):
                sql_facts, sql_used = _text_to_sql_facts(cur, question, entity_hint)
                facts += sql_facts
    finally:
        conn.close()

    # 중복 제거 + 상한
    facts = list(dict.fromkeys(facts))[:max_facts]
    context = "\n".join(f"{i}. {f}" for i, f in enumerate(facts, start=1))

    print("DEBUG rdb facts:", len(facts))

    return {
        "keywords": kw_list,
        "entities": {
            "players": [p["player_name"] for p in players],
            "teams": [t["team_name"] for t in teams],
        },
        "facts": facts,
        "context": context,
        "sql": sql_used,
    }


def _build_entity_hint(players, teams):
    hints = []
    for p in players:
        hints.append(f"선수 '{p['player_name']}' = player_id {p['player_id']}")
    for t in teams:
        hints.append(f"팀 '{t['team_name']}' = team_id {t['team_id']}")
    if not hints:
        return ""
    return "[질문에서 확인된 엔티티]\n" + "\n".join(hints)


if __name__ == "__main__":
    result = search_rdb_knowledge("페이커 평균 KDA 알려줘", ["Faker"])
    print("\n=== RDB context ===")
    print(result["context"])
    print("SQL:", result["sql"])
