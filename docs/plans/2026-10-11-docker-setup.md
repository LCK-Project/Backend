# Docker 의존성 관리 + ChromaDB 구축 · 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Backend는 `.env` 채우고 `docker compose up --build`로 API + MySQL이 뜨며 첫 기동 때 MySQL `article` 테이블에서 ChromaDB를 자동 구축한다. Frontend는 `docker compose up --build`로 nginx가 뜨고 `API_BASE_URL`로 `config.js`를 생성한다.

**Architecture:** 레포마다 자기 Dockerfile과 compose(패턴 1). ChromaDB는 API 컨테이너 안의 파일 저장소로 두고 볼륨에 보존하며, 완료 마커로 부분 빌드를 막는다. MySQL 준비는 `article` 건수 healthcheck와 빌드 스크립트의 재시도 두 겹으로 보장한다. 기사 소스는 JSON에서 MySQL로 바꾼다.

**Tech Stack:** Docker Compose, `python:3.12-slim`, `mysql:8.4`, `nginx:alpine`, chromadb, sentence-transformers(CPU torch), pytest.

**Spec:** `/Users/doo._.hyun/Study/Project/lck/docs/2026-10-11-docker-setup-design.md` (저장소 밖 절대 경로. 3절 결정, 5절 구성 상세, 6절 검증)

## Global Constraints

- `.env`와 `*.sql`은 이미지에 들어가지 않는다(`.dockerignore`). `Dump_Espo.sql`은 compose bind mount로만 쓴다.
- MySQL 계정은 root 고정. `MYSQL_PASSWORD` 비면 compose가 `${VAR:?메시지}`로 즉시 실패.
- 컬렉션 이름 `lol_esports_articles`, 청킹 `split_text_overlap(content, 1000, 200)` 유지.
- 완료 기준은 컬렉션 `count()`가 아니라 완료 마커 `<CHROMA_PATH>/.complete`(`{"article_count": N, "chunk_count": M, "built_at": ISO}`)다.
- `requirements.txt`는 전부 `==` 핀. torch는 `--extra-index-url https://download.pytorch.org/whl/cpu`.
- 플랫폼 고정(`platform:`) 금지. Apple Silicon과 x86 둘 다 빌드돼야 한다.
- 커밋 메시지·주석은 한국어. 산문에 대시(—) 금지. 각 커밋 끝에 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.
- 백엔드 안 1 계획(터미널 B) 소유 파일은 건드리지 않는다(아래 표).

## Review Focus

1. `content`가 NULL 또는 빈 문자열인 기사: 청크 0개로 건너뛰고 `article_count`에는 세지 않는다. (Task 2 `test_make_chunks_skips_empty_content`)
2. `published_at`이 NULL인 기사: metadata에 `""`가 아닌 `None`을 넣으면 chromadb가 거부하므로 빈 문자열로 넣는다. (Task 2 `test_metadata_null_published_at_becomes_empty_string`)
3. 마커는 있는데 기사 건수가 달라진 경우(덤프 교체): 다시 빌드해야 한다. (Task 2 `test_should_build_when_count_differs`)
4. 빌드 중 컨테이너가 죽은 뒤 재기동: 마커가 없으므로 임시 컬렉션을 지우고 처음부터. (Task 4 검증 3-1)
5. `article` 0건이 5분 넘게 지속(덤프 복원 실패): 빌드를 건너뛰고 서버는 뜬다. `/ask`의 기사 경로만 비고 다른 경로는 동작. (Task 2 `test_wait_for_articles_gives_up_returns_zero`, Task 4 수동 확인)

---

## 실행 모델과 터미널 분할

메인 세션은 오케스트레이터다. Task 1(계획서 커밋)은 백엔드 계획의 Task 1과 같은 커밋이다. Backend 작업(Task 2~5)은 터미널 C, Frontend 작업(Task 6)은 터미널 D가 한다. 둘은 레포가 다르다. 터미널 C는 같은 Backend 레포의 터미널 B(안 1 백엔드)와 동시에 돌므로 파일 소유권을 지킨다.

