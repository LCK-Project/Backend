from clova_extract import call_hyperclova_kg_answer
from neo4j_query import search_graph_knowledge


def answer_question_from_kg(question, graph_keywords=None, limit=100):
    lookup_keywords = graph_keywords or question
    kg_result = search_graph_knowledge(lookup_keywords, limit=limit)

    answer = call_hyperclova_kg_answer(
        question=question,
        graph_context=kg_result["context"],
    )

    return {
        "answer": answer,
        "graph": kg_result["graph"],
        "facts": kg_result["facts"],
        "context": kg_result["context"],
        "keywords": kg_result["keywords"],
    }
