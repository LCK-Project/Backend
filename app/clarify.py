"""
범위 되묻기 판정.

범위가 빠진 질문에 바로 답하지 않고 한 번 되묻기 위한 순수 판정 함수와,
선택지를 MySQL 에서 읽는 함수를 둔다. 설계는 docs/specs/2026-11-03-clarify-design.md.

축(axis):
  tournament  대회      season  시즌(연도)   opponent  상대 팀
  stage       정규/플옵  champion 챔피언       patch     패치
  topic       무엇이 궁금한지(팀·선수 이름만 있을 때)
"""

import re

AXES = ("tournament", "season", "opponent", "stage", "champion", "patch", "topic")

# 시기를 뜻하는 축. "요즘·최근" 같은 표현이 있으면 이 축으로는 되묻지 않는다.
TIME_AXES = ("tournament", "season", "patch")

# 연도·시즌·대회를 가리키는 토큰. 하나라도 있으면 시기 범위가 이미 있는 질문으로 본다.
EXPLICIT_SCOPE_TOKEN = re.compile(
    r"(20\d{2}|스프링|서머|spring|summer|cup|컵|라운드|rounds?|월즈|worlds|msi|플레이오프|playoffs?)",
    re.IGNORECASE,
)

# "가장 최근"을 뜻하는 표현. 되묻지 않고 최신 시즌으로 좁혀서 답한다.
RECENT_TOKEN = re.compile(r"(요즘|최근|현재|지금|올해|이번)")

YEAR_TOKEN = re.compile(r"20\d{2}")

# 하위 호환용 이름. 둘 중 하나라도 있으면 시기 범위가 있는 질문이다.
SCOPE_TOKEN = re.compile(f"{EXPLICIT_SCOPE_TOKEN.pattern}|{RECENT_TOKEN.pattern}", re.IGNORECASE)

STAGE_TOKEN = re.compile(r"(정규|플레이오프|playoffs?|regular|결승|final)", re.IGNORECASE)
PATCH_TOKEN = re.compile(r"(패치|patch|\b\d{2}\.\d{1,2}\b)", re.IGNORECASE)

PROMPTS = {
    "tournament": "어느 대회 기준으로 알아볼까요?",
    "season": "어느 시즌이 궁금하세요?",
    "opponent": "어느 팀과의 전적인가요?",
    "stage": "정규 시즌과 플레이오프 중 어디가 궁금하세요?",
    "champion": "어느 챔피언 기준인가요?",
    "patch": "어느 패치 기준인가요?",
    "topic": "{subject}의 무엇이 궁금하세요?",
}
TOPIC_PROMPT_NO_SUBJECT = "무엇이 궁금하세요?"

# 프론트가 선택지를 고른 뒤 원래 질문에 붙일 형식. {question} 과 {option} 자리만 쓴다.
TEMPLATES = {
    "tournament": "{question} ({option} 기준)",
    "season": "{question} ({option} 시즌 기준)",
    "opponent": "{question} ({option} 상대 기준)",
    "stage": "{question} ({option} 기준)",
    "champion": "{question} ({option} 챔피언 기준)",
    "patch": "{question} ({option} 패치 기준)",
    "topic": "{question} ({option} 중심으로)",
}

# topic 축의 고정 선택지. 팀·선수 이름만 던졌을 때 무엇이 궁금한지 고르게 한다.
TOPICS = {
    "team": ["성적", "로스터", "전략", "최근 소식"],
    "player": ["챔피언", "성적", "소속 이력", "최근 기사"],
    None: ["성적", "전략", "최근 소식"],
}

STAGE_LABELS = {"Regular": "정규 시즌", "Playoffs": "플레이오프"}


def has_scope_token(question: str) -> bool:
    """질문 안에 연도·시즌·대회 토큰이나 최근 표현이 있으면 True (시기 범위가 있는 질문)."""
    return bool(SCOPE_TOKEN.search(question or ""))


def has_recent_token(question: str) -> bool:
    """"요즘·최근·현재·지금·올해·이번" 처럼 가장 최근을 뜻하는 표현이 있으면 True."""
    return bool(RECENT_TOKEN.search(question or ""))


def already_scoped(question: str, axis: str) -> bool:
    """
    그 축의 범위가 질문에 이미 적혀 있으면 True. LLM 이 되묻자고 해도 규칙이 막는다.
    opponent·champion·topic 은 질문만 봐서는 알 수 없으므로 LLM 판단에 맡긴다.
    """
    q = question or ""
    if axis in ("tournament", "season"):
        return has_scope_token(q)
    if axis == "patch":
        return has_scope_token(q) or bool(PATCH_TOKEN.search(q))
    if axis == "stage":
        return bool(STAGE_TOKEN.search(q))
    return False