| 소유 | 터미널 C(이 계획) | 터미널 B(안 1 백엔드 계획) |
|---|---|---|
| 수정 | `requirements.txt`, `Dockerfile`, `docker-compose.yml`, `entrypoint.sh`, `.dockerignore`, `.gitattributes`, `.env.example`, `chroma_client.py`, `build_vector_db.py`, `rag_answer.py`, `pipeline.py`, `test_vector_search.py`, `tests/test_vector_build.py`, `README.md`의 맨 위 "빠른 시작" 절과 "설치"·"데이터 준비" 절 | `neo4j_query.py`, `graph_schema_config.py`, `api_server.py`, `pytest.ini`, `tests/__init__.py`, `tests/stubs.py`, `tests/test_graph_*.py`, `tests/test_node_detail.py`, `README.md`의 "응답 주요 필드" 표와 "노드 상세 조회" 절 |
| 금지 | 오른쪽 열 전부 | 왼쪽 열 전부 |

`tests/__init__.py`와 `pytest.ini`는 B가 만든다. C는 `pytest tests/test_vector_build.py`를 경로로 직접 실행하므로 둘 없이도 돈다. 머지는 B 먼저, C가 rebase 후 `README.md` 충돌만 손으로 합친다.

| 웨이브 | 태스크 | 실행자 | 산출 |
|---|---|---|---|
| W0 | Task 1 계획서 커밋 | 오케스트레이터(Backend main) | 기점 `<BASE>` |
| W1 | Task 2~5 | 터미널 C (Opus 5.5) · worktree `Backend/.claude/worktrees/lck-docker` | 브랜치 `feat/docker-setup` |
| W1 | Task 6 | 터미널 D (Sonnet 5.5) · worktree `Frontend/.claude/worktrees/lck-docker-web` | 브랜치 `feat/docker-web` |
| W2 | 리뷰 → B 머지 → C rebase·머지 → D 머지 → 전체 검증 | 오케스트레이터 + 리뷰어(Opus 5.5) | 머지 커밋 |

사람 사전 조건 2줄: Backend·Frontend 각각 `git log --oneline -1`이 기점 커밋인지, `git status --short`가 비어 있는지. Docker Desktop이 실행 중인지.

## 파일 구조 (Backend)

| 파일 | 책임 |
|---|---|
| `chroma_client.py` | `CHROMA_PATH`·모델명·컬렉션명 상수, `get_client()`, `get_model()`(지연 로드), `marker_path()`, `read_marker()`, `write_marker()` |
| `build_vector_db.py` | MySQL → 청크 → 임베딩 → 컬렉션. `--if-missing`, `--rebuild`. 순수 부분은 함수로 분리 |
| `rag_answer.py` | `search_articles`가 dict 리스트 반환 |
| `pipeline.py` | `article_context`·`article_chunks`에 dict 사용 |
| `entrypoint.sh` | 빌드(실패 삼킴) → `exec uvicorn` |
| `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.gitattributes`, `.env.example`, `requirements.txt` | 설계 5-1절 |
| `tests/test_vector_build.py` | 순수 함수 테스트 |

`build_vector_db.py` 공개 시그니처:

```python
def make_chunks(articles: list[dict]) -> tuple[list[dict], int]
    # articles: MySQL 행 dict(article_id, news_id, title, content, published_at, url)
    # -> (chunks, article_count). chunk = {"id": f"article_{article_id}_chunk_{i}", "text": str,
    #    "metadata": {"article_id": int, "news_id": str, "title": str, "published_at": str, "url": str, "chunk_id": int}}
def should_build(marker: dict | None, article_count: int) -> bool
def wait_for_articles(count_fn, attempts: int = 30, interval_sec: float = 10.0, sleep_fn=time.sleep) -> int
    # count_fn() 이 0보다 크면 즉시 그 값, attempts 번 모두 0이면 0
def fetch_articles(conn) -> list[dict]        # SELECT article_id, news_id, title, content, published_at, url FROM article ORDER BY article_id
def build(collection, model, chunks: list[dict], batch_size: int = 32, log=print) -> int   # 추가한 청크 수
def main(argv) -> int                          # 0 정상, 2 인자 오류
```

`rag_answer.search_articles(question, top_k=3) -> list[dict]`, 각 항목 `{"text", "title", "published_at", "url", "article_id"}`.

---

### Task 1: 계획서 커밋 (오케스트레이터)

백엔드 계획의 Task 1과 동일한 커밋이다(두 계획서를 한 번에 커밋). 별도 작업 없음.

---

