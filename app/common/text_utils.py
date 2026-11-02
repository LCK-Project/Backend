"""여러 검색 경로가 함께 쓰는 문자열 정리 함수."""

import html


def clean_text(value):
    """
    수집 단계에서 HTML 엔티티가 풀리지 않은 채 저장된 문자열(&#39; &quot; &amp; 등)을 원래 문자로 되돌린다.
    &amp;#39; 처럼 두 번 이스케이프된 것도 있어 바뀌지 않을 때까지 최대 3번 푼다. 문자열이 아니면 그대로.
    """
    if not isinstance(value, str):
        return value
    for _ in range(3):
        unescaped = html.unescape(value)
        if unescaped == value:
            break
        value = unescaped
    return value
