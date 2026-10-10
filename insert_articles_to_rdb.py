import json
import sqlite3
from chunk import split_text_overlap

JSON_PATH = "kmib_lck_yunminsop.json"
DB_PATH = "lck_kg.db"

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

with open(JSON_PATH, "r", encoding="utf-8") as f:
    articles = json.load(f)

for article_idx, article in enumerate(articles, start=1):
    news_id = article.get("news_id", "")
    title = article.get("title", "")
    content = article.get("content", "")
    published_at = article.get("published_at", "")
    provider = article.get("provider", "")
    byline = article.get("byline", "")
    url = article.get("provider_link_page", "")

    cur.execute("""
        INSERT OR REPLACE INTO article
        (article_id, news_id, title, content, published_at, provider, byline, url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        article_idx, news_id, title, content, published_at,
        provider, byline, url
    ))

    chunks = split_text_overlap(content, chunk_size=1000, overlap=200)

    for chunk_idx, chunk_text in enumerate(chunks, start=1):
        chunk_id = article_idx * 10000 + chunk_idx

        cur.execute("""
            INSERT OR REPLACE INTO article_chunk
            (chunk_id, article_id, chunk_order, chunk_text)
            VALUES (?, ?, ?, ?)
        """, (
            chunk_id, article_idx, chunk_idx, chunk_text
        ))

conn.commit()
conn.close()

print("✅ article / article_chunk 저장 완료")
print("기사 수:", len(articles))