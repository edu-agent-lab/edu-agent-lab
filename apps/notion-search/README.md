# 프로젝트 1: Notion 페이지 검색 및 요약

## 프로젝트 개요

교사가 자연어로("토론 수업 자료 찾아줘", "고1 수학 자료 찾아줘") 질문하면, MCP로 연결된
Notion 팀스페이스(수업 자료 14건)에서 관련 페이지를 찾아 OpenAI(gpt-5-mini)로 페이지별 요약을
생성해 보여주는 Streamlit 웹 서비스입니다. 질의 유형(제목/주제/속성)에 따라 다르게 매칭하고,
결과가 여러 건이면 화면 맨 위에 규칙 기반으로 만든 요약 문단을 먼저 보여줍니다. 골든셋
21건 기준 검색·분류 정확도 100%를 확인했습니다 (아래 "골든셋 · 평가" 참고).

## 전체 동작 흐름

설계 문서: [docs/notion-search/design.md](../../docs/notion-search/design.md)

```text
사용자 질문
      ↓
query_classifier.py   질의 유형 판단 + 검색 조건 구성
      ↓                                    QueryIntent
mcp_client.py         데이터셋 전체 조회 (앱 시작 시 1회, 캐싱)
      ↓                                    list[NotionPage]
search.py             속성·본문·제목 병합 → 필터링 → 랭킹
      ↓                                    list[PageMeta]
summarizer.py         페이지별 요약 생성 (OpenAI)
      ↓
app.py                검색창 + 결과 요약 + 결과 리스트
```

예시)

```
"수학 자료 찾아줘"

① 질의 분석      → 속성 필터 (subject=수학)
② 전체 조회      → 14건 (캐시 히트 시 0초)
③ 필터링·랭킹    → 3건
                   속성만으로는 1건. 본문 `- 과목: 공통수학1`과
                   제목까지 폴백해서 3건이 된다.
④ 요약 생성      → 카드마다 2~3문장
⑤ 화면 출력      → "수학 자료 3건을 찾았습니다. 프로젝트 2건, 퀴즈 1건입니다.
                    이 중 2건은 자료 생성 요청서입니다."
```

## 담당

| 파일 | 담당 | 역할 |
|---|---|---|
| `query_classifier.py` | 나 | 질의 유형 판단(주제/제목/속성) + QueryIntent 구성 |
| `prompt.py` | 나 | 필터 추출/요약용 프롬프트 템플릿 |
| `summarizer.py` | 나 | 검색 결과 페이지별 요약 생성 |
| `search.py` | 나 | 속성·본문·제목 병합, 정규화, 필터링, 랭킹 |
| `eval.py` | 나 | 골든셋 채점 (재현율/정확도/노이즈) |
| `mcp_client.py` | 팀원 | Notion MCP 서버 연결, 전체 조회·캐싱, 응답 파싱 |
| `llm_client.py` | 팀원 | LLM API 클라이언트 (OpenAI gpt-5-mini) + 재시도 |
| `app.py` | 공통 | Streamlit UI, 파이프라인 연결 |

## 모듈 간 계약

```
classify_query(질의) -> QueryIntent
fetch_all_pages()   -> list[NotionPage]      # 데이터셋 전체, 앱 시작 시 1회
search(intent, pages) -> list[PageMeta]      # 필터링·랭킹된 결과
summarize_text(title, content) -> str   # 페이지 1건 요약, app.py가 카드마다 호출
```

**`mcp_client`는 검색하지 않고 전체를 읽어오기만 한다.** 원래 `search_pages(intent)`로 잡았다가
바꾼 이유는 세 가지다.

- `API-post-search`는 **제목만** 검색한다. "토론"으로 찾으면 제목에 그 단어가 없는
  `근대화 과정에서 외세의 수용은 불가피했는가?`가 빠진다.
- 데이터가 **14건뿐**이라 전부 메모리에 올려도 부담이 없다.
- 속성이 절반쯤 비어 있어(과목 7/14, 학년 6/14 누락) **속성 -> 본문 -> 제목** 순으로
  폴백해야 하는데, 그러려면 데이터가 손에 있어야 한다.

데이터가 크게 늘면 서버 사이드 필터링으로 되돌려야 한다.

`QueryIntent`(query_classifier)와 `NotionPage`(mcp_client) 두 데이터클래스의 필드만 맞춰두면
서로의 구현이 끝나기 전에도 독립적으로 개발/테스트할 수 있다.

## 실행 방법

