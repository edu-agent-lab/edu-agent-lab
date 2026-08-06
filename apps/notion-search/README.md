# 프로젝트 1: Notion 페이지 검색 및 요약

사용자가 자연어로 질문하면 Notion 워크스페이스에서 관련 페이지를 검색하고,
AI가 내용을 요약해서 보여주는 Streamlit 웹 서비스입니다.

## 전체 동작 흐름

```text
사용자 질문
      ↓
query_classifier.py
(질문 분석)
      ↓
mcp_client.py
(Notion에서 페이지 검색)
      ↓
summarizer.py
(GPT로 페이지 요약)
      ↓
Streamlit 화면 출력
```

예시)

```
사용자
"3학년 식물 자료 찾아줘"

↓

① 질문 분석 → 주제 검색
② Notion 검색 → 관련 페이지 3개 조회
③ GPT 요약
④ 화면 출력
```

## 담당

| 파일 | 담당 | 역할 |
|---|---|---|
| `query_classifier.py` | 나 | 질의 유형 판단(주제/제목/속성) + QueryIntent 구성 |
| `prompt.py` | 나 | 필터 추출/요약용 프롬프트 템플릿 |
| `summarizer.py` | 나 | 검색 결과 페이지별 요약 생성 |
| `mcp_client.py` | 팀원 | Notion MCP 서버 연결, 검색/본문 조회 tool call |
| `openai_client.py` | 팀원 | LLM API 클라이언트 |
| `app.py` | 공통 | Streamlit UI, 파이프라인 연결 |

## 모듈 간 계약

`query_classifier.QueryIntent` (검색 조건) -> `mcp_client.search_pages()` -> `mcp_client.NotionPage` 목록
(본문 포함) -> `summarizer.summarize_results()` -> 화면에 결과+요약 표시.

```python
QueryIntent(type="topic", keyword="식물")
NotionPage(title="식물의 한살이", content="...")
```

각자 이 두 데이터클래스의 필드만 맞춰두면 서로의 구현이 끝나기 전에도 독립적으로 개발/테스트할 수 있다.
정확한 필드는 `query_classifier.py`, `mcp_client.py` 참고.

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

## 골든셋

질의 유형별(주제/제목/속성) 골든셋은 `docs/notion-search/`에 둔다.
