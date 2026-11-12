"""
질의응답 파이프라인 오케스트레이터.

흐름:
  질문
   └→ [LLM #1] 의도 분석 → {의도, 키워드}
        ├→ ChromaDB 기사검색 → [LLM #2] 기사 기반 답변          ┐
        ├→ Neo4j 관계검색   → [LLM #3] 그래프 기반 답변 + 그래프 │ 세 경로는 동시에 실행
        └→ MySQL(espo) 통계 → [LLM #4] RDB 통계 기반 답변       ┘
             └→ [LLM #5] 세 답변 통합 → 최종 답변 + 그래프
"""

import time
from concurrent.futures import ThreadPoolExecutor

from app.clarify import (
    decide_clarification, has_recent_token, latest_season, question_date_range, refine_recent_question,
    scope_date_range, scope_keywords, scope_options,
)
from app.llm.clova_extract import (
    analyze_question_intent,
    call_hyperclova_kg_answer,
    call_hyperclova_merge,
    call_hyperclova_rdb_answer,
    call_hyperclova_summary,
)
from app.search.neo4j_query import graph_focus, search_graph_knowledge
from app.timeline import build_timeline


def _search_rdb_safe(question, keywords, graph_limit=40, date_range=None):
    """
    RDB(espo) 통계 검색. 연결/조회 실패가 전체 답변을 죽이지 않도록 감싼다.
    (pymysql 등은 모듈 import 시점 부담이 있어 지연 import)
    """
    try:
        from app.search.rdb_query import search_rdb_knowledge
        return search_rdb_knowledge(question, keywords, max_facts=graph_limit, date_range=date_range)
    except Exception as e:  # noqa: BLE001
        print("DEBUG RDB search failed:", e)
        return {
            "keywords": [], "entities": {"players": [], "teams": []},
            "facts": [], "context": "", "sql": None,
        }


def _search_articles_safe(question, top_k=3, date_range=None):
    """
    ChromaDB 기사 검색. import/조회 실패가 전체 답변을 죽이지 않도록 감싼다.
    (rag_answer는 clova_extract·chroma_client 를 끌어오므로 지연 import)
    """
    try:
        from app.search.rag_answer import search_articles
        return search_articles(question, top_k=top_k, date_range=date_range)
    except Exception as e:  # noqa: BLE001
        print("DEBUG article search failed:", e)
        return []


def _timed(fn):
    """fn 을 실행하고 (결과, 걸린 초) 를 돌려준다."""
    started = time.perf_counter()
    return fn(), time.perf_counter() - started


def _article_branch(question, top_k, date_range):
    """기사 검색(ChromaDB) → 기사 기반 답변 (LLM #2)."""
    docs = _search_articles_safe(question, top_k=top_k, date_range=date_range)
    if not docs:
        return docs, "관련 기사를 찾지 못했습니다."
    article_context = "\n\n".join(
        f"[참고자료 {i + 1}] {doc['title']} ({doc['published_at'][:10]})\n{doc['text']}"
        for i, doc in enumerate(docs)
    )
    return docs, call_hyperclova_summary(question, article_context)


def _graph_branch(question, keywords, graph_limit, date_range, focus):
    """관계 검색(Neo4j) → 그래프 기반 답변 (LLM #3)."""
    kg_result = search_graph_knowledge(keywords, limit=graph_limit, date_range=date_range, focus=focus)
    return kg_result, call_hyperclova_kg_answer(question, kg_result["context"])


def _rdb_branch(question, keywords, date_range):
    """정형 통계 검색(MySQL espo) → RDB 기반 답변 (LLM #4)."""
    rdb_result = _search_rdb_safe(question, keywords, date_range=date_range)
    return rdb_result, call_hyperclova_rdb_answer(question, rdb_result["context"])


