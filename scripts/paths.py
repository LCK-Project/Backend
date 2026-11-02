"""스크립트가 함께 쓰는 경로. 어느 폴더에서 실행해도 저장소 기준으로 같은 파일을 가리킨다."""

from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT_DIR / "data"
DOCS_DIR = ROOT_DIR / "docs"

ARTICLES_JSON = DATA_DIR / "kmib_lck_yunminsop.json"   # 수집한 기사 원본
VECTOR_DATA_JSON = DATA_DIR / "vector_data.json"       # 기사 청크 (make_vector_data 출력)
ALIAS_DICTIONARY_CSV = DATA_DIR / "alias_dictionary.csv"
SQLITE_DB = DATA_DIR / "lck_kg.db"
SQLITE_SCHEMA = DATA_DIR / "schema.sql"
