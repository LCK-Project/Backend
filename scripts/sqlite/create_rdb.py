import os
import sqlite3

from scripts.paths import SQLITE_DB, SQLITE_SCHEMA

print("🚨 create_rdb.py 실행됨")

conn = sqlite3.connect(SQLITE_DB)

with open(SQLITE_SCHEMA, "r", encoding="utf-8") as f:
    sql = f.read()

conn.executescript(sql)
conn.commit()
conn.close()

print("✅ RDB 생성 완료")
print("DB 파일 위치:", os.path.abspath(SQLITE_DB))