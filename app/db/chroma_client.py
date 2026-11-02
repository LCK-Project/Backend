"""
ChromaDB 경로·모델·컬렉션 이름과 완료 마커를 한 곳에서 관리한다.

build_vector_db.py, rag_answer.py, test_vector_search.py 가 이 모듈을 쓴다.
chromadb 와 sentence-transformers 는 무거우므로 함수 안에서 지연 import 한다.
임베딩 모델 캐시 위치는 HF_HOME 환경변수(huggingface_hub 캐시)를 따른다.
"""

import json
import os

CHROMA_PATH = os.getenv("CHROMA_PATH", "./chroma_db")
COLLECTION = "lol_esports_articles"
BUILDING_COLLECTION = "lol_esports_articles__building"
MODEL_NAME = "jhgan/ko-sroberta-multitask"

_client = None
_model = None


def get_client():
    """CHROMA_PATH 의 PersistentClient 를 한 번만 만들어 재사용한다."""
    global _client
    if _client is None:
        import chromadb
        from chromadb.config import Settings

        _client = chromadb.PersistentClient(
            path=CHROMA_PATH, settings=Settings(anonymized_telemetry=False)
        )
    return _client


def get_model():
    """임베딩 모델을 처음 호출될 때 로드한다."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(MODEL_NAME)
    return _model


def marker_path():
    """빌드 완료 마커 파일 경로. 컬렉션 count 대신 이 파일로 완료를 판단한다."""
    return os.path.join(CHROMA_PATH, ".complete")


def read_marker():
    """마커가 없거나 깨졌으면 None."""
    try:
        with open(marker_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_marker(data):
    """임시 파일에 쓴 뒤 이름을 바꿔 마커가 반쯤 쓰인 채 남지 않게 한다."""
    os.makedirs(CHROMA_PATH, exist_ok=True)
    tmp = marker_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, marker_path())
