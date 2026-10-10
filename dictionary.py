import pandas as pd

df = pd.read_csv("alias_dictionary.csv")

ALIAS_DICT = {}

for _, row in df.iterrows():
    alias = str(row["alias"]).strip()
    canonical = str(row["canonical"]).strip()

    ALIAS_DICT[alias] = canonical

def _to_text(item):
    """엔티티가 문자열이 아니라 dict/list 로 와도 안전하게 문자열로 변환한다."""
    if isinstance(item, str):
        return item.strip()

    if isinstance(item, dict):
        # 흔한 키 우선 추출 → 없으면 첫 문자열 값 → 그래도 없으면 빈 문자열
        for key in ("name", "id", "value", "title"):
            if isinstance(item.get(key), str):
                return item[key].strip()
        for v in item.values():
            if isinstance(v, str):
                return v.strip()
        return ""

    if isinstance(item, (list, tuple)):
        return " ".join(_to_text(v) for v in item).strip()

    return str(item).strip()


def normalize_name(name):
    name = _to_text(name)
    return ALIAS_DICT.get(name, name)

def normalize_list(items):
    if not isinstance(items, list):
        items = [items] if items else []

    normalized = (normalize_name(item) for item in items)
    # 빈 문자열 제거 + 중복 제거(순서 유지)
    seen = set()
    result = []
    for name in normalized:
        if name and name not in seen:
            seen.add(name)
            result.append(name)
    return result

def normalize_result(result):
    # result 가 dict 가 아니면(예: 리스트/None) 빈 구조로 방어
    if not isinstance(result, dict):
        result = {}

    result["players"] = normalize_list(result.get("players", []))
    result["teams"] = normalize_list(result.get("teams", []))
    result["champions"] = normalize_list(result.get("champions", []))
    result["objectives"] = normalize_list(result.get("objectives", []))

    relations = result.get("relations", [])
    if not isinstance(relations, list):
        relations = []

    clean_relations = []
    for rel in relations:
        if not isinstance(rel, dict):
            continue
        rel["source"] = normalize_name(rel.get("source", ""))
        rel["target"] = normalize_name(rel.get("target", ""))
        clean_relations.append(rel)

    result["relations"] = clean_relations

    return result