def refine_recent_question(question: str, latest_season: str | None) -> str:
    """
    최근 표현이 있고 연도가 없는 질문에 최신 시즌을 붙인다. 그 외엔 그대로 돌려준다.
    예: "요즘 메타 어때?" + "2026" → "요즘 메타 어때? (2026 시즌 기준)"
    """
    if not latest_season or not has_recent_token(question) or YEAR_TOKEN.search(question or ""):
        return question
    return f"{question} ({latest_season} 시즌 기준)"


def decide_clarification(question: str, intent_result: dict, options_fn) -> dict | None:
    """
    되묻기가 필요하면 {"axis", "prompt", "options", "template"} 를, 아니면 None 을 돌려준다.
    조건 네 개가 모두 참일 때만 되묻는다:
      1. intent_result["needs_scope"] 가 True
      2. intent_result["scope_axis"] 가 AXES 안에 있다
      3. already_scoped(question, axis) 가 False
      4. options_fn(axis, subject, subject_type) 가 비어 있지 않은 리스트다 (예외는 None 취급)
    """
    if intent_result.get("needs_scope") is not True:
        return None
    axis = intent_result.get("scope_axis")
    if axis not in AXES:
        return None
    if already_scoped(question, axis):
        return None

    subject = intent_result.get("subject") or None
    subject_type = intent_result.get("subject_type")
    if subject_type not in ("team", "player"):
        subject_type = None

    try:
        options = options_fn(axis, subject, subject_type)
    except Exception as e:  # noqa: BLE001
        print("DEBUG clarify options failed:", e)
        return None
    if not isinstance(options, list) or not options:
        return None

    if axis == "topic":
        prompt = PROMPTS["topic"].format(subject=subject) if subject else TOPIC_PROMPT_NO_SUBJECT
    else:
        prompt = PROMPTS[axis]
    return {"axis": axis, "prompt": prompt, "options": options, "template": TEMPLATES[axis]}


# ---------- 선택지 (MySQL) ----------

def _query(sql, params=()):
    """한 번 연결해 rows(dict) 를 돌려준다. 실패는 호출자가 처리한다. pymysql 은 지연 import."""
    from app.db.mysql_connect import get_connection
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    finally:
        conn.close()


def _names(rows, key="name"):
    return [row[key] for row in rows if row.get(key)]


def _player_ids(subject):
    """subject 와 이름·별칭이 닿는 선수 id 목록."""
    like = f"%{subject}%"
    rows = _query(
        """
        SELECT DISTINCT p.player_id
        FROM player p
        LEFT JOIN entityalias ea ON ea.entity_id = p.entity_id
        WHERE p.player_name LIKE %s OR p.real_name LIKE %s OR ea.alias_name LIKE %s
        LIMIT 5
        """,
        (like, like, like),
    )
    return [row["player_id"] for row in rows]


def _subject_team_names(subject):
    """subject 와 이름·별칭이 닿는 팀의 team_name 집합. 조회 실패는 빈 집합."""
    like = f"%{subject}%"
    try:
        rows = _query(
            """
            SELECT DISTINCT t.team_name AS name
            FROM team t
            LEFT JOIN entityalias ea ON ea.entity_id = t.entity_id
            WHERE t.team_name LIKE %s OR ea.alias_name LIKE %s OR ea.normalized_alias LIKE %s
            """,
            (like, like, like.lower()),
        )
        return set(_names(rows))
    except Exception as e:  # noqa: BLE001
        print("DEBUG subject team lookup failed:", e)
        return set()


def scope_options(axis: str, subject: str | None = None, subject_type: str | None = None) -> list[str]:
    """
    축별 선택지. DB 에 실제 있는 이름만 돌려준다. 연결·조회 실패는 빈 리스트다.
    topic 은 고정 목록이라 DB 를 보지 않는다.
    """
    if axis == "topic":
        return list(TOPICS.get(subject_type) or TOPICS[None])

    try:
        if axis == "tournament":
            return _names(_query("SELECT tournament_name AS name FROM tournament ORDER BY tournament_id DESC"))

        if axis == "season":
            return _names(_query("SELECT season_name AS name FROM season ORDER BY season_year DESC"))

        if axis == "opponent":
            rows = _query("SELECT team_name AS name FROM team WHERE is_active = 1 ORDER BY team_name")
            names = _names(rows)
            if subject:
                # 질문의 주체 팀은 상대 선택지에서 뺀다. "T1" ↔ "티원" 처럼 표기가 달라도
                # 별칭 테이블로 같은 팀을 찾고, 그래도 못 찾으면 이름 포함 관계로 느슨하게 뺀다.
                excluded = _subject_team_names(subject)
                names = [n for n in names if n not in excluded and subject not in n and n not in subject]
            return names

        if axis == "stage":
            rows = _query("SELECT DISTINCT stage_name AS name FROM tournamentstage ORDER BY stage_name DESC")
            return [STAGE_LABELS.get(n, n) for n in _names(rows)]

        if axis == "champion":
            ids = _player_ids(subject) if subject else []
            if ids:
                marks = ",".join(["%s"] * len(ids))
                rows = _query(
                    f"""
                    SELECT c.champion_name AS name, COUNT(*) AS n
                    FROM gameparticipant gp JOIN champion c ON c.champion_id = gp.champion_id
                    WHERE gp.player_id IN ({marks})
                    GROUP BY c.champion_name ORDER BY n DESC, c.champion_name LIMIT 10
                    """,
                    tuple(ids),
                )
            else:
                rows = _query(
                    """
                    SELECT c.champion_name AS name, COUNT(*) AS n
                    FROM gameparticipant gp JOIN champion c ON c.champion_id = gp.champion_id
                    GROUP BY c.champion_name ORDER BY n DESC, c.champion_name LIMIT 10
                    """
                )
            return _names(rows)

        if axis == "patch":
            rows = _query(
                "SELECT COALESCE(official_label, canonical_version) AS name FROM patch "
                "ORDER BY season_year DESC, patch_order DESC, patch_id DESC LIMIT 8"
            )
            return _names(rows)
    except Exception as e:  # noqa: BLE001
        print("DEBUG scope_options failed:", e)
        return []
    return []


