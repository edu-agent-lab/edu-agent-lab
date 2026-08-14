"""Streamlit 웹 UI.

Day3 Step4 와이어프레임 구조를 그대로 따른다.

    [ 검색창 ]                                   [검색]
    ─────────────────────────────────────────────────
    검색 결과 요약
    수학 자료 3건을 찾았습니다. 프로젝트 2건, 퀴즈 1건. ...
    ─────────────────────────────────────────────────
    [ 결과 카드 ]  제목 · 자료유형 · 과목 · 날짜
                  2~3문장 요약
"""

from __future__ import annotations

import streamlit as st

from mcp_client import fetch_all_pages
from query_classifier import classify_query
from search import PageMeta, describe_results, search
from summarizer import summarize_text

# 결과가 많으면 요약을 그만큼 부른다. 첫 화면에는 이만큼만.
PAGE_SIZE = 8

st.set_page_config(page_title="Notion 수업 자료 검색", page_icon="🔍")
st.title("Notion 수업 자료 검색")


@st.cache_resource(show_spinner="Notion에서 자료를 읽는 중...")
def load_pages():
    """데이터셋 전체를 한 번만 읽는다. npx 기동까지 10초쯤 걸린다."""
    return fetch_all_pages()


@st.cache_data(show_spinner=False)
def cached_summary(title: str, content: str) -> str:
    """같은 페이지를 두 번 요약하지 않는다."""
    return summarize_text(title, content)


def render_card(meta: PageMeta) -> None:
    with st.container(border=True):
        st.markdown(f"**{meta.title}**")

        chips = [
            value
            for value in (
                meta.material_type,
                " / ".join(meta.subject_keys) or None,
                meta.grade,
                meta.date,
                "요청서" if meta.is_request else None,
            )
            if value
        ]
        if chips:
            st.caption(" · ".join(chips))

        try:
            st.write(cached_summary(meta.title, meta.page.content))
        except Exception as exc:  # 요약이 실패해도 검색 결과까지 가리지 않는다
            st.caption(f"요약을 만들지 못했습니다 ({exc})")

        if meta.page.url:
            st.link_button("Notion에서 열기", meta.page.url)


# --- 검색창 -------------------------------------------------------------

if "query" not in st.session_state:
    st.session_state.query = ""

with st.form("search", border=False):
    field, button = st.columns([5, 1], vertical_alignment="bottom")
    with field:
        typed = st.text_input(
            "검색어",
            label_visibility="collapsed",
            placeholder="예: 토론 수업 관련 자료 찾아줘",
        )
    with button:
        submitted = st.form_submit_button("검색", use_container_width=True)

if submitted:
    st.session_state.query = typed.strip()

query = st.session_state.query
if not query:
    st.stop()

# --- 검색 ---------------------------------------------------------------

pages = load_pages()

with st.spinner("검색 중..."):
    try:
        intent = classify_query(query, known_titles=[p.title for p in pages])
    except Exception as exc:
        st.error(f"질의를 이해하지 못했습니다: {exc}")
        st.stop()
    hits = search(intent, pages)

# --- 검색 결과 요약 ------------------------------------------------------

st.divider()
st.markdown("#### 검색 결과 요약")
st.write(describe_results(hits, intent))

if not hits:
    st.stop()

# --- 결과 리스트 ---------------------------------------------------------

st.divider()
for meta in hits[:PAGE_SIZE]:
    render_card(meta)

if len(hits) > PAGE_SIZE:
    st.caption(f"{len(hits)}건 중 상위 {PAGE_SIZE}건만 표시했습니다.")
