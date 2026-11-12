import os
import re

from app.db.connect import get_driver
from app.common.text_utils import clean_text
from app.common.graph_schema_config import VISUAL_EXCLUDED_LABELS, VISUAL_EXCLUDED_RELATIONS

print("### LOADED neo4j_query.py ###", os.path.abspath(__file__))


# =========================
# 표시용 유틸
# =========================

def _node_name(node):
    return clean_text(_raw_node_name(node))


def _raw_node_name(node):
    return (
        node.get("display_name")
        or node.get("name")
        or node.get("canonical_name")
        or node.get("entity_text")
        or node.get("team_name")
        or node.get("player_name")
        or node.get("champion_name")
        or node.get("league_name")
        or node.get("tournament_name")
        or node.get("title")
        or node.get("alias_name")
        or "unknown"
    )


def _node_label(node):
    labels = list(node.labels)

    priority = [
        "Team",
        "Player",
        "Champion",
        "League",
        "Tournament",
        "Match",
        "Staff",
        "Coach",
        "Objective",
        "Object",
        "Game",
        "Entity",
    ]

    for label in priority:
        if label in labels:
            return label

    return node.get("entity_type") or node.get("type") or (labels[0] if labels else "Node")


# Match 노드가 시각화 응답의 props 로 내보내는 키. 다른 키는 섞지 않는다.
MATCH_PROP_KEYS = (
    "match_stage",
    "score_a",
    "score_b",
    "best_of",
    "team_a_key",
    "team_b_key",
    "winner_key",
)


def build_match_name(props: dict) -> str:
    """Match 노드에는 name 계열 속성이 없어 팀 키와 날짜로 표시명을 만든다."""
    a = props.get("team_a_key")
    b = props.get("team_b_key")
    date = (props.get("match_date") or "")[:10]

    if a and b:
        name = f"{a.removeprefix('TEAM_')} vs {b.removeprefix('TEAM_')}"
        return f"{name} · {date}" if date else name

    if date:
        return f"경기 · {date}"

    return props.get("match_key") or "경기"


def node_to_dict(node, is_seed: bool) -> dict:
    """시각화 응답의 노드 dict. degree 는 0으로 두고 간선을 다 모은 뒤 채운다."""
    label = _node_label(node)

    if label == "Match":
        name = build_match_name({key: node.get(key) for key in (*MATCH_PROP_KEYS, "match_date", "match_key")})
        match_date = (node.get("match_date") or "")[:10] or None
        props = {key: node.get(key) for key in MATCH_PROP_KEYS if node.get(key) is not None}
    else:
        name = _node_name(node)
        match_date = None
        props = {}

    return {
        "id": str(node.element_id),
        "name": name,
        "label": label,
        "degree": 0,
        "is_seed": is_seed,
        "match_date": match_date,
        "props": props,
    }


def _relation_name(rel):
    return rel.type or rel.get("relation_type") or rel.get("type") or "RELATED"


# =========================
# 질문 키워드 추출
# =========================

STOPWORDS = {
    "알려줘", "보여줘", "설명해줘", "분석해줘", "찾아줘", "정리해줘",
    "말해줘", "해줘", "줘",
    "관련", "관련된", "내용", "정보", "데이터", "그래프", "관계",
    "결과", "질문", "답변",
    "어떻게", "왜", "뭐", "무엇", "누가", "언제", "어디서", "어떤",
    "은", "는", "이", "가", "을", "를", "의", "에", "에서", "으로", "로",
    "와", "과", "도", "만", "에게", "한테", "그리고", "또는",
}


