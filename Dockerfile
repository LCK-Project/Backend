FROM python:3.12-slim

WORKDIR /app

# 의존성 레이어를 소스와 분리해 소스만 바뀔 때 재설치하지 않는다
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x entrypoint.sh

# 벡터DB와 임베딩 모델 캐시는 compose 볼륨에 둔다
ENV CHROMA_PATH=/data/chroma_db HF_HOME=/data/hf_cache

EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
