print("🚨 test_dictionary.py 실행됨")

from dictionary import normalize_result

test_result = {
    "players": ["페이커", "이상혁", "기인", "김기인"],
    "teams": ["젠지", "GenG", "Gen.G", "티원", "한화생명", "HLE"],
    "champions": [],
    "objectives": ["바론", "내셔 남작", "블루", "레드"],
    "tournaments": [],
    "relations": [
        {"source": "페이커", "relation": "소속", "target": "티원"},
        {"source": "김기인", "relation": "소속", "target": "젠지"},
        {"source": "젠지", "relation": "획득", "target": "바론"}
    ]
}

print("정규화 전:")
print(test_result)

normalized = normalize_result(test_result)

print("\n정규화 후:")
print(normalized)