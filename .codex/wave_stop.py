#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import fcntl

ALLOWED_EDIT_TARGETS = {
    "algorithms/pi_algo_improve-by-agent.py",
    "log.md",
}
COUNT_FILE = "count.md"
LOCK_FILE = ".codex/wave.lock"
STATE_FILE = ".codex/wave_state.json"
TASK_FILE = "docs/task.md"
INIT_PROMPT_FILE = "docs/init_prompt.md"
LOG_FILE = "log.md"
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
    STATE_FILE,
    COUNT_FILE,
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


def load_configured_wave_count(count_path: Path) -> int:
    if not count_path.exists():
        raise FileNotFoundError(f"{COUNT_FILE} not found")

    text = count_path.read_text(encoding="utf-8")
    match = COUNT_RE.search(text)
    if not match:
        raise ValueError(f"wave_count not found in {COUNT_FILE}")
    return int(match.group(1))


def load_runtime_state(state_path: Path, configured_count: int) -> int:
    if configured_count < 0:
        raise ValueError("configured wave_count must be >= 0")

    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON in {STATE_FILE}: {exc}") from exc

        state_configured = state.get("configured_count")
        state_remaining = state.get("remaining")
        if (
            isinstance(state_configured, int)
            and isinstance(state_remaining, int)
            and 0 <= state_remaining <= state_configured
            and state_configured == configured_count
        ):
            return state_remaining
        # Reinitialize runtime state when the saved state is invalid or stale.

    persist_runtime_state(state_path, configured_count, configured_count)
    return configured_count


def persist_runtime_state(state_path: Path, configured_count: int, remaining: int) -> None:
    state_path.write_text(
        json.dumps(
            {
                "configured_count": configured_count,
                "remaining": remaining,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def read_required_text(project_root: Path, relative_path: str) -> str:
    path = project_root / relative_path
    return path.read_text(encoding="utf-8").strip()


def build_next_wave_prompt(project_root: Path, remaining: int) -> str:
    task_text = read_required_text(project_root, TASK_FILE)
    init_prompt_text = read_required_text(project_root, INIT_PROMPT_FILE)
    log_text = read_required_text(project_root, LOG_FILE)

    return (
        f"Continue to the next wave. Remaining waves in {COUNT_FILE}: {remaining}.\n"
        "Execute exactly one optimization wave in this turn.\n"
        "Before starting, follow the initialization instructions below and read the files again.\n\n"
        f"[{INIT_PROMPT_FILE}]\n{init_prompt_text}\n\n"
        f"[{TASK_FILE}]\n{task_text}\n\n"
        f"[{LOG_FILE}]\n{log_text}\n\n"
        "Constraints for this turn:\n"
        "- Execute exactly one wave only.\n"
        "- Read docs/task.md, docs/init_prompt.md, and log.md before editing.\n"
        "- Only modify allowed files for a normal optimization wave.\n"
        "- At the end of the wave, write a short summary and stop naturally.\n"
        "- Do not start another wave by yourself; the Stop hook will decide."
    )


def require_only_allowed_target(project_root: Path) -> tuple[bool, str]:
    changed_paths = git_changed_paths(project_root)
    disallowed = [path for path in changed_paths if path not in ALLOWED_EDIT_TARGETS]
    if disallowed:
        return (
            False,
            "disallowed modified files: "
            + ", ".join(disallowed)
            + "; only "
            + ", ".join(sorted(ALLOWED_EDIT_TARGETS))
            + " may change during a wave",
        )
    if "algorithms/pi_algo_improve-by-agent.py" not in changed_paths:
        return (
            False,
            "expected a change in algorithms/pi_algo_improve-by-agent.py before consuming a wave",
        )
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
    state_path = project_root / STATE_FILE
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    with lock_path.open("w", encoding="utf-8") as lockf:
        fcntl.flock(lockf, fcntl.LOCK_EX)

        try:
            configured_count = load_configured_wave_count(count_path)
        except FileNotFoundError:
            emit(
                {
                    "continue": False,
                    "stopReason": f"{COUNT_FILE} not found",
                    "systemMessage": f"{COUNT_FILE} not found, stop loop.",
                }
            )
            return 0
        except ValueError as exc:
            emit(
                {
                    "continue": False,
                    "stopReason": f"wave_count not found in {COUNT_FILE}",
                    "systemMessage": f"{exc}, stop loop.",
                }
            )
            return 0

        try:
            remaining = load_runtime_state(state_path, configured_count)
        except ValueError as exc:
            emit(
                {
                    "continue": False,
                    "stopReason": f"invalid runtime state in {STATE_FILE}",
                    "systemMessage": str(exc),
                }
            )
            return 0

        if remaining <= 0:
            emit(
                {
                    "continue": False,
                    "stopReason": "Wave budget exhausted",
                    "systemMessage": f"remaining waves in {STATE_FILE} is already 0, stop loop.",
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
        persist_runtime_state(state_path, configured_count, remaining)

        if remaining == 0:
            emit(
                {
                    "continue": False,
                    "stopReason": "Completed final wave",
                    "systemMessage": "All waves completed.",
                }
            )
            return 0

        next_prompt = build_next_wave_prompt(project_root, remaining)
        emit(
            {
                "decision": "block",
                "reason": next_prompt,
                "systemMessage": (
                    "Auto-continuing next wave with task/init/log context injected. "
                    f"Remaining: {remaining}"
                ),
            }
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
