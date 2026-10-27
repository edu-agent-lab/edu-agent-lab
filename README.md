# edu-agent-lab

교사의 수업 준비를 돕는 AI 에이전트 서비스를 만들어가는 과정을 담은 저장소입니다. MCP로
외부 서비스를 다루는 법부터 시작해, 이를 하나의 에이전트로 통합하는 것까지 단계적으로
진행합니다.

## 프로젝트 구성

| 단계 | 프로젝트 | 내용 | 상태 |
|---|---|---|---|
| 1 | [Notion 페이지 검색 및 요약](apps/notion-search) | MCP 클라이언트를 직접 구현해 Notion 팀스페이스에서 자연어 질의로 페이지를 검색·요약 | 완료 |
| 2 | AI 챗봇 기반 수업계획안 생성 | 멀티턴으로 요구를 수집해 수업계획안을 만들고, **NCIC 교육과정 성취기준으로 근거를 검증**한 뒤 Notion에 저장 | 진행 중 |
| 종합 | AI 기반 수업 활동 에이전트 서비스 | 여러 외부 서비스를 엮어 다양한 수업자료를 생성하는 에이전트로 통합 | 예정 |

## 저장소 구조

```
edu-agent-lab/
├── apps/
│   ├── notion-search/     프로젝트 1. Notion 자료 검색·요약 (Streamlit)
│   ├── ncic-crawler/      NCIC 교육과정 크롤러 -> ncic_2022_rag.jsonl (9,939건)
│   └── topic-retrieval/   프로젝트 2의 Retrieval 파트. 성취기준 검색 (슬롯 필터 + BM25 + 임베딩)
└── docs/
    ├── notion-search/     프로젝트 1 설계·평가 문서, 골든셋
    └── topic-retrieval/   검색 방식 선정 근거, 데이터 특성, 골든셋
```

각 폴더의 README에 실행 방법과 설계 결정이 적혀 있습니다.

## 프로젝트 2 진행 상황

전략 문서의 RAG 파이프라인 기준:

| 단계 | 담당 | 상태 |
|---|---|---|
| NCIC 자료 수집 · 전처리 | 크롤러 | 완료 (9,939건, doc_type 4종) |
| Indexing (Chunking · Embedding) | — | 완료. 성취기준은 원문이 한 문장 단위라 chunking 없이 레코드 = chunk |
| Query 전처리 (슬롯 추출) | — | 드롭다운으로 대체. 추출이 틀리면 사용자가 모르기 때문에 화면에서 직접 고른다. 에이전트에서는 LLM이 tool 인자로 채운다 |
| Keyword Search (BM25) | — | 완료. 문자 2-gram + 후보군 기준 IDF |
| Vector Search (dense) | — | 완료. `dragonkue/BGE-m3-ko` |
| Hybrid Search | — | 완료. BM25 주력 + dense 0.5 가산, BM25 0건 게이트 |
| RAG 평가 | — | 완료. 골든셋 19/19, 방식 비교 문서화 |
| LLM Context 구성 · 생성 | — | 완료. 성취기준(해설·고려사항) + 과목 맥락 3종, 내용 체계는 관련 영역만. 출력은 8개 항목 고정 ([`generation-notes.md`](docs/topic-retrieval/generation-notes.md)) |
| 멀티턴 챗봇 · Notion 저장 | — | 완료. `chat.py` — 주제 입력 -> 성취기준 번호 선택 -> 생성 -> 대화로 수정 -> Notion 저장 |
| 생성 품질 평가 | — | **미완**. 정답이 없는 산출물이라 체크리스트가 필요하다 |

근거와 측정값: [`docs/topic-retrieval/evaluation.md`](docs/topic-retrieval/evaluation.md),
데이터 특성: [`docs/topic-retrieval/data-notes.md`](docs/topic-retrieval/data-notes.md)
