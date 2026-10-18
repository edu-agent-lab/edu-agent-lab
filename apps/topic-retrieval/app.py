"""성취기준 검색 + 수업자료 생성 화면.

슬롯(학교급·과목·과정)은 **드롭다운으로 직접 받는다.** 자연어에서 뽑아내지 않는 이유:

- 선택지가 데이터에서 그대로 나온다. 학교급 3개, 과목 11~15개, 과정은 초·중이 1개이고
  고등학교만 최대 19개다. 고를 수 있는 규모다
- 슬롯은 "비슷하면 통과"가 아니라 맞거나 틀린 조건이다. 추출이 틀리면 엉뚱한 학교급
  성취기준으로 자료가 만들어지고 **사용자는 그게 틀렸는지 모른다**
- 주제만 자유 입력으로 두면 어휘가 어긋나도 임베딩이 받아낸다

**성취기준도 사용자가 고른다.** 검색이 Top-5를 주고, 체크한 것만 생성 근거로 넘긴다.
교육과정 근거 검증이 목적이라 LLM이 성취기준을 섞거나 지어내면 안 된다.

    streamlit run app.py
"""

from __future__ import annotations

import streamlit as st

from context_bundle import get_course_context, load_all_by_type
from data_loader import filter_by_slots, load_records, slot_options
from generate import MATERIAL_TYPES, generate_material
from llm_client import is_configured

TOP_K = 5

st.set_page_config(page_title="NCIC 수업자료 생성", page_icon="📚", layout="wide")
st.title("NCIC 수업자료 생성")
st.caption("국가교육과정 성취기준을 근거로 수업자료를 만듭니다.")


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

# --- 슬롯 입력 (사이드바) ------------------------------------------------

with st.sidebar:
    st.header("검색 조건")
    include_special = st.checkbox(
        "특수교육·전문교과 포함",
        help="기본은 제외한다. 일반 교과 code를 재사용해 중복이 생기고, "
        "특성화고 직업 교과가 결과를 채운다 (docs/topic-retrieval/data-notes.md)",
    )

    tree = slot_options(records, include_special=include_special)
    school_level = st.selectbox("학교급", list(tree))
    subject = st.selectbox("과목", list(tree[school_level]))

    courses = tree[school_level][subject]
    if len(courses) == 1:
        course = courses[0]
        st.caption(f"과정: {course}")
    else:
        picked = st.selectbox("과정", ["(전체)"] + courses)
        course = None if picked == "(전체)" else picked

    st.divider()
    material_type = st.radio("자료 유형", list(MATERIAL_TYPES))
    st.caption(MATERIAL_TYPES[material_type])

# --- 검색 ---------------------------------------------------------------

topic = st.text_input(
    "주제",
    placeholder="예: 개발과 환경 보전을 둘러싼 토론",
    help="수업에서 다룰 주제를 자유롭게 적으세요. 표현이 원문과 달라도 됩니다.",
)

if st.button("성취기준 검색", type="primary") and topic.strip():
    scoped = filter_by_slots(
        records, school_level=school_level, subject=subject, course=course
    )
    if not scoped:
        st.session_state.pop("hits", None)
        st.error("해당 학교급·과목 조합의 성취기준이 없습니다.")
        # 과목이 다른 학교급에만 있는 경우가 실제로 있다 (환경=중학교만, 교양=고등학교만).
        elsewhere = sorted({r["school_level"] for r in records if r["subject"] == subject})
        if elsewhere:
            st.info(f"'{subject}'는 {' · '.join(elsewhere)}에 있습니다.")
    else:
        index = load_index()
        with st.spinner(f"후보 {len(scoped)}건에서 검색 중..."):
            if index is None:
                from keyword_search import keyword_search

                hits = [(r, s) for r, s, _ in keyword_search(topic, scoped, top_k=TOP_K)]
            else:
                from hybrid_search import hybrid_search

                hits = hybrid_search(topic, scoped, index, top_k=TOP_K)
        st.session_state.hits = hits
        st.session_state.query = (school_level, subject, course, topic, len(scoped))
        st.session_state.pop("material", None)

if "hits" not in st.session_state:
    st.stop()

hits = st.session_state.hits
q_level, q_subject, q_course, q_topic, n_scoped = st.session_state.query
st.caption(
    f"{q_level} · {q_subject}" + (f" · {q_course}" if q_course else "")
    + f" · '{q_topic}' → 후보 {n_scoped}건"
)

# BM25가 0건이면 hybrid_search가 빈 결과를 돌려준다 — 주제 단어가 후보 어디에도 없다는 뜻.
if not hits:
    st.warning(
        f"'{q_topic}'와 관련된 성취기준을 찾지 못했습니다. "
        "다른 표현으로 바꾸거나 과목·학교급을 확인해 주세요."
    )
    st.stop()

# --- 성취기준 선택 -------------------------------------------------------

st.divider()
st.markdown("#### 근거로 쓸 성취기준을 고르세요")

picked = []
for rank, (record, score) in enumerate(hits, 1):
    with st.container(border=True):
        checked = st.checkbox(
            f"**[{record['code']}]** {record['content']}",
            value=(rank == 1),  # 1위만 기본 선택
            key=f"pick-{record['_id']}",
        )
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
        if checked:
            picked.append(record)

# --- 생성 ---------------------------------------------------------------
# 성취기준을 찾은 뒤 그 course의 성격·목표·내용체계·교수학습을 꺼내 함께 넘긴다.
# 검색이 아니라 조회다 (과목당 하나뿐이므로).

ctx_course = q_course or hits[0][0].get("course")
bundle = get_course_context(load_by_type(), q_level, q_subject, ctx_course)

st.divider()
col_btn, col_info = st.columns([1, 3])
with col_btn:
    go = st.button(
        f"{material_type} 생성",
        type="primary",
        disabled=not picked or not is_configured(),
    )
with col_info:
    if not is_configured():
        st.warning("OPENAI_API_KEY가 없어 생성을 쓸 수 없습니다 (.env.example 참고). 검색은 그대로 됩니다.")
    elif not picked:
        st.info("성취기준을 하나 이상 골라주세요.")
    else:
        found = {k: len(v) for k, v in bundle.items() if v}
        st.caption(
            f"성취기준 {len(picked)}건 + 과목 맥락 {sum(found.values())}건"
            + (f" ({ctx_course})" if ctx_course else "")
        )

if go:
    with st.spinner(f"{material_type}을 만드는 중..."):
        try:
            st.session_state.material = generate_material(
                school_level=q_level,
                subject=q_subject,
                course=ctx_course,
                topic=q_topic,
                material_type=material_type,
                standards=picked,
                bundle=bundle,
            )
        except Exception as exc:
            st.error(f"생성에 실패했습니다: {exc}")

if st.session_state.get("material"):
    st.divider()
    st.markdown(st.session_state.material)
    st.download_button(
        "마크다운으로 저장",
        st.session_state.material,
        file_name=f"{q_level}_{q_subject}_{material_type}.md",
        mime="text/markdown",
    )

# --- 과목 맥락 (참고용) --------------------------------------------------

if any(bundle.values()):
    st.divider()
    with st.expander(f"교육과정 원문 — {ctx_course}"):
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
                st.markdown(f"**{LABEL[doc_type]}**" + (f" — {title}" if title else ""))
                st.text(doc["text"])
