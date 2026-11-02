"""
범위 되묻기 판정.

시즌·대회 범위가 빠진 질문에 바로 답하지 않고 한 번 되묻기 위한 순수 판정 함수와,
선택지를 MySQL 에서 읽는 함수를 둔다. 설계는 docs/specs/2026-11-03-clarify-design.md 3-4 절.
"""

import re

# 연도·시즌·대회를 가리키는 토큰. 하나라도 있으면 범위가 이미 있는 질문으로 본다.
SCOPE_TOKEN = re.compile(
    r"(20\d{2}|스프링|서머|spring|summer|cup|컵|라운드|rounds?|월즈|worlds|msi|플레이오프|playoffs?)",
    re.IGNORECASE,
)

AXES = ("tournament", "season")

PROMPTS = {
    "tournament": "어느 대회 기준으로 알아볼까요?",
    "season": "어느 시즌이 궁금하세요?",
}


def has_scope_token(question: str) -> bool:
    """질문 안에 연도·시즌·대회를 가리키는 토큰이 있으면 True."""
    return bool(SCOPE_TOKEN.search(question or ""))


def decide_clarification(question: str, intent_result: dict, options_fn) -> dict | None:
    """
    되묻기가 필요하면 {"axis", "prompt", "options"} 를, 아니면 None 을 돌려준다.
    조건 네 개가 모두 참일 때만 되묻는다:
      1. 질문에 범위 토큰이 없다
      2. intent_result["needs_scope"] 가 True
      3. intent_result["scope_axis"] 가 "tournament" 또는 "season"
      4. options_fn(axis) 가 비어 있지 않은 리스트를 돌려준다 (예외가 나면 None 취급)
    """
    if has_scope_token(question):
        return None
    if intent_result.get("needs_scope") is not True:
        return None
    axis = intent_result.get("scope_axis")
    if axis not in AXES:
        return None
    try:
        options = options_fn(axis)
    except Exception as e:  # noqa: BLE001
        print("DEBUG clarify options failed:", e)
        return None
    if not isinstance(options, list) or not options:
        return None
    return {"axis": axis, "prompt": PROMPTS[axis], "options": options}


def scope_options(axis: str) -> list[str]:
    """
    선택지를 MySQL(espo) 에서 최신순으로 읽는다. 연결·조회 실패는 빈 리스트다.
    (pymysql 은 import 시점 부담이 있어 지연 import)
    """
    queries = {
        "tournament": "SELECT tournament_name AS name FROM tournament ORDER BY tournament_id DESC",
        "season": "SELECT season_name AS name FROM season ORDER BY season_year DESC",
    }
    sql = queries.get(axis)
    if not sql:
        return []
    try:
        from mysql_connect import get_connection
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
                return [row["name"] for row in cur.fetchall() if row.get("name")]
        finally:
            conn.close()
    except Exception as e:  # noqa: BLE001
        print("DEBUG scope_options failed:", e)
        return []