```bash
cd apps/notion-search
pip install -r requirements.txt
cp .env.example .env  # 값 채우기
streamlit run app.py
```

## MCP 연동 방식 (결정: 옵션 B)

Notion 공식 문서 기준으로 연결 방식이 두 가지 있는데, 실제로 `manual_mcp_test.py`로 둘 다 검증해본 결과 **옵션 B로 결정**.

**옵션 A: 원격 호스팅 서버** (`https://mcp.notion.com/mcp`, Streamable HTTP) — 채택 안 함
- 인증: OAuth 2.0 + PKCE. 브라우저 리다이렉트로 사람이 매번 로그인/승인해야 토큰이 나오는 구조라, 사람 개입 없이 돌아가야 하는 Streamlit 백엔드에는 안 맞음. (Claude Desktop에서 됐던 건 앱이 이 로그인 팝업을 대신 띄워줬기 때문.)
- `NOTION_TOKEN`(Integration Secret)을 Bearer로 그냥 보내면 **401 Unauthorized** — OAuth 토큰이 아니라서 거부됨.
- 가이드: [Build an MCP client](https://developers.notion.com/guides/mcp/build-mcp-client)

**옵션 B: 오픈소스 로컬 서버** (`@notionhq/notion-mcp-server`, Node 패키지, npx로 실행) — **채택**
- 인증: OAuth 없이 `NOTION_TOKEN`(Internal Integration Secret) 환경변수 하나. https://www.notion.so/profile/integrations 에서 발급, 대상 페이지에 Connections로 연결 필요
- 전송 방식: **stdio** (원격 HTTP 아님). `mcp` SDK의 `stdio_client` + `StdioServerParameters(command="npx", args=["-y", "@notionhq/notion-mcp-server"], env={"NOTION_TOKEN": ...})`로 붙는다. 예제: `manual_mcp_test.py`
- 참고: [오픈소스 저장소](https://github.com/makenotion/notion-mcp-server)
- **배포 시 주의**: 이 서버를 npx로 띄우는 방식이라, 배포 환경에도 Node.js가 설치되어 있어야 함 (로컬 개발 머신만이 아니라 실제 서비스가 돌아갈 서버/호스팅에도 필요).

**사용할 tool (실제 확인된 이름 — 스펙 문서의 `notion-search`/`notion-fetch`와 다름)**

옵션 B 서버는 Notion REST API를 그대로 감싼 도구 이름을 쓴다. 스펙 문서의 `notion-search`/`notion-fetch`는 옵션 A(원격 서버) 전용 이름으로 보이고, 옵션 B에는 그 이름의 tool이 없음.

| tool | 용도 | 입력 |
|---|---|---|
| `API-post-search` | 워크스페이스 검색 | `{"query": "..."}` |
| `API-retrieve-a-page` | 페이지 본문 조회 | `{"page_id": "..."}` |
| `API-retrieve-page-markdown` | 페이지를 마크다운으로 조회 | `{"page_id": "..."}` |
| `API-query-data-source` | DB(데이터소스) 조회/필터 | 데이터소스 ID + 필터 |
| `API-retrieve-a-data-source` | DB 스키마(속성명) 조회 | 데이터소스 ID |

전체 도구 목록은 `manual_mcp_test.py` 실행 시 `tools/list` 출력 참고 (24개).

- ATTRIBUTE 필터(학년/과목/날짜)는 `API-post-search`만으로는 부족할 수 있어, 먼저 `API-retrieve-a-data-source`로
  스키마(속성명)를 조회한 뒤 어떤 속성을 필터 조건으로 쓸지 확인이 필요함.
- Notion Integration을 대상 페이지/데이터베이스에 연결(Connections)해야 검색·조회가 됨. 프로젝트 데이터셋
  외에 팀 회의록 등 다른 페이지는 연결하지 않는 걸 권장 (검색 노이즈 방지).

**로컬에서 검증하려면 (팀원 각자)**

```bash
cd apps/notion-search
cp .env.example .env   # NOTION_TOKEN에 본인이 발급받은(or 공유받은) Integration Secret 채우기
pip install -r requirements.txt
python manual_mcp_test.py "검색어"
```

## 골든셋 · 평가

| 파일 | 용도 |
|---|---|
| [`docs/notion-search/golden-set.md`](../../docs/notion-search/golden-set.md) | 사람이 읽는 표 (가이드 Day2 Step3 산출물) |
| [`docs/notion-search/golden-set.jsonl`](../../docs/notion-search/golden-set.jsonl) | 채점용. 케이스당 한 줄 |
| `fixtures/pages.json` | Notion 응답 스냅샷. eval을 오프라인/무토큰으로 돌리기 위한 것 |

```bash
python eval.py              # 스냅샷으로 채점 (0.1초, 토큰 불필요)
python eval.py --refresh    # 스냅샷 다시 뜨고 채점
python eval.py --case topic-01
```

**지표** — 재현율은 기대 결과를 놓치지 않았는지, 정확도는 군더더기가 없는지,
노이즈는 `must_not`에 적은 페이지가 섞였는지를 본다. 전부 만점이어야 PASS다.

jsonl에는 markdown 표에 없는 케이스가 더 있다 — 결과 0건, 노이즈, 복합 필터, 순위.
케이스를 고칠 때는 **markdown과 jsonl 양쪽을** 수정한다.

**Day6 통과율 (골든셋 21건)**

| 모드 | 통과율 |
|---|---|
| `python eval.py` (검색만, 골든셋 정답 intent 사용) | 21/21 (100%) |
| `python eval.py --classify` (분류기 포함, 실제 LLM 호출) | 21/21 (100%) |

튜닝 과정에서 나온 발견(문항 수 할루시네이션, subject 추출 누락 등)과 프롬프트
전/후 비교는 [`docs/notion-search/evaluation-criteria.md`](../../docs/notion-search/evaluation-criteria.md)에
정리했다.

## 검색 결과 없음/모호할 때 처리 정책 (결정: 방식 B)

일치하는 결과가 없을 때, 유사도 높은 결과를 추천하지 않고 **명확한 안내 메시지만 표시**한다
("검색 결과가 없습니다. 다른 검색어로 시도해보세요.") — `app.py`에 이미 이 방식으로 구현되어 있음.

- 방식 A(유사 결과 N개를 "혹시 이걸 찾으시나요?" 형태로 제시)는 채택하지 않음. 초반 구현 난이도를 낮추기 위해
  방식 B로 먼저 가고, 시간이 남으면 방식 A로 고도화하는 걸 추천.

## 제약사항 및 범위

**범위 밖으로 정한 것**

- 정렬 기준 선택(날짜순/제목순), 필터 UI(학년·과목 드롭다운), 복수 페이지 동시 비교 — Day5
  가이드에서도 "필수 기능이 안정적으로 동작한 뒤에"로 미룬 선택 기능. 아직 손 안 댔다.
- 데이터셋 규모 확장 대응: 지금은 14건 전체를 앱 시작 시 한 번에 읽어 메모리에서 필터링한다
  (README "모듈 간 계약" 참고). 페이지가 크게 늘면 `mcp_client`를 서버 사이드 필터링(검색
  API 활용)으로 되돌려야 하는데, 그 리팩터링은 하지 않았다.

**알려진 동작 (버그는 아니지만 알아둘 것)**

- **애매한 질의는 전체를 보여준다.** "수업 자료 좀 보여줘"처럼 필터·키워드가 둘 다 없는
  질의는 "질의가 모호합니다" 같은 안내 없이 데이터셋 14건을 전부 반환한다. Day6에 정책으로
  검토했고, 별도 경고 없이 이대로 유지하기로 결정함(가짓수가 적어 전체를 보여줘도 유용하다고 판단).
- **날짜/속성 파싱은 완벽하지 않다.** 학년 표기가 데이터셋 형식("고1")과 다르게 들어오면
  (예: "5학년", "3학년") 정규화 없이 그대로 필터링되어 결과가 0건이 된다. 지금 데이터셋은
  전부 "고1"이라 실질적 영향은 없지만, 초·중등 자료가 섞이면 `_GRADES` 정규화 로직을 넓혀야 한다.
- **요약이 가끔 숫자를 확신 없이 서술한다.** Day6 튜닝으로 "문항 수를 지어내는" 문제는 없앴지만
  (본문에 명시 안 된 숫자는 언급하지 않도록 프롬프트 수정), LLM 특성상 정성적 서술에서
  드물게 과장/축소가 있을 수 있다. 정기적으로 골든셋 결과를 사람이 훑어보는 걸 권장.
- **배포 환경에 Node.js 필요.** MCP 서버를 `npx`로 띄우는 방식이라 로컬 개발 머신뿐 아니라
  실제 호스팅 서버에도 Node.js가 설치되어 있어야 한다 (위 "MCP 연동 방식" 참고).
