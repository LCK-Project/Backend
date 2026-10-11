import contextlib
import copy
import json
import os
import uuid

import requests
from dotenv import load_dotenv

load_dotenv()

print("★★★★ clova_extract.py 로드됨 ★★★★")

CLOVA_API_KEY = os.getenv("CLOVA_API_KEY")
CLOVA_APP_TYPE = os.getenv("CLOVA_APP_TYPE", "testapp")
CLOVA_MODEL = os.getenv("CLOVA_MODEL", "HCX-007")

CLOVA_API_URL = (
    f"https://clovastudio.stream.ntruss.com/"
    f"{CLOVA_APP_TYPE}/v3/chat-completions/{CLOVA_MODEL}"
)


def build_clova_prompt(chunk):
    return f"""
다음 롤 e스포츠 기사에서 지식그래프용 엔티티와 관계를 JSON으로 추출해줘.

추출 대상:
- 선수
- 팀
- 챔피언
- 오브젝트
- 대회
- 관계

별칭은 통일해줘.
예:
- 페이커, 이상혁 → Faker
- 티원 → T1
- 젠지 → Gen.G
- 바론 → Baron

반드시 아래 JSON 형식으로만 답해줘.

{{
  "players": [],
  "teams": [],
  "champions": [],
  "objectives": [],
  "tournaments": [],
  "relations": [
    {{
      "source": "",
      "relation": "",
      "target": ""
    }}
  ]
}}

기사:
{chunk}
"""


def extract_content_from_clova_response(response_text):
    """
    HyperCLOVA 응답(text/event-stream 또는 json)에서
    최종 content만 안정적으로 추출하는 함수
    """

    # 1) 혹시 일반 JSON 응답이면 먼저 처리.
    # 스트리밍 응답이면 여기서 항상 실패하는 것이 정상 경로라 로그 없이 2) 로 넘긴다.
    with contextlib.suppress(Exception):
        data = json.loads(response_text)

        if "result" in data:
            result = data["result"]
            if isinstance(result, dict):
                if "message" in result and "content" in result["message"]:
                    return result["message"]["content"]
                if "content" in result:
                    return result["content"]

        if "message" in data and "content" in data["message"]:
            return data["message"]["content"]

        if "choices" in data:
            return data["choices"][0]["message"]["content"]

    # 2) text/event-stream 응답 처리
    contents = []

    for line in response_text.splitlines():
        line = line.strip()

        if not line.startswith("data:"):
            continue

        raw = line.replace("data:", "", 1).strip()

        if raw == "[DONE]":
            continue

        try:
            obj = json.loads(raw)

            # HyperCLOVA streaming 응답에서 content 추출
            if "message" in obj:
                msg = obj["message"]

                # content가 있으면 우선 사용
                if msg.get("content"):
                    contents.append(msg["content"])

                # thinkingContent는 최종 답변이 아니라 중간 추론일 수 있으므로 제외
                # if "thinkingContent" in msg and msg["thinkingContent"]:
                #     contents.append(msg["thinkingContent"])

            elif "result" in obj:
                result = obj["result"]
                if isinstance(result, dict):
                    if "message" in result and "content" in result["message"]:
                        contents.append(result["message"]["content"])
                    elif "content" in result:
                        contents.append(result["content"])

            elif "choices" in obj:
                delta = obj["choices"][0].get("delta", {})
                if delta.get("content"):
                    contents.append(delta["content"])

        except Exception as e:  # noqa: BLE001
            print(f"CLOVA 스트리밍 줄 파싱 실패, 건너뜀: {e}")
            continue

    final_text = "".join(contents).strip()

    # 3) 같은 답변이 정확히 두 번 반복되면 한 번만 남기기
    if final_text:
        half = len(final_text) // 2
        if len(final_text) % 2 == 0 and final_text[:half] == final_text[half:]:
            final_text = final_text[:half]

    return final_text


def parse_json_only(text):
    text = text.strip()
    text = text.replace("```json", "")
    text = text.replace("```", "")
    text = text.strip()

    start = text.find("{")
    if start == -1:
        raise ValueError("JSON 시작 중괄호를 찾지 못함")

    text = text[start:]

    decoder = json.JSONDecoder()
    obj, _ = decoder.raw_decode(text)

    return obj


