#!/usr/bin/env python3
import argparse
import datetime as dt
import os
import subprocess
import sys
from pathlib import Path

from wave_stop import (
    append_journal,
    capture_worktree_snapshot,
    git_branch,
    git_changed_paths,
    git_head,
    load_project_policy,
    load_stop_hook_timeout_seconds,
    load_request,
    load_state,
    materialize_wave_prompt,
    now_utc,
    persist_state,
    PROJECT_POLICY_FILE,
    REQUEST_FILE,
    resolve_project_root,
    safe_git_branch,
    safe_git_changed_paths,
    safe_git_head,
    STATE_VERSION,
    STATE_FILE,
)


def build_initialized_state(
    project_root: Path,
    request: dict[str, object],
    request_sha: str,
    policy: dict[str, object],
    policy_sha: str,
) -> dict[str, object]:
    timestamp = now_utc()
    changed_paths = git_changed_paths(project_root, policy)
    return {
        "version": STATE_VERSION,
        "request_id": request["request_id"],
        "request_sha256": request_sha,
        "project_policy_sha256": policy_sha,
        "status": "queued",
        "requested_waves": request["requested_waves"],
        "attempted_waves": 0,
        "successful_waves": 0,
        "remaining_waves": request["requested_waves"],
        "current_wave": 1,
        "baseline_dirty_paths": sorted(changed_paths),
        "baseline_snapshot": capture_worktree_snapshot(project_root, policy),
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
    policy_sha: str,
    state: dict[str, object],
) -> dict[str, object]:
    recovered = dict(state)
    recovered["version"] = STATE_VERSION
    recovered["request_id"] = request["request_id"]
    recovered["request_sha256"] = request_sha
    recovered["project_policy_sha256"] = policy_sha
    recovered["requested_waves"] = request["requested_waves"]
    recovered["status"] = "queued"
    recovered["current_wave"] = recovered["successful_waves"] + 1 if recovered["remaining_waves"] > 0 else 0
    recovered["last_stop_reason"] = "Recovered stale validating state"
    recovered["updated_at"] = now_utc()
    recovered["worktree_path"] = str(project_root)
    return recovered


def runner_command(project_root: Path) -> list[str]:
    return [sys.executable, str(project_root / ".codex" / "wave_start.py")]


def recover_command(project_root: Path) -> list[str]:
    return [sys.executable, str(project_root / ".codex" / "wave_recover.py")]


