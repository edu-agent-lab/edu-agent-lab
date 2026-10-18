"""ncic-crawler가 만든 ncic_2022_rag.jsonl을 읽어서 검색 실험에 쓸 레코드 목록으로 만든다."""
import json
import os

DEFAULT_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "ncic-crawler", "output", "ncic_2022_rag.jsonl"
)


def load_records(path=DEFAULT_PATH, doc_type=None):
    """doc_type을 주면 그 타입만(예: "achievement_standard") 필터링해서 반환한다.
    각 레코드에 원본 파일 기준 줄 번호를 "_id"로 붙여준다(임베딩 캐시와 매칭용)."""
    records = []
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            r = json.loads(line)
            if doc_type is not None and r.get("doc_type") != doc_type:
                continue
            r["_id"] = i
            if r.get("doc_type") == "achievement_standard":
                # 키워드(BM25) 매칭용 필드. content만 쓰면 같은 영역(area)의 다른 코드에
                # 있는 표현("한살이")을 놓치고, text(해설+고려사항 포함)를 통째로 쓰면
                # 무관한 단어까지 걸려 노이즈가 생긴다 — content+area가 재현율/정밀도
                # 둘 다 실측으로 가장 나았다 (README 실험 기록 참고).
                r["search_text"] = f"{r['content']} {r['area']}"
            records.append(r)
    return records


def filter_by_slots(records, school_level=None, subject=None, grade_band=None, course=None):
    """학년/과목/학년군/코스 슬롯으로 1차 필터링 (정확 매칭).
    course는 achievement_standard 기준으로 좁혀진 이름("공통수학1")을 그대로 쓰면 된다
    (achievement_standard의 course 필드는 이미 이 단위로 저장돼 있음)."""
    out = records
    if school_level:
        out = [r for r in out if r.get("school_level") == school_level]
    if subject:
        out = [r for r in out if r.get("subject") == subject]
    if grade_band:
        out = [r for r in out if r.get("grade_band") == grade_band]
    if course:
        out = [r for r in out if r.get("course") == course]
    return out


# 일반 수업계획안 대상이 아닌 과목. 전체 9,939건의 57%를 차지하는데 성격이 다르다
# (docs/topic-retrieval/data-notes.md). 기본으로 빼고, 필요할 때만 켠다.
#
#   특수교육 교과/영역  점자·수어처럼 일반 교과에 없는 과목 + 일반 교과 code를 재사용해
#                      중복 code가 370종 생긴다
#   전문 교과          특성화고 직업 교과 816개 course 대부분. 크롤 미수집 171건의 92%도 여기
#   ~계열 선택 과목     예술고·과학고·체고 전공 심화
SPECIAL_SUBJECTS = frozenset({
    "특수교육 교과/영역",
    "전문 교과",
    "예술 계열 선택 과목",
    "과학 계열 선택 과목",
    "체육 계열 선택 과목",
})


def slot_options(records, include_special=False):
    """화면 드롭다운에 쓸 선택지를 데이터에서 뽑는다.

    반환: {school_level: {subject: [course, ...]}}

    course를 자유 입력으로 받지 않는 이유 — 전체 816개라 사용자가 정확히 말할 수 없다.
    학교급·과목으로 좁히면 초·중은 1개, 고등학교도 최대 19개로 줄어 고를 수 있다.
    """
    tree = {}
    for r in records:
        if not include_special and r["subject"] in SPECIAL_SUBJECTS:
            continue
        tree.setdefault(r["school_level"], {}).setdefault(r["subject"], set()).add(r["course"])
    return {
        lv: {subj: sorted(courses) for subj, courses in sorted(subs.items())}
        for lv, subs in sorted(tree.items())
    }
