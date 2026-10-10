import chromadb
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("jhgan/ko-sroberta-multitask")

client = chromadb.PersistentClient(path="./chroma_db")

collection = client.get_collection(
    name="lol_esports_articles"
)

query = "젠지 우승 요인을 알려줘"

query_embedding = model.encode(query).tolist()

results = collection.query(
    query_embeddings=[query_embedding],
    n_results=3
)

print("질문:", query)

for i, doc in enumerate(results["documents"][0], start=1):
    print("=" * 60)
    print(f"{i}번 검색 결과")
    print(doc[:500])