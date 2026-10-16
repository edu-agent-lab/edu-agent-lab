# topic-retrieval — NCIC 성취기준 검색 (프로젝트 2의 Retrieval 파트)

학년/과목/주제를 주면 `ncic-crawler`가 만든 `ncic_2022_rag.jsonl`(9,939건)에서
관련 성취기준을 찾는다. 에이전트에서 `search_standards(school_level, subject, topic)`
도구로 쓰일 부분이다.

**골든셋 38건 기준 Top-1 8/10 · R@3 0.92 · R@10 0.97 · 통과 33/38.**
어느 방식을 왜 골랐는지는 [`docs/topic-retrieval/evaluation.md`](../../docs/topic-retrieval/evaluation.md),
데이터 특성과 필터 설계는 [`data-notes.md`](../../docs/topic-retrieval/data-notes.md).

## 검색 방식

1. **슬롯 필터(정확 매칭)**: 학년/과목으로 후보를 먼저 좁힌다 (`data_loader.filter_by_slots`)
2. **키워드 검색(주력)**: 주제 문장을 문자 2-gram으로 토큰화해 BM25로 랭킹을 매긴다
   (`keyword_search.py`). 원래 형태소 분석(kiwipiepy)을 썼는데, BM25가 순위를 주도하는
   구성에서는 2-gram이 나았다(Top-1 6/10 -> 8/10) — 분석기가 "저작권"을 "저작"으로
   쪼개는 손실이 드러나기 때문이다. 의존성도 하나 줄었다.
   **BM25가 0건이면 "관련 자료 없음"으로 끝낸다** — 코사인에는 전역 임계값을 둘 수 없어서
   (0건 정답 질의의 1위 코사인 0.569 > 정답 있는 질의 0.497) 이게 유일하게 작동하는
   "결과 없음" 신호다. 매칭 대상은 `content + area`(성취기준 문장 +
   영역명) — 실험해보니 이게 재현율/정밀도 둘 다 제일 나았다:
   - `content`만 쓰면: 같은 영역(예: "생물의 한살이")의 다른 코드에만 있는 표현을 놓침
   - `text`(해설+고려사항까지 포함) 전체를 쓰면: 무관한 코드가 해설에 스친 단어 때문에
     걸려서 노이즈 발생 (예: "식물의 한살이" 검색에 "식물의 구조와 기능" 단원까지 상위권 오염)
   - `content + area`: 같은 영역 내 표현은 area로 잡히고, 무관한 영역의 지엽적 언급은
     안 걸림. `data_loader.load_records()`가 로드 시점에 `search_text` 필드로 미리 만들어둠
3. **임베딩 검색(dense)**: 로컬 임베딩 모델([`dragonkue/BGE-m3-ko`](https://huggingface.co/dragonkue/BGE-m3-ko),
   BAAI/bge-m3의 한국어 파인튜닝판)로 주제와 성취기준 간 코사인 유사도를 계산한다
   (`embedding_client.py`, `embedding_search.py`) — 표현이 달라도(예: "환경 보전" vs
   원문 "지속가능한 발전") 찾을 수 있음. OpenAI API 대신 로컬에서 돌기 때문에 API
   키/비용이 없는 대신, 최초 실행 시 모델(0.6B 파라미터)을 다운로드하고 추론도
   로컬 CPU/GPU로 하는 만큼 API 호출보다 느림
4. **하이브리드**: BM25를 기준선으로 두고 dense를 가산한다 — `bm25_정규화 + 0.5 * 코사인`
   (`hybrid_search.py`). RRF는 쓰지 않는다: 순위만 쓰고 점수 크기를 버려서 양쪽 골든셋에서
   일관되게 나빴다(통과 28/38 vs 가중합 32/38). `--fusion rrf`로 비교만 할 수 있게 남겨뒀다

## 준비

```bash
pip install -r requirements.txt
python build_index.py  # 성취기준 전체(5700여건)를 한 번 임베딩해서 index/에 캐싱
```

`.env`는 필요 없다 (임베딩이 로컬 모델이라 API 키 없음). `build_index.py`는 첫 실행 시
`dragonkue/BGE-m3-ko` 가중치를 허깅페이스에서 다운로드한 뒤(1GB대), 5700여 건을 CPU로
전부 인코딩한다 — API 호출과 달리 시간이 좀 걸릴 수 있다. 캐시는 `.gitignore`되어 있어
커밋되지 않으니, 다시 받으면 각자 한 번씩 돌려야 한다.

## 실행

```bash
python search.py --school_level 고등학교 --subject 사회 \
    --topic "개발과 환경 보전 중 무엇을 우선할 것인가"
```

## 평가

```bash
python eval.py              # 기본 구성
python eval.py --compare    # 단계별(filter/bm25/embed/hybrid) + 결합 방식 비교
python eval.py --case nr-topic-01 -v
```

골든셋 38건(`docs/topic-retrieval/golden-set.jsonl`). 두 구현의 케이스를 병합했고
출처를 접두사로 구분한다 — `tr-*`(course까지 좁힌 단일 정답), `nr-*`(복수 정답,
must_not/0건/어휘불일치, 특수교육 포함).

지표는 recall@3/@10, MRR, Top-1, 메타(필터 누수), 노이즈(must_not)다. 통과 조건은
"정답 전부 Top-10 + 노이즈 0 + Top-1 맞음 + 메타 1.00"이다.

## 아직 안 한 것 / 다음에 볼 것

- **슬롯 추출**: 지금은 CLI 인자로 받는다. 에이전트에서는 LLM이 tool 인자로 채우고,
  슬롯이 비면 검색하지 않고 되묻는 게 맞다
- `grade_band` 필터: 표기가 4종으로 깨져 있어 정규화 선행 필요 (data-notes.md 참고)
- 서술 문서(purpose_goals/content_system/teaching_assessment) 인덱스:
  골든셋에 `deferred` 케이스 3건을 남겨뒀다. 벡터 파일 1개 + 도구 1개면 켤 수 있다
- reranker: 남은 실패 중 `nr-semantic-01`이 첫 후보