# ---------- 고른 범위를 검색에 적용 ----------

def _year_range(year) -> tuple[str, str] | None:
    try:
        y = int(str(year)[:4])
    except (TypeError, ValueError):
        return None
    return (f"{y}-01-01", f"{y}-12-31")


def scope_date_range(scope: dict | None) -> tuple[str, str] | None:
    """
    프론트가 보낸 scope {"axis", "value"} 를 경기·기사 날짜 범위 ("YYYY-MM-DD", "YYYY-MM-DD") 로 바꾼다.
      season     → 그 해 전체
      tournament → tournamentstage 의 가장 이른 start_date ~ 가장 늦은 end_date. 없으면 이름 앞의 연도
      patch      → 그 패치의 season_year 전체 (패치 단위 경기 날짜는 아직 데이터에 없다)
      그 외       → None (opponent·stage·champion·topic 은 날짜 범위가 아니다)
    DB 실패는 이름의 연도로 대신하고, 그것도 없으면 None.
    """
    if not scope or not isinstance(scope, dict):
        return None
    axis, value = scope.get("axis"), scope.get("value")
    if not value:
        return None

    if axis == "season":
        return _year_range(value)

    if axis == "tournament":
        try:
            rows = _query(
                """
                SELECT MIN(ts.start_date) AS s, MAX(ts.end_date) AS e
                FROM tournament t JOIN tournamentstage ts ON ts.tournament_id = t.tournament_id
                WHERE t.tournament_name = %s
                """,
                (value,),
            )
            if rows and rows[0].get("s") and rows[0].get("e"):
                return (str(rows[0]["s"])[:10], str(rows[0]["e"])[:10])
        except Exception as e:  # noqa: BLE001
            print("DEBUG scope_date_range failed:", e)
        m = YEAR_TOKEN.search(str(value))
        return _year_range(m.group(0)) if m else None

    if axis == "patch":
        try:
            rows = _query(
                "SELECT season_year FROM patch WHERE official_label = %s OR canonical_version = %s LIMIT 1",
                (value, value),
            )
            if rows and rows[0].get("season_year"):
                return _year_range(rows[0]["season_year"])
        except Exception as e:  # noqa: BLE001
            print("DEBUG scope_date_range failed:", e)
        return None

    return None


# 질문에서 연도로 읽을 네 자리 수. 앞뒤에 숫자가 붙은 것("20000 골드" 의 2000)은 연도가 아니다.
QUESTION_YEAR = re.compile(r"(?<!\d)20\d{2}(?!\d)")


def question_date_range(question: str) -> tuple[str, str] | None:
    """
    질문에 적힌 연도를 날짜 범위로 바꾼다. "2024 티원 전략" → ("2024-01-01", "2024-12-31").
    연도가 여러 개면 가장 이른 해의 첫날부터 가장 늦은 해의 마지막 날까지다. 연도가 없으면 None.
    되묻기를 거치지 않은 질문도 적힌 연도 밖의 경기·기사가 섞이지 않게 하려고 쓴다.
    """
    years = sorted(int(y) for y in QUESTION_YEAR.findall(question or ""))
    if not years:
        return None
    return (f"{years[0]}-01-01", f"{years[-1]}-12-31")


def scope_keywords(scope: dict | None) -> list[str]:
    """상대 팀·챔피언처럼 그래프 검색 키워드로 쓸 수 있는 범위 값. 그 외 축은 빈 리스트."""
    if not scope or not isinstance(scope, dict):
        return []
    if scope.get("axis") in ("opponent", "champion") and scope.get("value"):
        return [str(scope["value"])]
    return []


def latest_season() -> str | None:
    """가장 최근 시즌 이름(예: "2026"). 연결·조회 실패는 None."""
    options = scope_options("season")
    return options[0] if options else None
