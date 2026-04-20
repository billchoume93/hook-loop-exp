#!/usr/bin/env python3
import argparse
import datetime as dt
from pathlib import Path

from wave_stop import (
    capture_worktree_snapshot,
    continue_command_env,
    git_branch,
    git_changed_paths,
    git_head,
    launch_continue_command,
    load_stop_hook_timeout_seconds,
    load_request,
    load_state,
    materialize_wave_prompt,
    now_utc,
    persist_state,
    REQUEST_FILE,
    resolve_project_root,
    STATE_FILE,
)


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


def build_recovered_state(
    project_root: Path,
    request: dict[str, object],
    request_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    recovered = dict(state)
    recovered["version"] = 2
    recovered["request_id"] = request["request_id"]
    recovered["request_sha256"] = request_sha
    recovered["requested_waves"] = request["requested_waves"]
    recovered["status"] = "queued"
    recovered["current_wave"] = recovered["successful_waves"] + 1 if recovered["remaining_waves"] > 0 else 0
    recovered["last_stop_reason"] = "Recovered stale validating state"
    recovered["updated_at"] = now_utc()
    recovered["worktree_path"] = str(project_root)
    return recovered


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

    should_recover_stale_same_request = (
        recovery_reason is not None
        and state["status"] == "validating"
        and state["request_id"] == request["request_id"]
        and state["request_sha256"] == request_sha
        and state["remaining_waves"] > 0
    )
    initialized_state = (
        build_recovered_state(project_root, request, request_sha, state)
        if should_recover_stale_same_request
        else build_initialized_state(project_root, request, request_sha)
    )
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
