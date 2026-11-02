print("🚨 rag_answer.py 실행됨")

from app.db.chroma_client import COLLECTION, get_client, get_model
from app.llm.clova_extract import call_hyperclova_summary
from app.common.text_utils import clean_text


def _get_collection():
    """컬렉션이 아직 없으면(빌드 전·빌드 실패) None."""
    import chromadb.errors

    try:
        return get_client().get_collection(name=COLLECTION)
    except (ValueError, chromadb.errors.NotFoundError):
        return None


def filter_by_date(items, start, end, top_k):
    """published_at 앞 10자리가 [start, end] 안인 항목만 top_k 개. 날짜가 없는 항목은 뺀다."""
    kept = [it for it in items if (it.get("published_at") or "")[:10] and start <= it["published_at"][:10] <= end]
    return kept[:top_k]


def search_articles(question, top_k=3, date_range=None):
    """
    질문과 가까운 기사 청크를 dict 리스트로 반환한다.
    각 항목: {"text", "title", "published_at", "url", "article_id"}
    컬렉션이 없으면 빈 리스트. date_range 가 ("YYYY-MM-DD", "YYYY-MM-DD") 면
    넉넉히 가져온 뒤 그 범위 안의 기사만 top_k 개 남긴다.
    """
    collection = _get_collection()
    if collection is None:
        return []

    query_embedding = get_model().encode(question).tolist()

    n_results = top_k * 8 if date_range else top_k
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        include=["documents", "metadatas"],
    )

    items = []
    for text, meta in zip(results["documents"][0], results["metadatas"][0]):
        meta = meta or {}
        items.append({
            "text": clean_text(text),
            "title": clean_text(meta.get("title", "")),
            "published_at": meta.get("published_at", ""),
            "url": meta.get("url", ""),
            "article_id": meta.get("article_id"),
        })
    if date_range:
        items = filter_by_date(items, date_range[0], date_range[1], top_k)
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
