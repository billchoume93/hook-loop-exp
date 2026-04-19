#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import fcntl

ALLOWED_EDIT_TARGET = "algorithms/pi_algo_improve-by-agent.py"
COUNT_FILE = "count.md"
LOCK_FILE = ".codex/wave.lock"
COUNT_RE = re.compile(r"wave_count\s*=\s*(\d+)")
FIXED_VERIFY_COMMAND = (
    "python3 algorithms/pi_algo_improve-by-agent.py 65536 | "
    "python3 tools/verify_pi_bin.py"
)
FIXED_BENCHMARK_COMMAND = "python3 run_verify_timed.py 65536 --repeats 1"
IGNORED_PATH_PREFIXES = (
    "__pycache__/",
    "algorithms/__pycache__/",
    "tools/__pycache__/",
)
IGNORED_PATHS = {
    ".codex/wave.lock",
}


def emit(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False))


def resolve_project_root(cwd: Path) -> Path:
    for directory in (cwd, *cwd.parents):
        if (directory / ".codex" / "hooks.json").exists():
            return directory
        if (directory / COUNT_FILE).exists():
            return directory
    return cwd


def git_changed_paths(project_root: Path) -> list[str]:
    completed = subprocess.run(
        ["git", "status", "--short"],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    )
    changed_paths: list[str] = []
    for line in completed.stdout.splitlines():
        if not line:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path in IGNORED_PATHS:
            continue
        if any(path.startswith(prefix) for prefix in IGNORED_PATH_PREFIXES):
            continue
        changed_paths.append(path)
    return changed_paths


def run_shell_command(project_root: Path, command: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    return subprocess.run(
        ["sh", "-lc", command],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def require_only_allowed_target(project_root: Path) -> tuple[bool, str]:
    changed_paths = git_changed_paths(project_root)
    disallowed = [path for path in changed_paths if path != ALLOWED_EDIT_TARGET]
    if disallowed:
        return (
            False,
            "disallowed modified files: "
            + ", ".join(disallowed)
            + f"; only {ALLOWED_EDIT_TARGET} may change during a wave",
        )
    if ALLOWED_EDIT_TARGET not in changed_paths:
        return (False, f"expected a change in {ALLOWED_EDIT_TARGET} before consuming a wave")
    return (True, "")


def require_fixed_verify(project_root: Path) -> tuple[bool, str]:
    completed = run_shell_command(project_root, FIXED_VERIFY_COMMAND)
    if completed.returncode != 0:
        details = completed.stderr.strip() or completed.stdout.strip() or "verification failed"
        return (False, f"fixed verify command failed: {FIXED_VERIFY_COMMAND}; {details}")
    return (True, "")


def require_fixed_benchmark(project_root: Path) -> tuple[bool, str]:
    completed = run_shell_command(project_root, FIXED_BENCHMARK_COMMAND)
    if completed.returncode != 0:
        details = completed.stderr.strip() or completed.stdout.strip() or "benchmark failed"
        return (False, f"fixed benchmark command failed: {FIXED_BENCHMARK_COMMAND}; {details}")
    output = completed.stdout
    if "digits=65536" not in output:
        return (False, f"benchmark output missing digits=65536: {FIXED_BENCHMARK_COMMAND}")
    if output.count("status=OK") < 2:
        return (
            False,
            "benchmark output did not show both implementations passing verification",
        )
    return (True, "")


def main() -> int:
    payload = json.load(sys.stdin)
    cwd = Path(payload["cwd"]).resolve()
    project_root = resolve_project_root(cwd)

    count_path = project_root / COUNT_FILE
    lock_path = project_root / LOCK_FILE
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    with lock_path.open("w", encoding="utf-8") as lockf:
        fcntl.flock(lockf, fcntl.LOCK_EX)

        if not count_path.exists():
            emit(
                {
                    "continue": False,
                    "stopReason": f"{COUNT_FILE} not found",
                    "systemMessage": f"{COUNT_FILE} not found, stop loop.",
                }
            )
            return 0

        text = count_path.read_text(encoding="utf-8")
        match = COUNT_RE.search(text)
        if not match:
            emit(
                {
                    "continue": False,
                    "stopReason": f"wave_count not found in {COUNT_FILE}",
                    "systemMessage": f"Cannot parse wave_count in {COUNT_FILE}, stop loop.",
                }
            )
            return 0

        remaining = int(match.group(1))
        if remaining <= 0:
            emit(
                {
                    "continue": False,
                    "stopReason": "Wave budget exhausted",
                    "systemMessage": "wave_count is already 0, stop loop.",
                }
            )
            return 0

        allowed_ok, allowed_reason = require_only_allowed_target(project_root)
        if not allowed_ok:
            emit(
                {
                    "continue": False,
                    "stopReason": "Wave rejected by file-scope check",
                    "systemMessage": allowed_reason,
                }
            )
            return 0

        verify_ok, verify_reason = require_fixed_verify(project_root)
        if not verify_ok:
            emit(
                {
                    "continue": False,
                    "stopReason": "Wave rejected by fixed verification check",
                    "systemMessage": verify_reason,
                }
            )
            return 0

        benchmark_ok, benchmark_reason = require_fixed_benchmark(project_root)
        if not benchmark_ok:
            emit(
                {
                    "continue": False,
                    "stopReason": "Wave rejected by fixed benchmark check",
                    "systemMessage": benchmark_reason,
                }
            )
            return 0

        remaining -= 1
        new_text = COUNT_RE.sub(f"wave_count={remaining}", text, count=1)
        count_path.write_text(new_text, encoding="utf-8")

        if remaining == 0:
            emit(
                {
                    "continue": False,
                    "stopReason": "Completed final wave",
                    "systemMessage": "All waves completed.",
                }
            )
            return 0

        next_prompt = (
            f"Continue to the next wave. Remaining waves in count.md: {remaining}. "
            "Execute exactly one wave only in this turn. "
            "At the end of the wave, write a short summary and stop naturally. "
            "Do not start another wave by yourself; the Stop hook will decide."
        )
        emit(
            {
                "decision": "block",
                "reason": next_prompt,
                "systemMessage": f"Auto-continuing next wave. Remaining: {remaining}",
            }
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
