"""보안 및 권한 제어 미들웨어 (Security & HITL)

프롬프트 인젝션으로 에이전트가 시스템 파일을 삭제하거나
악성 코드를 실행하는 것을 막기 위한 2중 방어 계층입니다.

[1] HumanInTheLoopMiddleware
    위험 도구(execute_python_code, delete_file, write_file)가
    실행되기 직전에 그래프를 멈추고 사용자 승인을 받습니다.

[2] SandboxPathMiddleware
    파일을 쓰거나 지우는 도구의 경로 인자가
    website/ 디렉터리 내부인지 검증합니다.
    ../ 상위 디렉터리 접근과 심볼릭 링크 탈출을 차단합니다.

두 계층의 실행 순서:

    모델이 tool_call 생성
      -> [1] HITL 인터럽트 (사용자 승인/수정/거부)
      -> [2] Sandbox 경로 검증
      -> 실제 도구 실행

Sandbox가 뒤에 오는 것이 의도된 설계입니다.
사용자가 HITL에서 edit로 인자를 고쳐도
최종 인자를 Sandbox가 다시 검증하기 때문입니다.
"""

import os

from typing import Any, Awaitable, Callable

from langchain.agents.middleware import (
    AgentMiddleware,
    HumanInTheLoopMiddleware,
    InterruptOnConfig,
    ToolCallRequest,
)
from langchain_core.messages import ToolMessage
from langgraph.types import Command


# ============================================================
# 설정
# ============================================================


# 에이전트가 파일을 생성/수정/삭제할 수 있는 유일한 디렉터리
SANDBOX_ROOT_NAME = "website"


# 경로 검증이 필요한 도구와 검사할 인자 이름
#
# execute_python_code는 경로 인자가 없어 여기서 막을 수 없습니다.
# 해당 도구는 HITL 승인만이 유일한 방어선입니다.
PATH_ARG_BY_TOOL: dict[str, str] = {
    "write_file": "file_path",
    "delete_file": "file_path",
    "create_directory": "dir_path",
}


# 사람의 승인이 필요한 위험 도구
DANGEROUS_TOOLS: tuple[str, ...] = (
    "execute_python_code",
    "delete_file",
    "write_file",
)


# ============================================================
# 경로 검증 유틸
# ============================================================


def get_sandbox_root() -> str:
    """샌드박스 루트의 정규화된 절대 경로를 반환합니다."""

    return os.path.realpath(
        os.path.join(
            os.getcwd(),
            SANDBOX_ROOT_NAME,
        )
    )


def resolve_path(raw_path: str) -> str:
    """입력 경로를 심볼릭 링크까지 해제한 절대 경로로 정규화합니다.

    abspath가 아닌 realpath를 쓰는 이유는
    abspath가 ../는 정리해도 심볼릭 링크는 따라가지 않아
    website/link -> C:/Windows 같은 탈출을 놓치기 때문입니다.
    """

    return os.path.realpath(
        os.path.join(
            os.getcwd(),
            raw_path,
        )
    )


def is_inside_sandbox(raw_path: str) -> bool:
    """정규화된 경로가 샌드박스 루트 내부인지 검사합니다."""

    root = get_sandbox_root()
    target = resolve_path(raw_path)

    # Windows 경로는 대소문자를 구분하지 않으므로 normcase로 맞춘다.
    root_key = os.path.normcase(root)
    target_key = os.path.normcase(target)

    if target_key == root_key:
        return True

    # os.sep을 붙이지 않으면 website_evil/ 이 website/ 로 통과한다.
    return target_key.startswith(
        root_key + os.sep
    )


# ============================================================
# [2] Path Traversal 방지 (Sandbox) 미들웨어
# ============================================================