### Task 2: `chroma_client.py`와 `build_vector_db.py` 순수 함수 (TDD)

**Files:**
- Create: `chroma_client.py`, `tests/test_vector_build.py`
- Modify: `build_vector_db.py`(전면 재작성), `test_vector_search.py`(`chroma_client` 사용), `requirements.txt`(`pytest` 추가만. 핀은 Task 4)

**Interfaces:**
- Produces: 파일 구조 절의 시그니처. `chroma_client.CHROMA_PATH = os.getenv("CHROMA_PATH", "./chroma_db")`, `COLLECTION = "lol_esports_articles"`, `MODEL_NAME = "jhgan/ko-sroberta-multitask"`, `BUILDING_COLLECTION = "lol_esports_articles__building"`.

- [ ] **Step 1: 실패하는 테스트 작성** (`tests/test_vector_build.py`. chromadb·torch를 import하지 않도록 `build_vector_db`는 모델·클라이언트를 함수 안에서 지연 import한다)

```python
import build_vector_db as b

def row(i, content, published_at="2025-09-07 00:00:00", title="t", url="u", news_id="n"):
    return {"article_id": i, "news_id": news_id, "title": title, "content": content, "published_at": published_at, "url": url}

def test_make_chunks_ids_and_metadata():
    chunks, n = b.make_chunks([row(7, "가" * 1500)])
    assert n == 1 and [c["id"] for c in chunks] == ["article_7_chunk_0", "article_7_chunk_1"]
    assert chunks[0]["metadata"] == {"article_id": 7, "news_id": "n", "title": "t", "published_at": "2025-09-07 00:00:00", "url": "u", "chunk_id": 0}
    assert len(chunks[0]["text"]) == 1000 and chunks[1]["text"] == "가" * 700
def test_make_chunks_skips_empty_content():
    chunks, n = b.make_chunks([row(1, ""), row(2, None), row(3, "본문")])
    assert n == 1 and [c["id"] for c in chunks] == ["article_3_chunk_0"]
def test_metadata_null_published_at_becomes_empty_string():
    chunks, _ = b.make_chunks([row(1, "본문", published_at=None, url=None)])
    assert chunks[0]["metadata"]["published_at"] == "" and chunks[0]["metadata"]["url"] == ""
def test_metadata_datetime_published_at_is_isoformat():
    import datetime
    chunks, _ = b.make_chunks([row(1, "본문", published_at=datetime.datetime(2025, 9, 7, 0, 0))])
    assert chunks[0]["metadata"]["published_at"] == "2025-09-07T00:00:00"
def test_should_build_without_marker():
    assert b.should_build(None, 634) is True
def test_should_build_when_count_differs():
    assert b.should_build({"article_count": 634, "chunk_count": 1500, "built_at": "x"}, 642) is True
def test_should_not_build_when_marker_matches():
    assert b.should_build({"article_count": 634, "chunk_count": 1500, "built_at": "x"}, 634) is False
def test_wait_for_articles_returns_first_positive():
    calls = iter([0, 0, 5]); slept = []
    assert b.wait_for_articles(lambda: next(calls), attempts=5, interval_sec=1, sleep_fn=slept.append) == 5 and slept == [1, 1]
def test_wait_for_articles_gives_up_returns_zero():
    slept = []
    assert b.wait_for_articles(lambda: 0, attempts=3, interval_sec=2, sleep_fn=slept.append) == 0 and slept == [2, 2, 2]
def test_build_adds_in_batches_and_returns_count():
    class Coll:
        def __init__(self): self.calls = []
        def add(self, ids, embeddings, documents, metadatas): self.calls.append(len(ids))
    class Model:
        def encode(self, texts, batch_size=32): return [[0.0] for _ in texts]
    chunks = [{"id": str(i), "text": "x", "metadata": {}} for i in range(70)]
    coll = Coll(); assert b.build(coll, Model(), chunks, batch_size=32, log=lambda *_: None) == 70 and coll.calls == [32, 32, 6]
def test_main_rejects_both_flags():
    assert b.main(["--if-missing", "--rebuild"]) == 2
```

