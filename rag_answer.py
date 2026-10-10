print("🚨 rag_answer.py 실행됨")

import chromadb
from sentence_transformers import SentenceTransformer
from clova_extract import call_hyperclova_summary

model = SentenceTransformer("jhgan/ko-sroberta-multitask")

client = chromadb.PersistentClient(path="./chroma_db")
collection = client.get_collection(name="lol_esports_articles")


def search_articles(question, top_k=3):
    query_embedding = model.encode(question).tolist()

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k
    )

    return results["documents"][0]


def answer_question(question):
    docs = search_articles(question, top_k=3)

    context = "\n\n".join(
        [f"[참고자료 {i+1}]\n{doc}" for i, doc in enumerate(docs)]
    )

    answer = call_hyperclova_summary(question, context)

    return answer


if __name__ == "__main__":
    question = input("질문을 입력하세요: ")

    answer = answer_question(question)

    print("\n=== AI 답변 ===")
    print(answer)