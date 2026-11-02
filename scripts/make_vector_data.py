import json

from app.common.chunk import split_text_overlap
from scripts.paths import ARTICLES_JSON, VECTOR_DATA_JSON

with open(
    ARTICLES_JSON,
    "r",
    encoding="utf-8"
) as f:

    articles = json.load(f)

vector_data = []

for article_idx, article in enumerate(articles):

    content = article.get("content", "")

    chunks = split_text_overlap(
        content,
        chunk_size=1000,
        overlap=200
    )

    for chunk_idx, chunk in enumerate(chunks):

        vector_data.append({
            "article_id": article_idx,
            "chunk_id": chunk_idx,
            "text": chunk
        })

with open(
    VECTOR_DATA_JSON,
    "w",
    encoding="utf-8"
) as f:

    json.dump(
        vector_data,
        f,
        ensure_ascii=False,
        indent=2
    )

print("저장 완료")
print("청크 수:", len(vector_data))