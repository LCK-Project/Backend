import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()

params = {
  "argument": {
    "query": "LCK",
    "published_at": {
      "from": "2025-06-01",
      "until": "2025-07-31"
    },
    "provider": [
      "국민일보"
    ],
    "byline": "윤민섭",
    "sort": {
      "date": "desc"
    },
    "return_from": "0",
    "return_size": "10000",
    "fields": [
      "news_id",
      "title",
      "content",
      "published_at",
      "enveloped_at",
      "dateline",
      "provider",
      "category",
      "category_incident",
      "hilight",
      "byline",
      "images",
      "images_caption",
      "provider_subject",
      "provider_news_id",
      "publisher_code",
      "provider_link_page",
      "printing_page",
      "tms_raw_stream"
    ]
  },
  "access_key": os.getenv("NEWS_API_ACCESS_KEY")
}

headers = {'Content-type': 'application/json'}

response = requests.post(
    "https://www.newstore.or.kr/api-newstore/v1/search/newsAllList.json",
    json=params,
    headers=headers
)

if response.status_code == 200:
    data = response.json()

    return_object = data.get("returnObject")

    if isinstance(return_object, str):
        return_object = json.loads(return_object)

    documents = return_object.get("documents", [])

    with open("kmib_lck_yunminsop.json", "w", encoding="utf-8") as f:
        json.dump(documents, f, ensure_ascii=False, indent=2)

    print("저장 완료: kmib_lck_yunminsop.json")
    print("저장된 기사 수:", len(documents))

else:
    print(response.content)
