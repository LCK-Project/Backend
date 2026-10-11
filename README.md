# LCK Knowledge Graph Backend

LCK(리그 오브 레전드 챔피언스 코리아) 뉴스 기사를 기반으로 한 하이브리드 질의응답 백엔드입니다.
질문 하나에 대해 **기사 벡터 검색(ChromaDB) + 지식그래프(Neo4j) + 정형 통계(MySQL)** 세 경로의 근거를 모아
HyperCLOVA X 로 최종 답변을 생성하고, FastAPI 로 제공합니다.
프론트엔드는 [LCK-Project/Frontend](https://github.com/LCK-Project/Frontend) 레포에 있습니다.

## 빠른 시작(Docker)

Docker Desktop(또는 Docker Engine + Compose)만 있으면 API 서버와 MySQL 이 함께 뜹니다.

```bash
git clone https://github.com/LCK-Project/Backend.git
cd Backend
cp .env.example .env
```

`.env` 에서 아래 값을 채웁니다. MySQL 계정은 root 고정이며 `MYSQL_PASSWORD` 가 비어 있으면 compose 가 바로 멈춥니다.

- Neo4j: `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`
- HyperCLOVA X: `CLOVA_API_KEY`, `CLOVA_APP_TYPE`, `CLOVA_MODEL`
- MySQL: `MYSQL_PASSWORD` (컨테이너의 root 비밀번호가 됩니다)

```bash
docker compose up --build
```

첫 기동은 MySQL 덤프 복원, 임베딩 모델 다운로드, 기사 임베딩 때문에 5~10분 걸리고 그동안 8000 포트는 닫혀 있습니다.
벡터 DB 와 모델 캐시는 볼륨에 남으므로 다음 기동부터는 바로 뜹니다. 확인은 `curl localhost:8000/` 입니다.

- 포트 바꾸기: `.env` 에 `MYSQL_HOST_PORT`(기본 3307), `API_HOST_PORT`(기본 8000)
- 벡터 DB 재빌드: `docker compose stop api && docker compose run --rm api python build_vector_db.py --rebuild && docker compose start api` (api 가 떠 있는 동안 같은 볼륨에 쓰면 ChromaDB 가 두 프로세스에서 열리므로 먼저 멈춘다)
- 전부 초기화: `docker compose down -v` (MySQL·벡터 DB·모델 캐시 볼륨 삭제)

## 답변 흐름

```text
질문
 └→ [LLM #1] 의도 분석 → {의도, 키워드}
      ├→ ChromaDB 기사 검색 → [LLM #2] 기사 기반 답변
      ├→ Neo4j 관계 검색    → [LLM #3] 그래프 기반 답변 + 그래프 데이터
      └→ MySQL(espo) 통계   → [LLM #4] RDB 통계 기반 답변
           └→ [LLM #5] 세 답변 통합 → 최종 답변
```

## 디렉터리 구성

| 파일 | 역할 |
|------|------|
| `api_server.py` | FastAPI 서버. `POST /ask` 엔드포인트 |
| `pipeline.py` | 질의응답 파이프라인 오케스트레이터 |
| `clova_extract.py` | HyperCLOVA X 호출(의도 분석, 엔티티 추출, 답변 생성, Text-to-SQL) |
| `rag_answer.py` | ChromaDB 기사 검색 + 기사 기반 답변 |
| `neo4j_query.py`, `kg_answer.py` | Neo4j 그래프 검색 + 그래프 기반 답변 |
| `rdb_query.py`, `mysql_connect.py` | MySQL(espo) 통계 검색 |
| `connect.py`, `neo4j_extract.py` | Neo4j 연결 및 추출 결과 저장 |
| `main.py` | 기사 → 청크 → 엔티티 추출 → Neo4j 적재 (그래프 구축 스크립트) |
| `make_vector_data.py`, `build_vector_db.py` | 기사 청킹 → 임베딩 → ChromaDB 구축 |
| `chunk.py`, `dictionary.py`, `alias_dictionary.csv` | 텍스트 청킹, 별칭 정규화 사전 |
| `graph_schema_config.py`, `graphrag_schema_planner.py` | 그래프 스키마 기준표와 정리 계획 생성기 (`docs/` 참고) |
| `news_api.py` | 빅카인즈 뉴스 API 수집 |
| `schema.sql`, `create_rdb.py`, `insert_articles_to_rdb.py`, `check_rdb.py` | SQLite(`lck_kg.db`) 기사 적재용 보조 스크립트 |
| `Dump_Espo.sql` | MySQL `espo` 데이터베이스 덤프(선수/팀/경기 통계) |
| `kmib_lck_yunminsop.json` | 수집된 기사 원본 데이터 |
| `test_*.py` | 각 모듈 단독 확인용 스크립트 |

## 사전 준비

- Python 3.10 이상
- Neo4j (Aura 또는 로컬 인스턴스)
- MySQL 8.x
- NAVER HyperCLOVA X API 키
- (선택) 빅카인즈 뉴스 API 키. 기사 수집을 새로 할 때만 필요합니다.

## 환경변수

`.env.example` 을 복사해 `.env` 를 만들고 값을 채웁니다.

```bash
cp .env.example .env
```

| 변수 | 설명 |
|------|------|
| `CLOVA_API_KEY`, `CLOVA_APP_TYPE`, `CLOVA_MODEL` | HyperCLOVA X 인증 정보. 기본 모델은 `HCX-007` |
| `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_DATABASE` | Neo4j 연결 정보 |
| `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE` | MySQL(espo) 연결 정보 |
| `NEWS_API_ACCESS_KEY` | 빅카인즈 API 키 (기사 수집 시에만) |
| `CORS_ORIGINS` | 허용할 프론트엔드 origin. 쉼표로 여러 개 지정, 기본값 `*` |

## Docker 없이 실행

호스트의 Python 가상환경에서 직접 실행할 때의 절차입니다. 위 "사전 준비"와 "환경변수"를 먼저 마칩니다.

### 설치

```bash
git clone https://github.com/LCK-Project/Backend.git
cd Backend

python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

`sentence-transformers` 설치 시 PyTorch 가 함께 받아지므로 시간이 걸릴 수 있습니다.
임베딩 모델 `jhgan/ko-sroberta-multitask` 는 최초 실행 시 자동으로 다운로드됩니다.

### 데이터 준비

처음 한 번만 수행합니다. 이미 구축된 DB 가 있으면 건너뜁니다.

#### 1. MySQL 통계 DB 복원

```bash
mysql -u root -p -e "CREATE DATABASE espo CHARACTER SET utf8mb4;"
mysql -u root -p espo < Dump_Espo.sql
python mysql_connect.py        # 연결 확인
```

#### 2. 벡터 DB(ChromaDB) 구축

MySQL `article` 테이블의 기사를 읽어 만들므로 1번이 먼저 끝나 있어야 합니다.

```bash
python build_vector_db.py --rebuild   # MySQL article → ./chroma_db (CHROMA_PATH 로 경로 변경)
python test_vector_search.py          # 검색 확인
```

`--if-missing` 을 주면 완료 마커(`chroma_db/.complete`)의 기사 건수가 현재와 같을 때 건너뜁니다.

#### 3. 지식그래프(Neo4j) 구축

기사를 청킹하고 HyperCLOVA 로 엔티티·관계를 추출해 Neo4j 에 적재합니다. LLM 호출이 많아 시간이 오래 걸립니다.

```bash
python main.py
python test_neo4j_query.py     # 조회 확인
```

### 서버 실행

```bash
uvicorn api_server:app --host 0.0.0.0 --port 8000 --reload
```

- 상태 확인: `GET http://localhost:8000/`
- API 문서: `http://localhost:8000/docs`

#### 질의 예시

```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "젠지 우승 요인을 알려줘"}'
```

응답 주요 필드:

| 필드 | 내용 |
|------|------|
| `answer` | 최종 통합 답변 |
| `article_answer`, `graph_answer`, `rdb_answer` | 경로별 개별 답변 |
| `graph` | 프론트엔드 시각화용 그래프. `nodes`(id, name, label, degree, is_seed, match_date, props) / `links`(source, target, type, evidence) |
| `related_chunks`, `graph_facts` | 그래프에서 찾은 관계 근거. `graph_facts` 각 항목은 source, source_label, relation, target, target_label, evidence |
| `article_chunks` | 검색된 기사 청크 |
| `rdb_facts`, `rdb_entities`, `rdb_sql` | 통계 근거와 실행된 SQL |

#### 노드 상세 조회

그래프에서 노드를 고르면 그 노드의 1홉 관계를 묶어서 돌려줍니다. `id` 에는 `/ask` 응답의 `graph.nodes[].id` 를 넣습니다.

```bash
curl "localhost:8000/node?id=<graph.nodes[].id>"
```

응답 키:

| 키 | 내용 |
|------|------|
| `id`, `name`, `label` | 선택한 노드 |
| `degree` | 시각화 제외 라벨·관계를 뺀 DB 기준 1홉 차수 |
| `record` | Team·Player 이면 `{wins, losses}`(WON_MATCH·LOST_MATCH 수), 그 외 `null` |
| `match` | Match 이면 `match_stage, score_a, score_b, best_of, team_a_key, team_b_key, winner_key`, 그 외 `null` |
| `groups` | `(relation, direction)` 별 이웃 묶음. 이웃 수가 많은 순, 각 묶음 `neighbors`(id, name, label, role)는 이름순 최대 20개 |

노드가 없으면 `404 {"detail": "node not found"}` 를 돌려줍니다.

## 프론트엔드 연동

프론트엔드 레포의 `config.js` 에서 `window.API_BASE_URL` 을 이 서버 주소로 맞추면 됩니다.
다른 도메인에 배포할 경우 `.env` 의 `CORS_ORIGINS` 에 프론트엔드 주소를 넣어 주세요.