- [ ] **Step 2: `.venv/bin/pytest -q tests/test_vector_build.py` FAIL 확인**
- [ ] **Step 3: 구현**
  - `make_chunks`: `content`가 falsy면 건너뜀. `published_at`은 `datetime`이면 `.isoformat()`, None이면 `""`, 문자열이면 그대로. `url`·`title`·`news_id` None → `""`.
  - `should_build`: `marker is None or marker.get("article_count") != article_count`.
  - `main(argv)`: `--if-missing`/`--rebuild` 상호 배타(둘 다면 2). 흐름: `count = wait_for_articles(...)` → 0이면 경고 로그 `기사 0건, ChromaDB 빌드 건너뜀` 후 0 반환 → `--if-missing`이고 `not should_build(read_marker(), count)`면 `완료 마커 일치({count}건), 건너뜀` 로그 후 0 → 아니면 `BUILDING_COLLECTION` 삭제(있으면)·본 컬렉션 삭제(있으면)·마커 삭제 → `fetch_articles` → `make_chunks` → `build`(100청크마다 `진행 {done}/{total}` 로그) → `BUILDING_COLLECTION.modify(name=COLLECTION)` → `write_marker({...})` → `ChromaDB 빌드 완료: {M} 청크 / {N} 기사` 로그 → 0.
  - 모델·chromadb·pymysql import는 `main` 안에서 한다(테스트가 torch 없이 돌게).
  - `test_vector_search.py`는 `chroma_client.get_client()`·`get_model()`을 쓰도록만 바꾼다.
- [ ] **Step 4: `pytest -q tests/test_vector_build.py` 전부 PASS**
- [ ] **Step 5: 커밋**: `벡터DB 구축 재작성: MySQL 기사 소스, 완료 마커, 기사 대기·재시도`

---

### Task 3: `search_articles` 반환 형식과 호출처

**Files:**
- Modify: `rag_answer.py`, `pipeline.py`

**Interfaces:**
- Produces: `search_articles(question, top_k=3) -> list[dict]`(`text, title, published_at, url, article_id`). 컬렉션이 없으면 빈 리스트(예외 대신).
- `pipeline.run_pipeline`의 `article_chunks`는 이 dict 리스트. `article_context`는 `f"[참고자료 {i}] {title} ({published_at[:10]})\n{text}"`.

- [ ] **Step 1: `rag_answer.py`**: 모듈 import 시점의 모델·컬렉션 로드를 함수 안 지연 로드로 바꾼다(`chroma_client.get_model()`, `get_client().get_collection(COLLECTION)`을 try로 감싸 `ValueError`·`chromadb.errors.NotFoundError`면 `[]`). `query(..., include=["documents", "metadatas"])` 결과를 dict로 조립. `answer_question`은 `item["text"]`로 join.
- [ ] **Step 2: `pipeline.py`**: `_search_articles_safe` 그대로, `article_context` 조립을 위 형식으로. 반환 `article_chunks: docs`(dict 리스트) 유지.
- [ ] **Step 3: 수동 확인(로컬 venv, MySQL 3307 컨테이너 사용)**: `CHROMA_PATH=/tmp/lck-chroma .venv/bin/python build_vector_db.py --rebuild` → 로그 끝에 `ChromaDB 빌드 완료: N 청크 / 634 기사`, N ≥ 1,000. 이어서 `CHROMA_PATH=/tmp/lck-chroma .venv/bin/python -c "from rag_answer import search_articles as s; r=s('한화생명 우승'); print(len(r), r[0]['title'], r[0]['published_at'][:10])"` → 3건, 제목·날짜 출력. 출력 원문을 보고서에 붙인다.
- [ ] **Step 4: 커밋**: `기사 검색 결과에 제목·날짜·URL 메타데이터 포함`

---

### Task 4: Dockerfile, compose, entrypoint, 핀

**Files:**
- Create: `Dockerfile`, `docker-compose.yml`, `entrypoint.sh`, `.dockerignore`
- Modify: `requirements.txt`(전부 `==` 핀 + torch CPU 인덱스), `.gitattributes`(`*.sh text eol=lf` 추가), `.env.example`(MySQL 절 주석: root 고정, 비밀번호 필수, `MYSQL_HOST_PORT`·`API_HOST_PORT` 선택)

