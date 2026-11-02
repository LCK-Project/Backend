from neo4j_query import node_to_dict
from tests.stubs import StubNode
from text_utils import clean_text


def test_clean_text_unescapes_entities():
    assert clean_text("&#39;도&#39;파민 | HLE vs T1") == "'도'파민 | HLE vs T1"
    assert clean_text("&quot;GOAT&quot; &amp; 페이커") == '"GOAT" & 페이커'

def test_clean_text_double_escaped():
    assert clean_text("&amp;#39;도&amp;#39;파민") == "'도'파민"

def test_clean_text_leaves_plain_and_non_strings():
    assert clean_text("페이커가 개잘했음 ㅋㅋ") == "페이커가 개잘했음 ㅋㅋ"
    assert clean_text(None) is None
    assert clean_text(191) == 191

def test_node_name_is_cleaned():
    d = node_to_dict(StubNode("4:x:9", ["FanVideo"], {"name": "&#39;도&#39;파민 | HLE vs T1 | 게임 2 하이라이트"}), is_seed=False)
    assert d["name"] == "'도'파민 | HLE vs T1 | 게임 2 하이라이트"
