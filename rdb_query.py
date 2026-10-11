"""
RDB(espo) 기반 정형 데이터 검색 - 하이브리드 방식.

흐름:
  키워드
   └→ 1) 엔티티 확정: player/team + 별칭(playeralias/teamalias) 매칭
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

def _resolve_players(cur, keywords):
    found = {}
    for kw in keywords:
        like = f"%{kw}%"
        cur.execute(
            """
            SELECT DISTINCT p.player_id, p.player_name, p.position
            FROM player p
            LEFT JOIN playeralias pa ON pa.player_id = p.player_id
            WHERE p.player_name LIKE %s
               OR p.real_name LIKE %s
               OR pa.alias_name LIKE %s
            LIMIT 5
            """,
            (like, like, like),
        )
        for row in cur.fetchall():
            found[row["player_id"]] = row
    return list(found.values())


def _resolve_teams(cur, keywords):
    found = {}
    for kw in keywords:
        like = f"%{kw}%"
        cur.execute(
            """
            SELECT DISTINCT t.team_id, t.team_name
            FROM team t
            LEFT JOIN teamalias ta ON ta.team_id = t.team_id
            WHERE t.team_name LIKE %s
               OR ta.alias_name LIKE %s
            LIMIT 5
            """,
            (like, like),
        )
        for row in cur.fetchall():
            found[row["team_id"]] = row
    return list(found.values())


# =========================
# 2) 고정 통계 쿼리 (정형 질문)
# =========================

def _player_overall_facts(cur, player):
    cur.execute(
        """
        SELECT COUNT(*) AS games,
               ROUND(AVG(kills), 1)   AS avg_k,
               ROUND(AVG(deaths), 1)  AS avg_d,
               ROUND(AVG(assists), 1) AS avg_a,
               ROUND(AVG((kills + assists) / NULLIF(deaths, 0)), 2) AS kda,
               ROUND(AVG(cs), 0)   AS avg_cs,
               ROUND(AVG(gold), 0) AS avg_gold
        FROM playergamestat
        WHERE player_id = %s
        """,
        (player["player_id"],),
    )
    row = cur.fetchone()
    if not row or not row["games"]:
        return []

    name = player["player_name"]
    pos = player.get("position") or "-"
    return [
        (
            f"(Player) {name}[{pos}] — {row['games']}게임, 평균 KDA {row['kda']} "
            f"(K {row['avg_k']} / D {row['avg_d']} / A {row['avg_a']}), "
            f"평균 CS {row['avg_cs']}, 평균 골드 {row['avg_gold']}"
        )
    ]


def _player_recent_games_facts(cur, player, limit=5):
    cur.execute(
        """
        SELECT c.champion_name, s.kills, s.deaths, s.assists,
               CASE WHEN g.winner_team_id = s.team_id THEN '승' ELSE '패' END AS result
        FROM playergamestat s
        JOIN game g ON g.game_id = s.game_id
        LEFT JOIN champion c ON c.champion_id = s.champion_id
        WHERE s.player_id = %s
        ORDER BY g.game_id DESC
        LIMIT %s
        """,
        (player["player_id"], limit),
    )
    facts = []
    name = player["player_name"]
    for row in cur.fetchall():
        champ = row["champion_name"] or "?"
        facts.append(
            f"(Game) {name} — {champ} {row['kills']}/{row['deaths']}/{row['assists']} {row['result']}"
        )
    return facts


def _team_record_facts(cur, team):
    cur.execute(
        """
        SELECT COUNT(*) AS matches,
               SUM(CASE WHEN m.winner_team_id = %s THEN 1 ELSE 0 END) AS wins
        FROM `match` m
        WHERE m.team_a_id = %s OR m.team_b_id = %s
        """,
        (team["team_id"], team["team_id"], team["team_id"]),
    )
    row = cur.fetchone()
    if not row or not row["matches"]:
        return []

    wins = int(row["wins"] or 0)
    losses = int(row["matches"]) - wins
    return [
        f"(Team) {team['team_name']} — 매치 {row['matches']}전 {wins}승 {losses}패"
    ]


def _team_roster_facts(cur, team):
    # teamroster 테이블이 비어 있어 실제 출전(playergamestat) 기준으로 선수 목록을 만든다.
    cur.execute(
        """
        SELECT DISTINCT p.player_name, p.position
        FROM playergamestat s
        JOIN player p ON p.player_id = s.player_id
        WHERE s.team_id = %s
        ORDER BY p.position
        """,
        (team["team_id"],),
    )
    members = [
        f"{row['player_name']}({row['position'] or '-'})" for row in cur.fetchall()
    ]
    if not members:
        return []
    return [f"(Team) {team['team_name']} 출전 선수: {', '.join(members)}"]


def _run_templates(cur, players, teams):
    facts = []
    for player in players:
        facts += _player_overall_facts(cur, player)
        facts += _player_recent_games_facts(cur, player)
    for team in teams:
        facts += _team_record_facts(cur, team)
        facts += _team_roster_facts(cur, team)
    return facts


# =========================
# 3) Text-to-SQL 폴백
# =========================

RDB_SCHEMA_PROMPT = """
[espo 데이터베이스 스키마] (MySQL, LCK e스포츠)

