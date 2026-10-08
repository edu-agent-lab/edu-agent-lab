# topic-retrieval (실험용)

`experiment/topic-retrieval` 브랜치 전용. 팀과 아직 합의 전인 개인 실험이라 여기서만 건드린다.

사용자가 학년/과목/주제(자유 문장)를 주면, `ncic-crawler`가 만든
`ncic_2022_rag.jsonl`에서 관련 성취기준을 찾는 검색 방식을 테스트하는 스크립트 모음.

## 검색 방식

1. **슬롯 필터(정확 매칭)**: 학년/과목으로 후보를 먼저 좁힌다 (`data_loader.filter_by_slots`)
2. **키워드 검색**: 주제 문장을 형태소 분석(kiwipiepy)해 명사 키워드를 뽑고, BM25로
   랭킹을 매긴다 (`keyword_search.py`). 매칭 대상은 `content + area`(성취기준 문장 +
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
4. **하이브리드**: 위 두 결과를 RRF(Reciprocal Rank Fusion)로 합쳐서 최종 순위를 매긴다
   (`hybrid_search.py`) — 한쪽만 성공했다고 다른 쪽을 생략하지 않고 항상 둘 다 돌려서 합산

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

## 아직 안 한 것 / 다음에 볼 것

- RRF 대신 가중합 등 다른 결합 방식과 비교
- top_k, RRF_K 같은 하이퍼파라미터 튜닝
- teaching_assessment/content_system/purpose_goals도 같은 방식으로 검색할지 결정
- 검색 품질 평가용 골든셋 준비 (지금은 눈으로만 확인)
- 임베딩 쪽도 `content+area` 정도로 입력을 좁혔을 때 결과가 달라지는지 비교
  (지금은 `text` 필드 그대로 임베딩 — 임베딩은 의미 기반이라 부가 텍스트가 껴도
  BM25만큼 노이즈에 취약하진 않을 것으로 예상되지만 실측은 안 해봄)
