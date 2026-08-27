# 📈 주식 정보 웹사이트 구축 에이전트 (Stock Info Agent)

사용자가 기업명 또는 종목 코드를 입력하면 **실시간 주가 · 과거 추이 · 재무 지표 · 관련 뉴스**를 수집하고, 그 데이터로 **주식 정보 웹사이트를 직접 만들어 주는** LLM 기반 에이전트입니다.

---

## 1. 프로젝트 방향성

### 목표

금융 데이터 수집 도구(Tool)를 만들고, 이를 **파일 제어 도구와 결합**하여 자율적으로 작동하는 AI 에이전트를 구축합니다.

이 프로젝트의 핵심은 "LLM에게 질문하고 답을 받는 것"이 아니라, **LLM이 도구를 스스로 골라 써서 실제 산출물(웹사이트 파일)을 만들어 내게 하는 것**입니다.

### 설계 원칙 3가지

**① 데이터를 지어내지 않는다**

주가, PER, PBR, ROE, 매출액, 뉴스는 **반드시 Tool이 반환한 실제 값만** 사용합니다. Tool이 값을 주지 못하면 숫자를 추측하지 않고 `정보 없음`으로 표시합니다. 금융 정보를 다루는 이상 이 원칙이 가장 중요합니다.

**② 자율성에는 반드시 통제가 따른다**

