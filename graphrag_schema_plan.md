# Neo4j GraphRAG Schema Plan

## 1. 현재 Neo4j 구조 파악

### 입력 파일
- node_counts: `C:\Users\USER\OneDrive\문서\카카오톡 받은 파일\neo4j_query_table_data_2026-6-27.csv`
- node_properties: `C:\Users\USER\OneDrive\문서\카카오톡 받은 파일\neo4j_query_table_data_2026-6-27 (1).csv`
- relationships: `C:\Users\USER\OneDrive\문서\카카오톡 받은 파일\neo4j_query_table_data_2026-6-27 (2).csv`

### 노드 수
- SourceEvidence: 3526
- Entity: 1458
- ArticleChunk: 698
- Article: 634
- Game: 555
- Match: 209
- Champion: 138
- Alias: 103
- Player: 68
- Team: 10
- Tournament: 5
- League: 1

### 라벨 레이어
- domain: Champion, Game, League, Match, Player, Team, Tournament
- extracted/entity: Coach, Entity, Event, GameEntity, Group, Item, Object, Objective, Role, Spell, Stage, Structure, Venue
- source/evidence: Alias, Article, ArticleChunk, SourceEvidence

## 2. 불필요하거나 중복된 Label/Relation 후보

### 같은 속성 구조를 공유하는 라벨
- Coach, Entity, Event, GameEntity, Group, Item, Object, Objective, Role, Spell, Stage, Structure, Venue: `canonical_name, created_at, entity_id, entity_type, from_mysql, name`

### 같은 관계 패턴인데 속성 구조가 다른 관계
- (Entity)-[:CAPTURED]->(Entity)
- (Entity)-[:COACHES]->(Entity)
- (Entity)-[:DEFEATED]->(Entity)
- (Entity)-[:MEMBER_OF]->(Entity)
- (Entity)-[:MENTIONED_WITH]->(Entity)
- (Entity)-[:PARTICIPATED_IN]->(Entity)
- (Entity)-[:PLAYED]->(Entity)
- (Entity)-[:PLAYS_ROLE]->(Entity)
- (Entity)-[:USED]->(Entity)

### 낮은 신호로 분리할 관계
- HAS_ALIAS
- HAS_CHUNK
- HAS_EVIDENCE
- MENTIONED_WITH
- RELATED_TO
- SAME_AS
- SUPPORTS

### Entity-Entity 관계 타입
- ANNOUNCED: 1
- BENCHED: 1
- CAPTURED: 2
- COACHES: 2
- COMPETES_WITH: 1
- DEFEATED: 2
- DEFEATED_BY: 1
- IS_PART_OF: 1
- MEMBER_OF: 2
- MENTIONED_WITH: 2
- PARTICIPATED_IN: 2
- PLAYED: 2
- PLAYS_ROLE: 2
- RELATED_TO: 1
- RE_SIGNED_WITH: 1
- SAME_AS: 1
- STARTED_OVER: 1
- TRANSFERRED_TO: 1
- USED: 2

## 3. Entity를 Team/Player/Champion 등으로 정규화할 기준

- 이름 우선순위: canonical_name, team_name, player_name, champion_name, tournament_name, league_name, name

### 정규화 규칙
- Team: 팀 alias나 canonical_name이 Team.team_name/name과 일치하면 Team으로 승격한다.
- Player: 선수 alias, 실명, canonical_name이 Player 이름과 일치하면 Player로 승격한다.
- Champion: 챔피언 이름과 alias가 일치하면 Champion으로 승격한다.
- Tournament: 시즌/스플릿/대회명이 들어간 엔티티는 Tournament로 승격한다.

### 관계명 기반 타입 힌트
- MEMBER_OF: Player -> Team
- COACHES: Coach -> Team
- PICKED_CHAMPION: Player -> Champion
- PICKED_IN: Champion -> Game
- PLAYED_IN: Player -> Game
- PLAYED_GAME: Team -> Game
- PLAYED_MATCH: Team -> Match
- WON_GAME: Team -> Game
- WON_MATCH: Team -> Match
- PART_OF_MATCH: Game -> Match
- PART_OF_TOURNAMENT: Match -> Tournament
- BELONGS_TO_LEAGUE: Tournament -> League

## 4. 기사별 그래프와 전체 통합 그래프 분리 기준

