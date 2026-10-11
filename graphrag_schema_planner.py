import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from graph_schema_config import (
    ARTICLE_GRAPH_LABELS,
    COMMUNITY_GRAPH_SCHEMA,
    DOMAIN_LABELS,
    EVIDENCE_RELATIONS,
    EXTRACTION_ENTITY_LABELS,
    GENERIC_RELATIONS,
    GLOBAL_GRAPH_LABELS,
    LOW_SIGNAL_RELATIONS,
    NORMALIZATION_RELATION_HINTS,
    NORMALIZATION_TARGET_LABELS,
    SOURCE_LABELS,
)

DEFAULT_FILENAMES = {
    "node_counts": "neo4j_query_table_data_2026-6-27.csv",
    "node_properties": "neo4j_query_table_data_2026-6-27 (1).csv",
    "relationships": "neo4j_query_table_data_2026-6-27 (2).csv",
}


def _candidate_dirs():
    home = Path.home()
    return [
        Path.cwd(),
        home / "OneDrive" / "문서" / "카카오톡 받은 파일",
        home / "Documents" / "카카오톡 받은 파일",
        home / "Downloads",
    ]


def _find_default_file(kind):
    filename = DEFAULT_FILENAMES[kind]

    for directory in _candidate_dirs():
        path = directory / filename
        if path.exists():
            return path

    return Path(filename)


def _read_csv(path):
    for encoding in ("utf-8-sig", "utf-8", "cp949"):
        try:
            with open(path, newline="", encoding=encoding) as f:
                return list(csv.DictReader(f))
        except UnicodeDecodeError:
            continue

    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(f))


def _parse_count(value):
    try:
        return int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return 0


def _parse_property_list(value):
    text = str(value or "").strip()

    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]

    props = []
    for prop in text.split(","):
        prop = prop.strip().strip("'\"")
        if prop:
            props.append(prop)

    return props


def _property_signature(value):
    return tuple(sorted(_parse_property_list(value)))


def _label_layer(label):
    if label in SOURCE_LABELS:
        return "source/evidence"
    if label in DOMAIN_LABELS:
        return "domain"
    if label in EXTRACTION_ENTITY_LABELS:
        return "extracted/entity"
    if label in {"Community", "CommunitySummary"}:
        return "community"
    return "unknown"


def _relation_layer(row):
    rel_type = row["rel_type"]
    from_label = row["from_label"]
    to_label = row["to_label"]

    if rel_type in EVIDENCE_RELATIONS or from_label in ARTICLE_GRAPH_LABELS:
        return "article/evidence graph"
    if rel_type in GENERIC_RELATIONS:
        return "low-signal helper graph"
    if from_label in GLOBAL_GRAPH_LABELS and to_label in GLOBAL_GRAPH_LABELS:
        return "global domain graph"
    return "mixed/needs-review"


def _load_schema(node_counts_path, node_properties_path, relationships_path):
    node_counts = _read_csv(node_counts_path)
    node_properties = _read_csv(node_properties_path)
    relationships = _read_csv(relationships_path)

    return {
        "node_counts_path": str(node_counts_path),
        "node_properties_path": str(node_properties_path),
        "relationships_path": str(relationships_path),
        "node_counts": node_counts,
        "node_properties": node_properties,
        "relationships": relationships,
    }


def _summarize_current_structure(schema):
    counts = {
        row["label"]: _parse_count(row.get("count"))
        for row in schema["node_counts"]
        if row.get("label")
    }

    props_by_label = {
        row["label"]: _parse_property_list(row.get("properties"))
        for row in schema["node_properties"]
        if row.get("label")
    }

    labels_by_layer = defaultdict(list)
    for label in sorted(set(counts) | set(props_by_label)):
        labels_by_layer[_label_layer(label)].append(label)

    relations_by_layer = defaultdict(list)
    for row in schema["relationships"]:
        if not row.get("from_label") or not row.get("rel_type") or not row.get("to_label"):
            continue
        relations_by_layer[_relation_layer(row)].append({
            "from_label": row["from_label"],
            "rel_type": row["rel_type"],
            "to_label": row["to_label"],
            "rel_props": _parse_property_list(row.get("rel_props")),
        })

    return {
        "node_counts": counts,
        "props_by_label": props_by_label,
        "labels_by_layer": dict(labels_by_layer),
        "relations_by_layer": dict(relations_by_layer),
    }