- [ ] **Step 1: `requirements.txt` 핀**: 현재 venv의 `pip freeze`에서 직접 의존 패키지(fastapi, uvicorn[standard], pydantic, python-dotenv, requests, neo4j, pymysql, chromadb, sentence-transformers, pandas, pytest, torch) 버전만 `==`로 적고, 첫 줄에 `--extra-index-url https://download.pytorch.org/whl/cpu`. torch는 `torch==<버전>+cpu`가 아니라 `torch==<버전>`으로 적는다(인덱스가 CPU 휠을 고른다).
- [ ] **Step 2: `.dockerignore`**: `.venv`, `chroma_db`, `__pycache__`, `*.pyc`, `.env`, `*.sql`, `kmib_lck_yunminsop.json`, `vector_data.json`, `lck_kg.db`, `.claude`, `.git`, `docs`, `tests`
- [ ] **Step 3: `Dockerfile`**: `FROM python:3.12-slim` → `WORKDIR /app` → `COPY requirements.txt .` → `RUN pip install --no-cache-dir -r requirements.txt` → `COPY . .` → `RUN chmod +x entrypoint.sh` → `ENV CHROMA_PATH=/data/chroma_db HF_HOME=/data/hf_cache` → `EXPOSE 8000` → `ENTRYPOINT ["./entrypoint.sh"]`
- [ ] **Step 4: `entrypoint.sh`**: `#!/bin/sh`, `set -u`, `python build_vector_db.py --if-missing || echo "[entrypoint] ChromaDB 빌드 실패, 기사 경로 없이 기동"`, `exec uvicorn api_server:app --host 0.0.0.0 --port 8000`
- [ ] **Step 5: `docker-compose.yml`**: 설계 5-1절의 YAML 그대로(healthcheck는 `article` 건수 조회, `${MYSQL_PASSWORD:?...}`, 호스트 포트 변수화).
- [ ] **Step 6: 검증(설계 6절 번호)**: 미리 `docker rm -f lck-mysql && docker volume rm lck-mysql-data`로 수동 컨테이너를 정리한다(같은 3307 포트).
  - 6-1: `.env`의 `MYSQL_PASSWORD`를 잠시 비우고 `docker compose config` → 오류 메시지. 복구.
  - 1: `docker compose down -v && docker compose up --build -d` → `docker compose logs -f api`에서 `ChromaDB 빌드 완료: N 청크 / 634 기사`(N ≥ 1,000) 확인 후 `curl -s localhost:8000/` 200.
  - 2: `curl -s -X POST localhost:8000/ask -H 'Content-Type: application/json' -d '{"question":"한화생명 우승 전략을 알려줘"}' | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d['article_chunks']), d['article_answer'][:80])"` → `3`과 "관련 기사를 찾지 못했습니다"가 아닌 문장.
  - 3: `time docker compose restart api` 후 `curl localhost:8000/` 200이 30초 안. 로그에 `완료 마커 일치(634건), 건너뜀`. 첫 `/ask`가 90초 안에 200.
  - 3-1: `docker compose down -v && docker compose up -d`, 로그에 `진행 100/` 이 보일 때 `docker compose kill api` → `docker compose up -d api` → 로그에 다시 `진행 ` 부터 시작(마커 없음).
  - 4: `docker compose exec mysql mysql -uroot -p"$MYSQL_PASSWORD" -N espo -e "SELECT COUNT(*) FROM article"` → 634.
  - 6: `docker compose run --rm --no-deps api sh -c "ls /app/.env /app/Dump_Espo.sql"` → 둘 다 `No such file`.
  - 7: `docker image ls --format '{{.Repository}} {{.Size}}' | grep api` → 2.5GB 이하.
  - 각 결과 원문을 보고서에 붙인다.
- [ ] **Step 7: 커밋**: `Docker 구성 추가: API·MySQL compose, 기사 건수 healthcheck, 의존성 버전 고정`

---

### Task 5: README "빠른 시작"

**Files:**
- Modify: `README.md`(맨 위에 "빠른 시작(Docker)" 절 추가, 기존 "설치"·"데이터 준비"·"서버 실행"을 "Docker 없이 실행" 절 아래로 내림. "응답 주요 필드" 표와 "노드 상세 조회" 절은 건드리지 않는다)

