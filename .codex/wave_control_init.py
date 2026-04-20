#!/usr/bin/env python3
import argparse
import datetime as dt
import json
from pathlib import Path

from wave_stop import (
    REQUEST_FILE,
    STATE_FILE,
    capture_worktree_snapshot,
    continue_command_env,
    git_branch,
    git_changed_paths,
    git_head,
    launch_continue_command,
    load_request,
    load_state,
    materialize_wave_prompt,
    now_utc,
    persist_state,
    resolve_project_root,
)

HOOKS_FILE = ".codex/hooks.json"
DEFAULT_STALE_VALIDATING_SECONDS = 180


def build_initialized_state(project_root: Path, request: dict[str, object], request_sha: str) -> dict[str, object]:
    timestamp = now_utc()
    changed_paths = git_changed_paths(project_root)
    return {
        "version": 2,
        "request_id": request["request_id"],
        "request_sha256": request_sha,
        "status": "queued",
        "requested_waves": request["requested_waves"],
        "attempted_waves": 0,
        "successful_waves": 0,
        "remaining_waves": request["requested_waves"],
        "current_wave": 1,
        "baseline_dirty_paths": sorted(changed_paths),
        "baseline_snapshot": capture_worktree_snapshot(project_root),
        "base_head": git_head(project_root),
        "base_branch": git_branch(project_root),
        "worktree_path": str(project_root),
        "last_result": None,
        "last_stop_reason": None,
        "created_at": timestamp,
        "updated_at": timestamp,
    }


def shell_preview(command: str, env: dict[str, str]) -> str:
    exports = [
        f'PROJECT_ROOT="{env["PROJECT_ROOT"]}"',
        f'REQUEST_ID="{env["REQUEST_ID"]}"',
        f'REQUEST_FILE="{env["REQUEST_FILE"]}"',
        f'STATE_FILE="{env["STATE_FILE"]}"',
        f'TASK_FILE="{env["TASK_FILE"]}"',
        f'WAVE_NUMBER="{env["WAVE_NUMBER"]}"',
        f'REQUESTED_WAVES="{env["REQUESTED_WAVES"]}"',
        f'REMAINING_WAVES="{env["REMAINING_WAVES"]}"',
    ]
    return " ".join(exports + [command])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Initialize the control-plane state for a new multi-wave campaign."
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Launch the request continue_command immediately after initialization.",
    )
    return parser.parse_args()


def parse_utc_timestamp(value: object) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def load_stop_hook_timeout_seconds(project_root: Path) -> int:
    hooks_path = project_root / HOOKS_FILE
    if not hooks_path.exists():
        return DEFAULT_STALE_VALIDATING_SECONDS
    try:
        data = json.loads(hooks_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return DEFAULT_STALE_VALIDATING_SECONDS
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return DEFAULT_STALE_VALIDATING_SECONDS
    stop_entries = hooks.get("Stop")
    if not isinstance(stop_entries, list):
        return DEFAULT_STALE_VALIDATING_SECONDS
    for entry in stop_entries:
        if not isinstance(entry, dict):
            continue
        nested_hooks = entry.get("hooks")
        if not isinstance(nested_hooks, list):
            continue
        for hook in nested_hooks:
            if not isinstance(hook, dict):
                continue
            timeout = hook.get("timeout")
            if isinstance(timeout, int) and timeout > 0:
                return timeout
    return DEFAULT_STALE_VALIDATING_SECONDS


def can_reinitialize(project_root: Path, state: dict[str, object]) -> tuple[bool, str | None]:
    if state["status"] in {"idle", "completed", "failed", "aborted"}:
        return (True, None)
    if state["status"] != "validating":
        return (False, None)
    updated_at = parse_utc_timestamp(state.get("updated_at"))
    if updated_at is None:
        return (True, "recovering validating state with missing updated_at")
    stale_validating_seconds = load_stop_hook_timeout_seconds(project_root)
    age = (dt.datetime.now(dt.timezone.utc) - updated_at).total_seconds()
    if age >= stale_validating_seconds:
        return (
            True,
            "recovering stale validating state after "
            f"{age:.0f}s without completion (threshold={stale_validating_seconds}s)",
        )
    return (False, None)


def main() -> int:
    args = parse_args()
    project_root = resolve_project_root(Path.cwd())

    try:
        request, request_sha = load_request(project_root)
        state = load_state(project_root)
    except ValueError as exc:
        print(f"controller state invalid: {exc}")
        return 1

    if request is None or request_sha is None:
        print(f"set a new request in {REQUEST_FILE} before running initialization")
        return 1

    can_init, recovery_reason = can_reinitialize(project_root, state)
    if not can_init:
        print(
            f"cannot initialize while {STATE_FILE} is active "
            f"(request_id={state['request_id']}, status={state['status']})"
        )
        return 1

    initialized_state = build_initialized_state(project_root, request, request_sha)
    persist_state(project_root, initialized_state)
    prompt_path = materialize_wave_prompt(project_root, request, initialized_state)
    env = continue_command_env(project_root, request, initialized_state, prompt_path)
    command_preview = shell_preview(str(request["continue_command"]), env)

    print(f"initialized request {request['request_id']} for wave 1/{request['requested_waves']}")
    print(f"prompt_file={prompt_path}")
    print(f"next_command={command_preview}")
    if recovery_reason is not None:
        print(recovery_reason)

    if args.run:
        return launch_continue_command(project_root, request, initialized_state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