def _find_schema_cleanup_candidates(schema):
    prop_groups = defaultdict(list)
    for row in schema["node_properties"]:
        label = row.get("label")
        if not label:
            continue

        signature = _property_signature(row.get("properties"))
        if signature:
            prop_groups[signature].append(label)

    duplicate_label_shapes = [
        {
            "labels": sorted(labels),
            "shared_properties": list(signature),
        }
        for signature, labels in prop_groups.items()
        if len(labels) > 1
    ]

    pattern_props = defaultdict(set)
    rel_type_pairs = defaultdict(set)
    for row in schema["relationships"]:
        pattern = (row.get("from_label"), row.get("rel_type"), row.get("to_label"))
        if not all(pattern):
            continue

        pattern_props[pattern].add(tuple(_parse_property_list(row.get("rel_props"))))
        rel_type_pairs[row["rel_type"]].add((row["from_label"], row["to_label"]))

    duplicate_relation_patterns = [
        {
            "from_label": pattern[0],
            "rel_type": pattern[1],
            "to_label": pattern[2],
            "property_shapes": [list(props) for props in sorted(prop_sets)],
        }
        for pattern, prop_sets in pattern_props.items()
        if len(prop_sets) > 1
    ]

    overloaded_relation_types = [
        {
            "rel_type": rel_type,
            "label_pairs": [
                {"from_label": pair[0], "to_label": pair[1]}
                for pair in sorted(pairs)
            ],
        }
        for rel_type, pairs in rel_type_pairs.items()
        if len(pairs) > 1
    ]

    low_signal_relations = [
        {
            "from_label": row["from_label"],
            "rel_type": row["rel_type"],
            "to_label": row["to_label"],
        }
        for row in schema["relationships"]
        if row.get("rel_type") in LOW_SIGNAL_RELATIONS
    ]

    entity_to_entity_relations = [
        {
            "rel_type": row["rel_type"],
            "rel_props": _parse_property_list(row.get("rel_props")),
        }
        for row in schema["relationships"]
        if row.get("from_label") == "Entity" and row.get("to_label") == "Entity"
    ]

    entity_relation_counts = Counter(row["rel_type"] for row in entity_to_entity_relations)

    return {
        "duplicate_label_shapes": duplicate_label_shapes,
        "duplicate_relation_patterns": duplicate_relation_patterns,
        "overloaded_relation_types": overloaded_relation_types,
        "low_signal_relations": low_signal_relations,
        "entity_to_entity_relation_types": dict(sorted(entity_relation_counts.items())),
    }


def _build_normalization_criteria(schema):
    observed_labels = {
        row.get("label")
        for row in schema["node_properties"]
        if row.get("label")
    }

    criteria = [
        {
            "target": "Team",
            "identity": ["team_id", "team_name", "canonical_name", "name"],
            "sources": ["Team", "Entity", "Alias"],
            "rule": "팀 alias나 canonical_name이 Team.team_name/name과 일치하면 Team으로 승격한다.",
        },
        {
            "target": "Player",
            "identity": ["player_id", "player_name", "canonical_name", "name"],
            "sources": ["Player", "Entity", "Alias"],
            "rule": "선수 alias, 실명, canonical_name이 Player 이름과 일치하면 Player로 승격한다.",
        },
        {
            "target": "Champion",
            "identity": ["champion_id", "champion_name", "canonical_name", "name"],
            "sources": ["Champion", "Entity", "Alias"],
            "rule": "챔피언 이름과 alias가 일치하면 Champion으로 승격한다.",
        },
        {
            "target": "Tournament",
            "identity": ["tournament_id", "tournament_name", "canonical_name", "name"],
            "sources": ["Tournament", "Entity"],
            "rule": "시즌/스플릿/대회명이 들어간 엔티티는 Tournament로 승격한다.",
        },
    ]

    relation_hints = []
    observed_rel_types = {row.get("rel_type") for row in schema["relationships"]}
    for rel_type, hint in NORMALIZATION_RELATION_HINTS.items():
        if rel_type in observed_rel_types:
            relation_hints.append({
                "rel_type": rel_type,
                "source_label": hint["source"],
                "target_label": hint["target"],
            })

    candidate_entity_labels = sorted(observed_labels & set(NORMALIZATION_TARGET_LABELS.values()))

    return {
        "canonical_property_priority": [
            "canonical_name",
            "team_name",
            "player_name",
            "champion_name",
            "tournament_name",
            "league_name",
            "name",
        ],
        "criteria": criteria,
        "relation_hints": relation_hints,
        "observed_normalization_targets": candidate_entity_labels,
    }