- [ ] **Step 1: 빠른 시작 절**: clone → `cp .env.example .env` 후 채울 변수(Neo4j 4개, CLOVA 3개, `MYSQL_PASSWORD`) → `docker compose up --build` → 첫 기동은 모델 다운로드와 임베딩으로 5~10분, 그동안 8000이 닫혀 있음 → 확인 `curl localhost:8000/`. 포트 바꾸기(`MYSQL_HOST_PORT`, `API_HOST_PORT`), 재빌드(`docker compose run --rm api python build_vector_db.py --rebuild`), 초기화(`down -v`) 세 줄.
- [ ] **Step 2: "데이터 준비" 절의 벡터DB 항목을 `make_vector_data.py` 없이 `python build_vector_db.py --rebuild`(MySQL 필요)로 고친다.**
- [ ] **Step 3: 커밋**: `README에 Docker 빠른 시작 추가`

---

### Task 6: Frontend 컨테이너 (터미널 D)

**Files (Frontend 레포):**
- Create: `Dockerfile`, `docker-compose.yml`, `docker-entrypoint.sh`, `.dockerignore`
- Modify: `README.md`("빠른 시작(Docker)" 절 추가), `.gitattributes`(없으면 생성, `*.sh text eol=lf`)

**Interfaces:**
- Produces: `localhost:5500`에서 대시보드. `config.js` 내용 `window.API_BASE_URL = "<API_BASE_URL 또는 http://localhost:8000>";`

- [ ] **Step 1: `.dockerignore`**: `.git`, `.claude`, `docs`, `Dockerfile`, `docker-compose.yml`, `README.md`, `tests`
- [ ] **Step 2: `Dockerfile`**: `FROM nginx:alpine` → `COPY . /usr/share/nginx/html/` → `COPY docker-entrypoint.sh /docker-entrypoint.d/40-config-js.sh` → `RUN chmod +x /docker-entrypoint.d/40-config-js.sh`. (nginx 이미지는 `/docker-entrypoint.d/*.sh`를 기동 전에 실행하므로 ENTRYPOINT를 바꾸지 않는다.)
- [ ] **Step 3: `docker-entrypoint.sh`**: `#!/bin/sh`, `echo "window.API_BASE_URL = \"${API_BASE_URL:-http://localhost:8000}\";" > /usr/share/nginx/html/config.js`
- [ ] **Step 4: `docker-compose.yml`**: 서비스 `web`, `build: .`, `ports: ["${WEB_HOST_PORT:-5500}:80"]`, `environment: API_BASE_URL: ${API_BASE_URL:-http://localhost:8000}`
- [ ] **Step 5: 검증(설계 6절 5번)**: `docker compose up --build -d` → `curl -s localhost:5500/config.js` 가 `window.API_BASE_URL = "http://localhost:8000";` → `docker compose down` → `API_BASE_URL=http://example:9000 docker compose up -d` → `curl -s localhost:5500/config.js`에 `example:9000` → `curl -s -o /dev/null -w '%{http_code}' localhost:5500/` 200. 브라우저에서 `localhost:5500` 열어 백엔드(8000)에 질문이 가는지 1회 확인. 출력 원문을 보고서에.
- [ ] **Step 6: README**: 빠른 시작 절(`docker compose up --build` → `localhost:5500`, 백엔드 주소는 브라우저에서 닿는 주소여야 한다는 한 줄, `API_BASE_URL`·`WEB_HOST_PORT` 변수).
- [ ] **Step 7: 커밋**: `프론트 Docker 구성 추가: nginx 정적 서빙과 API 주소 주입`

---

## 실행 프롬프트 (터미널 C, Backend)

권장 실행 설정: 모델 Opus 5.5, 추론 수준 high, 에이전트 종류 general-purpose. 프로젝트 루트 `/Users/doo._.hyun/Study/Project/lck/Backend`에서 Claude Code를 열고 붙여 넣는다. Task 1이 `main`에 커밋된 뒤에만 유효하다.

