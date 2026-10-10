import sqlite3

conn = sqlite3.connect("lck_kg.db")
cur = conn.cursor()

cur.execute("SELECT COUNT(*) FROM article")
article_count = cur.fetchone()[0]

cur.execute("SELECT COUNT(*) FROM article_chunk")
chunk_count = cur.fetchone()[0]

print("기사 수:", article_count)
print("청크 수:", chunk_count)

cur.execute("""
    SELECT article_id, title, published_at
    FROM article
    LIMIT 5
""")

for row in cur.fetchall():
    print(row)

conn.close()