def run_pipeline(question, top_k=3, graph_limit=100, skip_clarify=False, scope=None):
    # 1) 의도 분석 (LLM #1)
    intent_result = analyze_question_intent(question)
    keywords = intent_result.get("keywords") or question
    print("DEBUG intent:", intent_result.get("intent"))
    print("DEBUG keywords:", keywords)

    # 1-1) 범위 되묻기. 시즌·대회가 빠진 질문이면 검색과 나머지 LLM 호출 없이 바로 되묻는다.
    #      skip_clarify 는 프론트가 선택지를 고른 뒤 보내는 두 번째 질문에 붙이는 하드 가드다.
    if not skip_clarify:
        clarification = decide_clarification(question, intent_result, scope_options)
        if clarification:
            print("DEBUG clarify:", clarification["axis"])
            return {
                "type": "clarify",
                "question": question,
                "intent": intent_result.get("intent", ""),
                "clarify": clarification,
            }

    # 1-2) "요즘·최근·현재" 같은 표현은 되묻지 않고 최신 시즌을 붙여 검색·답변을 좁힌다.
    #      의도 분석은 원문으로 이미 끝났고, 이후 단계는 모두 좁힌 질문을 쓴다.
    if has_recent_token(question):
        question = refine_recent_question(question, latest_season())
        print("DEBUG recent → ", question)

    # 1-3) 되묻기에서 고른 범위를 검색에 적용한다. 시즌·대회·패치는 경기·기사 날짜 범위로,
    #      상대 팀·챔피언은 그래프 검색 키워드로. (질문 문장에는 프론트가 이미 붙여서 보냈다)
    #      되묻기에서 고른 범위가 날짜로 바뀌지 않으면 질문에 적힌 연도를 쓴다("2024 티원 전략" → 2024년).
    date_range = scope_date_range(scope) or question_date_range(question)
    extra_keywords = scope_keywords(scope)
    if date_range or extra_keywords:
        print("DEBUG scope:", scope, "→ date_range", date_range, "keywords", extra_keywords)
    if extra_keywords:
        base = keywords if isinstance(keywords, list) else [keywords]
        keywords = base + [k for k in extra_keywords if k not in base]

    # 2~4) 기사·그래프·통계 세 경로는 서로의 결과를 쓰지 않으므로 동시에 돌린다.
    #       각 경로는 "검색 → 그 결과로 LLM 답변" 까지가 한 묶음이다. 차례로 돌리면 세 번의 LLM 대기가
    #       그대로 더해지지만, 동시에 돌리면 가장 느린 경로 하나만큼만 기다린다.
    focus = graph_focus(question)
    branches = {
        "article": lambda: _article_branch(question, top_k, date_range),
        "graph": lambda: _graph_branch(question, keywords, graph_limit, date_range, focus),
        "rdb": lambda: _rdb_branch(question, keywords, date_range),
    }
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=len(branches)) as pool:
        futures = {name: pool.submit(_timed, fn) for name, fn in branches.items()}
        # result() 는 경로 안에서 난 예외를 그대로 다시 던진다(차례로 돌리던 때와 같은 실패 방식).
        results = {name: future.result() for name, future in futures.items()}
    wall = time.perf_counter() - started
    spent = {name: seconds for name, (_, seconds) in results.items()}
    print(
        "DEBUG timing " + " ".join(f"{name}={seconds:.1f}s" for name, seconds in spent.items())
        + f" → 동시 실행 {wall:.1f}s (차례로 돌렸다면 {sum(spent.values()):.1f}s)"
    )
    docs, article_answer = results["article"][0]
    kg_result, graph_answer = results["graph"][0]
    rdb_result, rdb_answer = results["rdb"][0]

    # 5) 세 답변 통합 (LLM #5)
    final_answer = call_hyperclova_merge(
        question, article_answer, graph_answer, rdb_answer
    )

    return {
        "type": "answer",
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
        # 날짜 스트립의 대회 띠. 그래프의 경기 기간과 겹치는 대회만 담는다.
        "timeline": build_timeline(kg_result["graph"]),
        "rdb_facts": rdb_result["facts"],
        "rdb_context": rdb_result["context"],
        "rdb_entities": rdb_result["entities"],
        "rdb_sql": rdb_result["sql"],
    }


if __name__ == "__main__":
    result = run_pipeline("젠지 우승 전략을 알려줘")
    print("\n=== 최종 답변 ===")
    print(result["answer"])