def _build_graph_separation_design(schema):
    structure = _summarize_current_structure(schema)

    return {
        "article_graph": {
            "purpose": "관계가 어느 기사/청크에서 나왔는지 추적하는 근거 그래프",
            "labels": sorted(set(structure["labels_by_layer"].get("source/evidence", []))),
            "main_relations": [
                "Article-[:HAS_CHUNK]->ArticleChunk",
                "Article-[:HAS_EVIDENCE]->SourceEvidence",
                "ArticleChunk-[:SUPPORTS]->SourceEvidence",
            ],
            "query_use": "출처 확인, 특정 기사별 관계 확인, 답변 근거 표시",
        },
        "global_graph": {
            "purpose": "정규화된 LCK 도메인 지식그래프",
            "labels": sorted(
                set(structure["labels_by_layer"].get("domain", []))
                | set(structure["labels_by_layer"].get("extracted/entity", []))
            ),
            "main_relations": [
                "Team/Player/Champion/Match/Game/Tournament 중심의 정규화 관계",
                "관계 속성에 article_id, confidence, raw_relation_type 보존",
            ],
            "query_use": "선수/팀/대회 중심 Local Search",
        },
        "community_summary_graph": {
            "purpose": "여러 기사에서 반복되는 관계 묶음을 요약한 상위 그래프",
            "labels": ["Community", "CommunitySummary"],
            "main_relations": COMMUNITY_GRAPH_SCHEMA["relations"],
            "query_use": "전체 이슈/흐름 질문 Global Search",
        },
    }


def _build_community_summary_plan(schema):
    structure = _summarize_current_structure(schema)
    counts = structure["node_counts"]

    likely_entity_labels = [
        label
        for label in sorted(GLOBAL_GRAPH_LABELS)
        if label in counts or label in structure["props_by_label"]
    ]

    return {
        "new_nodes": {
            "Community": COMMUNITY_GRAPH_SCHEMA["properties"],
            "CommunitySummary": [
                "summary_id",
                "community_id",
                "summary",
                "source",
                "created_at",
            ],
        },
        "connect_to": {
            "entities": likely_entity_labels,
            "evidence": ["ArticleChunk", "SourceEvidence", "Article"],
        },
        "recommended_relations": [
            "Community-[:CONTAINS_ENTITY {weight, rank}]->Entity/Team/Player/Champion",
            "Community-[:SUPPORTED_BY]->ArticleChunk",
            "Community-[:SUMMARIZES]->CommunitySummary",
            "Community-[:PART_OF_COMMUNITY]->Community",
        ],
        "build_order": [
            "정규화된 global graph에서 커뮤니티 탐지 결과를 만든다.",
            "community_id별 핵심 Entity와 관련 ArticleChunk를 모은다.",
            "LLM으로 community summary를 생성한다.",
            "Community와 CommunitySummary 노드를 Neo4j에 저장한다.",
        ],
    }


