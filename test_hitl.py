"""HITL 인터럽트 동작 검증

실제 LLM을 호출하지 않고 가짜 모델로 tool_call을 주입하여
위험 도구에서 그래프가 실제로 멈추는지 확인합니다.

    python test_hitl.py
"""

from langchain.agents import create_agent
from langchain_core.language_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from middleware import SECURITY_MIDDLEWARE
from tools import FILE_TOOLS


# 이미 존재하는 파일을 쓰면 "reject 됐는데 파일이 있다"는 오탐이 난다.
# 절대 존재하지 않을 고유 경로를 쓴다.
PROBE_PATH = "website/__hitl_reject_probe__.html"


def print_title(title):
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


class ScriptedModel(GenericFakeChatModel):
    """지정한 AIMessage를 순서대로 돌려주는 가짜 모델."""

    def bind_tools(self, tools, **kwargs):
        # create_agent가 도구를 바인딩할 때 그대로 자기 자신을 반환
        return self


def build_agent(messages):
    return create_agent(
        model=ScriptedModel(messages=iter(messages)),
        tools=FILE_TOOLS,
        system_prompt="테스트용 에이전트",
        middleware=SECURITY_MIDDLEWARE,
        checkpointer=InMemorySaver(),
    )


failures = 0


# ------------------------------------------------------------
# 1. 위험 도구(write_file) -> 인터럽트가 발생해야 한다
# ------------------------------------------------------------

print_title("1. write_file 호출 시 HITL 인터럽트 발생 여부")

danger_call = AIMessage(
    content="",
    tool_calls=[
        {
            "name": "write_file",
            "args": {
                "file_path": PROBE_PATH,
                "content": "<h1>hello</h1>",
            },
            "id": "call_1",
        }
    ],
)

# 거부된 뒤 모델이 한 번 더 호출되므로 후속 응답까지 미리 준비한다.
agent = build_agent(
    [
        danger_call,
        AIMessage(content="사용자가 거부하여 중단했습니다."),
    ]
)

config = {"configurable": {"thread_id": "t1"}}

result = agent.invoke(
    {"messages": [("user", "index.html 만들어줘")]},
    config,
)

interrupts = result.get("__interrupt__")

if interrupts:
    print("✅ 인터럽트 발생 - 그래프가 승인 대기 상태로 멈춤")

    payload = interrupts[0].value

    print()
    print("인터럽트 payload:")
    print(payload)
else:
    failures += 1
    print("❌ 인터럽트가 발생하지 않음 (도구가 그대로 실행됨)")


# ------------------------------------------------------------
# 2. reject 결정 -> 도구가 실행되지 않아야 한다
# ------------------------------------------------------------

print_title("2. 사용자가 reject 했을 때 도구 미실행 여부")

if interrupts:
    resumed = agent.invoke(
        Command(
            resume={
                "decisions": [
                    {
                        "type": "reject",
                        "message": "사용자가 파일 생성을 거부했습니다.",
                    }
                ]
            }
        ),
        config,
    )

    tool_messages = [
        m
        for m in resumed["messages"]
        if m.__class__.__name__ == "ToolMessage"
    ]

    print("ToolMessage 개수:", len(tool_messages))

    for m in tool_messages:
        print("  내용:", str(m.content)[:120])

    import os

    if os.path.exists(PROBE_PATH):
        failures += 1
        print(f"❌ {PROBE_PATH} 가 실제로 생성됨 - reject가 무시되었습니다")
        os.remove(PROBE_PATH)
    else:
        print(f"✅ {PROBE_PATH} 가 생성되지 않음 - reject 정상 동작")
else:
    print("(1번이 실패하여 건너뜀)")


# ------------------------------------------------------------
# 3. 안전한 도구(list_directory) -> 인터럽트 없이 통과해야 한다
# ------------------------------------------------------------

print_title("3. 안전한 도구는 인터럽트 없이 통과하는지")

safe_call = AIMessage(
    content="",
    tool_calls=[
        {
            "name": "list_directory",
            "args": {"dir_path": "."},
            "id": "call_2",
        }
    ],
)

safe_agent = build_agent(
    [safe_call, AIMessage(content="조회 완료")]
)

safe_result = safe_agent.invoke(
    {"messages": [("user", "목록 보여줘")]},
    {"configurable": {"thread_id": "t2"}},
)

if safe_result.get("__interrupt__"):
    failures += 1
    print("❌ 안전한 도구인데 인터럽트가 발생함")
else:
    print("✅ list_directory 는 인터럽트 없이 실행됨")


# ------------------------------------------------------------
# 4. 사용자가 approve 해도 Sandbox가 탈출 경로를 막아야 한다
#    (2중 방어: HITL 통과 -> Sandbox 차단)
# ------------------------------------------------------------

print_title("4. approve 해도 Sandbox가 경로 탈출을 막는지")

import os

ESCAPE_PATH = "website/../_sandbox_escape_probe.txt"

escape_call = AIMessage(
    content="",
    tool_calls=[
        {
            "name": "write_file",
            "args": {
                "file_path": ESCAPE_PATH,
                "content": "pwned",
            },
            "id": "call_3",
        }
    ],
)

escape_agent = build_agent(
    [
        escape_call,
        AIMessage(content="차단되었습니다."),
    ]
)

escape_config = {"configurable": {"thread_id": "t3"}}

escape_result = escape_agent.invoke(
    {"messages": [("user", "저장해줘")]},
    escape_config,
)

if not escape_result.get("__interrupt__"):
    failures += 1
    print("❌ HITL 인터럽트가 발생하지 않음")
else:
    print("1) HITL 인터럽트 발생 -> 사용자가 approve 한다고 가정")

    # 최악의 시나리오: 사용자가 내용을 확인하지 않고 승인
    escape_result = escape_agent.invoke(
        Command(
            resume={"decisions": [{"type": "approve"}]}
        ),
        escape_config,
    )

    tool_messages = [
        m
        for m in escape_result["messages"]
        if m.__class__.__name__ == "ToolMessage"
    ]

    blocked = any(
        "보안 오류" in str(m.content)
        for m in tool_messages
    )

    escaped_file = os.path.realpath(
        os.path.join(os.getcwd(), ESCAPE_PATH)
    )

    created = os.path.exists(escaped_file)

    print(f"2) 탈출 대상 경로: {escaped_file}")

    if created:
        failures += 1
        print("❌ 파일이 생성됨 - Sandbox 탈출 성공 (심각)")
        os.remove(escaped_file)
    elif blocked:
        print("✅ Sandbox가 차단 - 파일 미생성, 모델에 보안 오류 반환")
        for m in tool_messages:
            print("   반환:", str(m.content).splitlines()[0])
    else:
        failures += 1
        print("❌ 파일도 없고 차단 메시지도 없음 - 예상 밖 동작")


print()
print("=" * 70)

if failures:
    print(f"❌ 실패 {failures}건")
else:
    print("✅ 모든 테스트 통과")

print("=" * 70)
