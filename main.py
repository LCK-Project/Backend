import sys

# Windows 콘솔(cp949)에서 이모지 등 유니코드 출력 시 UnicodeEncodeError 방지
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

print("🚨 지금 실행되는 main.py 맞음")
from neo4j_extract import save_to_neo4j

import json
import os

from dictionary import normalize_result
from chunk import split_text_overlap
from clova_extract import extract_entities_with_clova

JSON_PATH = "kmib_lck_yunminsop.json"

if not os.path.exists(JSON_PATH):
    print(f"❌ JSON 파일을 찾을 수 없습니다: {JSON_PATH}")
    exit()

with open(JSON_PATH, "r", encoding="utf-8") as f:
    articles = json.load(f)

articles = articles[:50]

print(f"✅ 기사 수: {len(articles)}개")

for article_idx, article in enumerate(articles, start=1):
    title = article.get("title", "")
    content = article.get("content", "")

    if not content:
        print(f"⚠️ {article_idx}번 기사 본문 없음: {title}")
        continue

    chunks = split_text_overlap(
        content,
        chunk_size=1000,
        overlap=200
    )

    chunks = chunks[:50]

    print("=" * 60)
    print(f"📰 기사 {article_idx}: {title}")
    print(f"✂️ 청크 수: {len(chunks)}개")

    for chunk_idx, chunk in enumerate(chunks, start=1):
        print(f"\n--- 청크 {chunk_idx}/{len(chunks)} 분석 중 ---")
        print("청크 미리보기:", chunk[:100].replace("\n", " "))

        result = extract_entities_with_clova(chunk)

        result = normalize_result(result)
        
        print("정규화 결과:", result)
        

        print("추출 결과:", result)

        save_to_neo4j(result)