league(league_id, league_name, region, description)
tournament(tournament_id, league_id, tournament_name, season_year, split, start_date, end_date)
  - split 예: 'Spring','Summer'
team(team_id, team_name, region, founded_year, description, is_active)
teamalias(team_alias_id, team_id, alias_name, alias_type)  -- 팀 별칭
player(player_id, player_name, real_name, position, nationality, birth_date, is_active)
  - position 예: 'top','jng','mid','bot','sup'
playeralias(player_alias_id, player_id, alias_name, alias_type)  -- 선수 별칭
champion(champion_id, champion_name, role_type, description)
`match`(match_id, tournament_id, match_date, team_a_id, team_b_id, match_format,
        match_stage, winner_team_id, score_a, score_b)
  -- 주의: match 는 예약어이므로 반드시 백틱 `match` 로 표기
  -- team_a_id/team_b_id = 참가팀, winner_team_id = 승리팀, score_a/score_b = 세트 스코어
game(game_id, match_id, game_no, blue_team_id, red_team_id, winner_team_id,
     duration_seconds, external_game_id, patch, url)
playergamestat(player_game_stat_id, game_id, player_id, team_id, champion_id,
     kills, deaths, assists, cs, gold, side, position,
     deaths_at_15, gold_at_15, xp_at_15, cs_at_15, gold_diff_at_15,
     xp_diff_at_15, cs_diff_at_15, damage_to_champions, vision_score,
     wards_placed, wards_killed)
  -- 게임당 선수 1행. KDA = (kills + assists) / deaths
teamgamestat(team_game_stat_id, game_id, team_id, total_kills, total_deaths,
     dragons, barons, towers, total_gold, void_grubs, atakhans, heralds,
     inhibitors, first_dragon, first_baron, first_tower)

[규칙]
- 선수/팀 이름은 player.player_name, team.team_name 뿐 아니라
  playeralias.alias_name, teamalias.alias_name 으로도 검색할 것.
- team.region 은 'Korea' 같은 국가명이다. 'LCK' 같은 리그명이 아니므로
  팀을 region 으로 거르지 마라. 팀은 team_name/teamalias 로만 식별하라.
- [질문에서 확인된 엔티티]로 team_id/player_id 가 주어지면 그 id 를 그대로 써라.
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


def search_rdb_knowledge(question, keywords, max_facts=40):
    """
    질문/키워드 기반으로 espo RDB에서 정형 사실을 조회한다.
    반환: {keywords, entities, facts(list[str]), context(str), sql}
    """
    kw_list = _as_keyword_list(keywords)
    print("DEBUG rdb keywords:", kw_list)

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
                facts += _run_templates(cur, players, teams)

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
