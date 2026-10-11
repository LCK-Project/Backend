from connect import get_driver
from graph_schema_config import VISUAL_EXCLUDED_LABELS, VISUAL_EXCLUDED_RELATIONS
import os
import re

print("### LOADED neo4j_query.py ###", os.path.abspath(__file__))


# =========================
# 표시용 유틸
# =========================

def _node_name(node):
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

    return list(dict.fromkeys(result))


# =========================
# 그래프 조회 Cypher
# =========================

EXCLUDED_RELATIONS = VISUAL_EXCLUDED_RELATIONS
EXCLUDED_LABELS = VISUAL_EXCLUDED_LABELS


# 키워드에 매칭되는 시드 노드 n 의 조건. 구조·클레임 두 쿼리가 어긋나지 않도록 한 번만 쓴다.
# Team 은 "한화생명" 같은 약칭을 aliases 배열에만 갖고 있어 aliases 매칭이 필요하다.
SEED_WHERE = """
WHERE none(label IN labels(n) WHERE label IN $excluded_labels)
AND any(kw IN $keywords WHERE
    toLower(coalesce(n.name, '')) CONTAINS kw
    OR toLower(coalesce(n.canonical_name, '')) CONTAINS kw
    OR toLower(coalesce(n.team_name, '')) CONTAINS kw
    OR toLower(coalesce(n.player_name, '')) CONTAINS kw
    OR toLower(coalesce(n.champion_name, '')) CONTAINS kw
    OR toLower(coalesce(n.staff_name, '')) CONTAINS kw
    OR any(a IN coalesce(n.aliases, []) WHERE toLower(a) CONTAINS kw)
)
"""


# 시드 하나의 구조 간선을 관계 타입별로 이만큼만 가져와 LIMIT 안에서 매치·소속·코치 관계가 고루 들어가게 한다.
STRUCTURE_PER_TYPE_LIMIT = 20


# 1) 구조 간선. Game·ArticleClaim 은 제외 라벨로, 클레임 연결 관계는 제외 관계로 빠진다.
# 같은 (n, 타입, m) 의 중복 관계는 하나로 접고, 타입별 상한을 건 뒤 전체 LIMIT 를 건다.
KEYWORD_CYPHER = f"""
MATCH (n)
{SEED_WHERE}
MATCH (n)-[r]-(m)
WHERE NOT type(r) IN $excluded_relations
AND none(label IN labels(m) WHERE label IN $excluded_labels)
WITH n, type(r) AS rel_type, m, head(collect(r)) AS r
WITH n, rel_type, collect({{r: r, m: m}})[0..$per_type] AS items
UNWIND items AS item
RETURN n, item.r AS r, item.m AS m, startNode(item.r) AS source, endNode(item.r) AS target
LIMIT $limit
"""


# 2) 클레임 간선. (s)<-[:SOURCE_ENTITY]-(c:ArticleClaim)-[:TARGET_ENTITY]->(t) 를 s -> t 간선 하나로 편다.
CLAIM_CYPHER = f"""
MATCH (n)
{SEED_WHERE}
MATCH (n)-[:SOURCE_ENTITY|TARGET_ENTITY]-(c:ArticleClaim)
MATCH (c)-[:SOURCE_ENTITY]->(s), (c)-[:TARGET_ENTITY]->(t)
WHERE none(label IN labels(s) WHERE label IN $excluded_labels)
AND none(label IN labels(t) WHERE label IN $excluded_labels)
RETURN n, s, t, c.relation_type AS relation_type, c.article_key AS article_key,
       c.evidence_text AS evidence_text, c.confidence AS confidence
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
        "text": record["evidence_text"],
        "confidence": record["confidence"],
    }


def _iter_edges(structure_records, claim_records):
    """구조 레코드 먼저, 클레임 레코드 다음 순서로 (source, target, type, evidence) 를 낸다.

    같은 (source, target, type) 은 먼저 나온 것만 남으므로 구조 간선이 클레임 간선보다 우선한다.
    """
    seen = set()

    for record in structure_records:
        source, target = record["source"], record["target"]
        edge = (source, target, _relation_name(record["r"]), None)
        key = (str(source.element_id), str(target.element_id), edge[2])

        if key not in seen:
            seen.add(key)
            yield edge

    for record in claim_records:
        source, target = record["s"], record["t"]
        edge = (source, target, record["relation_type"], _claim_evidence(record))
        key = (str(source.element_id), str(target.element_id), edge[2])

        if key not in seen:
            seen.add(key)
            yield edge


def records_to_graph(structure_records: list, claim_records: list, seed_ids: set[str]) -> dict:
    nodes = {}
    links = []

    for source, target, relation, evidence in _iter_edges(structure_records, claim_records):
        source_id = _add_node(nodes, source, seed_ids)
        target_id = _add_node(nodes, target, seed_ids)

        links.append({
            "source": source_id,
            "target": target_id,
            "type": relation,
            "evidence": evidence,
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

    for source, target, relation, evidence in _iter_edges(structure_records, claim_records):
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


def search_graph_knowledge(keywords, limit=100):
    """
    질문 키워드 기반으로 Neo4j subgraph와 LLM 답변용 triple context를 함께 반환한다.
    """

    keywords = _extract_keywords(keywords)

    print("DEBUG graph keywords:", keywords)

    if not keywords:
        print("DEBUG no valid graph keywords")
        return _empty_graph_result()

    driver = get_driver()
    params = {
        "keywords": keywords,
        "excluded_relations": EXCLUDED_RELATIONS,
        "excluded_labels": EXCLUDED_LABELS,
        "limit": limit,
        "per_type": STRUCTURE_PER_TYPE_LIMIT,
    }

    with driver.session() as session:
        structure_records = list(session.run(KEYWORD_CYPHER, **params))
        claim_records = list(session.run(CLAIM_CYPHER, **params))

    if not structure_records and not claim_records:
        print(f"DEBUG no graph match for keywords {keywords}")
        return _empty_graph_result(keywords)

    seed_ids = {str(record["n"].element_id) for record in structure_records + claim_records}
    graph = records_to_graph(structure_records, claim_records, seed_ids)
    facts = records_to_facts(structure_records, claim_records)
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
    groups = {}
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