def _build_cypher_templates():
    return {
        "constraints": [
            "CREATE CONSTRAINT article_id IF NOT EXISTS FOR (n:Article) REQUIRE n.article_id IS UNIQUE;",
            "CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (n:ArticleChunk) REQUIRE n.chunk_id IS UNIQUE;",
            "CREATE CONSTRAINT team_id IF NOT EXISTS FOR (n:Team) REQUIRE n.team_id IS UNIQUE;",
            "CREATE CONSTRAINT player_id IF NOT EXISTS FOR (n:Player) REQUIRE n.player_id IS UNIQUE;",
            "CREATE CONSTRAINT champion_id IF NOT EXISTS FOR (n:Champion) REQUIRE n.champion_id IS UNIQUE;",
            "CREATE CONSTRAINT community_id IF NOT EXISTS FOR (n:Community) REQUIRE n.community_id IS UNIQUE;",
        ],
        "promote_entity_to_domain_label": [
            "// Team 부분을 Player, Champion 등 목표 라벨로 바꿔서 사용한다.",
            "MATCH (e:Entity {canonical_name: $canonical_name})",
            "SET e:Team",
            "SET e.normalized_from_entity = true",
        ],
        "create_community": [
            "MERGE (c:Community {community_id: $community_id})",
            "SET c.title = $title,",
            "    c.summary = $summary,",
            "    c.level = $level,",
            "    c.entity_count = $entity_count,",
            "    c.article_count = $article_count,",
            "    c.created_at = datetime()",
        ],
        "link_community_entity": [
            "MATCH (c:Community {community_id: $community_id})",
            "MATCH (e {canonical_name: $canonical_name})",
            "MERGE (c)-[r:CONTAINS_ENTITY]->(e)",
            "SET r.weight = $weight, r.rank = $rank",
        ],
        "link_community_evidence": [
            "MATCH (c:Community {community_id: $community_id})",
            "MATCH (chunk:ArticleChunk {chunk_id: $chunk_id})",
            "MERGE (c)-[:SUPPORTED_BY]->(chunk)",
        ],
    }


def build_plan(node_counts_path, node_properties_path, relationships_path):
    schema = _load_schema(node_counts_path, node_properties_path, relationships_path)

    return {
        "input_files": {
            "node_counts": schema["node_counts_path"],
            "node_properties": schema["node_properties_path"],
            "relationships": schema["relationships_path"],
        },
        "current_structure": _summarize_current_structure(schema),
        "cleanup_candidates": _find_schema_cleanup_candidates(schema),
        "normalization_criteria": _build_normalization_criteria(schema),
        "graph_separation_design": _build_graph_separation_design(schema),
        "community_summary_plan": _build_community_summary_plan(schema),
        "cypher_templates": _build_cypher_templates(),
    }


def _render_list(items):
    if not items:
        return "- 없음"
    return "\n".join(f"- {item}" for item in items)


