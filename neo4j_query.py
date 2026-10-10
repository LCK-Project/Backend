from connect import get_driver
from graph_schema_config import QUERY_EXCLUDED_LABELS, QUERY_EXCLUDED_RELATIONS
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
        "Game",
        "Entity",
    ]

    for label in priority:
        if label in labels:
            return label

    return node.get("entity_type") or node.get("type") or (labels[0] if labels else "Node")


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

EXCLUDED_RELATIONS = QUERY_EXCLUDED_RELATIONS
EXCLUDED_LABELS = QUERY_EXCLUDED_LABELS


KEYWORD_CYPHER = """
MATCH (n)
WHERE none(label IN labels(n) WHERE label IN $excluded_labels)
AND any(kw IN $keywords WHERE
    toLower(coalesce(n.display_name, '')) CONTAINS kw
    OR toLower(coalesce(n.name, '')) CONTAINS kw
    OR toLower(coalesce(n.canonical_name, '')) CONTAINS kw
    OR toLower(coalesce(n.entity_text, '')) CONTAINS kw
    OR toLower(coalesce(n.team_name, '')) CONTAINS kw
    OR toLower(coalesce(n.player_name, '')) CONTAINS kw
    OR toLower(coalesce(n.champion_name, '')) CONTAINS kw
    OR toLower(coalesce(n.league_name, '')) CONTAINS kw
    OR toLower(coalesce(n.tournament_name, '')) CONTAINS kw
)
MATCH (n)-[r]-(m)
WHERE NOT type(r) IN $excluded_relations
AND none(label IN labels(m) WHERE label IN $excluded_labels)
RETURN n, r, m, startNode(r) AS source, endNode(r) AS target
LIMIT $limit
"""


# =========================
# 결과 변환
# =========================

def _add_node(nodes, node):
    node_id = str(node.element_id)

    if node_id not in nodes:
        nodes[node_id] = {
            "id": node_id,
            "name": _node_name(node),
            "label": _node_label(node),
        }

    return node_id


def _add_link(links, seen_links, source_id, target_id, relation_name):
    link_key = (source_id, target_id, relation_name)

    if link_key in seen_links:
        return

    seen_links.add(link_key)

    links.append({
        "source": source_id,
        "target": target_id,
        "type": relation_name,
    })


def _record_relation_nodes(record):
    source = record.get("source")
    target = record.get("target")

    if source is None or target is None:
        return record["n"], record["m"]

    return source, target


def _records_to_graph(records):
    nodes = {}
    links = []
    seen_links = set()

    for record in records:
        r = record["r"]
        source, target = _record_relation_nodes(record)

        source_id = _add_node(nodes, source)
        target_id = _add_node(nodes, target)

        _add_link(
            links=links,
            seen_links=seen_links,
            source_id=source_id,
            target_id=target_id,
            relation_name=_relation_name(r),
        )

    return {
        "nodes": list(nodes.values()),
        "links": links,
    }


def _records_to_facts(records):
    facts = []
    seen_facts = set()

    for record in records:
        r = record["r"]
        source, target = _record_relation_nodes(record)

        fact = {
            "source": _node_name(source),
            "source_label": _node_label(source),
            "relation": _relation_name(r),
            "target": _node_name(target),
            "target_label": _node_label(target),
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

    with driver.session() as session:
        records = list(session.run(
            KEYWORD_CYPHER,
            keywords=keywords,
            excluded_relations=EXCLUDED_RELATIONS,
            excluded_labels=EXCLUDED_LABELS,
            limit=limit,
        ))

    if not records:
        print(f"DEBUG no graph match for keywords {keywords}")
        return _empty_graph_result(keywords)

    graph = _records_to_graph(records)
    facts = _records_to_facts(records)
    context = format_graph_facts(facts)

    print("DEBUG graph nodes:", len(graph["nodes"]))
    print("DEBUG graph links:", len(graph["links"]))
    print("DEBUG graph facts:", len(facts))
    print("DEBUG sample nodes:", graph["nodes"][:5])
    print("DEBUG sample links:", graph["links"][:5])

    return {
        "keywords": keywords,
        "graph": graph,
        "facts": facts,
        "context": context,
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
