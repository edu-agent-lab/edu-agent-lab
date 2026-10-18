"""문자 2-gram + BM25 기반 키워드 검색.

단순히 "쿼리 키워드가 몇 종류나 매칭됐냐"로 세면, 흔한 단어가 여기저기 다 걸려서
정작 핵심 단어로 좁혀지지 않는다. BM25는 단어별로 "이 후보군에서 얼마나 희귀한가"
(IDF)를 반영해 흔한 단어의 기여를 낮추고 문서 길이도 보정해준다.

**IDF는 넘겨받은 후보군 기준으로 계산된다.** 그래서 슬롯 필터로 좁힌 뒤에 부르는 게
중요하다 — "중학교 사회 74건 안에서 '환경'이 얼마나 드문가"가 전체 5,789건 기준보다
정확하다.

## 토크나이저: 형태소 분석(kiwipiepy) -> 문자 2-gram

원래 kiwipiepy로 명사(NNG/NNP/SL)만 뽑았다. 조사를 떼려는 의도는 같은데, 분석기가
단어를 잘못 쪼개는 손실이 BM25 중심 랭킹에서 그대로 드러난다 — "저작권"을 "저작"으로,
"한살이"를 "한"+"살이"로 쪼개면 그 조각이 무관한 문서에도 걸린다.

2-gram은 어절 원형을 토큰에 그대로 남기면서 조사 문제도 해결한다:

    "저작권을" -> 저작권을 · 저작 · 작권 · 권을
    "저작권"   -> 저작권   · 저작 · 작권        <- 겹친다

골든셋 38건 실측 (BM25가 랭킹을 주도할 때의 Top-1):

| 랭킹            | kiwi | 2gram |
|-----------------|------|-------|
| BM25 단독       | 6/10 | 7/10  |
| BM25 주력       | 6/10 | 8/10  |
| dense 주력      | 9/10 | 9/10  |  <- dense가 주력이면 차이 없음

`수분`(인수분해를 자르다 나오는 조각)처럼 2-gram도 쓰레기 토큰을 만들지만, BM25의
IDF가 흔한 조각의 기여를 눌러준다. kiwipiepy 의존성이 사라지는 이점도 있다.
"""
import re

from rank_bm25 import BM25Okapi

_TOKEN = re.compile(r"[가-힣A-Za-z0-9]+")
_HANGUL = re.compile(r"[가-힣]")


def tokenize(text):
    """어절 + 한글 문자 2-gram. 문서 인덱싱과 쿼리에 같은 함수를 써야 비교가 된다."""
    out = []
    for word in _TOKEN.findall(text.lower()):
        out.append(word)
        if len(word) > 1 and _HANGUL.match(word):
            out += [word[i : i + 2] for i in range(len(word) - 1)]
    return out


def extract_keywords(text):
    """중복 제거된 키워드 목록 (표시/디버깅용). 2-gram 조각은 빼고 어절만 보여준다."""
    seen = []
    for tok in _TOKEN.findall(text.lower()):
        if len(tok) >= 2 and tok not in seen:
            seen.append(tok)
    return seen


def keyword_search(query, records, text_field="search_text", top_k=20):
    """BM25로 랭킹을 매긴다. records는 이미 슬롯 필터로 좁혀진 상태여야 한다.

    반환: [(record, bm25_score, matched_keywords), ...] score 내림차순, score<=0 제외.

    **결과가 빈 리스트면 "질의 단어가 후보 어디에도 없다"는 뜻이다.** 이게 공짜로
    얻는 "관련 자료 없음" 신호다 — dense는 코사인이 항상 양수라 뭐라도 반환하지만
    BM25는 겹치는 단어가 없으면 0점이라 걸러진다. hybrid_search가 이걸 게이트로 쓴다.
    """
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