class SandboxPathMiddleware(AgentMiddleware):
    """파일 조작 도구의 경로를 website/ 내부로 제한하는 미들웨어입니다.

    도구가 실행되기 직전에 인자를 가로채어 경로를 정규화하고,
    샌드박스를 벗어나면 도구를 실행하지 않고 오류 ToolMessage를
    모델에게 돌려줍니다.

    sync와 async 양쪽을 모두 구현합니다.
    LangGraph Studio는 async로 그래프를 실행하기 때문에
    sync만 정의하면 NotImplementedError가 발생합니다.
    """

    def _check(
        self,
        request: ToolCallRequest,
    ) -> ToolMessage | None:
        """차단해야 하면 오류 ToolMessage를, 통과시킬 것이면 None을 반환합니다."""

        tool_name = request.tool_call["name"]

        arg_name = PATH_ARG_BY_TOOL.get(
            tool_name
        )

        # 경로 인자가 없는 도구는 검사 대상이 아니다.
        if arg_name is None:
            return None

        tool_args = request.tool_call.get(
            "args",
            {},
        )

        raw_path = tool_args.get(arg_name)

        tool_call_id = request.tool_call["id"]

        # 경로가 비어 있거나 문자열이 아니면 통과시키지 않는다 (fail-closed).
        if (
            not isinstance(raw_path, str)
            or not raw_path.strip()
        ):
            print(
                f"\n[Sandbox] 🚫 차단: {tool_name} 의 "
                f"{arg_name} 인자가 올바른 경로 문자열이 아닙니다."
            )

            return ToolMessage(
                content=(
                    f"보안 오류: {tool_name} 호출이 차단되었습니다.\n"
                    f"{arg_name} 인자에 올바른 경로 문자열이 필요합니다."
                ),
                tool_call_id=tool_call_id,
                status="error",
            )

        if not is_inside_sandbox(raw_path):
            resolved = resolve_path(raw_path)
            root = get_sandbox_root()

            print(
                f"\n[Sandbox] 🚫 차단: {tool_name} "
                f"-> {raw_path}"
            )
            print(
                f"[Sandbox]    정규화 경로: {resolved}"
            )
            print(
                f"[Sandbox]    허용 루트:   {root}"
            )

            return ToolMessage(
                content=(
                    f"보안 오류: {tool_name} 호출이 차단되었습니다.\n"
                    f"요청 경로: {raw_path}\n"
                    f"정규화된 경로: {resolved}\n"
                    f"허용된 디렉터리: {root}\n\n"
                    f"이 에이전트는 {SANDBOX_ROOT_NAME}/ 디렉터리 "
                    f"내부에만 파일을 만들거나 지울 수 있습니다.\n"
                    f"../ 를 이용한 상위 디렉터리 접근은 허용되지 않습니다.\n"
                    f"{SANDBOX_ROOT_NAME}/ 내부 경로로 다시 시도하세요."
                ),
                tool_call_id=tool_call_id,
                status="error",
            )

        return None

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[
            [ToolCallRequest],
            ToolMessage | Command[Any],
        ],
    ) -> ToolMessage | Command[Any]:
        """동기 도구 실행을 가로채 경로를 검증합니다."""

        blocked = self._check(request)

        if blocked is not None:
            return blocked

        return handler(request)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[
            [ToolCallRequest],
            Awaitable[ToolMessage | Command[Any]],
        ],
    ) -> ToolMessage | Command[Any]:
        """비동기 도구 실행을 가로채 경로를 검증합니다."""

        blocked = self._check(request)

        if blocked is not None:
            return blocked

        return await handler(request)


# ============================================================
# [1] Human-in-the-loop (HITL) 인터셉터
# ============================================================


# LangGraph의 interrupt_before는 노드 단위로만 걸리기 때문에
# tools 노드에 걸면 get_current_price 같은 안전한 조회 도구까지
# 전부 멈춰 세우게 됩니다.
#
# HumanInTheLoopMiddleware는 after_model 훅에서 tool_call을 보고
# 위험 도구일 때만 interrupt를 발생시키므로
# "위험한 도구가 호출되기 직전에만 일시 정지"라는 요구에 맞습니다.
security_hitl_middleware = HumanInTheLoopMiddleware(
    interrupt_on={
        "execute_python_code": InterruptOnConfig(
            allowed_decisions=[
                "approve",
                "edit",
                "reject",
            ],
            description=(
                "⚠️ 임의의 Python 코드를 실행하려 합니다.\n"
                "코드 내용을 직접 확인하세요. "
                "파일 삭제, 네트워크 요청, 외부 명령 실행이 포함되어 있지 않은지 "
                "반드시 검토한 뒤 승인하세요."
            ),
        ),
        "delete_file": InterruptOnConfig(
            allowed_decisions=[
                "approve",
                "edit",
                "reject",
            ],
            description=(
                "⚠️ 파일을 삭제하려 합니다.\n"
                "삭제 대상 경로가 의도한 파일이 맞는지 확인하세요."
            ),
        ),
        "write_file": InterruptOnConfig(
            allowed_decisions=[
                "approve",
                "edit",
                "reject",
            ],
            description=(
                "⚠️ 파일을 생성하거나 덮어쓰려 합니다.\n"
                "저장 경로와 내용을 확인하세요."
            ),
        ),
    },
    description_prefix=(
        "🔐 위험 도구 실행 승인 요청"
    ),
)


sandbox_path_middleware = SandboxPathMiddleware()


# ============================================================
# Middleware 그룹
# ============================================================


# create_agent(middleware=...) 에 그대로 넘기면 됩니다.
#
# 주의: HITL은 interrupt()를 사용하므로 checkpointer가 반드시 필요합니다.
# LangGraph Studio / langgraph dev 는 checkpointer를 자동으로 제공하지만,
# 로컬 스크립트에서 invoke할 때는 직접 넣어야 합니다.
SECURITY_MIDDLEWARE = [
    security_hitl_middleware,
    sandbox_path_middleware,
]
