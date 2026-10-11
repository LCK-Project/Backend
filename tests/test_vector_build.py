import build_vector_db as b

def row(i, content, published_at="2025-09-07 00:00:00", title="t", url="u", news_id="n"):
    return {"article_id": i, "news_id": news_id, "title": title, "content": content, "published_at": published_at, "url": url}

def test_make_chunks_ids_and_metadata():
    chunks, n = b.make_chunks([row(7, "가" * 1500)])
    assert n == 1 and [c["id"] for c in chunks] == ["article_7_chunk_0", "article_7_chunk_1"]
    assert chunks[0]["metadata"] == {"article_id": 7, "news_id": "n", "title": "t", "published_at": "2025-09-07 00:00:00", "url": "u", "chunk_id": 0}
    assert len(chunks[0]["text"]) == 1000 and chunks[1]["text"] == "가" * 700
def test_make_chunks_skips_empty_content():
    chunks, n = b.make_chunks([row(1, ""), row(2, None), row(3, "본문")])
    assert n == 1 and [c["id"] for c in chunks] == ["article_3_chunk_0"]
def test_metadata_null_published_at_becomes_empty_string():
    chunks, _ = b.make_chunks([row(1, "본문", published_at=None, url=None)])
    assert chunks[0]["metadata"]["published_at"] == "" and chunks[0]["metadata"]["url"] == ""
def test_metadata_datetime_published_at_is_isoformat():
    import datetime
    chunks, _ = b.make_chunks([row(1, "본문", published_at=datetime.datetime(2025, 9, 7, 0, 0))])
    assert chunks[0]["metadata"]["published_at"] == "2025-09-07T00:00:00"
def test_should_build_without_marker():
    assert b.should_build(None, 634) is True
def test_should_build_when_count_differs():
    assert b.should_build({"article_count": 634, "chunk_count": 1500, "built_at": "x"}, 642) is True
def test_should_not_build_when_marker_matches():
    assert b.should_build({"article_count": 634, "chunk_count": 1500, "built_at": "x"}, 634) is False
def test_wait_for_articles_returns_first_positive():
    calls = iter([0, 0, 5]); slept = []
    assert b.wait_for_articles(lambda: next(calls), attempts=5, interval_sec=1, sleep_fn=slept.append) == 5 and slept == [1, 1]
def test_wait_for_articles_gives_up_returns_zero():
    slept = []
    assert b.wait_for_articles(lambda: 0, attempts=3, interval_sec=2, sleep_fn=slept.append) == 0 and slept == [2, 2, 2]
def test_build_adds_in_batches_and_returns_count():
    class Coll:
        def __init__(self): self.calls = []
        def add(self, ids, embeddings, documents, metadatas): self.calls.append(len(ids))
    class Model:
        def encode(self, texts, batch_size=32): return [[0.0] for _ in texts]
    chunks = [{"id": str(i), "text": "x", "metadata": {}} for i in range(70)]
    coll = Coll(); assert b.build(coll, Model(), chunks, batch_size=32, log=lambda *_: None) == 70 and coll.calls == [32, 32, 6]
def test_main_rejects_both_flags():
    assert b.main(["--if-missing", "--rebuild"]) == 2
