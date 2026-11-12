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
- 벡터 DB 재빌드: `docker compose stop api && docker compose run --rm api python -m scripts.build_vector_db --rebuild && docker compose start api` (api 가 떠 있는 동안 같은 볼륨에 쓰면 ChromaDB 가 두 프로세스에서 열리므로 먼저 멈춘다)
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

### 그래프의 핵심 노드(시드) 고르기

지식그래프 검색은 질문 키워드에 맞는 핵심 노드를 먼저 고르고 그 1홉 이웃을 가져옵니다. 핵심 노드 규칙은 `app/search/neo4j_query.py` 에 있습니다.

- 후보는 `Entity` 라벨이 붙은 개체(팀, 선수, 챔피언, 스태프, 대회, 오브젝트 등)뿐입니다. 경기, 팬 댓글, 팬 영상은 이름에 팀 이름이나 댓글 본문이 들어 있어 후보에 넣으면 질문과 무관한 노드가 대량으로 잡히므로, 핵심 노드의 이웃으로만 나옵니다.
- 이름이나 별칭이 키워드와 정확히 같을 때만 핵심으로 봅니다(소문자, 공백 제거 후 비교). 정확히 같은 것이 하나도 없을 때만 부분 포함으로 다시 찾습니다.
- 숫자뿐인 키워드("2024", "5월")는 쓰지 않습니다. 연도는 날짜 범위로만 적용합니다.

핵심 노드가 팀이면 그 팀 소속으로 뛴 게임의 픽을 세어 많이 쓴 (선수, 챔피언) 쌍을 함께 가져옵니다. 픽은 팀이 아니라 선수에 붙어 있어 1홉만으로는 챔피언이 나오지 않기 때문입니다. 질문이 전략·밴픽·챔피언을 묻으면 경기를 최근 8개씩으로 줄이고 픽을 20쌍으로 늘리며, 그 외에는 경기 20개씩에 픽 8쌍입니다. 경기는 최근 것부터 담습니다.

기사·그래프·통계 세 경로는 서로의 결과를 쓰지 않으므로 동시에 실행합니다. 로그의 `DEBUG timing` 줄에 경로별 시간과 동시 실행 시간이 찍힙니다.

### 범위 되묻기 (한 번)

