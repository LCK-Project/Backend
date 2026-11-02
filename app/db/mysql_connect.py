"""
MySQL(espo / Dump_Espo.sql) 연결 헬퍼.

RDB(정형 데이터)는 선수/팀/경기/게임/스탯 등 수치·집계 질문의 근거가 된다.
이 모듈은 연결만 담당하고, 질의 로직은 rdb_query.py 에서 처리한다.
"""

import os

import pymysql
from dotenv import load_dotenv

load_dotenv()

MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "espo")


def get_connection():
    """
    espo DB 연결을 새로 만들어 반환한다.
    - utf8mb4 로 한글 팀/선수명 깨짐 방지
    - DictCursor 로 컬럼명 기반 접근
    호출 측에서 반드시 close() 해야 한다.
    """
    return pymysql.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        database=MYSQL_DATABASE,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=5,
    )


if __name__ == "__main__":
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("SHOW TABLES")
        tables = [next(iter(row.values())) for row in cur.fetchall()]
    conn.close()
    print(f"espo 연결 성공. 테이블 {len(tables)}개:", tables)
