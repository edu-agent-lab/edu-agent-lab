# ncic-crawler

NCIC(국가교육과정정보센터, https://ncic.re.kr/inv/org/list.do) 원문 인벤토리에서
"보기" 버튼을 눌렀을 때 나오는 팝업 본문(성취기준 등)을 크롤링하는 스크립트.

## 동작 원리

1. `GET /inv/org/list.do` — 세션 쿠키 + CSRF 토큰 획득
2. `POST /api/inv/inventoryNodeList.do` — 좌측 트리(시대 → 학교급 → 과목 → 세부 항목)를
   재귀적으로 조회해 원하는 리프 노드(`ref`)를 찾음
3. `POST /inv/org/view.do` — 리프 노드의 `seq`로 "보기" 팝업 본문 HTML을 요청
4. 응답 안의 `.boardViewContent` HTML을 파싱해 구조화

참고: 항목에 따라 본문이 `.boardViewContent`(일반 HTML)가 아니라 HWP 웹에디터용
`data-hwpjson` 주석으로 내려오는 경우도 있음(예: "성격 및 목표" 페이지). 이 스크립트는
`.boardViewContent` 포맷(성취기준, 교수·학습 및 평가 페이지)만 처리한다.

## 크롤링 대상 & 출력

- **`crawl_achievement_standards()`** — "2. 내용 체계 및 성취기준 > 나. 성취기준" 페이지.
  단원별로 성취기준(코드 + 내용), 성취기준 해설, 적용 시 고려 사항을 구조화한다.
  → `output/common_math1_standards.json`
- **`crawl_teaching_and_assessment()`** — "3. 교수·학습 및 평가" 페이지.
  "가. 교수·학습"/"나. 평가" 아래 (1)(2) 하위 절별로 원문의 위계 기호((가)(나), ①②③,
  ㉠㉡㉢)를 그대로 살린 문장 리스트(`lines`)와, LLM 프롬프트에 바로 붙여넣을 수 있는
  이어붙인 텍스트(`text`)를 함께 제공한다.
  → `output/common_math1_teaching_assessment.json`

  주의: 이 페이지에는 "평가의 방향/방법" 같은 **일반 운영 지침**만 있고, 성취기준별
  A/B/C(상/중/하) 수준 평가기준표는 들어있지 않다. 그런 세부 채점 기준이 필요하면
  KICE(한국교육과정평가원)가 별도로 발간하는 "교육과정 평가기준" 자료를 따로 찾아야 한다.

## 실행

```bash
python3 ncic_crawl.py
```

기본값은 2022 개정 교육과정 · 고등학교 · 수학 · 공통수학1 이며, 위 두 파일이 모두 저장된다.

## 다른 과목/단원 크롤링하려면

`main()`의 `crawl_achievement_standards()` / `crawl_teaching_and_assessment()` 호출부에서
다음을 바꾸면 된다.

- `subject_folder_title`: 트리에서 과목 폴더명 (예: `"공통수학1, 공통수학2"`)
- `achievement_leaf_title` / `leaf_title`: 리프 노드명
  (예: `"나. 성취기준 - 공통수학2"`, `"3. 교수·학습 및 평가"`)
- `degreeCode`/`classCode`/`subjectCode`/`openYear`/`openMonth`: 시대/학교급/과목/개정년월
  (`find_leaf`가 호출하는 `inventoryNodeList.do` 파라미터와 동일)

여러 과목을 한 번에 크롤링하려면 두 함수를 반복 호출하면 된다.
서버 부하를 고려해 호출 사이에 약간의 지연(`time.sleep`)을 넣는 것을 권장한다.

## 전체 크롤링 (RAG용 JSONL)

`crawl_2022_full.py`는 2022 개정 교육과정(degreeCode=1014) 전 학교급·전 과목을
재귀적으로 순회하며 "2. 내용 체계 및 성취기준" + "3. 교수·학습 및 평가"를 모두
크롤링해 RAG에 바로 쓸 수 있는 JSONL로 저장한다.

```bash
python3 crawl_2022_full.py
```

- 범위: 초등학교·중학교·고등학교·초중등학교(통합)·특수교육, 각 2022.12 원본
  (초중등학교(통합)만 2022.12 판이 없어 2024.08 사용 — 단, 이 카테고리는 본문 없이
  빈 페이지 구조라 실제로는 0건 수집됨)
- 출력: `output/ncic_2022_rag.jsonl` (한 줄 = 성취기준 1개, 또는 교수학습/평가 하위 절 1개)
- 에러 로그: `output/ncic_2022_errors.jsonl` (트리 항목별로 `boardViewContent 없음` 등 사유 기록,
  전체 실행은 중단되지 않음)
- 네트워크 오류(curl 실패)는 `Session._curl`에서 자동 재시도(최대 3회, 지수 백오프)

레코드 스키마:

```json
// doc_type == "achievement_standard"
{
  "doc_type": "achievement_standard",
  "school_level": "고등학교",
  "subject": "수학",
  "course": "공통수학1",
  "grade_band": null,               // 초/중은 "[초등학교 3∼4학년]" 형태로 채워짐
  "area": "다항식",
  "code": "10공수1-01-01",
  "content": "다항식의 사칙연산의 원리를 설명하고, 그 계산을 할 수 있다.",
  "explanation": "...",             // 해당 영역의 성취기준 해설 (nullable)
  "considerations": "...",          // 적용 시 고려 사항 (nullable)
  "seq": "10069902",
  "text": "임베딩/프롬프트에 바로 넣을 수 있게 위 필드를 조합한 문자열"
}

// doc_type == "teaching_assessment"
{
  "doc_type": "teaching_assessment",
  "school_level": "고등학교",
  "subject": "수학",
  "course": "공통수학1, 공통수학2",
  "top": "평가",                    // "교수·학습" | "평가"
  "sub": "평가 방법",
  "seq": "10069866",
  "text": "..."
}
```

### 학교급/과목 트리 구조가 균일하지 않음에 주의

- 고등학교처럼 한 과목 아래 여러 과정(예: 수학 → 공통수학1/공통수학2/대수/미적분Ⅰ...)이
  있으면 "2./3." 항목이 각 과정 폴더 안에 있고, 초·중학교처럼 과정이 하나면 과목 바로
  아래 "1./2./3."이 있다 — `crawl_2022_full.py`의 `walk()`는 이 깊이 차이를 노드 자신의
  `invDepth` 필드를 그대로 따라가며 재귀 처리하므로 학교급/과목별로 값을 따로 넣을 필요는 없다.
- "2. 내용 체계 및 성취기준"이 폴더(가./나. 하위 항목 있음)인 경우와, 단일 과정이라
  "가.내용체계"+"나.성취기준"이 한 페이지에 합쳐진 leaf인 경우가 둘 다 있다 — 후자는
  본문에서 "나. 성취기준" 표제 이후만 잘라 파싱한다(`_standards_lines_only`).
- 초/중학교처럼 학년군별로 성취기준이 또 나뉘는 경우, "나. 성취기준" 폴더 아래
  `[초등학교 3∼4학년]` 같은 리프가 더 있다 — `grade_band` 필드로 남긴다.

## 재크롤(누락분 보충)

`crawl_2022_resume.py`는 `crawl_2022_full.py` 실행이 네트워크 오류 등으로 일부만
성공했을 때, 지정한 (학교급, 과목) 조합만 다시 크롤링해 기존 `ncic_2022_rag.jsonl`의
해당 부분만 교체·병합한다. `TARGETS`/`REPLACE_KEYS`를 필요에 맞게 수정해서 쓰면 된다.
