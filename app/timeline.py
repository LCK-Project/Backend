"""
날짜 스트립용 대회 띠.

/ask 응답의 그래프에 담긴 경기 날짜 범위와 겹치는 대회를 MySQL 에서 읽어
{"tournaments": [{"name", "start", "end"}]} 로 돌려준다.
설계는 Frontend/docs/specs/2026-11-12-range-strip-design.md 4절.
"""

# 대회의 시작·끝은 tournament.start_date 가 아니라 실제 경기 날짜로 구한다.
# 스트립의 경기 점이 항상 띠 안에 들어오게 하기 위해서다.
TOURNAMENT_SPAN_SQL = """
SELECT t.tournament_name AS name, MIN(m.match_date) AS s, MAX(m.match_date) AS e
FROM `match` m JOIN tournament t ON t.tournament_id = m.tournament_id
WHERE m.match_date IS NOT NULL
GROUP BY t.tournament_id, t.tournament_name
HAVING s <= %s AND e >= %s
ORDER BY s
"""


def _query(sql, params=()):
    """한 번 연결해 rows(dict) 를 돌려준다. pymysql 은 지연 import."""
    from app.db.mysql_connect import get_connection
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    finally:
        conn.close()


def graph_date_span(graph: dict | None) -> tuple[str, str] | None:
    """그래프의 날짜 있는 Match 노드 최소일·최대일 ("YYYY-MM-DD", "YYYY-MM-DD"). 없으면 None."""
    dates = sorted(
        node["match_date"][:10]
        for node in (graph or {}).get("nodes", [])
        if node.get("label") == "Match" and isinstance(node.get("match_date"), str) and node["match_date"]
    )
    if not dates:
        return None
    return (dates[0], dates[-1])


def build_timeline(graph: dict | None) -> dict:
    """그래프의 경기 기간과 겹치는 대회 띠. 경기가 없거나 조회가 실패하면 빈 목록이다."""
    span = graph_date_span(graph)
    if not span:
        return {"tournaments": []}
    try:
        rows = _query(TOURNAMENT_SPAN_SQL, (f"{span[1]} 23:59:59", span[0]))
    except Exception as e:  # noqa: BLE001
        print("DEBUG timeline failed:", e)
        return {"tournaments": []}
    return {
        "tournaments": [
            {"name": row["name"], "start": str(row["s"])[:10], "end": str(row["e"])[:10]}
            for row in rows
            if row.get("name") and row.get("s") and row.get("e")
        ]
    }