### article_graph
- 목적: 관계가 어느 기사/청크에서 나왔는지 추적하는 근거 그래프
- 사용처: 출처 확인, 특정 기사별 관계 확인, 답변 근거 표시
- 라벨: Alias, Article, ArticleChunk, SourceEvidence
- 주요 관계:
- Article-[:HAS_CHUNK]->ArticleChunk
- Article-[:HAS_EVIDENCE]->SourceEvidence
- ArticleChunk-[:SUPPORTS]->SourceEvidence

### global_graph
- 목적: 정규화된 LCK 도메인 지식그래프
- 사용처: 선수/팀/대회 중심 Local Search
- 라벨: Champion, Coach, Entity, Event, Game, GameEntity, Group, Item, League, Match, Object, Objective, Player, Role, Spell, Stage, Structure, Team, Tournament, Venue
- 주요 관계:
- Team/Player/Champion/Match/Game/Tournament 중심의 정규화 관계
- 관계 속성에 article_id, confidence, raw_relation_type 보존

### community_summary_graph
- 목적: 여러 기사에서 반복되는 관계 묶음을 요약한 상위 그래프
- 사용처: 전체 이슈/흐름 질문 Global Search
- 라벨: Community, CommunitySummary
- 주요 관계:
- CONTAINS_ENTITY
- SUPPORTED_BY
- SUMMARIZES
- PART_OF_COMMUNITY

## 5. Community Summary 노드를 추가할 위치

### 새 노드
- Community: community_id, title, summary, level, entity_count, article_count, created_at
- CommunitySummary: summary_id, community_id, summary, source, created_at

### 연결 대상
- entities: Champion, Coach, Entity, Event, Game, GameEntity, Group, Item, League, Match, Object, Objective, Player, Role, Spell, Stage, Structure, Team, Tournament, Venue
- evidence: ArticleChunk, SourceEvidence, Article

### 추천 관계
- Community-[:CONTAINS_ENTITY {weight, rank}]->Entity/Team/Player/Champion
- Community-[:SUPPORTED_BY]->ArticleChunk
- Community-[:SUMMARIZES]->CommunitySummary
- Community-[:PART_OF_COMMUNITY]->Community

### 생성 순서
- 정규화된 global graph에서 커뮤니티 탐지 결과를 만든다.
- community_id별 핵심 Entity와 관련 ArticleChunk를 모은다.
- LLM으로 community summary를 생성한다.
- Community와 CommunitySummary 노드를 Neo4j에 저장한다.

## 참고 Cypher 템플릿

### constraints
```cypher
CREATE CONSTRAINT article_id IF NOT EXISTS FOR (n:Article) REQUIRE n.article_id IS UNIQUE;
CREATE CONSTRAINT chunk_id IF NOT EXISTS FOR (n:ArticleChunk) REQUIRE n.chunk_id IS UNIQUE;
CREATE CONSTRAINT team_id IF NOT EXISTS FOR (n:Team) REQUIRE n.team_id IS UNIQUE;
CREATE CONSTRAINT player_id IF NOT EXISTS FOR (n:Player) REQUIRE n.player_id IS UNIQUE;
CREATE CONSTRAINT champion_id IF NOT EXISTS FOR (n:Champion) REQUIRE n.champion_id IS UNIQUE;
CREATE CONSTRAINT community_id IF NOT EXISTS FOR (n:Community) REQUIRE n.community_id IS UNIQUE;
```

### promote_entity_to_domain_label
```cypher
// Team 부분을 Player, Champion 등 목표 라벨로 바꿔서 사용한다.
MATCH (e:Entity {canonical_name: $canonical_name})
SET e:Team
SET e.normalized_from_entity = true
```

### create_community
```cypher
MERGE (c:Community {community_id: $community_id})
SET c.title = $title,
    c.summary = $summary,
    c.level = $level,
    c.entity_count = $entity_count,
    c.article_count = $article_count,
    c.created_at = datetime()
```

### link_community_entity
```cypher
MATCH (c:Community {community_id: $community_id})
MATCH (e {canonical_name: $canonical_name})
MERGE (c)-[r:CONTAINS_ENTITY]->(e)
SET r.weight = $weight, r.rank = $rank
```

### link_community_evidence
```cypher
MATCH (c:Community {community_id: $community_id})
MATCH (chunk:ArticleChunk {chunk_id: $chunk_id})
MERGE (c)-[:SUPPORTED_BY]->(chunk)
```
