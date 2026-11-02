"""
Neo4j/GraphRAG schema rules used by analysis and query code.

이 파일은 DB를 직접 수정하지 않는다. 현재 그래프를 어떤 레이어로 볼지,
어떤 라벨/관계를 정규화 대상으로 볼지 정의하는 기준표다.
"""

SOURCE_LABELS = {
    "Article",
    "ArticleChunk",
    "SourceEvidence",
    "Alias",
}

DOMAIN_LABELS = {
    "League",
    "Tournament",
    "Match",
    "Game",
    "Team",
    "Player",
    "Champion",
}

EXTRACTION_ENTITY_LABELS = {
    "Entity",
    "Coach",
    "Event",
    "GameEntity",
    "Group",
    "Item",
    "Object",
    "Objective",
    "Role",
    "Spell",
    "Stage",
    "Structure",
    "Venue",
}

COMMUNITY_LABELS = {
    "Community",
    "CommunitySummary",
}

EVIDENCE_RELATIONS = {
    "HAS_CHUNK",
    "HAS_EVIDENCE",
    "SUPPORTS",
    "HAS_ALIAS",
}

GENERIC_RELATIONS = {
    "MENTIONS",
    "MENTIONED_WITH",
    "RELATED_TO",
    "SAME_AS",
    "HAS_EXTRACTED_RELATION",
}

LOW_SIGNAL_RELATIONS = EVIDENCE_RELATIONS | GENERIC_RELATIONS

QUERY_EXCLUDED_LABELS = sorted(SOURCE_LABELS)
QUERY_EXCLUDED_RELATIONS = sorted(LOW_SIGNAL_RELATIONS)

NORMALIZATION_TARGET_LABELS = {
    "team": "Team",
    "player": "Player",
    "champion": "Champion",
    "league": "League",
    "tournament": "Tournament",
    "match": "Match",
    "game": "Game",
    "coach": "Coach",
    "objective": "Objective",
    "role": "Role",
}

NORMALIZATION_RELATION_HINTS = {
    "MEMBER_OF": {"source": "Player", "target": "Team"},
    "COACHES": {"source": "Coach", "target": "Team"},
    "PICKED_CHAMPION": {"source": "Player", "target": "Champion"},
    "PICKED_IN": {"source": "Champion", "target": "Game"},
    "PLAYED_IN": {"source": "Player", "target": "Game"},
    "PLAYED_GAME": {"source": "Team", "target": "Game"},
    "PLAYED_MATCH": {"source": "Team", "target": "Match"},
    "WON_GAME": {"source": "Team", "target": "Game"},
    "WON_MATCH": {"source": "Team", "target": "Match"},
    "PART_OF_MATCH": {"source": "Game", "target": "Match"},
    "PART_OF_TOURNAMENT": {"source": "Match", "target": "Tournament"},
    "BELONGS_TO_LEAGUE": {"source": "Tournament", "target": "League"},
}

ARTICLE_GRAPH_LABELS = {
    "Article",
    "ArticleChunk",
    "SourceEvidence",
}

GLOBAL_GRAPH_LABELS = DOMAIN_LABELS | EXTRACTION_ENTITY_LABELS

COMMUNITY_GRAPH_SCHEMA = {
    "node_label": "Community",
    "summary_label": "CommunitySummary",
    "properties": [
        "community_id",
        "title",
        "summary",
        "level",
        "entity_count",
        "article_count",
        "created_at",
    ],
    "relations": [
        "CONTAINS_ENTITY",
        "SUPPORTED_BY",
        "SUMMARIZES",
        "PART_OF_COMMUNITY",
    ],
}

# 그래프 패널 시각화용 제외 기준. QUERY_EXCLUDED_* 는 다른 코드가 쓰므로 그대로 둔다.
# Game 은 Match 단위로만 보여 주기 위해, ArticleClaim 은 엔티티 간 간선으로 펴서 보내기 위해 뺀다.
VISUAL_EXCLUDED_LABELS = sorted(SOURCE_LABELS | {"Game", "ArticleClaim"})
VISUAL_EXCLUDED_RELATIONS = sorted(LOW_SIGNAL_RELATIONS | {"ASSERTS", "SOURCE_ENTITY", "TARGET_ENTITY", "PLAYED_ON", "PART_OF_MATCH"})
