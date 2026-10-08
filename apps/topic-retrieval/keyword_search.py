"""형태소 분석 + BM25 기반 키워드 검색.

단순히 "쿼리 키워드가 몇 종류나 매칭됐냐"로 세면, 흔한 단어(예: '한살이'가
형태소 분석기에서 '한'+'살이'로 쪼개졌을 때의 '살이')가 여기저기 다 걸려서
정작 핵심 단어('식물')로 좁혀지지 않는 문제가 생긴다. BM25는 단어별로
"전체 문서에서 얼마나 희귀한가"(IDF)를 반영해서, 흔한 단어의 기여를 낮추고
문서 길이도 보정해준다.
"""
from kiwipiepy import Kiwi
from rank_bm25 import BM25Okapi

_kiwi = Kiwi()

# 키워드로 쓸 품사: 일반명사(NNG), 고유명사(NNP), 외국어(SL, 예: AI/DNA 등 영문 약어)
_KEYWORD_POS = {"NNG", "NNP", "SL"}


def tokenize(text):
    """형태소 분석해서 명사 위주 토큰을 반환한다 (중복 제거 안 함 — BM25는 빈도가 필요).
    문서 인덱싱, 쿼리 토큰화 양쪽에 같은 함수를 써야 '토큰 대 토큰'으로 정확히 비교된다."""
    return [t.form for t in _kiwi.tokenize(text) if t.tag in _KEYWORD_POS and len(t.form) >= 2]


def extract_keywords(text):
    """중복 제거된 키워드 목록 (표시/디버깅용)."""
    seen = []
    for tok in tokenize(text):
        if tok not in seen:
            seen.append(tok)
    return seen


def keyword_search(query, records, text_field="search_text", top_k=20):
    """BM25로 랭킹을 매긴다. 후보(records)는 이미 학년/과목으로 필터링된 상태여야 한다
    — IDF가 "이 후보군 안에서 얼마나 희귀한가"를 기준으로 계산되기 때문에, 후보군이
    바뀌면(예: 다른 과목) 같은 단어라도 가중치가 달라진다.
    반환: [(record, bm25_score, matched_keywords), ...] score 내림차순, score<=0 제외."""
    query_tokens = tokenize(query)
    if not query_tokens or not records:
        return []

    doc_tokens = [tokenize(r.get(text_field, "")) for r in records]
    bm25 = BM25Okapi(doc_tokens)
    scores = bm25.get_scores(query_tokens)

    query_kw_set = set(query_tokens)
    scored = []
    for r, score, toks in zip(records, scores, doc_tokens):
        if score > 0:
            matched = sorted(query_kw_set & set(toks))
            scored.append((r, float(score), matched))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]
