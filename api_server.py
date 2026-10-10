import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from pipeline import run_pipeline

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


@app.get("/")
def home():
    return {"message": "LCK Knowledge Graph API is running"}


@app.post("/ask")
def ask(req: QuestionRequest):
    result = run_pipeline(req.question)

    return {
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
