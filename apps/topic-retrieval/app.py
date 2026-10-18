"""성취기준 검색 화면.

슬롯(학교급·과목·과정)은 **드롭다운으로 직접 받는다.** 자연어에서 뽑아내지 않는 이유:

- 선택지가 데이터에서 그대로 나온다. 학교급 3개, 과목 11~15개, 과정은 초·중이 1개이고
  고등학교만 최대 19개다. 고를 수 있는 규모다
- 슬롯은 "비슷하면 통과"가 아니라 맞거나 틀린 조건이다. 추출이 틀리면 엉뚱한 학교급
  성취기준으로 수업계획안이 나오고 **사용자는 그게 틀렸는지 모른다**
- 주제만 자유 입력으로 두면 어휘가 어긋나도 임베딩이 받아낸다

CLI(`search.py`)와 같은 입력을 받는다. 검색 로직은 그대로 쓴다.

    streamlit run app.py
"""

from __future__ import annotations

import streamlit as st

from context_bundle import get_course_context, load_all_by_type
from data_loader import filter_by_slots, load_records, slot_options

TOP_K = 5

st.set_page_config(page_title="NCIC 성취기준 검색", page_icon="📚")
st.title("NCIC 성취기준 검색")


@st.cache_resource(show_spinner="성취기준을 읽는 중...")
def load_standards():
    return load_records(doc_type="achievement_standard")


@st.cache_resource(show_spinner="문서 전체를 읽는 중...")
def load_by_type():
    """성격·목표·내용체계·교수학습을 course로 꺼내 쓰기 위한 사전."""
    return load_all_by_type()


@st.cache_resource(show_spinner="임베딩 인덱스를 읽는 중...")
def load_index():
    """없으면 None. BM25만으로도 검색은 된다."""
    from embedding_search import EmbeddingIndex

    try:
        return EmbeddingIndex()
    except FileNotFoundError:
        return None


records = load_standards()

# --- 슬롯 입력 ---------------------------------------------------------

with st.sidebar:
    st.header("검색 조건")
    include_special = st.checkbox(
        "특수교육·전문교과 포함",
        help="기본은 제외한다. 일반 교과 code를 재사용해 중복이 생기고, "
        "특성화고 직업 교과가 결과를 채운다 (data-notes.md 참고)",
    )

    tree = slot_options(records, include_special=include_special)

    school_level = st.selectbox("학교급", list(tree))
    subject = st.selectbox("과목", list(tree[school_level]))

    courses = tree[school_level][subject]
    course = (
        courses[0]
        if len(courses) == 1
        else st.selectbox("과정", ["(전체)"] + courses)
    )
    if course == "(전체)":
        course = None
    if len(courses) == 1:
        st.caption(f"과정: {courses[0]}")

topic = st.text_input(
    "주제",
    placeholder="예: 개발과 환경 보전을 둘러싼 토론",
    help="수업에서 다룰 주제를 자유롭게 적으세요. 표현이 원문과 달라도 됩니다.",
)
search = st.button("검색", type="primary")

# --- 검색 -------------------------------------------------------------

if not search or not topic.strip():
    if search:
        st.warning("주제를 입력해 주세요.")
    st.stop()

scoped = filter_by_slots(
    records, school_level=school_level, subject=subject, course=course
)
st.caption(
    f"{school_level} · {subject}" + (f" · {course}" if course else "")
    + f" → 후보 {len(scoped)}건"
)

if not scoped:
    st.error("해당 학교급·과목 조합의 성취기준이 없습니다.")
    # 과목이 다른 학교급에만 있는 경우가 실제로 있다 (환경=중학교만, 교양=고등학교만).
    elsewhere = sorted(
        {r["school_level"] for r in records if r["subject"] == subject}
    )
    if elsewhere:
        st.info(f"'{subject}'는 {' · '.join(elsewhere)}에 있습니다.")
    st.stop()

index = load_index()
with st.spinner("검색 중..."):
    if index is None:
        from keyword_search import keyword_search

        hits = [(r, s) for r, s, _ in keyword_search(topic, scoped, top_k=TOP_K)]
        st.caption("임베딩 인덱스가 없어 키워드 검색만 했습니다 (`python build_index.py`)")
    else:
        from hybrid_search import hybrid_search

        hits = hybrid_search(topic, scoped, index, top_k=TOP_K)

# BM25가 0건이면 hybrid_search가 빈 결과를 돌려준다 — 주제 단어가 후보 어디에도 없다는 뜻.
if not hits:
    st.warning(
        f"'{topic}'와 관련된 성취기준을 찾지 못했습니다. "
        "다른 표현으로 바꾸거나 과목·학교급을 확인해 주세요."
    )
    st.stop()

# --- 결과 -------------------------------------------------------------

st.divider()
for rank, (record, score) in enumerate(hits, 1):
    with st.container(border=True):
        st.markdown(f"**[{record['code']}]** {record['content']}")
        meta = " · ".join(
            x for x in (record.get("grade_band"), record.get("area")) if x
        )
        st.caption(f"{rank}위 · {score:.3f} · {meta}")

        if record.get("explanation"):
            with st.expander("성취기준 해설"):
                st.write(record["explanation"])
        if record.get("considerations"):
            with st.expander("적용 시 고려 사항"):
                st.write(record["considerations"])

# --- 과목 맥락 ---------------------------------------------------------
# 성취기준을 찾은 뒤 그 course의 성격·목표·내용체계·교수학습을 꺼낸다. 검색이 아니라
# 조회다 (과목당 하나뿐이므로). 수업계획안을 만들 때 근거로 함께 넘길 부분이다.

ctx_course = course or hits[0][0].get("course")
bundle = get_course_context(load_by_type(), school_level, subject, ctx_course)
if any(bundle.values()):
    st.divider()
    st.markdown(f"#### 과목 맥락 — {ctx_course}")
    LABEL = {
        "purpose_goals": "성격 · 목표",
        "content_system": "내용 체계",
        "teaching_assessment": "교수·학습 및 평가",
    }
    for doc_type, docs in bundle.items():
        for doc in docs:
            title = " · ".join(
                x for x in (doc.get("section"), doc.get("top"), doc.get("sub")) if x
            )
            with st.expander(f"{LABEL[doc_type]}" + (f" — {title}" if title else "")):
                st.text(doc["text"])
