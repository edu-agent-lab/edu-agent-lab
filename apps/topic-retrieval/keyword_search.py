"""형태소 분석 기반 키워드 정확 매칭 검색.

사용자가 문장으로 준 주제("개발과 환경 보전 중 우선순위")에서 명사 위주 키워드를
뽑아내고, 각 레코드의 text에 그 키워드가 몇 개나 등장하는지로 점수를 매긴다.
조사가 붙은 형태("환경보전을")는 단순 substring 매칭이 잘 안 맞기 때문에 형태소
분석으로 어간만 추출해서 비교한다.
"""
from kiwipiepy import Kiwi

_kiwi = Kiwi()

# 키워드로 쓸 품사: 일반명사(NNG), 고유명사(NNP), 외국어(SL, 예: AI/DNA 등 영문 약어)
_KEYWORD_POS = {"NNG", "NNP", "SL"}


def extract_keywords(text, min_len=2):
    """텍스트에서 명사 위주 키워드(어간)를 중복 제거해 리스트로 반환한다."""
    tokens = _kiwi.tokenize(text)
    seen = []
    for t in tokens:
        if t.tag in _KEYWORD_POS and len(t.form) >= min_len:
            if t.form not in seen:
                seen.append(t.form)
    return seen


def keyword_search(query, records, text_field="text", top_k=20):
    """query에서 키워드를 뽑아, 각 레코드 text에 등장하는 키워드 수로 랭킹을 매긴다.
    반환: [(record, score, matched_keywords), ...] score 내림차순, score==0인 것은 제외."""
    keywords = extract_keywords(query)
    if not keywords:
        return []

    scored = []
    for r in records:
        haystack = r.get(text_field, "")
        matched = [kw for kw in keywords if kw in haystack]
        if matched:
            scored.append((r, len(matched), matched))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]
