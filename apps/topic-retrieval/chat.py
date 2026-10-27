"""대화형 수업자료 생성 화면 (멀티턴).

    streamlit run chat.py

흐름: 주제 입력 -> 성취기준 검색 -> 번호로 선택 -> 생성 -> 수정 요청 반복 -> Notion 저장

**슬롯(학교급·과목·과정·자료 유형)은 여전히 사이드바 드롭다운으로 받는다.** app.py와 같은
이유다 — 대화에서 뽑다가 틀리면 엉뚱한 학교급 성취기준으로 자료가 만들어지고 사용자는 그걸
모른다. 대화가 맡는 건 주제 입력과 생성 후 수정("2차시로 줄여줘", "활동지를 더 쉽게")이다.

**성취기준 선택은 LLM을 거치지 않는다.** 메시지에서 숫자만 읽는다("1, 3번" -> 1·3위).
숫자가 없으면 새 주제로 보고 다시 검색한다.

**맥락은 선택한 성취기준의 과정으로 가져온다.** app.py는 검색 1위의 과정을 쓰는데, 과정을
"(전체)"로 두면 1위와 다른 과정의 성취기준을 골랐을 때 맥락이 어긋난다. 여러 과정을 고르면
과정별 맥락을 합친다.
"""

from __future__ import annotations

import re

import streamlit as st

from context_bundle import get_course_context, load_all_by_type
from data_loader import filter_by_slots, load_records, slot_options
from generate import MATERIAL_TYPES, SYSTEM, build_prompt, revise_material
from llm_client import generate as llm_generate
from llm_client import is_configured
from notion_save import is_configured as notion_configured
from notion_save import page_title, save_material

TOP_K = 5

st.set_page_config(page_title="NCIC 수업자료 대화", page_icon="💬", layout="wide")
st.title("NCIC 수업자료 대화")
st.caption("주제를 말하면 성취기준을 찾아 자료를 만들고, 대화로 고쳐 나갑니다.")


@st.cache_resource(show_spinner="성취기준을 읽는 중...")
def load_standards():
    return load_records(doc_type="achievement_standard")


@st.cache_resource(show_spinner="문서 전체를 읽는 중...")
def load_by_type():
    return load_all_by_type()


@st.cache_resource(show_spinner="임베딩 인덱스를 읽는 중...")
def load_index():
    """인덱스나 임베딩 의존성(torch)이 없으면 None. BM25만으로도 검색은 된다."""
    try:
        from embedding_search import EmbeddingIndex

        return EmbeddingIndex()
    except (FileNotFoundError, ImportError):
        return None


def search(topic: str, scoped: list[dict]) -> list[tuple[dict, float]]:
    index = load_index()
    if index is None:
        from keyword_search import keyword_search

        return [(r, s) for r, s, _ in keyword_search(topic, scoped, top_k=TOP_K)]
    from hybrid_search import hybrid_search

    return hybrid_search(topic, scoped, index, top_k=TOP_K)


def course_context(school_level: str, subject: str, picked: list[dict]) -> dict:
    """선택한 성취기준들의 과정마다 맥락을 가져와 합친다 (같은 문서는 한 번만)."""
    merged: dict[str, list[dict]] = {}
    for course in dict.fromkeys(r["course"] for r in picked):
        for doc_type, docs in get_course_context(
            load_by_type(), school_level, subject, course
        ).items():
            have = merged.setdefault(doc_type, [])
            seen = {d["_id"] for d in have}
            have += [d for d in docs if d["_id"] not in seen]
    return merged


def parse_picks(text: str, n: int) -> list[int]:
    """"1, 3번" -> [0, 2]. 범위 밖 숫자는 버린다."""
    nums = [int(x) for x in re.findall(r"\d+", text)]
    return list(dict.fromkeys(i - 1 for i in nums if 1 <= i <= n))


def eul(word: str) -> str:
    """받침에 맞는 목적격 조사. "수업계획안을", "퀴즈를"."""
    last = ord(word[-1]) - 0xAC00
    return word + ("을" if 0 <= last < 11172 and last % 28 else "를")


def say(role: str, content: str) -> None:
    st.session_state.messages.append({"role": role, "content": content})


def reset() -> None:
    for key in ("messages", "stage", "hits", "topic", "prompt", "material"):
        st.session_state.pop(key, None)


# --- 슬롯 (사이드바) -----------------------------------------------------

records = load_standards()

with st.sidebar:
    st.header("검색 조건")
    include_special = st.checkbox("특수교육·전문교과 포함")
    tree = slot_options(records, include_special=include_special)
    school_level = st.selectbox("학교급", list(tree))
    subject = st.selectbox("과목", list(tree[school_level]))
    courses = tree[school_level][subject]
    if len(courses) == 1:
        course = courses[0]
        st.caption(f"과정: {course}")
    else:
        picked_course = st.selectbox("과정", ["(전체)"] + courses)
        course = None if picked_course == "(전체)" else picked_course

    st.divider()
    material_type = st.radio("자료 유형", list(MATERIAL_TYPES))
    st.divider()
    if st.button("새로 시작", use_container_width=True):
        reset()

