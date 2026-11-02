import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.search.neo4j_query import get_node_detail
from app.pipeline import run_pipeline

app = FastAPI(title="LCK Knowledge Graph API")

# 프론트엔드(별도 레포)에서 호출할 수 있도록 CORS 허용.
# 운영 환경에서는 CORS_ORIGINS 에 허용할 도메인을 쉼표로 구분해 지정한다.
_origins = os.getenv("CORS_ORIGINS", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins.split(",")],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class QuestionRequest(BaseModel):
    question: str
    # 선택지를 고른 뒤 보내는 두 번째 질문은 되묻기를 건너뛴다 (docs/specs/2026-11-03-clarify-design.md 3-1)
    skip_clarify: bool = False
    # 고른 범위 {"axis": "season", "value": "2024"}. 시즌·대회·패치는 날짜 필터, 상대·챔피언은 검색 키워드로 쓴다.
    scope: dict | None = None


@app.get("/")
def home():
    return {"message": "LCK Knowledge Graph API is running"}


@app.post("/ask")
def ask(req: QuestionRequest):
    result = run_pipeline(req.question, skip_clarify=req.skip_clarify, scope=req.scope)

    # 범위 되묻기. 검색·답변 없이 되묻는 문장과 선택지만 돌려준다.
    if result.get("type") == "clarify":
        return {
            "type": "clarify",
            "question": result["question"],
            "intent": result["intent"],
            "clarify": result["clarify"],
        }

    return {
        "type": "answer",
        "question": result["question"],
        "intent": result["intent"],
        "graph_keyword": result["keywords"],
        "answer": result["answer"],
        "article_answer": result["article_answer"],
        "graph_answer": result["graph_answer"],
        "rdb_answer": result["rdb_answer"],
        "answer_source": "hybrid",
        "related_chunks": result["graph_context"].splitlines(),
        "article_chunks": result["article_chunks"],
        "graph_facts": result["graph_facts"],
        "kg_keywords": result["kg_keywords"],
        "graph": result["graph"],
        "rdb_entities": result["rdb_entities"],
        "rdb_facts": result["rdb_facts"],
        "rdb_sql": result["rdb_sql"],
    }


@app.get("/node")
def node(id: str):
    detail = get_node_detail(id)

    if detail is None:
        raise HTTPException(status_code=404, detail="node not found")

    return detail