def shell_preview(command: list[str]) -> str:
    return " ".join(command)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Initialize the control-plane state for a new multi-wave campaign."
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Launch the hook-driven foreground wave bootstrap immediately after initialization.",
    )
    abort_group = parser.add_mutually_exclusive_group()
    abort_group.add_argument(
        "--abort-active",
        action="store_true",
        default=True,
        help="Abort an existing active queued/running/validating campaign before initializing the new request. This is the default behavior.",
    )
    abort_group.add_argument(
        "--no-abort-active",
        action="store_false",
        dest="abort_active",
        help="Refuse initialization if an active queued/running/validating campaign still exists.",
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


def is_rebootstrappable_same_request(
    state: dict[str, object],
    request: dict[str, object],
) -> bool:
    return state["status"] == "queued" and state.get("request_id") == request["request_id"]


def state_matches_current_request(
    state: dict[str, object],
    request: dict[str, object],
    request_sha: str,
    policy_sha: str,
) -> bool:
    return (
        state.get("request_id") == request["request_id"]
        and state.get("request_sha256") == request_sha
        and state.get("project_policy_sha256") == policy_sha
    )


def has_live_campaign_runtime(project_root: Path) -> bool:
    try:
        completed = subprocess.run(
            ["ps", "-eo", "pid=,args="],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    own_pid = str(os.getpid())
    needles = (
        "codex exec",
        ".codex/wave_start.py",
        ".codex/wave_stop.py",
        "run_verify_timed.py",
        "pi_algo_improve-by-agent.py",
    )
    project_root_text = str(project_root)
    for line in completed.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        pid, _, args = stripped.partition(" ")
        if own_pid and pid == own_pid:
            continue
        if project_root_text in args and any(needle in args for needle in needles):
            return True
    return False


def run_wave_start(project_root: Path) -> int:
    completed = subprocess.run(runner_command(project_root), cwd=project_root, check=False)
    return completed.returncode


def recover_then_maybe_start(project_root: Path) -> int:
    recovery = subprocess.run(recover_command(project_root), cwd=project_root, check=False)
    try:
        state = load_state(project_root)
    except ValueError as exc:
        print(f"controller state invalid after recovery: {exc}")
        return 1
    if state["status"] == "completed":
        print(f"request {state['request_id']} completed during recovery")
        return 0
    if state["status"] == "queued":
        return run_wave_start(project_root)
    return recovery.returncode if recovery.returncode != 0 else 1


def abort_active_campaign(
    project_root: Path,
    state: dict[str, object],
    *,
    replacement_request_id: str,
) -> str:
    aborted_state = dict(state)
    aborted_state["status"] = "aborted"
    aborted_state["last_stop_reason"] = (
        f"Aborted by wave_control_init.py while switching to request {replacement_request_id}"
    )
    aborted_state["updated_at"] = now_utc()
    persist_state(project_root, aborted_state)
    append_journal(
        project_root,
        {
            "timestamp": now_utc(),
            "request_id": state["request_id"],
            "wave": state["current_wave"],
            "event_type": "campaign_aborted_for_new_request",
            "git_head": safe_git_head(project_root),
            "branch": safe_git_branch(project_root),
            "changed_paths": safe_git_changed_paths(project_root),
            "validation_result": "aborted",
            "benchmark_result": None,
            "budget_consumed": False,
            "stop_reason": (
                f"Aborted active campaign {state['request_id']} in favor of {replacement_request_id}"
            ),
        },
    )
    return (
        f"aborted active campaign {state['request_id']} "
        f"(status={state['status']}) in favor of {replacement_request_id}"
    )


def describe_active_conflict(state: dict[str, object], request: dict[str, object]) -> str:
    active_request_id = state["request_id"]
    requested_request_id = request["request_id"]
    if active_request_id == requested_request_id:
        return (
            f"cannot initialize while {STATE_FILE} is active "
            f"(request_id={active_request_id}, status={state['status']})"
        )
    return (
        f"cannot initialize new request {requested_request_id} while {STATE_FILE} still tracks "
        f"active request {active_request_id} (status={state['status']}); "
        "rerun with default behavior or pass --abort-active to terminate the old campaign first"
    )


def main() -> int:
    args = parse_args()
    project_root = resolve_project_root(Path.cwd())

    try:
        request, request_sha = load_request(project_root)
        policy, policy_sha = load_project_policy(project_root)
        state = load_state(project_root)
    except ValueError as exc:
        print(f"controller state invalid: {exc}")
        return 1

    if request is None or request_sha is None:
        print(f"set a new request in {REQUEST_FILE} before running initialization")
        return 1
    if policy is None or policy_sha is None:
        print(f"set project policy in {PROJECT_POLICY_FILE} before running initialization")
        return 1

    if args.run and state_matches_current_request(state, request, request_sha, policy_sha):
        if state["status"] == "queued":
            print(
                f"resuming queued request {request['request_id']} "
                f"wave {state['current_wave']}/{state['requested_waves']}"
            )
            return run_wave_start(project_root)
        if state["status"] in {"running", "validating"}:
            if has_live_campaign_runtime(project_root):
                print(
                    f"request {request['request_id']} still has a live runtime; "
                    "refusing to start a duplicate campaign"
                )
                return 1
            print(
                f"recovering stale {state['status']} request {request['request_id']} "
                f"wave {state['current_wave']} before starting"
            )
            return recover_then_maybe_start(project_root)
        if state["status"] == "completed":
            print(f"request {request['request_id']} is already completed")
            return 0

    can_init, recovery_reason = can_reinitialize(project_root, state)
    aborted_request_id: str | None = None
    if not can_init:
        if is_rebootstrappable_same_request(state, request):
            can_init = True
            recovery_reason = (
                f"reinitialized queued request {request['request_id']} from existing controller state"
            )
        elif args.abort_active and state["status"] in {"queued", "running", "validating"}:
            aborted_request_id = str(state["request_id"])
            if state["request_id"] == request["request_id"]:
                print(
                    "active campaign restart requested: "
                    f"request={state['request_id']} status={state['status']}"
                )
            else:
                print(
                    "active campaign conflict detected: "
                    f"old_request={state['request_id']} status={state['status']} "
                    f"new_request={request['request_id']}"
                )
            recovery_reason = abort_active_campaign(
                project_root,
                state,
                replacement_request_id=str(request["request_id"]),
            )
            state = load_state(project_root)
            can_init, _ = can_reinitialize(project_root, state)
        if not can_init:
            print(describe_active_conflict(state, request))
            return 1

    should_recover_stale_same_request = (
        recovery_reason is not None
        and state["status"] == "validating"
        and state["request_id"] == request["request_id"]
        and state["request_sha256"] == request_sha
        and state.get("project_policy_sha256") == policy_sha
        and state["remaining_waves"] > 0
    )
    initialized_state = (
        build_recovered_state(project_root, request, request_sha, policy_sha, state)
        if should_recover_stale_same_request
        else build_initialized_state(project_root, request, request_sha, policy, policy_sha)
    )
    persist_state(project_root, initialized_state)
    prompt_path = materialize_wave_prompt(project_root, request, initialized_state)
    command = runner_command(project_root)
    command_preview = shell_preview(command)

    if aborted_request_id is not None:
        print(
            f"switched active campaign: old_request={aborted_request_id} "
            f"new_request={request['request_id']}"
        )
    print(f"initialized request {request['request_id']} for wave 1/{request['requested_waves']}")
    print(f"prompt_file={prompt_path}")
    print(f"next_command={command_preview}")
    if recovery_reason is not None:
        print(recovery_reason)

    if args.run:
        return run_wave_start(project_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