# 조건을 바꾸면 이전 대화의 검색 결과·자료는 더 이상 맞지 않는다.
slots = (school_level, subject, course, material_type)
if st.session_state.get("slots") != slots:
    st.session_state.slots = slots
    reset()

st.session_state.setdefault("messages", [])
st.session_state.setdefault("stage", "topic")

if not st.session_state.messages:
    say(
        "assistant",
        f"**{school_level} · {subject}" + (f" · {course}" if course else "")
        + f"** {eul(material_type)} 만들게요. 수업 주제를 알려주세요.\n\n"
        "예: 개발과 환경 보전을 둘러싼 갈등",
    )

for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

if not is_configured():
    st.warning("OPENAI_API_KEY가 없어 자료 생성은 쓸 수 없습니다 (저장소 루트 .env). 검색은 됩니다.")

# --- 대화 처리 -----------------------------------------------------------

placeholder = {
    "topic": "수업 주제를 입력하세요",
    "pick": "근거로 쓸 번호를 입력하세요 (예: 1, 3) — 숫자 없이 쓰면 새 주제로 검색",
    "revise": "고칠 내용을 말해 주세요 (예: 2차시로 줄이고 활동지를 더 쉽게)",
}[st.session_state.stage]

user_text = st.chat_input(placeholder)
if not user_text:
    if st.session_state.get("material"):
        col_md, col_notion = st.columns(2)
        with col_md:
            st.download_button(
                "마크다운으로 저장",
                st.session_state.material,
                file_name=f"{school_level}_{subject}_{material_type}.md",
                mime="text/markdown",
                use_container_width=True,
            )
        with col_notion:
            if st.button(
                "Notion에 저장",
                use_container_width=True,
                disabled=not notion_configured(),
                help=None if notion_configured() else "NOTION_TOKEN이 없습니다 (저장소 루트 .env)",
            ):
                title = page_title(
                    school_level=school_level,
                    subject=subject,
                    topic=st.session_state.topic,
                    material_type=material_type,
                )
                with st.spinner("Notion에 저장하는 중..."):
                    try:
                        url = save_material(title, st.session_state.material)
                        say("assistant", f"Notion에 저장했어요: [{title}]({url})")
                    except Exception as exc:
                        say("assistant", f"Notion 저장에 실패했습니다: {exc}")
                st.rerun()
    st.stop()

say("user", user_text)
stage = st.session_state.stage
hits = st.session_state.get("hits") or []
picks = parse_picks(user_text, len(hits)) if stage == "pick" else []

if stage == "revise":
    with st.spinner("고치는 중..."):
        try:
            st.session_state.material = revise_material(
                st.session_state.prompt, st.session_state.material, user_text
            )
            say("assistant", st.session_state.material)
        except Exception as exc:
            say("assistant", f"수정에 실패했습니다: {exc}")

elif stage == "pick" and picks:
    picked = [hits[i][0] for i in picks]
    prompt = build_prompt(
        school_level=school_level,
        subject=subject,
        course=course or (picked[0]["course"] if len({r["course"] for r in picked}) == 1 else None),
        topic=st.session_state.topic,
        material_type=material_type,
        standards=picked,
        bundle=course_context(school_level, subject, picked),
    )
    with st.spinner(f"{eul(material_type)} 만드는 중... (30초 안팎)"):
        try:
            st.session_state.material = llm_generate(prompt, system=SYSTEM)
            st.session_state.prompt = prompt
            st.session_state.stage = "revise"
            codes = ", ".join(r["code"] for r in picked)
            say("assistant", st.session_state.material)
            say("assistant", f"근거: {codes}\n\n고칠 부분이 있으면 말해 주세요.")
        except Exception as exc:
            say("assistant", f"생성에 실패했습니다: {exc}")

else:
    # topic 단계, 또는 pick 단계에서 숫자 없이 입력 -> 새 주제로 검색
    topic = user_text.strip()
    scoped = filter_by_slots(records, school_level=school_level, subject=subject, course=course)
    with st.spinner(f"후보 {len(scoped)}건에서 검색 중..."):
        hits = search(topic, scoped) if scoped else []
    if not hits:
        say(
            "assistant",
            f"'{topic}'와 관련된 성취기준을 찾지 못했어요. "
            "다른 표현으로 말하거나 사이드바의 과목·학교급을 확인해 주세요.",
        )
        st.session_state.stage = "topic"
    else:
        st.session_state.hits = hits
        st.session_state.topic = topic
        st.session_state.stage = "pick"
        lines = [
            f"{i}. **[{r['code']}]** {r['content']}  \n"
            f"   _{' · '.join(x for x in (r.get('course'), r.get('area')) if x)}_"
            for i, (r, _) in enumerate(hits, 1)
        ]
        say(
            "assistant",
            "관련 성취기준이에요. 근거로 쓸 번호를 골라 주세요 (여러 개 가능).\n\n"
            + "\n".join(lines),
        )

st.rerun()
