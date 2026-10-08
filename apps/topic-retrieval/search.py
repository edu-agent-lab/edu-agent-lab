#!/usr/bin/env python3
"""학년/과목/주제를 주면 관련 성취기준을 찾아서 보여주는 실험용 CLI.

사전 준비: python build_index.py (최초 1회, 임베딩 캐시 생성)

사용 예:
    python search.py --school_level 고등학교 --subject 사회 \
        --topic "개발과 환경 보전 중 무엇을 우선할 것인가"
"""
import argparse

from data_loader import load_records, filter_by_slots
from embedding_search import EmbeddingIndex
from hybrid_search import hybrid_search


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--school_level", required=True, help="예: 초등학교/중학교/고등학교/특수교육")
    ap.add_argument("--subject", required=True, help="예: 사회, 국어, 수학 ...")
    ap.add_argument("--topic", required=True, help="사용자가 말한 토론 주제(자유 문장)")
    ap.add_argument("--top_k", type=int, default=10)
    args = ap.parse_args()

    all_records = load_records(doc_type="achievement_standard")
    scoped = filter_by_slots(all_records, school_level=args.school_level, subject=args.subject)
    print(f"슬롯 필터링 후 후보: {len(scoped)}건 "
          f"({args.school_level} · {args.subject})")

    if not scoped:
        print("해당 학년/과목 조합의 성취기준이 없습니다.")
        return

    index = EmbeddingIndex()
    results = hybrid_search(args.topic, scoped, index, top_k=args.top_k)

    print(f"\n주제: {args.topic!r}\n")
    for i, (record, score) in enumerate(results, 1):
        print(f"[{i}] rrf={score:.4f}  {record['code']}  ({record['area']})")
        print(f"    {record['content']}")
        print()


if __name__ == "__main__":
    main()
