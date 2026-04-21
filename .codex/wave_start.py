#!/usr/bin/env python3
import json
import subprocess
import sys
import tomllib
from pathlib import Path

from wave_stop import (
    HOOKS_FILE,
    PROJECT_POLICY_FILE,
    REQUEST_FILE,
    STATE_FILE,
    STATE_VERSION,
    append_journal,
    continue_command_env,
    load_project_policy,
    load_request,
    load_state,
    materialize_wave_prompt,
    now_utc,
    persist_state,
    resolve_project_root,
    safe_git_branch,
    safe_git_changed_paths,
    safe_git_head,
)

CONFIG_FILE = ".codex/config.toml"


def fail(message: str) -> int:
    print(f"[wave-start] {message}")
    return 1


def load_codex_hooks_enabled(project_root: Path) -> bool:
    config_path = project_root / CONFIG_FILE
    if not config_path.exists():
        return False
    with config_path.open("rb") as handle:
        config = tomllib.load(handle)
    features = config.get("features")
    return isinstance(features, dict) and features.get("codex_hooks") is True


def has_stop_hook(project_root: Path) -> bool:
    hooks_path = project_root / HOOKS_FILE
    if not hooks_path.exists():
        return False
    try:
        data = json.loads(hooks_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return False
    stop_entries = hooks.get("Stop")
    if not isinstance(stop_entries, list) or not stop_entries:
        return False
    for entry in stop_entries:
        if not isinstance(entry, dict):
            continue
        nested_hooks = entry.get("hooks")
        if isinstance(nested_hooks, list) and nested_hooks:
            return True
    return False


def validate_hook_preflight(project_root: Path) -> str | None:
    if not load_codex_hooks_enabled(project_root):
        return f"{CONFIG_FILE} must enable [features].codex_hooks = true before starting a campaign"
    if not has_stop_hook(project_root):
        return f"{HOOKS_FILE} must define a Stop hook before starting a campaign"
    if not (project_root / ".codex" / "wave_stop.py").exists():
        return ".codex/wave_stop.py must exist before starting a campaign"
    return None


def validate_ready_state(
    request: dict[str, object],
    request_sha: str,
    policy_sha: str,
    state: dict[str, object],
) -> str | None:
    if state.get("version") != STATE_VERSION:
        return f"{STATE_FILE} must be reinitialized to version {STATE_VERSION}; run `python3 .codex/wave_control_init.py`"
    if state["request_id"] != request["request_id"]:
        return (
            f"controller binding mismatch: state={state['request_id']} request={request['request_id']}; "
            "run `python3 .codex/wave_control_init.py` first"
        )
    if state["request_sha256"] != request_sha:
        return f"{REQUEST_FILE} changed after initialization; run `python3 .codex/wave_control_init.py`"
    if state.get("project_policy_sha256") != policy_sha:
        return f"{PROJECT_POLICY_FILE} changed after initialization; run `python3 .codex/wave_control_init.py`"
    if state["status"] == "completed":
        return f"request {request['request_id']} is already completed"
    if state["status"] in {"failed", "aborted"}:
        return f"request {request['request_id']} stopped with status={state['status']}: {state['last_stop_reason']}"
    if state["status"] != "queued":
        return f"cannot start a wave while controller state is {state['status']}"
    if int(state["current_wave"]) < 1 or int(state["remaining_waves"]) < 1:
        return "queued state must have current_wave >= 1 and remaining_waves >= 1"
    return None


def requeue_after_child_exit(
    project_root: Path,
    before_state: dict[str, object],
    child_exit_code: int,
) -> int:
    state = load_state(project_root)
    if state["request_id"] != before_state["request_id"]:
        return child_exit_code
    if state["status"] == "completed":
        return child_exit_code
    if state["status"] == "queued":
        return child_exit_code
    if state["status"] not in {"running", "validating"}:
        return child_exit_code

    reason = (
        f"Codex child exited with code {child_exit_code} while controller still marked "
        f"request {state['request_id']} wave {state['current_wave']} as {state['status']}; "
        "Stop hook did not complete state transition"
    )
    requeued = dict(state)
    requeued["status"] = "queued"
    requeued["last_stop_reason"] = reason
    requeued["updated_at"] = now_utc()
    persist_state(project_root, requeued)
    append_journal(
        project_root,
        {
            "timestamp": now_utc(),
            "request_id": state["request_id"],
            "wave": state["current_wave"],
            "event_type": "wave_start_child_exit_requeued",
            "git_head": safe_git_head(project_root),
            "branch": safe_git_branch(project_root),
            "changed_paths": safe_git_changed_paths(project_root),
            "validation_result": "requeued",
            "benchmark_result": None,
            "budget_consumed": False,
            "stop_reason": reason,
        },
    )
    print(f"[wave-start] {reason}", file=sys.stderr)
    print(f"[wave-start] requeued request={state['request_id']} wave={state['current_wave']}", file=sys.stderr)
    return child_exit_code if child_exit_code != 0 else 1


def main() -> int:
    project_root = resolve_project_root(Path.cwd())
    try:
        request, request_sha = load_request(project_root)
        _policy, policy_sha = load_project_policy(project_root)
        state = load_state(project_root)
    except ValueError as exc:
        return fail(str(exc))

    if request is None or request_sha is None:
        return fail(f"set a new request in {REQUEST_FILE} before starting the wave")

    preflight_error = validate_hook_preflight(project_root)
    if preflight_error is not None:
        return fail(preflight_error)

    validation_error = validate_ready_state(request, request_sha, policy_sha, state)
    if validation_error is not None:
        return fail(validation_error)

    prompt_path = materialize_wave_prompt(project_root, request, state)
    env = continue_command_env(project_root, request, state, prompt_path)
    running_state = dict(state)
    running_state["status"] = "running"
    running_state["last_stop_reason"] = None
    running_state["updated_at"] = now_utc()
    persist_state(project_root, running_state)

    print(
        f"[wave-start] launching request={request['request_id']} "
        f"wave={state['current_wave']}/{state['requested_waves']}"
    )
    print(f"[wave-start] prompt_file={prompt_path}")
    completed = subprocess.run(
        ["sh", "-lc", str(request["continue_command"])],
        cwd=project_root,
        env=env,
        check=False,
    )
    return requeue_after_child_exit(project_root, running_state, completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
