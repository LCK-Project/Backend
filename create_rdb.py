import os
import sqlite3

print("🚨 create_rdb.py 실행됨")

conn = sqlite3.connect("lck_kg.db")

with open("schema.sql", "r", encoding="utf-8") as f:
    sql = f.read()

conn.executescript(sql)
conn.commit()
conn.close()

print("✅ RDB 생성 완료")
print("DB 파일 위치:", os.path.abspath("lck_kg.db"))