에이전트에게 파일 쓰기와 코드 실행 권한을 주는 순간, 프롬프트 인젝션으로 시스템이 손상될 수 있는 경로가 열립니다. 그래서 **보안 미들웨어를 기능과 동등한 우선순위**로 취급합니다. (→ [3. 보안 구조](#3-보안-구조-security--hitl))

**③ 채팅으로 코드를 보여주고 끝내지 않는다**

에이전트는 HTML 예제를 대화창에 출력하는 것으로 작업을 끝내면 안 됩니다. 파일 Tool을 사용해 **실제로 디스크에 웹사이트를 생성**해야 완료입니다.

### 동작 흐름

```
사용자: "엔비디아 주식 정보 웹사이트 만들어줘"
   │
   ├─ 1. 기업명 → 종목코드 변환 (NVIDIA → NVDA)
   │       확신이 없으면 추측하지 않고 사용자에게 확인
   │
   ├─ 2. get_current_price          현재가 / 등락률 / 거래량
   ├─ 3. get_historical_ohlcv       최근 30일 OHLCV
   ├─ 4. get_financial_metrics      PER / PBR / ROE / 매출 / 영업이익
   ├─ 5. get_company_disclosures    최근 뉴스 헤드라인
   │
   └─ 6. website/ 디렉터리에 웹사이트 생성
           index.html · style.css · script.js
           (Chart.js CDN으로 주가 추이 차트 렌더링)
```

---

## 2. 사전 준비

> ⚠️ 아래 명령어는 **일반 터미널**(`PS C:\...>`)에서 실행하세요.
> 파이썬 셸(`>>>`) 안에서 실행하면 `SyntaxError`가 납니다.

```bash
# 금융 데이터 수집
pip install yfinance pandas

# LLM 에이전트 및 도구 구성
pip install langchain langchain-openai langgraph python-dotenv
```

설치 중 노란색 PATH 관련 Warning이나 `[notice]` 문구가 떠도 설치 실패가 아니므로 무시해도 됩니다.

### 검증된 버전

| 패키지 | 버전 |
|---|---|
| langchain | 1.3.15 |
| langgraph | 1.2.11 |
| langchain-openai | 1.5.1 |
| python-dotenv | 1.2.3 |
| yfinance | 1.7.0 |
| pandas | 3.0.5 |

> `langchain` 1.x 기준으로 작성되었습니다. 0.x 계열에서는 `create_agent`와 미들웨어 API가 존재하지 않습니다.

### 환경변수

`agent-system/.env` 에 OpenAI API 키를 넣습니다.

```
OPENAI_API_KEY=sk-...
```

---

## 3. 보안 구조 (Security & HITL)

에이전트에게 `write_file`, `delete_file`, `execute_python_code` 권한이 있다는 것은, **조회한 뉴스 본문에 악의적인 지시문이 섞여 들어오면 시스템 파일이 삭제될 수 있다**는 뜻입니다. 이를 막기 위해 2중 방어 계층을 둡니다.

```
모델이 tool_call 생성
   │
   ├─ [1] HITL 인터럽트      위험 도구면 멈추고 사용자 승인을 받는다
   │                          (approve / edit / reject)
   │
   ├─ [2] Sandbox 경로 검증   경로가 website/ 내부인지 확인한다
   │
   └─ 실제 도구 실행
```

### [1] Human-in-the-Loop 인터셉터

`execute_python_code`, `delete_file`, `write_file` 호출 직전에 그래프를 **일시 정지**하고 사용자 승인을 받습니다.

LangGraph의 `interrupt_before` 대신 **`HumanInTheLoopMiddleware`** 를 사용합니다. 이유는 다음과 같습니다.

`interrupt_before=["tools"]`는 **노드 단위**로 걸리기 때문에 어떤 도구가 호출되는지 구분하지 못합니다. 이걸 걸어두면 `get_current_price` 같은 안전한 조회 도구까지 전부 멈춰서, 웹사이트 하나 만드는 데 승인 프롬프트가 8~10번 뜹니다. `HumanInTheLoopMiddleware`는 `after_model` 훅에서 tool_call의 **이름을 보고** 위험 도구일 때만 인터럽트하므로, "위험한 도구가 호출되기 직전에만 정지"라는 요구에 정확히 맞습니다.

### [2] Path Traversal 방지 (Sandbox)

파일을 생성·수정·삭제하는 도구의 경로 인자를 가로채, `website/` 디렉터리 내부인지 검증합니다.

| 도구 | 검사하는 인자 |
|---|---|
| `write_file` | `file_path` |
| `delete_file` | `file_path` |
| `create_directory` | `dir_path` |

> `create_directory`는 원래 스펙에 없었지만 포함시켰습니다. 빼두면 에이전트가 아무 위치에나 디렉터리를 만들 수 있어 명백한 구멍이 되기 때문입니다.

경로 정규화에 `os.path.abspath`가 아닌 **`os.path.realpath`** 를 씁니다. `abspath`는 `../`는 정리하지만 **심볼릭 링크는 따라가지 않아서**, 공격자가 `website/link → C:\Windows` 를 만들어 두면 그대로 통과시킵니다.

추가로 두 가지를 처리합니다.

- Windows 경로는 대소문자를 구분하지 않으므로 `os.path.normcase`로 정규화 후 비교
- 접두어 비교에 `os.sep`을 붙여 `website_evil/` 이 `website/` 로 오통과하는 것을 방지

### 두 계층의 순서가 중요한 이유

Sandbox 검증이 HITL **뒤에** 옵니다. 의도된 설계입니다.

사용자가 HITL의 `edit`로 인자를 직접 수정할 수 있는데, Sandbox가 앞에 있으면 **수정된 최종 인자는 검증되지 않은 채 실행**됩니다. Sandbox를 뒤에 두면 사람이 무엇을 하든 최종 인자가 반드시 검증됩니다.

이 설계 덕분에 **사용자가 내용을 확인하지 않고 승인해 버린 최악의 경우에도 경로 탈출이 차단**됩니다. 프롬프트 인젝션의 목표가 결국 "사람을 속이는 것"이라는 점을 생각하면, 이 계층이 실질적인 마지막 방어선입니다.

---

## 4. 구성된 도구 목록

### 📈 주식 데이터 Tool (`STOCK_TOOLS`)

| 함수 | 설명 |
|---|---|
| `get_current_price` | 실시간 주가, 전일 종가, 등락률, 거래량 |
| `get_historical_ohlcv` | 기간별 시가·고가·저가·종가·거래량 (day/week/month) |
| `get_financial_metrics` | PER, PBR, ROE, EPS, 매출액, 영업이익, 시가총액 |
| `get_company_disclosures` | 최근 관련 뉴스 헤드라인 (날짜·제목·언론사·링크) |

### 📁 파일 시스템 Tool (`FILE_TOOLS`)

| 함수 | 설명 | 보안 |
|---|---|---|
| `read_file` | 파일 내용 조회 | — |
| `write_file` | 파일 생성/덮어쓰기 | 🔐 승인 + 📁 경로 검증 |
| `delete_file` | 파일 삭제 | 🔐 승인 + 📁 경로 검증 |
| `create_directory` | 디렉터리 생성 | 📁 경로 검증 |
| `list_directory` | 파일/폴더 목록 조회 | — |
| `execute_python_code` | Python 코드 실행 | 🔐 승인 |

두 그룹은 `tools.py`에서 `ALL_TOOLS = FILE_TOOLS + STOCK_TOOLS` 로 합쳐져 에이전트에 주입됩니다.

---

## 5. 파일 구성

```
src/domain-agent/
├── agent.py              에이전트 정의 (시스템 프롬프트 + 도구 + 미들웨어)
├── tools.py              도구 10개 (주식 4 + 파일 6)
├── middleware.py         보안 미들웨어 (HITL + Sandbox)
├── run_agent.py          터미널 실행기 (승인 흐름 처리)
├── langgraph.json        LangGraph Studio 설정
├── test_tools.py         도구 단독 테스트
├── test_middleware.py    경로 검증 테스트
├── test_hitl.py          인터럽트 / 2중 방어 테스트
└── website/              에이전트가 생성하는 웹사이트 (샌드박스 루트)
```

---

## 6. 실행 방법

### 단계 1 — 도구 단독 테스트

```bash
python test_tools.py
```

애플(AAPL)의 현재가, 과거 OHLCV 배열, 재무 지표 딕셔너리, 뉴스 목록이 에러 없이 출력되면 정상입니다.

### 단계 2 — 보안 미들웨어 테스트

LLM을 호출하지 않으므로 **API 비용이 들지 않습니다.**

```bash
python test_middleware.py   # 경로 검증 21개 케이스
python test_hitl.py         # 인터럽트 / 거부 / 2중 방어 4개 케이스
```

`test_hitl.py`는 가짜 모델로 tool_call을 주입해 결정론적으로 검증하므로, 실행할 때마다 같은 결과가 나옵니다.

### 단계 3 — 에이전트 실행

```bash
python run_agent.py "테슬라 주식 정보 웹사이트 만들어줘"
```

위험 도구 차례가 되면 아래처럼 멈추고 승인을 묻습니다.

```
======================================================================
🔐 위험 도구 실행 승인 요청
======================================================================
도구: write_file

설명:
  ⚠️ 파일을 생성하거나 덮어쓰려 합니다.
저장 경로와 내용을 확인하세요.

인자:
    file_path: website/index.html
    content: <!DOCTYPE html> ...

승인하시겠습니까? [a] 승인  [r] 거부 :
```

승인 없이 전 과정을 자동으로 돌리려면 (데모·테스트용):

```bash
python run_agent.py --auto-approve "테슬라 주식 정보 웹사이트 만들어줘"
```

완료되면 `website/index.html`을 브라우저로 열어 확인합니다.

### LangGraph Studio로 실행

```bash
langgraph dev
```

`langgraph.json`이 `agent.py:agent`를 그래프로 노출합니다.

---

## 7. 트러블슈팅

### `ModuleNotFoundError: No module named 'langchain'`

해당 패키지가 설치되지 않았습니다. `pip install langchain`을 다시 실행하세요.

### `SyntaxError: invalid syntax` (pip install 입력 시)

파이썬 셸(`>>>`)에 들어가 있는 상태입니다. `exit()`로 빠져나온 뒤 다시 설치 명령어를 입력하세요.

### 등락률이 `정보 없음`으로 표시됨

> ⚠️ 예전 README에는 "장 마감 후 발생하는 일시적 현상이니 안심해도 된다"고 적혀 있었으나 **사실이 아닙니다.**

Yahoo Finance chart API의 `meta`에는 `previousClose`라는 키가 **애초에 존재하지 않습니다** (`chartPreviousClose`만 있음). 따라서 장중이든 장 마감 후든 **항상** `None`이 나오는 코드 버그였습니다.

`chartPreviousClose`로 바꾸는 것도 정답이 아닙니다. `range=5d`에서 그 값은 전일 종가가 아니라 **5일 창 이전의 종가**입니다. 현재는 **종가 배열의 끝에서 두 번째 값**을 전일 종가로 쓰도록 수정되어 있습니다.

### `NotImplementedError: Asynchronous implementation of awrap_tool_call is not available`

미들웨어에 동기 버전만 구현한 경우입니다. LangGraph Studio는 그래프를 **비동기**로 실행하므로 `wrap_tool_call`과 `awrap_tool_call`을 **둘 다** 구현해야 합니다. `middleware.py`의 `SandboxPathMiddleware`가 그 예시입니다.

### 승인 프롬프트가 뜨지 않고 그냥 실행됨

HITL은 `interrupt()`를 사용하므로 **checkpointer가 반드시 필요합니다.**

LangGraph Studio / `langgraph dev`는 플랫폼이 자동으로 주입하지만, 로컬 스크립트에서 `invoke`할 때는 직접 넘겨야 합니다.

```python
from langgraph.checkpoint.memory import InMemorySaver

agent = create_coding_agent(checkpointer=InMemorySaver())
```

`agent.py`의 모듈 레벨 `agent` 객체에는 **일부러 checkpointer를 넣지 않았습니다.** Studio 배포 시 플랫폼 checkpointer와 충돌할 수 있기 때문입니다.

---

## 8. 알려진 한계

### `execute_python_code`는 경로 검증으로 막을 수 없습니다

이 도구에는 경로 인자가 없어 Sandbox 미들웨어가 개입할 지점이 없습니다. `os.remove("C:/...")` 같은 코드를 그대로 실행할 수 있고, **HITL 승인이 유일한 방어선**입니다.

즉 **사용자가 코드를 읽지 않고 승인하면 뚫립니다.** 근본적인 해결은 서브프로세스 격리(`CodexSandboxExecutionPolicy` / `DockerExecutionPolicy`)이며, 아직 적용되어 있지 않습니다.

### 한국 종목은 일부 재무지표가 비어 있습니다

`005930.KS`(삼성전자) 기준으로 가격·등락률·매출액·영업이익·ROE는 정상 조회되지만, **PER · PBR · EPS는 `None`** 으로 옵니다. yfinance가 KRX 종목에 대해 해당 필드를 채워주지 않기 때문이며 코드 문제가 아닙니다.

설계 원칙 ①에 따라 `정보 없음`으로 표시되므로 동작은 의도대로지만, **데모에서 삼성전자를 쓰면 재무지표 카드 3개가 비어 보인다**는 점을 미리 알고 있어야 합니다.

### 배당수익률 단위 주의

yfinance 1.x는 `dividendYield`를 **이미 퍼센트 단위**로 반환합니다 (`0.35` == `0.35%`). 여기에 100을 곱하면 애플 배당수익률이 `35%`로 표시되는 버그가 생깁니다. 현재 코드는 곱하지 않습니다.

---

## 9. 투자 관련 고지

이 프로젝트는 **정보 제공 및 학습 목적**입니다. 에이전트는 투자 판단을 대신하지 않으며, 생성된 웹사이트의 내용은 투자 권유가 아닙니다. 데이터는 Yahoo Finance에서 수집되며 지연·누락·오류가 있을 수 있습니다.
