"""Streamlit 웹 UI: 검색창 -> 결과 목록(+요약)."""

import streamlit as st

from mcp_client import search_pages
from query_classifier import classify_query
from summarizer import summarize_results

st.set_page_config(page_title="Notion 수업 자료 검색", page_icon="🔍")
st.title("Notion 수업 자료 검색")

query = st.text_input("검색어를 입력하세요", placeholder="예: 토론 수업 진행 방법 관련 페이지 찾아줘")

if query:
    with st.spinner("검색 중..."):
        try:
            intent = classify_query(query)
            pages = search_pages(intent)
        except NotImplementedError:
            st.error("아직 구현되지 않은 기능입니다. (query_classifier / mcp_client 구현 필요)")
            st.stop()

    if not pages:
        st.info("검색 결과가 없습니다. 다른 검색어로 시도해보세요.")
    else:
        summaries = summarize_results(pages)
        st.write(f"{len(pages)}건의 결과를 찾았습니다.")
        for page in pages:
            with st.container(border=True):
                st.subheader(page.title)
                st.write(summaries[page.page_id])
                st.link_button("Notion에서 열기", page.url)
