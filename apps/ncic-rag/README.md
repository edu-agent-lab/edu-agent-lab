# ncic-rag — NCIC 성취기준 검색 (프로젝트 2의 Retrieval 파트)

`apps/ncic-crawler`가 만든 `output/ncic_2022_rag.jsonl`(9,784건)을 검색 가능한 형태로
바꾸고(Indexing), 질문에서 NCIC 근거를 찾는다(Retrieval).

```
ncic_2022_rag.jsonl  ─ index.py ─→  vecs.npy        (한 번만)
질문 ─ retrieve.py ─→ 메타 필터 + dense + BM25 ─→ Top-K 레코드 ─→ LLM 컨텍스트
```

## 파일

| 파일 | 역할 |
|---|---|
| `dataset.py` | JSONL 로드 + 임베딩 입력 문자열 생성 (`to_text`). index/retrieve가 공유 |
| `index.py` | 전체를 bge-m3-ko로 인코딩해 `vecs.npy` 저장 |
| `retrieve.py` | 메타 필터 → dense/BM25/hybrid → Top-K |

`vecs.npy`는 40MB이고 `index.py`로 언제든 다시 만들 수 있어 커밋하지 않는다.

## 실행

```bash
pip install -r requirements.txt
python index.py                 # 첫 실행: 모델 2GB 다운로드 + CPU 인코딩 20~40분
python retrieve.py "중학교 사회에서 환경 문제로 토론할 때 성취기준"
python retrieve.py "..." --mode bm25 --school-level 중학교 --doc-type achievement_standard
```

`--mode bm25`는 `vecs.npy` 없이도 돌아간다(모델 로드 없음). 파이프라인만 확인할 때 쓴다.

## 인덱싱 대상 — 전체를 넣는다

doc_type 4종 9,784건을 모두 임베딩한다. 대신 **doc_type별로 임베딩 입력을 다르게** 만든다.

| doc_type | 건수 | 임베딩 입력 |
|---|---|---|
| `achievement_standard` | 5,709 | 프리픽스 + `[code] content` + `explanation` |
| `teaching_assessment` | 1,629 | 프리픽스 + `text` |
| `purpose_goals` | 1,620 | 프리픽스 + `text` |
| `content_system` | 826 | 프리픽스 + `text` |

프리픽스는 `school_level subject course (grade_band/area/section/top·sub)`. 질의에 과목·학년이
섞여 들어오므로 본문 앞에 붙여 그 어휘로도 걸리게 한다.

**성취기준만 `text`를 쓰지 않는 이유**: `text`에 포함된 `considerations`(중앙값 482자)는
성취기준별이 아니라 **영역 공통** 텍스트다. 같은 영역 성취기준 5건에 같은 500자가 붙어
있어서 그대로 임베딩하면 그 영역 안에서 순위 변별이 무너진다. 어느 쪽이 실제로 나은지는
질의셋으로 재야 하므로 `to_text(row, variant)`에 세 가지를 남겨뒀다.

| variant | 성취기준 입력 | 성격 |
|---|---|---|
| `v1` | content만 | 변별 최대, 어휘 최소 |
| `v2` | content + explanation | 기본값 |
| `v3` | text 전체 | considerations까지. "토론" 같은 수업 방법 어휘가 여기 있다 |

```bash
python index.py --variant v3 --out vecs_v3.npy
python retrieve.py "..." --variant v3 --vecs vecs_v3.npy
```

**임베딩에 안 넣은 필드도 검색 결과에서 그대로 읽힌다.** 벡터는 "몇 번째 레코드가 가까운가"를
고르는 데만 쓰고, 고른 뒤에는 원본 레코드(모든 필드)를 꺼내 LLM에 넘긴다.

## 검색 — 메타 필터 + dense + BM25

**① 메타데이터 필터**가 먼저다. 학교급·과목은 "비슷하면 통과"가 아니라 맞거나 틀린
조건이라, 벡터에 맡기면 중학교 질의에 고등학교 자료가 섞인다. 점수를 깎는 게 아니라
후보에서 제외한다.

**② dense**: bge-m3-ko. `normalize_embeddings=True`로 저장했으므로 내적이 곧 코사인이고
`vecs @ q` 한 줄이다.

**③ BM25**: 어휘가 정확히 맞아야 하는 것(성취기준 코드, "부등식", "인수분해")에 강하다.
토크나이저는 기호만 떼는 수준이라 "토론을" ≠ "토론"인 한계가 있다. 그 손실은 dense가
메우고, 질의셋에서 조사 때문에 놓치는 게 실제로 보이면 `kiwipiepy`를 붙인다.

②③의 점수 스케일이 달라서(코사인 0~1, BM25 0~30) 각자 최대값으로 나눈 뒤
`BM25_WEIGHT`(0.4)로 섞는다.

`WEIGHT`(doc_type별 가중치)는 전부 1.0 = 끈 상태다. 성취기준 5,709건과 서술 문서 4,075건이
한 인덱스에 있어 성취기준이 밀릴 수 있는데, 실제로 그런지는 질의셋을 봐야 안다.

## 평가

```bash
python eval_ncic.py              # hybrid (기본)
python eval_ncic.py --compare    # bm25 / dense / hybrid 한 표로
python eval_ncic.py --case topic-01 -v
```

골든셋 22건(`docs/ncic-rag/golden-set.jsonl`) — 초등 4 · 중등 8 · 고등 5 · 특수교육 4 ·
무필터 4, 유형은 topic 9 / lexical 3 / semantic 2 / filter 3 / empty 2 / doc_type 3.

| mode | Top-1 | R@3 | R@10 | 노이즈 | 통과 |
|---|---|---|---|---|---|
| bm25 | 7/13 | 0.58 | 0.79 | 3 | 10/22 |
| dense | 10/13 | 0.71 | 0.86 | 4 | 12/22 |
| **hybrid** | **11/13** | **0.72** | 0.85 | **2** | **14/22** |

튜닝 근거(토크나이저·가중치·비중을 왜 그 값으로 정했는지)와 남은 실패 8건의 원인은
[`docs/ncic-rag/evaluation.md`](../../docs/ncic-rag/evaluation.md)에 정리했다.

## 다음 (아직 안 한 것)

- v2 vs v3 비교 (`index.py --variant v3 --out vecs_v3.npy`)
- 질의에서 학교급·과목·course 추출 → 필터로 넘기기 (프로젝트 1 `classify_query` 재사용)
- 검색 결과를 LLM 컨텍스트로 넘기는 부분 (Retrieval 이후 단계)
