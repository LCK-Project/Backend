print("🚨 build_vector_db.py 실행됨")

import json
import chromadb
from sentence_transformers import SentenceTransformer

with open("vector_data.json", "r", encoding="utf-8") as f:
    vector_data = json.load(f)

print("불러온 청크 수:", len(vector_data))

model = SentenceTransformer("jhgan/ko-sroberta-multitask")

client = chromadb.PersistentClient(path="./chroma_db")

collection = client.get_or_create_collection(
    name="lol_esports_articles"
)

for item in vector_data:
    text = item["text"]

    embedding = model.encode(text).tolist()

    collection.add(
        ids=[f'article_{item["article_id"]}_chunk_{item["chunk_id"]}'],
        embeddings=[embedding],
        documents=[text],
        metadatas=[{
            "article_id": item["article_id"],
            "chunk_id": item["chunk_id"]
        }]
    )

print("✅ Vector DB 저장 완료")
print("저장된 청크 수:", collection.count())