"""검색으로 찾은 성취기준의 course를 가지고, 계획안 생성에 필요한 나머지
3종 문서(purpose_goals/content_system/teaching_assessment)를 묶어서 가져온다.

주의: course 표기 단위가 문서 타입마다 다르다.
- achievement_standard: "공통수학1" (특정 코스로 좁혀짐)
- purpose_goals/teaching_assessment: "공통수학1, 공통수학2" (여러 코스가 묶인
  그룹 단위 문서라서). 그래서 정확 매칭이 아니라 포함 관계로 매칭한다.
"""
from collections import defaultdict

from data_loader import load_records, DEFAULT_PATH


def load_all_by_type(path=DEFAULT_PATH):
    """전체 doc_type을 한 번에 로드해서 {doc_type: [record, ...]} 로 묶어둔다.
    같은 요청 안에서 여러 코스를 조회할 거면 이걸 한 번만 불러서 재사용하면 된다."""
    by_type = defaultdict(list)
    for r in load_records(path):
        by_type[r["doc_type"]].append(r)
    return by_type


def _course_matches(record_course, target_course):
    if record_course is None or target_course is None:
        return record_course == target_course
    return target_course in record_course or record_course in target_course


def get_course_context(by_type, school_level, subject, course):
    """school_level/subject/course로 purpose_goals, content_system,
    teaching_assessment를 각각 찾아서 반환한다. (achievement_standard는 이미
    검색으로 찾은 상태라 여기서는 다루지 않음.)"""

    def find(doc_type):
        return [
            r for r in by_type.get(doc_type, [])
            if r["school_level"] == school_level
            and r["subject"] == subject
            and _course_matches(r.get("course"), course)
        ]

    return {
        "purpose_goals": find("purpose_goals"),
        "content_system": find("content_system"),
        "teaching_assessment": find("teaching_assessment"),
    }


if __name__ == "__main__":
    # 간단 확인용: 검색 없이 course만 지정해서 나머지 3종이 잘 묶이는지 본다.
    by_type = load_all_by_type()
    bundle = get_course_context(by_type, "고등학교", "수학", "공통수학1")
    for doc_type, records in bundle.items():
        print(f"{doc_type}: {len(records)}건")
        for r in records[:2]:
            print("  -", r["text"][:80])
