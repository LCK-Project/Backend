#!/bin/sh
set -u

# 완료 마커가 없거나 기사 건수가 바뀌었을 때만 빌드한다. 실패해도 서버는 띄운다.
python build_vector_db.py --if-missing || echo "[entrypoint] ChromaDB 빌드 실패, 기사 경로 없이 기동"

exec uvicorn api_server:app --host 0.0.0.0 --port 8000