```
[1단계: 작업 공간 만들기] 다른 무엇보다 먼저 이것부터 해라.
루트 /Users/doo._.hyun/Study/Project/lck/Backend 에서 `git log --oneline -1` 을 실행해 기점 커밋 해시를 기록해라. 그 커밋 메시지가 "구현 계획 추가: 안 1 백엔드 그래프 응답 보강과 Docker 의존성 관리" 가 아니면 중단하고 BLOCKED 로 보고해라. 그 해시를 <BASE> 라 부른다.
  git worktree add -b feat/docker-setup /Users/doo._.hyun/Study/Project/lck/Backend/.claude/worktrees/lck-docker <BASE>
를 실행한 뒤 EnterWorktree 도구에 path=/Users/doo._.hyun/Study/Project/lck/Backend/.claude/worktrees/lck-docker 를 넘겨 세션을 옮겨라.
진입 후 아래를 확인하고, 하나라도 어긋나면 중단하고 BLOCKED 로 보고해라:
  - pwd 가 /Users/doo._.hyun/Study/Project/lck/Backend/.claude/worktrees/lck-docker 인지
  - git log --oneline -1 이 <BASE> 인지
  - docs/plans/2026-10-11-docker-setup.md 가 존재하는지
  - 설계 /Users/doo._.hyun/Study/Project/lck/docs/2026-10-11-docker-setup-design.md 가 존재하는지(저장소 밖 절대 경로다)
  - git status --short 가 비어 있는지
  - cp /Users/doo._.hyun/Study/Project/lck/Backend/.env ./.env 로 환경 파일을 복사했는지(gitignore 대상이다. 커밋하지 않는다)
  - python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest 가 성공하는지
  - docker info 가 성공하고(Docker Desktop 실행 중), docker ps 에 lck-mysql 컨테이너가 보이는지(Task 3 수동 확인에서 3307 로 쓴다. Task 4 검증 직전에 이 컨테이너를 지운다)

[2단계: 실행] 계획서 docs/plans/2026-10-11-docker-setup.md 의 Task 2 부터 Task 5 까지 순서대로 수행한다. 역할: 백엔드 인프라 구현자. 각 태스크의 Step 을 체크박스 순서대로 하고, 테스트·검증 스텝은 실제로 실행해 출력으로 확인한다. 설계 문서는 계획서가 가리키는 절만 읽는다.
허용 Files: requirements.txt, Dockerfile, docker-compose.yml, entrypoint.sh, .dockerignore, .gitattributes, .env.example, chroma_client.py, build_vector_db.py, rag_answer.py, pipeline.py, test_vector_search.py, tests/test_vector_build.py, README.md 의 "빠른 시작" 절과 "설치"·"데이터 준비"·"서버 실행" 절.
수정 금지: neo4j_query.py, graph_schema_config.py, api_server.py, clova_extract.py, rdb_query.py, pytest.ini, tests/ 의 다른 파일, README.md 의 "응답 주요 필드" 표와 "노드 상세 조회" 절, make_vector_data.py 와 vector_data.json 과 kmib_lck_yunminsop.json(삭제 여부는 사용자가 정한다. 건드리지 않는다), docs/ 아래, 그 외 모든 파일. 같은 레포에서 다른 터미널이 안 1 백엔드 계획을 동시에 진행 중이다.
공유 계약: 계획서 Global Constraints 와 "파일 구조" 절의 시그니처, 설계 5-1 절의 compose YAML 을 글자 단위로 지킨다. 테스트 코드는 계획서의 것을 그대로 쓰고 단언을 약화하지 않는다. 테스트가 틀렸다고 판단되면 고치지 말고 BLOCKED 로 보고한다.
검증: Task 4 Step 6 의 검증 항목(6-1, 1, 2, 3, 3-1, 4, 6, 7)을 모두 수행하고 출력 원문을 보고서에 붙인다. 첫 빌드는 수 분 걸린다. 끝나면 `docker compose down` 으로 내린다(볼륨은 남긴다).
커밋: 계획서의 각 태스크 마지막 Step 메시지로 태스크 단위 원자 커밋. 마지막 줄에 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` 를 넣는다. 산문에 대시(—) 를 쓰지 않는다.
보고서: /Users/doo._.hyun/Study/Project/lck/Backend/.claude/reports/docker-report.md 에 태스크별 커밋 해시, `pytest -q tests/test_vector_build.py` 최종 출력, 검증 항목별 출력 원문, 핀한 버전 목록, 계획과 달리 한 결정(있다면)을 적는다.
완료 형식: 마지막 메시지는 `DONE DOCKER feat/docker-setup <HEAD 해시>` 한 줄과 보고서 경로. 실패나 막힘은 `BLOCKED DOCKER <사유>`.
```

## 실행 프롬프트 (터미널 D, Frontend)

권장 실행 설정: 모델 Sonnet 5.5, 추론 수준 medium, 에이전트 종류 general-purpose. 프로젝트 루트 `/Users/doo._.hyun/Study/Project/lck/Frontend`에서 Claude Code를 열고 붙여 넣는다. 프론트 계획의 Task 1(픽스처 커밋)이 `main`에 있어야 한다.

```
[1단계: 작업 공간 만들기] 다른 무엇보다 먼저 이것부터 해라.
루트 /Users/doo._.hyun/Study/Project/lck/Frontend 에서 `git log --oneline -1` 을 실행해 기점 커밋 해시를 기록해라. 그 커밋 메시지가 "픽스처 추가: 안 1 프론트 개발용 /ask·/node 목 응답과 구현 계획" 이 아니면 중단하고 BLOCKED 로 보고해라. 그 해시를 <BASE> 라 부른다.
  git worktree add -b feat/docker-web /Users/doo._.hyun/Study/Project/lck/Frontend/.claude/worktrees/lck-docker-web <BASE>