def extract_entities_with_clova(chunk):
    print("🔥 함수 진입")

    prompt = build_clova_prompt(chunk)

    headers = {
        "Authorization": f"Bearer {CLOVA_API_KEY}",
        "X-NCP-CLOVASTUDIO-REQUEST-ID": str(uuid.uuid4()),
        "Content-Type": "application/json",
        "Accept": "text/event-stream"
    }

    body = {
        "messages": [
            {
                "role": "system",
                "content": "너는 e스포츠 기사에서 지식그래프용 JSON만 추출하는 분석기다."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0.1,
        "topP": 0.8,
        "topK": 0,
        "maxCompletionTokens": 2048,
        "repetitionPenalty": 1.05
    }

    response = requests.post(
        CLOVA_API_URL,
        headers=headers,
        json=body,
        timeout=90
    )

# 아래 print 두줄 원래 상태로 되돌려두려면 ############# 
    print("CLOVA HTTP STATUS:", response.status_code)
    print("CLOVA RAW RESPONSE:", repr(response.text[:1000]))

#################################################################

    if response.status_code != 200:
        return {
            "players": [],
            "teams": [],
            "champions": [],
            "objectives": [],
            "tournaments": [],
            "relations": [],
            "error": response.text
        }

    content = extract_content_from_clova_response(response.text)

    print("EXTRACTED CONTENT:", repr(content[:1000]))

    try:
        result = parse_json_only(content)
        return result
    except Exception as e:  # noqa: BLE001
        print("JSON 파싱 실패:", e)
        return {
            "players": [],
            "teams": [],
            "champions": [],
            "objectives": [],
            "tournaments": [],
            "relations": [],
            "error": str(e),
            "raw_content": content
        }

       
       
def call_hyperclova_summary(question, context):
    prompt = f"""
아래 참고자료를 바탕으로 사용자의 질문에 답변해줘.
반드시 참고자료에 있는 내용만 근거로 답변해줘.
없는 내용은 추측하지 말고 "제공된 기사에서는 확인되지 않습니다"라고 말해줘.

[사용자 질문]
{question}

[참고자료]
{context}
"""

    headers = {
        "Authorization": f"Bearer {CLOVA_API_KEY}",
        "X-NCP-CLOVASTUDIO-REQUEST-ID": str(uuid.uuid4()),
        "Content-Type": "application/json",
        "Accept": "text/event-stream"
    }

    body = {
        "messages": [
            {
                "role": "system",
                "content": "너는 롤 e스포츠 기사 기반 질의응답 도우미다."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0.2,
        "topP": 0.8,
        "topK": 0,
        "maxCompletionTokens": 1024,
        "repetitionPenalty": 1.05
    }

    response = requests.post(
        CLOVA_API_URL,
        headers=headers,
        json=body,
        timeout=90
    )

    content = extract_content_from_clova_response(response.text)

    return content


def _call_clova_chat(system_prompt, user_prompt, *, temperature=0.2, max_tokens=1024):
    """
    HyperCLOVA chat-completions 공통 호출 헬퍼.
    성공 시 (content, None), 실패 시 (None, error_text) 반환.
    """
    headers = {
        "Authorization": f"Bearer {CLOVA_API_KEY}",
        "X-NCP-CLOVASTUDIO-REQUEST-ID": str(uuid.uuid4()),
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }

    body = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "topP": 0.8,
        "topK": 0,
        "maxCompletionTokens": max_tokens,
        "repetitionPenalty": 1.05,
    }

    response = requests.post(CLOVA_API_URL, headers=headers, json=body, timeout=90)

    if response.status_code != 200:
        return None, response.text

    return extract_content_from_clova_response(response.text), None


def _analyze_question_intent_uncached(question):
    """
    질문 의도 분석(파이프라인 1단계).
    HyperCLOVA로 의도 문장과 검색 키워드 목록을 추출한다.
    반환: {"intent": str, "keywords": list[str]}
    """
    system = "너는 LCK e스포츠 질의응답 시스템의 질문 분석기다. 반드시 JSON만 출력한다."
    user = f"""다음 사용자 질문의 의도와 검색 키워드를 추출해줘.

별칭은 통일해줘.
예: 페이커/이상혁 → Faker, 티원 → T1, 젠지 → Gen.G

반드시 아래 JSON 형식으로만 답해줘.
{{
  "intent": "질문 의도를 한 문장으로",
  "keywords": ["검색", "키워드", "목록"]
}}

질문:
{question}
"""

    content, error = _call_clova_chat(system, user, temperature=0.0, max_tokens=512)

    if error or not content:
        return {"intent": "", "keywords": [], "error": error}

    try:
        result = parse_json_only(content)
        if not isinstance(result.get("keywords"), list):
            result["keywords"] = []
        result.setdefault("intent", "")
        return result
    except Exception as e:  # noqa: BLE001
        print("의도 분석 JSON 파싱 실패:", e)
        return {"intent": "", "keywords": [], "error": str(e), "raw_content": content}


# 의도 분석 결과 캐시. LLM 키워드 추출이 호출마다 달라지면 같은 질문에도 그래프가 바뀌어
# 그래프 좌표가 흔들린다(완료 조건 5). 같은 질문에는 같은 키워드·그래프를 돌려주도록 프로세스 안에서 고정한다.
# functools.lru_cache 는 오류 결과까지 캐시하므로 쓰지 않고, 오류가 없는 결과만 넣는다.
_INTENT_CACHE_MAX = 256
_intent_cache = {}


def analyze_question_intent(question):
    """
    질문 의도 분석의 캐시 래퍼. 앞뒤 공백을 지운 질문을 키로 쓰고,
    호출자가 캐시를 바꾸지 못하도록 사본을 돌려준다.
    반환: {"intent": str, "keywords": list[str]}
    """
    key = question.strip()

    if key in _intent_cache:
        return copy.deepcopy(_intent_cache[key])

    result = _analyze_question_intent_uncached(key)

    if "error" not in result:
        # dict 는 삽입 순서를 지키므로 첫 키가 가장 오래된 항목이다.
        if len(_intent_cache) >= _INTENT_CACHE_MAX:
            del _intent_cache[next(iter(_intent_cache))]
        _intent_cache[key] = copy.deepcopy(result)

    return result


analyze_question_intent.cache_clear = _intent_cache.clear


def call_hyperclova_merge(question, article_answer, graph_answer, rdb_answer=""):
    """
    기사 / 지식그래프 / RDB(정형 통계) 기반 답변을 하나로 통합(파이프라인 마지막 단계).
    LLM 호출 실패 시 세 답변을 단순 결합해서 반환한다.
    """
    fallback = (
        f"[기사 기반]\n{article_answer}\n\n"
        f"[지식그래프 기반]\n{graph_answer}\n\n"
        f"[RDB 통계 기반]\n{rdb_answer}"
    )

    system = "너는 LCK e스포츠 질의응답 도우미다."
    user = f"""아래 세 개의 답변을 하나의 자연스러운 한국어 답변으로 통합해줘.

통합 원칙:
- 세 답변에 있는 사실만 사용하고 새로운 내용을 지어내지 마.
- 중복되는 내용은 한 번만 말해.
- 기사 기반 설명, 지식그래프 관계, RDB 통계(승패·KDA 등 수치)를 자연스럽게 엮어줘.
- 수치·전적 같은 구체적 통계는 RDB 통계 답변을 우선 근거로 삼아.
- 답변들이 서로 충돌하면 그 점을 짚어줘.
- 특정 관점에서 "확인되지 않습니다"라고만 한 답변은 무시하고, 사실이 있는 답변을 활용해.

[사용자 질문]
{question}

[기사 기반 답변]
{article_answer}

[지식그래프 기반 답변]
{graph_answer}

[RDB 통계 기반 답변]
{rdb_answer}
"""

    content, error = _call_clova_chat(system, user, temperature=0.2, max_tokens=1024)

    if error or not content:
        return fallback

    return content.strip()


def call_hyperclova_rdb_answer(question, rdb_context):
    """
    RDB(정형 통계) 사실만 바탕으로 질문에 답한다(파이프라인 RDB 단계).
    """
    if not rdb_context.strip():
        return (
            "RDB(정형 데이터)에서 질문과 직접 연결되는 통계를 찾지 못했습니다."
        )

    system = "너는 LCK e스포츠 통계 데이터(RDB) 기반 질의응답 도우미다."
    user = f"""아래 RDB 통계 사실만 바탕으로 사용자의 질문에 답변해줘.
이 사실들은 MySQL(espo)에서 조회한 선수/팀/경기 통계다.

답변 원칙:
- 반드시 [RDB 통계 사실]에 있는 수치만 근거로 사용해.
- 기사나 외부 지식을 추측해서 보태지 마.
- 사실이 부족하면 "RDB 통계만으로는 확인하기 어렵습니다"라고 말해.
- 승/패, KDA, 골드 같은 수치는 구체적으로 제시해.

[사용자 질문]
{question}

[RDB 통계 사실]
{rdb_context}
"""

    # HCX-007 추론 토큰 여유를 위해 넉넉히 잡는다.
    content, error = _call_clova_chat(system, user, temperature=0.1, max_tokens=2048)

    if error or not content:
        return "RDB 통계 답변 생성 중 오류가 발생했습니다."

    return content.strip()


def generate_sql_with_clova(question, schema_prompt, entity_hint=""):
    """
    질문을 MySQL SELECT 문 하나로 변환(Text-to-SQL).
    SQL 텍스트만 반환하며, 안전성 검증은 호출 측(rdb_query._sanitize_sql)에서 한다.
    """
    system = (
        "너는 자연어 질문을 MySQL SELECT 쿼리로 변환하는 변환기다. "
        "오직 SELECT 문 하나만, 설명 없이 출력한다."
    )
    user = f"""{schema_prompt}

{entity_hint}

위 스키마를 사용해서 아래 질문에 답할 수 있는 MySQL SELECT 쿼리를 딱 하나만 작성해줘.

규칙:
- SELECT(또는 WITH) 문 하나만 출력. 설명·주석·마크다운 금지.
- INSERT/UPDATE/DELETE/DROP 등 데이터 변경 구문 금지.
- 결과가 많을 수 있으면 LIMIT 을 붙여라.
- 예약어 match 테이블은 반드시 백틱 `match` 로 표기.

[질문]
{question}
"""

    # HCX-007은 추론(thinking) 모델이라 thinkingContent가 토큰을 먼저 소비한다.
    # 토큰이 부족하면 실제 SQL(content)이 비므로 충분히 크게 잡는다.
    content, error = _call_clova_chat(system, user, temperature=0.0, max_tokens=2048)

    if error or not content:
        print("DEBUG generate_sql 실패:", error)
        return ""

    return content.strip()


def call_hyperclova_kg_answer(question, graph_context):
    if not graph_context.strip():
        return (
            "지식그래프에서 질문과 직접 연결되는 관계를 찾지 못했습니다. "
            "먼저 Neo4j에 해당 선수, 팀, 경기, 대회 관계가 저장되어 있는지 확인해주세요."
        )

    prompt = f"""
아래 지식그래프 사실만 바탕으로 사용자의 질문에 답변해줘.
지식그래프 사실은 Neo4j에서 조회한 관계 triple이다.

답변 원칙:
- 반드시 [지식그래프 사실]에 있는 관계만 근거로 사용해.
- 기사 원문이나 외부 지식을 추측해서 보태지 마.
- 관계가 부족하면 "지식그래프에 있는 사실만으로는 확인하기 어렵습니다"라고 말해.
- 관계 이름이 영어/코드 형태이면 자연스러운 한국어로 풀어서 설명해.

[사용자 질문]
{question}

[지식그래프 사실]
{graph_context}
"""

    headers = {
        "Authorization": f"Bearer {CLOVA_API_KEY}",
        "X-NCP-CLOVASTUDIO-REQUEST-ID": str(uuid.uuid4()),
        "Content-Type": "application/json",
        "Accept": "text/event-stream"
    }

    body = {
        "messages": [
            {
                "role": "system",
                "content": "너는 LCK 지식그래프 기반 질의응답 도우미다."
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0.1,
        "topP": 0.8,
        "topK": 0,
        "maxCompletionTokens": 1024,
        "repetitionPenalty": 1.05
    }

    response = requests.post(
        CLOVA_API_URL,
        headers=headers,
        json=body,
        timeout=90
    )

    if response.status_code != 200:
        return f"HyperCLOVA 호출 중 오류가 발생했습니다: {response.text}"

    content = extract_content_from_clova_response(response.text)

    return content.strip()
