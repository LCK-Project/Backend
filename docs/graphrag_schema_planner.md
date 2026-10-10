# GraphRAG Schema Planner

이 도구는 Neo4j에서 export한 CSV 3개를 읽어서 GraphRAG용 정리 계획을 만든다.
DB를 직접 수정하지 않고, Markdown/JSON 리포트만 생성한다.

## 입력 CSV

- 노드 개수 CSV: `label,count,sample_props`
- 라벨별 속성 CSV: `label,properties`
- 관계 구조 CSV: `from_label,rel_type,rel_props,to_label`

현재 카카오톡으로 받은 파일명 기준:

```text
neo4j_query_table_data_2026-6-27.csv
neo4j_query_table_data_2026-6-27 (1).csv
neo4j_query_table_data_2026-6-27 (2).csv
```

## 실행

파일이 `카카오톡 받은 파일` 폴더에 그대로 있으면:

```powershell
python graphrag_schema_planner.py
```

명시적으로 경로를 줄 때:

```powershell
python graphrag_schema_planner.py `
  --node-counts "C:\Users\USER\OneDrive\문서\카카오톡 받은 파일\neo4j_query_table_data_2026-6-27.csv" `
  --node-properties "C:\Users\USER\OneDrive\문서\카카오톡 받은 파일\neo4j_query_table_data_2026-6-27 (1).csv" `
  --relationships "C:\Users\USER\OneDrive\문서\카카오톡 받은 파일\neo4j_query_table_data_2026-6-27 (2).csv"
```

## 생성 파일

```text
graphrag_schema_plan.md
graphrag_schema_plan.json
```

리포트에는 아래 내용이 들어간다.

- 현재 Neo4j 구조 파악
- 불필요하거나 중복된 Label/Relation 후보
- Entity를 Team/Player/Champion 등으로 정규화할 기준
- 기사별 그래프와 전체 통합 그래프 분리 설계
- Community Summary 노드를 추가할 위치
- 참고 Cypher 템플릿

## 주의

`graphrag_schema_plan.md` 안의 Cypher는 바로 대량 실행하기보다 검토용 초안으로 사용한다.
특히 Entity를 Team/Player/Champion으로 승격하는 작업은 alias와 canonical_name 검증 후 단계적으로 적용한다.