를 실행한 뒤 EnterWorktree 도구에 path=/Users/doo._.hyun/Study/Project/lck/Frontend/.claude/worktrees/lck-docker-web 를 넘겨 세션을 옮겨라.
진입 후 아래를 확인하고, 하나라도 어긋나면 중단하고 BLOCKED 로 보고해라:
  - pwd 가 /Users/doo._.hyun/Study/Project/lck/Frontend/.claude/worktrees/lck-docker-web 인지
  - git log --oneline -1 이 <BASE> 인지
  - 계획 /Users/doo._.hyun/Study/Project/lck/Backend/docs/plans/2026-10-11-docker-setup.md 와 설계 /Users/doo._.hyun/Study/Project/lck/docs/2026-10-11-docker-setup-design.md 가 존재하는지(둘 다 이 저장소 밖 절대 경로다)
  - git status --short 가 비어 있는지
  - docker info 가 성공하는지(Docker Desktop 실행 중)

[2단계: 실행] 계획서의 Task 6 만 수행한다. 역할: 프론트 인프라 구현자. Step 을 체크박스 순서대로 하고 검증 스텝은 실제로 실행해 출력으로 확인한다.
허용 Files: Dockerfile, docker-compose.yml, docker-entrypoint.sh, .dockerignore, .gitattributes, README.md 의 새 "빠른 시작(Docker)" 절.
수정 금지: index.html, config.js, assets/, fixtures/, tests/, docs/, README.md 의 다른 절, 그 외 모든 파일. 같은 레포에서 다른 터미널이 index.html 을 고치는 중이다.
검증: 계획서 Task 6 Step 5 를 모두 수행하고 출력 원문을 보고서에 붙인다. 끝나면 `docker compose down`.
커밋: Task 6 Step 7 메시지로 커밋 1개. 마지막 줄에 `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` 를 넣는다. 산문에 대시(—) 를 쓰지 않는다.
보고서: /Users/doo._.hyun/Study/Project/lck/Frontend/.claude/reports/docker-web-report.md 에 커밋 해시와 검증 출력 원문.
완료 형식: 마지막 메시지는 `DONE DOCKER-WEB feat/docker-web <HEAD 해시>` 한 줄과 보고서 경로. 실패나 막힘은 `BLOCKED DOCKER-WEB <사유>`.
```

## 통합 게이트 (오케스트레이터)

1. 각 태스크 커밋 뒤 diff 리뷰: 허용 파일 밖 변경 없음, `.env`·`*.sql`이 이미지에 없음, 시그니처 일치, 테스트 단언 미변경.
2. Task 5 뒤 Opus 5.5 리뷰어가 브랜치 전체를 Review Focus 5항목 중심으로 본다.
3. 머지 순서: 안 1 백엔드(`feat/graph-panel-api`) → 이 브랜치 rebase, `README.md` 충돌 해소 → 머지 → Frontend `feat/docker-web` 머지.
4. 머지 뒤 깨끗한 상태에서 설계 6절 검증 1·2·5를 다시 돈다. 2번에서 `article_answer`가 채워지는지가 이 작업의 최종 확인이다.
5. 수동 컨테이너 `lck-mysql`과 볼륨 `lck-mysql-data`가 지워졌는지 확인하고, 안 1 스펙 0-2절의 MySQL 행을 compose 기준으로 갱신한다.
