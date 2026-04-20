#!/usr/bin/env python3
import argparse
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

    if state["status"] not in {"idle", "completed", "failed", "aborted"}:
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

    if args.run:
        return launch_continue_command(project_root, request, initialized_state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
