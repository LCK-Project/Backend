"""
질의응답 파이프라인 오케스트레이터.

흐름:
  질문
   └→ [LLM #1] 의도 분석 → {의도, 키워드}
        ├→ ChromaDB 기사검색 → [LLM #2] 기사 기반 답변
        ├→ Neo4j 관계검색   → [LLM #3] 그래프 기반 답변 + 그래프 데이터
        └→ MySQL(espo) 통계 → [LLM #4] RDB 통계 기반 답변
             └→ [LLM #5] 세 답변 통합 → 최종 답변 + 그래프
"""

from clova_extract import (
    analyze_question_intent,
    call_hyperclova_kg_answer,
    call_hyperclova_merge,
    call_hyperclova_rdb_answer,
    call_hyperclova_summary,
)
from neo4j_query import search_graph_knowledge


def _search_rdb_safe(question, keywords, graph_limit=40):
    """
    RDB(espo) 통계 검색. 연결/조회 실패가 전체 답변을 죽이지 않도록 감싼다.
    (pymysql 등은 모듈 import 시점 부담이 있어 지연 import)
    """
    try:
        from rdb_query import search_rdb_knowledge
        return search_rdb_knowledge(question, keywords, max_facts=graph_limit)
    except Exception as e:  # noqa: BLE001
        print("DEBUG RDB search failed:", e)
        return {
            "keywords": [], "entities": {"players": [], "teams": []},
            "facts": [], "context": "", "sql": None,
        }


def _search_articles_safe(question, top_k=3):
    """
    ChromaDB 기사 검색. import/조회 실패가 전체 답변을 죽이지 않도록 감싼다.
    (rag_answer는 clova_extract·chroma_client 를 끌어오므로 지연 import)
    """
    try:
        from rag_answer import search_articles
        return search_articles(question, top_k=top_k)
    except Exception as e:  # noqa: BLE001
        print("DEBUG article search failed:", e)
        return []


def run_pipeline(question, top_k=3, graph_limit=100):
    # 1) 의도 분석 (LLM #1)
    intent_result = analyze_question_intent(question)
    keywords = intent_result.get("keywords") or question
    print("DEBUG intent:", intent_result.get("intent"))
    print("DEBUG keywords:", keywords)

    # 2) 기사 검색(ChromaDB) → 기사 기반 답변 (LLM #2)
    docs = _search_articles_safe(question, top_k=top_k)
    if docs:
        article_context = "\n\n".join(
            f"[참고자료 {i + 1}] {doc['title']} ({doc['published_at'][:10]})\n{doc['text']}"
            for i, doc in enumerate(docs)
        )
        article_answer = call_hyperclova_summary(question, article_context)
    else:
        article_context = ""
        article_answer = "관련 기사를 찾지 못했습니다."

    # 3) 관계 검색(Neo4j) → 그래프 기반 답변 (LLM #3)
    kg_result = search_graph_knowledge(keywords, limit=graph_limit)
    graph_answer = call_hyperclova_kg_answer(question, kg_result["context"])

    # 4) 정형 통계 검색(MySQL espo) → RDB 기반 답변 (LLM #4)
    rdb_result = _search_rdb_safe(question, keywords)
    rdb_answer = call_hyperclova_rdb_answer(question, rdb_result["context"])

    # 5) 세 답변 통합 (LLM #5)
    final_answer = call_hyperclova_merge(
        question, article_answer, graph_answer, rdb_answer
    )

    return {
        "question": question,
        "intent": intent_result.get("intent", ""),
        "keywords": keywords,
        "answer": final_answer,
        "article_answer": article_answer,
        "graph_answer": graph_answer,
        "rdb_answer": rdb_answer,
        "article_chunks": docs,
        "graph_facts": kg_result["facts"],
        "graph_context": kg_result["context"],
        "kg_keywords": kg_result["keywords"],
        "graph": kg_result["graph"],
        "rdb_facts": rdb_result["facts"],
        "rdb_context": rdb_result["context"],
        "rdb_entities": rdb_result["entities"],
        "rdb_sql": rdb_result["sql"],
    }


if __name__ == "__main__":
    result = run_pipeline("젠지 우승 전략을 알려줘")
    print("\n=== 최종 답변 ===")
    print(result["answer"])