def _normalize_text(text):
    text = str(text).lower().strip()
    text = re.sub(r"[?!,:;()\[\]{}\"']", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


NUMERIC_KEYWORD = re.compile(r"\d+(년|월|일)?")


def _extract_keywords(keywords):
    if isinstance(keywords, str):
        raw_texts = [keywords]
    elif isinstance(keywords, list):
        raw_texts = keywords
    else:
        raw_texts = []

    result = []

    for text in raw_texts:
        text = _normalize_text(text)

        if not text:
            continue

        # 짧은 원문은 후보로 유지
        if 2 <= len(text) <= 20 and text not in STOPWORDS:
            result.append(text)
            if "." in text:
                result.append(text.replace(".", ""))

        # 조사 제거용 단순 치환
        for particle in [
            "에서", "으로", "에게", "한테",
            "은", "는", "이", "가", "을", "를", "의", "에", "로", "와", "과", "도", "만",
        ]:
            text = text.replace(particle, " ")

        for token in text.split():
            token = token.strip().strip(".")

            if not token:
                continue

            if len(token) < 2:
                continue

            if token in STOPWORDS:
                continue

            result.append(token)
            if "." in token:
                result.append(token.replace(".", ""))

    # 숫자뿐인 키워드("2024", "2024년")는 뺀다. 경기 노드 이름이 "2024-01-25 젠지 vs 브리온" 처럼
    # 날짜로 시작해서, 연도가 키워드로 들어가면 그 해의 아무 경기나 시드로 잡혀 질문과 무관한 팀이 딸려 온다.
    # 연도는 키워드가 아니라 날짜 범위(date_range)로 적용한다.
    return [kw for kw in dict.fromkeys(result) if not NUMERIC_KEYWORD.fullmatch(kw)]


# =========================
# 그래프 조회 Cypher
# =========================

EXCLUDED_RELATIONS = VISUAL_EXCLUDED_RELATIONS
EXCLUDED_LABELS = VISUAL_EXCLUDED_LABELS


# 시드(질문의 핵심 노드) 찾기.
#
# 후보는 :Entity 라벨이 붙은 개체(팀·선수·챔피언·스태프·대회·오브젝트 등)뿐이다. 경기·팬 댓글·팬 영상은
# 이름에 팀 이름이나 댓글 본문이 들어 있어 후보에 넣으면 "젠지" 한 단어에 경기 125개가 시드로 잡힌다.
# 이런 노드는 시드의 이웃으로만 그래프에 나온다.
#
# 이름·별칭이 키워드와 정확히 같을 때만 시드로 본다(소문자, 공백 제거 후 비교). 부분 포함으로 찾으면
# "kt" 가 "Renekton"·"Viktor"·"SKT T1" 에 걸린다. 정확히 같은 것이 하나도 없을 때만 부분 포함으로 물러난다.
SEED_NAME_LIST = """[n.name, n.canonical_ko, n.canonical_en, n.display_name, n.player_name,
     n.champion_name, n.champion_name_en] + coalesce(n.aliases, [])"""

SEED_EXACT_CYPHER = f"""
MATCH (n:Entity)
WHERE none(label IN labels(n) WHERE label IN $excluded_labels)
AND any(c IN {SEED_NAME_LIST} WHERE c IS NOT NULL AND replace(toLower(c), ' ', '') IN $keys)
RETURN elementId(n) AS id
"""

SEED_CONTAINS_CYPHER = f"""
MATCH (n:Entity)
WHERE none(label IN labels(n) WHERE label IN $excluded_labels)
AND any(c IN {SEED_NAME_LIST} WHERE c IS NOT NULL
        AND any(k IN $keys WHERE replace(toLower(c), ' ', '') CONTAINS k))
RETURN elementId(n) AS id
"""

# 구조·클레임 두 쿼리가 같은 시드를 쓰도록 찾아 둔 시드 id 로만 거른다.
SEED_WHERE = "WHERE elementId(n) IN $seed_ids"


def seed_keys(keywords: list[str]) -> list[str]:
    """시드 비교용 키. 소문자화된 키워드에서 공백을 빼고 중복을 없앤다."""
    return list(dict.fromkeys(kw.replace(" ", "") for kw in keywords if kw.replace(" ", "")))


def find_seed_ids(session, keywords: list[str]) -> list[str]:
    """정확 일치로 시드를 찾고, 하나도 없으면 부분 포함으로 다시 찾는다."""
    params = {"keys": seed_keys(keywords), "excluded_labels": EXCLUDED_LABELS}
    if not params["keys"]:
        return []
    ids = [row["id"] for row in session.run(SEED_EXACT_CYPHER, **params)]
    if ids:
        return ids
    print("DEBUG no exact seed, falling back to contains:", params["keys"])
    return [row["id"] for row in session.run(SEED_CONTAINS_CYPHER, **params)]


# 시드 하나의 구조 간선을 관계 타입별로 이만큼만 가져와 LIMIT 안에서 매치·소속·코치 관계가 고루 들어가게 한다.
STRUCTURE_PER_TYPE_LIMIT = 20


# 1) 구조 간선. Game·ArticleClaim 은 제외 라벨로, 클레임 연결 관계는 제외 관계로 빠진다.
# 같은 (n, 타입, m) 의 중복 관계는 하나로 접고, 타입별 상한을 건 뒤 전체 LIMIT 를 건다.
# 날짜 범위가 있으면 범위 밖 경기는 상한을 걸기 전에 뺀다. 뒤에서 빼면 타입별 상한 20건이
# 다른 해의 경기로 채워져 정작 그 해의 경기가 몇 개 남지 않는다.
KEYWORD_CYPHER = f"""
MATCH (n)
{SEED_WHERE}
MATCH (n)-[r]-(m)
WHERE NOT type(r) IN $excluded_relations
AND none(label IN labels(m) WHERE label IN $excluded_labels)
AND ($date_start IS NULL OR NOT m:Match OR m.match_date IS NULL
     OR ($date_start <= substring(m.match_date, 0, 10) AND substring(m.match_date, 0, 10) <= $date_end))
WITH n, type(r) AS rel_type, m, collect(r) AS rs
ORDER BY coalesce(m.match_date, '') DESC
WITH n, rel_type, collect({{
    r: head(rs), m: m,
    spans: [x IN rs | [x.start_date, x.end_date]],
    game_keys: [x IN rs WHERE x.game_key IS NOT NULL | x.game_key]
}}) AS found
WITH n, found, CASE WHEN rel_type IN $match_types THEN $per_match ELSE $per_type END AS cap
WITH n, CASE
    WHEN size(found) <= cap OR NOT $spread THEN found[0..cap]
    ELSE [i IN range(0, cap - 1) | found[toInteger(i * size(found) / cap)]]
END AS items
UNWIND items AS item
RETURN n, item.r AS r, item.m AS m, startNode(item.r) AS source, endNode(item.r) AS target,
       item.spans AS spans, item.game_keys AS game_keys
LIMIT $limit
"""
# spans·game_keys 는 접힌 관계 전부에서 모은다. 간선은 하나로 접지만 "언제" 는 접기 전 것이 다 필요하다.
# spans 는 소속·코치 관계의 [start_date, end_date] 목록, game_keys 는 픽처럼 게임에 묶인 관계의 게임 키 목록이다.


# 경기는 최근 것부터 정렬한다(ORDER BY). 순서 없이 자르면 어느 해 경기가 남을지 실행마다 달라진다.
# 상한을 넘을 때 고르는 방식은 $spread 로 갈린다.
#   - 날짜 범위가 없는 질문($spread = false): 최근 것부터 상한만큼.
#   - 날짜 범위가 있는 질문($spread = true): 그 기간 전체에서 같은 간격으로 상한만큼.
#     최근 것만 담으면 "2024 2025 티원 전략" 이 2025년 여름 경기로만 채워져 2024년이 통째로 빠진다.
# 경기 관계($match_types)는 질문 종류에 따라 상한($per_match)을 따로 둔다. GRAPH_FOCUS 참고.


# 3) 팀의 주력 픽. 픽은 팀이 아니라 선수에 붙어 있어 팀 시드의 1홉에는 챔피언이 나오지 않는다.
# 그 팀 소속으로 뛴 게임(PLAYED_IN.team_key)의 픽만 세어, 많이 쓴 (선수, 챔피언) 쌍부터 $team_picks 개를 가져온다.
# 반환 형식은 구조 간선과 같아서(source=선수, target=챔피언) 같은 변환 함수를 탄다.
TEAM_PICKS_CYPHER = """
MATCH (n:Team) WHERE elementId(n) IN $seed_ids
MATCH (n)-[:PLAYED_GAME]->(g:Game)-[:PART_OF_MATCH]-(mt:Match)
WHERE $date_start IS NULL
   OR ($date_start <= substring(mt.match_date, 0, 10) AND substring(mt.match_date, 0, 10) <= $date_end)
MATCH (p:Player)-[pi:PLAYED_IN]->(g) WHERE pi.team_key = n.entity_key
MATCH (p)-[r:PICKED_CHAMPION]->(c:Champion) WHERE r.game_key = g.game_key
WITH n, p, c, collect(r) AS rs
ORDER BY size(rs) DESC
WITH n, collect({p: p, c: c, r: head(rs), game_keys: [x IN rs | x.game_key]})[0..$team_picks] AS items
UNWIND items AS item
RETURN n, item.r AS r, item.c AS m, item.p AS source, item.c AS target,
       [] AS spans, item.game_keys AS game_keys
"""


# 질문 종류별 그래프 구성.
#   per_match  : 시드 하나의 경기 관계(승·패·출전)를 타입별로 몇 개까지 담을지
#   team_picks : 팀 시드의 주력 (선수, 챔피언) 쌍을 몇 개까지 담을지
# 기본은 경기 위주(타입별 20 = 기존 값)에 픽을 조금 곁들인다. 전략 질문은 답변이 픽·조합을 다루므로
# 경기를 최근 8개로 줄이고(세 타입 합쳐 24건이라 100건 제한 안에서 로스터·코치가 잘리지 않는다)
# 픽을 20쌍으로 늘린다. 20쌍은 다섯 포지션에 평균 네 챔피언씩이다.
MATCH_REL_TYPES = ["WON_MATCH", "LOST_MATCH", "PLAYED_MATCH"]
GRAPH_FOCUS = {
    "default": {"per_match": STRUCTURE_PER_TYPE_LIMIT, "team_picks": 8},
    "strategy": {"per_match": 8, "team_picks": 20},
}
STRATEGY_TOKEN = re.compile(r"(전략|밴픽|픽|챔피언|챔프|조합|메타|운영)")


def graph_focus(question: str) -> str:
    """질문이 전략·밴픽·챔피언을 묻으면 "strategy", 아니면 "default"."""
    return "strategy" if STRATEGY_TOKEN.search(question or "") else "default"


# 게임 키 → 그 게임이 속한 경기 날짜. 픽 간선의 날짜를 구하는 데 쓴다. Game.game_key 에는 인덱스가 있다.
GAME_DATE_CYPHER = """
MATCH (g:Game)-[:PART_OF_MATCH]-(mt:Match)
WHERE g.game_key IN $game_keys
RETURN g.game_key AS game_key, mt.match_date AS match_date
"""


# 2) 클레임 간선. (s)<-[:SOURCE_ENTITY]-(c:ArticleClaim)-[:TARGET_ENTITY]->(t) 를 s -> t 간선 하나로 편다.
CLAIM_CYPHER = f"""
MATCH (n)
{SEED_WHERE}
MATCH (n)-[:SOURCE_ENTITY|TARGET_ENTITY]-(c:ArticleClaim)
MATCH (c)-[:SOURCE_ENTITY]->(s), (c)-[:TARGET_ENTITY]->(t)
WHERE none(label IN labels(s) WHERE label IN $excluded_labels)
AND none(label IN labels(t) WHERE label IN $excluded_labels)
OPTIONAL MATCH (a:Article)-[:ASSERTS]->(c)
RETURN n, s, t, c.relation_type AS relation_type, c.article_key AS article_key,
       c.evidence_text AS evidence_text, c.confidence AS confidence,
       a.published_at AS published_at
LIMIT $limit
"""


# =========================
# 결과 변환
# =========================

def _add_node(nodes, node, seed_ids):
    node_id = str(node.element_id)

    if node_id not in nodes:
        nodes[node_id] = node_to_dict(node, node_id in seed_ids)

    return node_id


def _claim_evidence(record):
    return {
        "article_key": record["article_key"],
        "text": clean_text(record["evidence_text"]),
        "confidence": record["confidence"],
    }


# =========================
# 간선의 "언제" (날짜 스트립 기간 선택용)
# =========================
# when 은 [시작일, 종료일] 구간의 목록이다(둘 다 "YYYY-MM-DD", 양 끝 포함, 종료일 None 은 열린 구간).
# 하루짜리 사실은 시작일과 종료일이 같다. 날짜를 구할 수 없는 간선은 None 이며 프론트는 항상 보여준다.
# 설계: Frontend/docs/specs/2026-11-12-range-strip-design.md 4-2절.

DAY_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")
# 기사 키 "ARTICLE_01100201.20250306154350001" 의 점 뒤 여덟 자리가 발행일이다.
ARTICLE_KEY_DAY = re.compile(r"\.(\d{4})(\d{2})(\d{2})\d")

# 노드 자체가 날짜를 가진 라벨과 그 속성. 이 노드에 닿는 간선은 그 날짜 하루로 본다.
NODE_DATE_KEYS = {
    "Match": "match_date",
    "FanComment": "comment_published_at",
    "FanVideo": "video_published_at",
    "FanOpinion": "created_at",
}


def _day(value) -> str | None:
    text = str(value or "")[:10]
    return text if DAY_PATTERN.fullmatch(text) else None


def _node_day(node) -> str | None:
    key = NODE_DATE_KEYS.get(_node_label(node))
    return _day(node.get(key)) if key else None


def _merge_when(*lists) -> list | None:
    """구간 목록들을 합쳐 중복을 빼고 시작일순으로 정렬한다. 하나도 없으면 None."""
    spans = {(span[0], span[1]) for spans in lists if spans for span in spans}
    if not spans:
        return None
    return [list(span) for span in sorted(spans, key=lambda x: (x[0] or "", x[1] or "9999"))]


def structure_when(record, game_dates: dict | None = None) -> list | None:
    """
    구조 간선의 when. 우선순위:
      1. 관계의 start_date ~ end_date (소속·코치). 한쪽만 있으면 그쪽이 열린 구간이다.
      2. 관계의 game_key 로 찾은 경기 날짜 (픽).
      3. 양끝 노드 중 날짜를 가진 노드(경기·팬 댓글 등)의 그 날짜.
    """
    spans = []
    for start, end in record.get("spans") or []:
        start, end = _day(start), _day(end)
        if start or end:
            spans.append([start, end])
    for game_key in record.get("game_keys") or []:
        day = _day((game_dates or {}).get(game_key))
        if day:
            spans.append([day, day])
    if not spans:
        for node in (record["source"], record["target"]):
            day = _node_day(node)
            if day:
                spans.append([day, day])
    return _merge_when(spans)


def claim_when(record) -> list | None:
    """클레임 간선의 when. 기사 발행일 하루다. 발행일이 없으면 기사 키에 박힌 날짜를 쓴다."""
    day = _day(record.get("published_at"))
    if not day:
        m = ARTICLE_KEY_DAY.search(str(record.get("article_key") or ""))
        day = _day("-".join(m.groups())) if m else None
    return [[day, day]] if day else None


def _iter_edges(structure_records, claim_records, game_dates=None):
    """구조 레코드 먼저, 클레임 레코드 다음 순서로 (source, target, type, evidence, when) 을 낸다.

    같은 (source, target, type) 은 먼저 나온 것만 남으므로 구조 간선이 클레임 간선보다 우선한다.
    단 when 은 같은 종류(구조끼리, 클레임끼리)의 중복에서 전부 모은다. 구조 간선에 클레임의
    기사 날짜를 섞지 않는 이유는, 소속 기간에 기사 발행일이 끼면 기간 밖에서도 소속으로 보이기 때문이다.
    """
    edges: dict[tuple, list] = {}
    structure_keys = set()

    for record in structure_records:
        source, target = record["source"], record["target"]
        relation = _relation_name(record["r"])
        key = (str(source.element_id), str(target.element_id), relation)
        when = structure_when(record, game_dates)
        structure_keys.add(key)

        if key in edges:
            edges[key][4] = _merge_when(edges[key][4], when)
        else:
            edges[key] = [source, target, relation, None, when]

    for record in claim_records:
        source, target = record["s"], record["t"]
        key = (str(source.element_id), str(target.element_id), record["relation_type"])
        if key in structure_keys:
            continue
        when = claim_when(record)

        if key in edges:
            edges[key][4] = _merge_when(edges[key][4], when)
        else:
            edges[key] = [source, target, record["relation_type"], _claim_evidence(record), when]

    return [tuple(edge) for edge in edges.values()]


def records_to_graph(structure_records: list, claim_records: list, seed_ids: set[str], game_dates: dict | None = None) -> dict:
    nodes: dict[str, dict] = {}
    links = []

    for source, target, relation, evidence, when in _iter_edges(structure_records, claim_records, game_dates):
        source_id = _add_node(nodes, source, seed_ids)
        target_id = _add_node(nodes, target, seed_ids)

        links.append({
            "source": source_id,
            "target": target_id,
            "type": relation,
            "evidence": evidence,
            "when": when,
        })

    # degree 는 응답에 담긴 간선 기준으로 양끝 등장 횟수를 센다.
    for link in links:
        nodes[link["source"]]["degree"] += 1
        nodes[link["target"]]["degree"] += 1

    return {
        "nodes": list(nodes.values()),
        "links": links,
    }


def records_to_facts(structure_records: list, claim_records: list) -> list[dict]:
    facts = []
    seen_facts = set()

    for source, target, relation, evidence, _when in _iter_edges(structure_records, claim_records):
        source_node = node_to_dict(source, False)
        target_node = node_to_dict(target, False)

        fact = {
            "source": source_node["name"],
            "source_label": source_node["label"],
            "relation": relation,
            "target": target_node["name"],
            "target_label": target_node["label"],
            "evidence": evidence,
        }

        fact_key = (
            fact["source"],
            fact["source_label"],
            fact["relation"],
            fact["target"],
            fact["target_label"],
        )

        if fact_key in seen_facts:
            continue

        seen_facts.add(fact_key)
        facts.append(fact)

    return facts


def format_graph_facts(facts, max_facts=50):
    selected_facts = facts[:max_facts]

    return "\n".join(
        [
            (
                f"{idx}. ({fact['source_label']}) {fact['source']} "
                f"-[{fact['relation']}]-> "
                f"({fact['target_label']}) {fact['target']}"
            )
            for idx, fact in enumerate(selected_facts, start=1)
        ]
    )


def _empty_graph_result(keywords=None):
    return {
        "keywords": keywords or [],
        "graph": {
            "nodes": [],
            "links": [],
        },
        "facts": [],
        "context": "",
    }


def _when_overlaps(when, start: str, end: str) -> bool:
    """when 구간 중 하나라도 [start, end] 와 겹치면 True. 날짜를 모르는(None·빈 목록) 간선은 True."""
    if not when:
        return True
    return any((span[0] or "0000-01-01") <= end and (span[1] or "9999-12-31") >= start for span in when)


def filter_graph_by_date(graph: dict, facts: list[dict], start: str, end: str) -> tuple[dict, list[dict]]:
    """
    날짜 범위(둘 다 "YYYY-MM-DD", 양 끝 포함) 밖의 것을 뺀다.
      - 범위 밖 Match 노드와 그에 닿는 간선. 날짜가 없는 Match 는 남긴다.
      - when 이 범위와 겹치지 않는 간선(범위 밖의 소속·픽·기사 관계). when 이 없는 간선은 남긴다.
    그 간선에서 나온 사실도 함께 빼고, 간선이 모두 사라진 비시드 노드도 뺀다. degree 는 다시 센다.
    """
    removed = {
        n["id"] for n in graph["nodes"]
        if n.get("label") == "Match" and n.get("match_date") and not (start <= n["match_date"] <= end)
    }
    names = {n["id"]: n["name"] for n in graph["nodes"]}

    links, dropped = [], []
    for l in graph["links"]:
        keep = (
            l["source"] not in removed and l["target"] not in removed
            and _when_overlaps(l.get("when"), start, end)
        )
        (links if keep else dropped).append(l)
    if not removed and not dropped:
        return graph, facts

    degree: dict[str, int] = {}
    for l in links:
        degree[l["source"]] = degree.get(l["source"], 0) + 1
        degree[l["target"]] = degree.get(l["target"], 0) + 1

    nodes = []
    for n in graph["nodes"]:
        if n["id"] in removed:
            continue
        d = degree.get(n["id"], 0)
        # 간선을 모두 잃은 노드는 뺀다. 시드는 질문의 주체라 남기지만, 팬 영상처럼 그 자체가 날짜를 가진
        # 종류는 간선이 다 빠졌다면 범위 밖 시점의 것이므로 시드여도 뺀다.
        if d == 0 and (not n.get("is_seed") or n.get("label") in NODE_DATE_KEYS):
            continue
        nodes.append({**n, "degree": d})

    # 사실은 (출발 이름, 관계, 도착 이름) 으로 간선과 맞춘다. 남은 간선에도 같은 키가 있으면 남긴다.
    fact_key = lambda source, relation, target: (source, relation, target)
    kept_keys = {fact_key(names[l["source"]], l["type"], names[l["target"]]) for l in links}
    dropped_keys = {fact_key(names[l["source"]], l["type"], names[l["target"]]) for l in dropped} - kept_keys
    kept_facts = [f for f in facts if fact_key(f["source"], f["relation"], f["target"]) not in dropped_keys]
    return {"nodes": nodes, "links": links}, kept_facts


def search_graph_knowledge(keywords, limit=100, date_range=None, focus="default"):
    """
    질문 키워드 기반으로 Neo4j subgraph와 LLM 답변용 triple context를 함께 반환한다.
    date_range 가 ("YYYY-MM-DD", "YYYY-MM-DD") 면 그 밖의 경기와, 그 기간에 걸치지 않는 관계를 뺀다.
    focus 는 GRAPH_FOCUS 의 키다. 질문 종류에 따라 경기와 픽의 비중을 바꾼다.
    """

    keywords = _extract_keywords(keywords)

    print("DEBUG graph keywords:", keywords)

    if not keywords:
        print("DEBUG no valid graph keywords")
        return _empty_graph_result()

    driver = get_driver()
    params = {
        "excluded_relations": EXCLUDED_RELATIONS,
        "excluded_labels": EXCLUDED_LABELS,
        "limit": limit,
        "per_type": STRUCTURE_PER_TYPE_LIMIT,
        "date_start": date_range[0] if date_range else None,
        "date_end": date_range[1] if date_range else None,
        "match_types": MATCH_REL_TYPES,
        "spread": bool(date_range),
        **GRAPH_FOCUS.get(focus, GRAPH_FOCUS["default"]),
    }

    with driver.session() as session:
        params["seed_ids"] = find_seed_ids(session, keywords)
        if not params["seed_ids"]:
            print(f"DEBUG no seed entity for keywords {keywords}")
            return _empty_graph_result(keywords)
        structure_records = list(session.run(KEYWORD_CYPHER, **params))
        pick_records = list(session.run(TEAM_PICKS_CYPHER, **params))
        # 사실 목록은 앞에서부터 50개만 LLM 에 들어간다. 전략 질문이면 픽이 잘리지 않게 앞에 둔다.
        structure_records = pick_records + structure_records if focus == "strategy" else structure_records + pick_records
        claim_records = list(session.run(CLAIM_CYPHER, **params))
        # 픽처럼 게임에 묶인 간선의 날짜를 구하려고 게임 키를 한 번에 경기 날짜로 바꾼다.
        game_keys = sorted({key for record in structure_records for key in (record.get("game_keys") or [])})
        game_dates = {}
        if game_keys:
            for row in session.run(GAME_DATE_CYPHER, game_keys=game_keys):
                game_dates[row["game_key"]] = row["match_date"]

    if not structure_records and not claim_records:
        print(f"DEBUG no graph match for keywords {keywords}")
        return _empty_graph_result(keywords)

    seed_ids = {str(record["n"].element_id) for record in structure_records + claim_records}
    graph = records_to_graph(structure_records, claim_records, seed_ids, game_dates)
    facts = records_to_facts(structure_records, claim_records)
    if date_range:
        before = len(graph["nodes"])
        graph, facts = filter_graph_by_date(graph, facts, date_range[0], date_range[1])
        print(f"DEBUG graph date filter {date_range}: nodes {before} → {len(graph['nodes'])}")
    context = format_graph_facts(facts)

    print("DEBUG graph nodes:", len(graph["nodes"]))
    print("DEBUG graph links:", len(graph["links"]))
    print("DEBUG graph facts:", len(facts))

    return {
        "keywords": keywords,
        "graph": graph,
        "facts": facts,
        "context": context,
    }


# =========================
# 노드 상세 조회 (/node)
# =========================

NODE_CYPHER = """
MATCH (n) WHERE elementId(n) = $id
OPTIONAL MATCH (n)-[r]-(m)
WHERE NOT type(r) IN $excluded_relations
AND none(label IN labels(m) WHERE label IN $excluded_labels)
RETURN n, r, m, startNode(r) AS source
"""

NODE_NEIGHBOR_LIMIT = 20
RECORD_LABELS = {"Team", "Player"}


def _run_node_query(node_id: str) -> list:
    """Cypher 실행만 맡는다. 테스트에서는 monkeypatch 로 스텁 레코드를 돌려준다."""
    driver = get_driver()

    with driver.session() as session:
        return list(session.run(
            NODE_CYPHER,
            id=node_id,
            excluded_relations=EXCLUDED_RELATIONS,
            excluded_labels=EXCLUDED_LABELS,
        ))


def get_node_detail(node_id: str) -> dict | None:
    records = _run_node_query(node_id)

    if not records:
        return None

    node = node_to_dict(records[0]["n"], False)
    selected_id = node["id"]

    # (relation, direction) 별로 이웃 id 를 키로 모은다. 기간별 MEMBER_OF 처럼 같은 이웃과의
    # 간선이 여럿이면 하나로 합친다. degree 는 합치기 전 간선 수(DB 1홉 차수)로 센다.
    groups: dict[tuple[str, str], dict[str, dict]] = {}
    degree = 0
    wins = 0
    losses = 0

    for record in records:
        r = record["r"]

        if r is None:
            continue

        relation = _relation_name(r)
        direction = "out" if str(record["source"].element_id) == selected_id else "in"
        neighbor = node_to_dict(record["m"], False)
        role = r.get("role") if relation == "MEMBER_OF" else None
        degree += 1

        neighbors = groups.setdefault((relation, direction), {})
        existing = neighbors.get(neighbor["id"])

        if existing is None:
            neighbors[neighbor["id"]] = {
                "id": neighbor["id"],
                "name": neighbor["name"],
                "label": neighbor["label"],
                "role": role,
            }
        elif existing["role"] is None:
            existing["role"] = role

        if relation == "WON_MATCH":
            wins += 1
        elif relation == "LOST_MATCH":
            losses += 1

    # 합친 뒤 이웃 수 내림차순, 같으면 관계 이름 오름차순. 20개 제한은 이름 정렬 뒤에 건다.
    ordered = sorted(groups.items(), key=lambda item: (-len(item[1]), item[0][0]))

    return {
        "id": selected_id,
        "name": node["name"],
        "label": node["label"],
        "degree": degree,
        "record": {"wins": wins, "losses": losses} if node["label"] in RECORD_LABELS else None,
        "match": node["props"] if node["label"] == "Match" else None,
        "groups": [
            {
                "relation": relation,
                "direction": direction,
                "neighbors": sorted(neighbors.values(), key=lambda x: x["name"])[:NODE_NEIGHBOR_LIMIT],
            }
            for (relation, direction), neighbors in ordered
        ],
    }


# =========================
# 메인 함수
# =========================

def search_graph_by_keyword(keywords, limit=100):
    """
    질문 키워드 기반 그래프 시각화용 함수.

    - 질문에서 키워드 추출
    - Neo4j 노드 이름 속성과 매칭
    - 매칭된 노드 주변 1-hop 관계 반환
    - 매칭 실패 시 빈 그래프 반환
    """

    return search_graph_knowledge(keywords, limit=limit)["graph"]


# =========================
# 직접 테스트용
# =========================

if __name__ == "__main__":
    result = search_graph_by_keyword("젠지 우승 전략 알려줘")

    print("nodes:", len(result["nodes"]))
    print("links:", len(result["links"]))
    print(result)
