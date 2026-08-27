"""보안 미들웨어 단독 테스트

Path Traversal 차단이 실제로 동작하는지 검증합니다.
    python test_middleware.py
"""

from langchain_core.messages import ToolMessage

from middleware import (
    DANGEROUS_TOOLS,
    SANDBOX_ROOT_NAME,
    SECURITY_MIDDLEWARE,
    get_sandbox_root,
    is_inside_sandbox,
    resolve_path,
    sandbox_path_middleware,
)


def print_title(title):
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


class FakeRequest:
    """ToolCallRequest 대신 쓰는 최소 스텁."""

    def __init__(self, name, args):
        self.tool_call = {
            "name": name,
            "args": args,
            "id": "call_test_1",
        }


def handler(request):
    return ToolMessage(
        content="ALLOWED",
        tool_call_id=request.tool_call["id"],
    )


print_title("0. 샌드박스 루트")

print("허용 루트:", get_sandbox_root())


print_title("1. 경로 판정 (is_inside_sandbox)")

cases = [
    # (경로, 통과해야 하는가)
    (f"{SANDBOX_ROOT_NAME}/index.html", True),
    (f"{SANDBOX_ROOT_NAME}/css/style.css", True),
    (f"{SANDBOX_ROOT_NAME}", True),
    (f"./{SANDBOX_ROOT_NAME}/script.js", True),
    (f"{SANDBOX_ROOT_NAME}/../{SANDBOX_ROOT_NAME}/ok.html", True),
    # 차단되어야 하는 경로
    ("../secret.txt", False),
    ("../../.env", False),
    (f"{SANDBOX_ROOT_NAME}/../../.env", False),
    ("C:/Windows/System32/drivers/etc/hosts", False),
    ("/etc/passwd", False),
    ("tools.py", False),
    (f"{SANDBOX_ROOT_NAME}_evil/x.html", False),
    (f"{SANDBOX_ROOT_NAME}/../tools.py", False),
]

failures = 0

for path, should_pass in cases:
    actual = is_inside_sandbox(path)
    ok = actual == should_pass

    if not ok:
        failures += 1

    mark = "OK  " if ok else "FAIL"
    verdict = "허용" if actual else "차단"
    expected = "허용" if should_pass else "차단"

    print(
        f"[{mark}] {path:<45} -> {verdict} (기대: {expected})"
    )

    if not ok:
        print(f"        정규화: {resolve_path(path)}")


print_title("2. 미들웨어 차단 동작 (wrap_tool_call)")

tool_cases = [
    ("write_file", {"file_path": f"{SANDBOX_ROOT_NAME}/index.html", "content": "hi"}, True),
    ("write_file", {"file_path": "../../.env", "content": "pwned"}, False),
    ("delete_file", {"file_path": "../../../Windows/notepad.exe"}, False),
    ("create_directory", {"dir_path": f"{SANDBOX_ROOT_NAME}/assets"}, True),
    ("create_directory", {"dir_path": "C:/temp/evil"}, False),
    # 경로 인자가 없는 도구는 이 미들웨어의 검사 대상이 아님
    ("get_current_price", {"symbol": "AAPL"}, True),
    ("execute_python_code", {"code": "import os; os.remove('x')"}, True),
    # fail-closed 확인
    ("write_file", {"file_path": "", "content": "x"}, False),
]

for name, args, should_pass in tool_cases:
    result = sandbox_path_middleware.wrap_tool_call(
        FakeRequest(name, args),
        handler,
    )

    allowed = result.content == "ALLOWED"
    ok = allowed == should_pass

    if not ok:
        failures += 1

    mark = "OK  " if ok else "FAIL"
    verdict = "실행됨" if allowed else "차단됨"

    print(f"[{mark}] {name:<20} {str(args)[:45]:<47} -> {verdict}")


print_title("3. 미들웨어 등록 상태")

print("SECURITY_MIDDLEWARE:", len(SECURITY_MIDDLEWARE))

for mw in SECURITY_MIDDLEWARE:
    print("  -", type(mw).__name__)

print("HITL 대상 도구:", list(DANGEROUS_TOOLS))


print()
print("=" * 70)

if failures:
    print(f"❌ 실패 {failures}건")
else:
    print("✅ 모든 테스트 통과")

print("=" * 70)
