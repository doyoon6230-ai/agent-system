import os
import random
import shutil
from pathlib import Path
from langchain.agents import create_agent
from typing import Any, Awaitable, Callable
from datetime import datetime
from langchain.agents.middleware import (
    AgentMiddleware,
    HumanInTheLoopMiddleware,
    InterruptOnConfig,
    ToolCallRequest,
)
from typing import Any
from langchain_core.messages import SystemMessage
from langchain_core.messages import ToolMessage
from langchain.agents.middleware import before_agent, wrap_tool_call, AgentState
from langgraph.runtime import Runtime
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import StructuredTool, ToolException
from langchain_openai import ChatOpenAI
from langgraph.types import Command

'''
============================================================================================================================
# 1. 보안 및 권한 제어 미들웨어 (Security & HITL)
============================================================================================================================
'''

@before_agent
def workspace_index_middleware(state: AgentState, runtime: Runtime) -> dict[str, Any] | None:
    """Workspace Index Middleware

    에이전트 시작 시 workspace의 문서 파일들을 스캔하여
    파일 목록을 state에 저장합니다.

    이를 통해 LLM은 매번 list_directory를 호출하지 않고도
    workspace의 파일 구조를 즉시 파악할 수 있습니다.
    """
    print("\n[Workspace Index] 파일 인덱싱 시작...")

    cwd = os.getcwd()
    file_list = []

    # 지원하는 확장자 (MD, CSV, TXT)
    extensions = {'.md', '.csv', '.txt'}

    # workspace 스캔 (최대 3단계 깊이)
    for root, dirs, files in os.walk(cwd):
        # 제외할 디렉터리
        dirs[:] = [d for d in dirs if not d.startswith('.')
                   and d not in ['__pycache__', 'node_modules', 'venv', '.cache', 'backup']]

        level = root.replace(cwd, '').count(os.sep)
        if level > 3:
            continue

        for file in files:
            if file.startswith('.'):
                continue

            file_ext = os.path.splitext(file)[1].lower()

            if file_ext in extensions:
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, cwd)
                file_list.append(f"  • {rel_path}")

    # 인덱스 요약
    index_info = [
        f"📁 Workspace: {cwd}",
        f"📊 총 {len(file_list)}개 파일 발견\n",
        "📋 파일 목록:"
    ]
    index_info.extend(file_list)

    print(f"[Workspace Index] ✅ {len(file_list)}개 파일 인덱싱 완료")

    # 시스템 메시지로 인덱스 정보 추가
    system_message = SystemMessage(
        content=f"[Workspace Index]\n{chr(10).join(index_info)}\n\n사용자가 요청하는 문서를 이 목록에서 찾아 처리하세요."
    )

    return {"messages": [system_message]}


@wrap_tool_call
async def auto_backup_middleware(request, handler):
    """Auto Backup Middleware

    edit_file 도구로 파일을 수정하기 전에 자동으로 백업을 생성합니다.
    백업 파일은 backup/ 디렉터리에 "파일명_YYYYMMDD_HHMMSS.확장자" 형식으로 저장됩니다.

    예시:
    - meeting.md 수정 시 → backup/meeting_20260730_143022.md 생성
    """
    tool_name = request.tool_call["name"]
    tool_args = request.tool_call.get("args", {})

    # edit_file 도구만 백업
    if tool_name != "edit_file":
        return await handler(request)

    file_path = tool_args.get("file_path")
    if not file_path or not os.path.exists(file_path):
        # 파일이 없으면 백업 없이 진행
        return await handler(request)

    try:
        # backup 디렉터리 생성
        backup_dir = Path("backup")
        backup_dir.mkdir(exist_ok=True)

        # 파일명과 확장자 분리
        file_name = os.path.basename(file_path)
        name_without_ext, ext = os.path.splitext(file_name)

        # 현재 시각으로 백업 파일명 생성
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_filename = f"{name_without_ext}_{timestamp}{ext}"
        backup_path = backup_dir / backup_filename

        # 파일 복사
        shutil.copy2(file_path, backup_path)
        print(f"\n[Auto Backup] 💾 백업 생성: {backup_path}")

    except Exception as e:
        print(f"[Auto Backup] ⚠️ 백업 실패: {e}")
        # 백업 실패해도 원본 작업은 진행

    # 원본 edit_file 도구 실행
    return await handler(request)
    # ============================================================
# 4. 에러 처리 및 자가 복구 미들웨어 (Resilience)
# ============================================================


def handle_financial_tool_error(error: ToolException) -> str:
    error_message = str(error)
    if "Rate Limit" in error_message:
        return "⚠️ [시스템 알림]: 금융 API 호출 제한(Rate Limit)을 초과했습니다. 잠시 후 다시 시도해주세요."
    elif "Connection" in error_message:
        return "⚠️ [시스템 알림]: 외부 금융 데이터 서버와 연결할 수 없습니다. 임시 더미 가격: 50,000원 (참고용)"
    else:
        return f"⚠️ [시스템 알림]: 도구 실행 중 오류가 발생했습니다. (사유: {error_message})"


def _get_current_price_impl(ticker: str) -> str:
    """주어진 티커(ticker)의 현재 금융 자산 가격을 조회합니다."""
    chance = random.random()

    if chance < 0.4:
        raise ToolException("Rate Limit exceeded: Too many requests.")
    elif chance < 0.7:
        raise ToolException("Connection timeout while fetching data.")

    mock_prices = {"AAPL": "180.95 USD", "TSLA": "240.50 USD", "BTC": "65,000 USD"}
    price = mock_prices.get(ticker.upper(), "100.00 USD")
    return f"{ticker.upper()}의 현재가: {price}"


get_current_price = StructuredTool.from_function(
    func=_get_current_price_impl,
    name="get_current_price",
    description="주어진 티커(ticker)의 현재 금융 자산 가격을 조회합니다.",
    handle_tool_error=handle_financial_tool_error,
)


# ============================================================
# 에이전트 및 프롬프트 설정 (LangGraph dev 구동용)
# ============================================================

llm = ChatOpenAI(model="gpt-4o", temperature=0)

prompt = ChatPromptTemplate.from_messages([
    ("system", "당신은 전문 금융 어시스턴트입니다. 도구 사용 중 에러 메시지가 반환되면, 시스템의 지침에 따라 사용자에게 유연하게 대응하세요."),
    MessagesPlaceholder("chat_history", optional=True),
    ("human", "{input}"),
    MessagesPlaceholder("agent_scratchpad"),
])

tools = [get_current_price]

# 미들웨어를 지원하는 최신 create_agent 사용
graph = create_agent(
    model=llm,
    tools=tools,
    system_prompt="당신은 전문 금융 어시스턴트입니다. 도구 사용 중 에러 메시지가 반환되면, 시스템의 지침에 따라 사용자에게 유연하게 대응하세요.",
    middleware=SECURITY_MIDDLEWARE,
)
