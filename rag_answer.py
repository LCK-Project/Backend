print("🚨 rag_answer.py 실행됨")

from chroma_client import COLLECTION, get_client, get_model
from clova_extract import call_hyperclova_summary


def _get_collection():
    """컬렉션이 아직 없으면(빌드 전·빌드 실패) None."""
    import chromadb.errors

    try:
        return get_client().get_collection(name=COLLECTION)
    except (ValueError, chromadb.errors.NotFoundError):
        return None


def search_articles(question, top_k=3):
    """
    질문과 가까운 기사 청크를 dict 리스트로 반환한다.
    각 항목: {"text", "title", "published_at", "url", "article_id"}
    컬렉션이 없으면 빈 리스트.
    """
    collection = _get_collection()
    if collection is None:
        return []

    query_embedding = get_model().encode(question).tolist()

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        include=["documents", "metadatas"],
    )

    items = []
    for text, meta in zip(results["documents"][0], results["metadatas"][0]):
        meta = meta or {}
        items.append({
            "text": text,
            "title": meta.get("title", ""),
            "published_at": meta.get("published_at", ""),
            "url": meta.get("url", ""),
            "article_id": meta.get("article_id"),
        })
    return items


def answer_question(question):
    docs = search_articles(question, top_k=3)

    context = "\n\n".join(
        [f"[참고자료 {i+1}]\n{item['text']}" for i, item in enumerate(docs)]
    )

    answer = call_hyperclova_summary(question, context)

    return answer


if __name__ == "__main__":
    question = input("질문을 입력하세요: ")

    answer = answer_question(question)

    print("\n=== AI 답변 ===")
    print(answer)
