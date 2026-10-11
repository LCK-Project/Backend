"""neo4j 드라이버 없이 변환 함수를 시험하기 위한 스텁."""


class StubNode:
    """neo4j Node 흉내. element_id, labels, get 만 제공한다."""

    def __init__(self, element_id: str, labels: list[str], props: dict):
        self.element_id = element_id
        self.labels = frozenset(labels)
        self._props = dict(props)

    def get(self, key, default=None):
        return self._props.get(key, default)


class StubRel:
    """neo4j Relationship 흉내. type, start, end, get 을 제공한다."""

    def __init__(self, type: str, start: StubNode, end: StubNode, props: dict | None = None):
        self.type = type
        self.start = start
        self.end = end
        self._props = dict(props or {})

    def get(self, key, default=None):
        return self._props.get(key, default)


def structure_record(n, r, m) -> dict:
    return {"n": n, "r": r, "m": m, "source": r.start, "target": r.end}


def claim_record(n, s, t, relation_type, article_key, evidence_text, confidence) -> dict:
    return {
        "n": n,
        "s": s,
        "t": t,
        "relation_type": relation_type,
        "article_key": article_key,
        "evidence_text": evidence_text,
        "confidence": confidence,
    }