def _render_markdown(plan):
    counts = plan["current_structure"]["node_counts"]
    labels_by_layer = plan["current_structure"]["labels_by_layer"]
    cleanup = plan["cleanup_candidates"]
    normalization = plan["normalization_criteria"]
    separation = plan["graph_separation_design"]
    community = plan["community_summary_plan"]

    top_counts = sorted(counts.items(), key=lambda item: item[1], reverse=True)

    lines = [
        "# Neo4j GraphRAG Schema Plan",
        "",
        "## 1. 현재 Neo4j 구조 파악",
        "",
        "### 입력 파일",
    ]

    for key, path in plan["input_files"].items():
        lines.append(f"- {key}: `{path}`")

    lines.extend(["", "### 노드 수"])
    for label, count in top_counts:
        lines.append(f"- {label}: {count}")

    lines.extend(["", "### 라벨 레이어"])
    for layer, labels in sorted(labels_by_layer.items()):
        lines.append(f"- {layer}: {', '.join(labels)}")

    lines.extend([
        "",
        "## 2. 불필요하거나 중복된 Label/Relation 후보",
        "",
        "### 같은 속성 구조를 공유하는 라벨",
    ])
    if cleanup["duplicate_label_shapes"]:
        for item in cleanup["duplicate_label_shapes"]:
            labels = ", ".join(item["labels"])
            props = ", ".join(item["shared_properties"])
            lines.append(f"- {labels}: `{props}`")
    else:
        lines.append("- 없음")

    lines.extend(["", "### 같은 관계 패턴인데 속성 구조가 다른 관계"])
    if cleanup["duplicate_relation_patterns"]:
        for item in cleanup["duplicate_relation_patterns"]:
            lines.append(
                f"- ({item['from_label']})-[:{item['rel_type']}]->({item['to_label']})"
            )
    else:
        lines.append("- 없음")

    lines.extend(["", "### 낮은 신호로 분리할 관계"])
    low_signal = sorted({item["rel_type"] for item in cleanup["low_signal_relations"]})
    lines.append(_render_list(low_signal))

    lines.extend(["", "### Entity-Entity 관계 타입"])
    if cleanup["entity_to_entity_relation_types"]:
        for rel_type, count in cleanup["entity_to_entity_relation_types"].items():
            lines.append(f"- {rel_type}: {count}")
    else:
        lines.append("- 없음")

    lines.extend([
        "",
        "## 3. Entity를 Team/Player/Champion 등으로 정규화할 기준",
        "",
        f"- 이름 우선순위: {', '.join(normalization['canonical_property_priority'])}",
        "",
        "### 정규화 규칙",
    ])
    for item in normalization["criteria"]:
        lines.append(f"- {item['target']}: {item['rule']}")

    lines.extend(["", "### 관계명 기반 타입 힌트"])
    if normalization["relation_hints"]:
        for item in normalization["relation_hints"]:
            lines.append(
                f"- {item['rel_type']}: {item['source_label']} -> {item['target_label']}"
            )
    else:
        lines.append("- 현재 CSV에서 타입 힌트로 쓸 관계가 뚜렷하게 보이지 않음")

    lines.extend(["", "## 4. 기사별 그래프와 전체 통합 그래프 분리 기준"])
    for graph_name, graph in separation.items():
        lines.extend([
            "",
            f"### {graph_name}",
            f"- 목적: {graph['purpose']}",
            f"- 사용처: {graph['query_use']}",
            f"- 라벨: {', '.join(graph['labels'])}",
            "- 주요 관계:",
        ])
        lines.append(_render_list(graph["main_relations"]))

    lines.extend([
        "",
        "## 5. Community Summary 노드를 추가할 위치",
        "",
        "### 새 노드",
    ])
    for label, props in community["new_nodes"].items():
        lines.append(f"- {label}: {', '.join(props)}")

    lines.extend(["", "### 연결 대상"])
    for name, labels in community["connect_to"].items():
        lines.append(f"- {name}: {', '.join(labels)}")

    lines.extend(["", "### 추천 관계"])
    lines.append(_render_list(community["recommended_relations"]))

    lines.extend(["", "### 생성 순서"])
    lines.append(_render_list(community["build_order"]))

    lines.extend(["", "## 참고 Cypher 템플릿"])
    for name, query_lines in plan["cypher_templates"].items():
        lines.extend(["", f"### {name}", "```cypher"])
        lines.extend(query_lines)
        lines.append("```")

    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(
        description="Analyze Neo4j CSV exports and produce a GraphRAG schema plan."
    )
    parser.add_argument("--node-counts", type=Path, default=_find_default_file("node_counts"))
    parser.add_argument("--node-properties", type=Path, default=_find_default_file("node_properties"))
    parser.add_argument("--relationships", type=Path, default=_find_default_file("relationships"))
    parser.add_argument("--out-json", type=Path, default=Path("graphrag_schema_plan.json"))
    parser.add_argument("--out-md", type=Path, default=Path("graphrag_schema_plan.md"))

    args = parser.parse_args()

    for path in (args.node_counts, args.node_properties, args.relationships):
        if not path.exists():
            raise FileNotFoundError(f"CSV 파일을 찾지 못했습니다: {path}")

    plan = build_plan(args.node_counts, args.node_properties, args.relationships)

    args.out_json.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    args.out_md.write_text(_render_markdown(plan), encoding="utf-8")

    print("GraphRAG schema plan generated")
    print("JSON:", args.out_json.resolve())
    print("Markdown:", args.out_md.resolve())


if __name__ == "__main__":
    main()