"T1의 전략이 궁금해"처럼 시즌·대회에 따라 답이 달라지는데 범위가 없는 질문은 바로 답하지 않고 한 번 되묻습니다.
의도 분석(LLM #1)이 `needs_scope`·`scope_axis` 를 함께 내고, 질문에 연도·시즌·대회 토큰이 없으면 나머지 검색과 LLM 호출을 건너뛰고
아래 응답을 돌려줍니다. 선택지는 MySQL `tournament`·`season` 테이블에 실제 있는 이름만 최신순으로 넣습니다.

```json
{ "type": "clarify", "question": "T1의 전략이 궁금해", "intent": "...",
  "clarify": { "axis": "tournament", "prompt": "어느 대회 기준으로 알아볼까요?", "options": ["2026 LCK Rounds 3-4", "..."] } }
```

프론트는 고른 선택지를 응답의 `template` 대로 질문에 붙여(`T1의 전략이 궁금해 (2025 LCK Cup 기준)`)
`{"question": "...", "skip_clarify": true, "scope": {"axis": "tournament", "value": "2025 LCK Cup"}}` 로 다시 보냅니다.
`skip_clarify` 가 true 면 항상 답하므로 되묻기는 질문당 한 번입니다. 일반 답변 응답에는 `"type": "answer"` 가 붙습니다.

되묻는 축(`axis`)과 선택지 출처:

| axis | 언제 | 선택지 |
|---|---|---|
| `tournament` | 전략·성적·밴픽인데 대회가 없다 | `tournament` 테이블 |
| `season` | 로스터·소속인데 연도가 없다 | `season` 테이블 |
| `opponent` | 전적·맞대결인데 상대 팀이 없다 | `team` (주체 팀 제외) |
| `stage` | 대회는 있는데 정규/플레이오프가 없다 | `tournamentstage` |
| `champion` | 선수 챔피언 통계인데 챔피언이 없다 | 그 선수가 쓴 챔피언 상위 10 (`gameparticipant`) |
| `patch` | 메타·밸런스인데 패치가 없다 | `patch` 최신 8개 |
| `topic` | 팀·선수 이름만 있다 | 고정 목록(팀: 성적·로스터·전략·최근 소식, 선수: 챔피언·성적·소속 이력·최근 기사) |

"요즘·최근·현재·지금·올해·이번" 이 있으면 되묻지 않고 질문에 최신 시즌을 붙여 답합니다.
질문에 연도가 적혀 있으면("2024 티원 전략") 되묻지 않고 그 해를 날짜 범위로 씁니다. 연도가 여러 개면 가장 이른 해부터 가장 늦은 해까지입니다.
`scope` 는 검색에도 적용됩니다. 시즌·대회·패치는 경기(Neo4j Match 노드), 날짜가 있는 관계(소속 기간, 픽, 기사 관계), 기사의 날짜 범위로, 상대 팀·챔피언은 그래프 검색 키워드로 씁니다.
기사 데이터는 현재 2025년 것만 있어서 다른 해를 고르면 기사 근거가 비는 게 정상입니다.
판정 규칙은 `app/clarify.py`, 설계는 `docs/specs/2026-11-03-clarify-design.md` 에 있습니다.

## 디렉터리 구성

```text
Backend/
├── app/                      # API 서버와 질의응답 파이프라인 (서버가 import 하는 코드만)
│   ├── api_server.py         # FastAPI 서버. POST /ask, GET /node
│   ├── pipeline.py           # 질의응답 파이프라인 오케스트레이터
│   ├── clarify.py            # 범위 되묻기 판정과 선택지
│   ├── llm/
│   │   └── clova_extract.py  # HyperCLOVA X 호출(의도 분석, 엔티티 추출, 답변 생성, Text-to-SQL)
│   ├── search/
│   │   ├── neo4j_query.py    # Neo4j 그래프 검색, 노드 상세
│   │   ├── rag_answer.py     # ChromaDB 기사 검색 + 기사 기반 답변
│   │   ├── rdb_query.py      # MySQL(espo) 통계 검색 (고정 쿼리 + Text-to-SQL)
│   │   └── kg_answer.py      # 그래프 기반 답변 단독 호출
│   ├── db/
│   │   ├── connect.py        # Neo4j 드라이버
│   │   ├── mysql_connect.py  # MySQL 연결
│   │   └── chroma_client.py  # ChromaDB 클라이언트, 임베딩 모델
│   └── common/
│       ├── text_utils.py     # HTML 엔티티 정리 등 문자열 유틸
│       ├── chunk.py          # 텍스트 청킹
│       └── graph_schema_config.py  # 그래프 스키마 기준표 (시각화 제외 라벨·관계)
├── scripts/                  # 오프라인 구축·점검 스크립트 (저장소 루트에서 python -m 으로 실행)
│   ├── paths.py              # data/·docs/ 경로 상수
│   ├── build_vector_db.py    # MySQL article → ChromaDB (컨테이너 기동 시 자동 실행)
│   ├── build_graph.py        # 기사 → 청크 → 엔티티 추출 → Neo4j 적재
│   ├── neo4j_extract.py      # 추출 결과 Neo4j 저장
│   ├── dictionary.py         # 별칭 정규화 사전 로더
│   ├── make_vector_data.py   # 기사 청크 JSON 생성
│   ├── news_api.py           # 빅카인즈 뉴스 API 수집
│   ├── graphrag_schema_planner.py  # 그래프 스키마 정리 계획 생성기
│   ├── sqlite/               # SQLite(lck_kg.db) 기사 적재용 보조 스크립트
│   └── manual/               # 사람이 직접 돌려 보는 확인 스크립트 (pytest 대상 아님)
├── data/                     # 데이터 파일 (기사 원본, 별칭 사전, 옛 MySQL 덤프, SQLite 등)
├── tests/                    # pytest 단위 테스트
└── docs/                     # 설계 문서, 계획서, 스키마 정리 계획
```

MySQL 컨테이너가 적재하는 덤프는 저장소 밖 상위 폴더의 `Dump20261027.sql` 입니다(`docker-compose.yml`). `data/Dump_Espo.sql` 은 이전 스키마 덤프입니다.

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
| `NEO4J_URI`, `NEO4J_USER`(또는 Aura 형식 `NEO4J_USERNAME`), `NEO4J_PASSWORD`, `NEO4J_DATABASE` | Neo4j 연결 정보 |
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
mysql -u root -p espo < ../Dump20261027.sql
python -m app.db.mysql_connect   # 연결 확인
```

#### 2. 벡터 DB(ChromaDB) 구축

MySQL `article` 테이블의 기사를 읽어 만들므로 1번이 먼저 끝나 있어야 합니다.

```bash
python -m scripts.build_vector_db --rebuild      # MySQL article → ./chroma_db (CHROMA_PATH 로 경로 변경)
python -m scripts.manual.check_vector_search     # 검색 확인
```

`--if-missing` 을 주면 완료 마커(`chroma_db/.complete`)의 기사 건수가 현재와 같을 때 건너뜁니다.

#### 3. 지식그래프(Neo4j) 구축

기사를 청킹하고 HyperCLOVA 로 엔티티·관계를 추출해 Neo4j 에 적재합니다. LLM 호출이 많아 시간이 오래 걸립니다.

```bash
python -m scripts.build_graph
python -m scripts.manual.check_neo4j_query   # 조회 확인
```

### 서버 실행

```bash
uvicorn app.api_server:app --host 0.0.0.0 --port 8000 --reload
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
| `graph` | 프론트엔드 시각화용 그래프. `nodes`(id, name, label, degree, is_seed, match_date, props) / `links`(source, target, type, evidence, when). `when` 은 그 관계가 성립한 때의 `[시작일, 종료일]` 구간 목록이다(소속·코치는 기간, 픽은 경기 날짜, 기사 관계는 발행일). 날짜를 모르면 `null` |
| `timeline` | 날짜 스트립용 대회 띠. `tournaments`(name, start, end). 그래프의 경기 기간과 겹치는 대회만, 실제 경기 날짜 기준으로 담는다. 경기가 없거나 조회가 실패하면 빈 목록 |
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
