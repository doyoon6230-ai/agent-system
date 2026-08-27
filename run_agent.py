"""주식 정보 웹사이트 구축 에이전트 실행기

HITL 승인 흐름을 터미널에서 처리합니다.

    python run_agent.py "테슬라 주식 정보 웹사이트 만들어줘"

옵션:
    --auto-approve   승인 프롬프트 없이 전부 자동 승인 (데모/테스트용)
"""

import sys

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from agent import create_coding_agent


def print_rule(title=""):
    print()
    print("=" * 70)
    if title:
        print(title)
        print("=" * 70)


def format_args(args):
    """승인 화면에 보여줄 인자를 읽기 좋게 자릅니다."""

    lines = []

    for key, value in args.items():
        text = str(value)

        if len(text) > 500:
            text = (
                text[:500]
                + f"\n        ... (총 {len(str(value))}자, 이하 생략)"
            )

        lines.append(f"    {key}: {text}")

    return "\n".join(lines)


def ask_decision(action, auto_approve):
    """단일 도구 호출에 대한 사용자 결정을 받습니다."""

    print_rule("🔐 위험 도구 실행 승인 요청")

    print(f"도구: {action['name']}")
    print()
    print("설명:")
    print(f"  {action.get('description', '')}")
    print()
    print("인자:")
    print(format_args(action.get("args", {})))
    print()

    if auto_approve:
        print("[--auto-approve] 자동 승인합니다.")
        return {"type": "approve"}

    while True:
        choice = input(
            "승인하시겠습니까? [a] 승인  [r] 거부 : "
        ).strip().lower()

        if choice in ("a", "approve", "y"):
            return {"type": "approve"}

        if choice in ("r", "reject", "n"):
            reason = input(
                "거부 사유 (엔터 시 생략): "
            ).strip()

            return {
                "type": "reject",
                "message": reason or "사용자가 실행을 거부했습니다.",
            }

        print("a 또는 r 을 입력하세요.")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    auto_approve = "--auto-approve" in sys.argv

    if args:
        user_input = " ".join(args)
    else:
        user_input = input("요청을 입력하세요: ").strip()

    agent = create_coding_agent(
        checkpointer=InMemorySaver()
    )

    config = {
        "configurable": {"thread_id": "run-1"},
        "recursion_limit": 50,
    }

    payload = {"messages": [("user", user_input)]}

    print_rule(f"요청: {user_input}")

    while True:
        result = agent.invoke(payload, config)

        interrupts = result.get("__interrupt__")

        if not interrupts:
            break

        # 인터럽트에 담긴 모든 도구 호출에 대해 결정을 모은다.
        value = interrupts[0].value

        decisions = [
            ask_decision(action, auto_approve)
            for action in value["action_requests"]
        ]

        payload = Command(
            resume={"decisions": decisions}
        )

    print_rule("최종 응답")
    print(result["messages"][-1].content)

    print_rule("도구 호출 요약")

    for message in result["messages"]:
        tool_calls = getattr(
            message,
            "tool_calls",
            None,
        )

        if tool_calls:
            for call in tool_calls:
                print(f"  - {call['name']}")


if __name__ == "__main__":
    main()
