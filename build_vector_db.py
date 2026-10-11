"""
MySQL article 테이블에서 기사를 읽어 ChromaDB 컬렉션을 만든다.

사용법:
  python build_vector_db.py               # --rebuild 와 같다
  python build_vector_db.py --rebuild     # 마커·컬렉션을 지우고 처음부터
  python build_vector_db.py --if-missing  # 완료 마커가 현재 기사 건수와 맞으면 건너뜀

빌드는 임시 컬렉션(BUILDING_COLLECTION)에 넣고 끝난 뒤 본 이름으로 바꾼 다음
완료 마커를 쓴다. 도중에 죽으면 마커가 없으므로 다음 기동 때 처음부터 다시 한다.
chromadb·모델·pymysql 은 main 안에서 import 한다(테스트가 torch 없이 돌게).
"""

import datetime
import os
import sys
import time
from chunk import split_text_overlap

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200
PROGRESS_EVERY = 100


def _text(value):
    return "" if value is None else str(value)


def _published_at(value):
    # chromadb metadata 는 None 을 받지 않으므로 빈 문자열로 넣는다
    if value is None:
        return ""
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    return str(value)


def make_chunks(articles: list[dict]) -> tuple[list[dict], int]:
    """본문이 빈 기사는 건너뛰고, 청크를 하나 이상 만든 기사만 센다."""
    chunks = []
    article_count = 0
    for a in articles:
        content = a.get("content")
        if not content:
            continue
        article_count += 1
        article_id = a["article_id"]
        for i, text in enumerate(split_text_overlap(content, CHUNK_SIZE, CHUNK_OVERLAP)):
            chunks.append({
                "id": f"article_{article_id}_chunk_{i}",
                "text": text,
                "metadata": {
                    "article_id": int(article_id),
                    "news_id": _text(a.get("news_id")),
                    "title": _text(a.get("title")),
                    "published_at": _published_at(a.get("published_at")),
                    "url": _text(a.get("url")),
                    "chunk_id": i,
                },
            })
    return chunks, article_count


def should_build(marker: dict | None, article_count: int) -> bool:
    return marker is None or marker.get("article_count") != article_count


def wait_for_articles(count_fn, attempts: int = 30, interval_sec: float = 10.0, sleep_fn=time.sleep) -> int:
    """count_fn() 이 0보다 크면 즉시 그 값을, attempts 번 모두 0이면 0을 반환한다."""
    for _ in range(attempts):
        count = count_fn()
        if count > 0:
            return count
        sleep_fn(interval_sec)
    return 0


def fetch_articles(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT article_id, news_id, title, content, published_at, url "
            "FROM article ORDER BY article_id"
        )
        return list(cur.fetchall())


def build(collection, model, chunks: list[dict], batch_size: int = 32, log=print) -> int:
    """청크를 batch_size 단위로 임베딩해 컬렉션에 넣고, 넣은 청크 수를 반환한다."""
    total = len(chunks)
    done = 0
    next_log = PROGRESS_EVERY
    for start in range(0, total, batch_size):
        batch = chunks[start:start + batch_size]
        texts = [c["text"] for c in batch]
        embeddings = model.encode(texts, batch_size=batch_size)
        collection.add(
            ids=[c["id"] for c in batch],
            embeddings=[list(map(float, e)) for e in embeddings],
            documents=texts,
            metadatas=[c["metadata"] for c in batch],
        )
        done += len(batch)
        if done >= next_log or done == total:
            log(f"진행 {done}/{total}")
            next_log = (done // PROGRESS_EVERY + 1) * PROGRESS_EVERY
    return done


def _count_articles():
    from mysql_connect import get_connection

    try:
        conn = get_connection()
    except Exception as e:  # noqa: BLE001
        print(f"[build_vector_db] MySQL 연결 실패, 재시도: {e}", flush=True)
        return 0
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM article")
            return int(cur.fetchone()["n"])
    except Exception as e:  # noqa: BLE001
        print(f"[build_vector_db] article 조회 실패, 재시도: {e}", flush=True)
        return 0
    finally:
        conn.close()


def _delete_collection(client, name):
    try:
        client.delete_collection(name)
    except Exception as e:  # noqa: BLE001
        # 없으면 지울 것도 없다
        print(f"[build_vector_db] 기존 컬렉션 삭제 건너뜀: {e}", flush=True)


def main(argv) -> int:
    if_missing = "--if-missing" in argv
    rebuild = "--rebuild" in argv
    unknown = [a for a in argv if a not in ("--if-missing", "--rebuild")]
    if (if_missing and rebuild) or unknown:
        print("사용법: python build_vector_db.py [--if-missing | --rebuild]", file=sys.stderr)
        return 2

    def log(*args):
        print("[build_vector_db]", *args, flush=True)

    count = wait_for_articles(_count_articles)
    if count == 0:
        log("경고: 기사 0건, ChromaDB 빌드 건너뜀")
        return 0

    import chroma_client as cc

    if if_missing and not should_build(cc.read_marker(), count):
        log(f"완료 마커 일치({count}건), 건너뜀")
        return 0

    client = cc.get_client()
    _delete_collection(client, cc.BUILDING_COLLECTION)
    _delete_collection(client, cc.COLLECTION)
    if os.path.exists(cc.marker_path()):
        os.remove(cc.marker_path())

    from mysql_connect import get_connection

    conn = get_connection()
    try:
        articles = fetch_articles(conn)
    finally:
        conn.close()
    chunks, article_count = make_chunks(articles)
    log(f"기사 {len(articles)}건 중 본문 있는 {article_count}건, 청크 {len(chunks)}개 임베딩 시작")

    model = cc.get_model()
    collection = client.create_collection(cc.BUILDING_COLLECTION)
    chunk_count = build(collection, model, chunks, log=log)
    collection.modify(name=cc.COLLECTION)

    # 마커의 article_count 는 다음 기동 때 COUNT(*) 와 비교하므로 테이블 건수를 적는다
    cc.write_marker({
        "article_count": count,
        "chunk_count": chunk_count,
        "built_at": datetime.datetime.now(datetime.UTC).isoformat(),
    })
    log(f"ChromaDB 빌드 완료: {chunk_count} 청크 / {article_count} 기사")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
