#!/usr/bin/env python3
from pathlib import Path

from wave_stop import (
    append_journal,
    append_wave_history_entry,
    build_diagnostic_log_entry,
    build_missing_required_notes,
    classify_wave_targets,
    git_branch,
    git_head,
    load_project_policy,
    load_request,
    load_state,
    next_wave_state,
    now_utc,
    persist_state,
    require_exact_verify,
    resolve_project_root,
    safe_git_branch,
    safe_git_changed_paths,
    safe_git_head,
)


def fail(message: str) -> int:
    print(f"[wave-recover] {message}")
    return 1


def requeue_current_wave(project_root: Path, state: dict[str, object], reason: str) -> int:
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
            "event_type": "wave_recovery_requeued",
            "git_head": safe_git_head(project_root),
            "branch": safe_git_branch(project_root),
            "changed_paths": safe_git_changed_paths(project_root),
            "validation_result": "requeued",
            "benchmark_result": None,
            "budget_consumed": False,
            "stop_reason": reason,
        },
    )
    print(f"[wave-recover] requeued wave {state['current_wave']}: {reason}")
    return 1


def persist_recovered_next_state(
    project_root: Path,
    state: dict[str, object],
    next_state: dict[str, object],
    *,
    event_type: str,
    validation_result: str,
    stop_reason: str | None,
) -> None:
    if next_state["status"] != "completed":
        next_state["status"] = "queued"
    persist_state(project_root, next_state)
    append_journal(
        project_root,
        {
            "timestamp": now_utc(),
            "request_id": state["request_id"],
            "wave": state["current_wave"],
            "event_type": event_type,
            "git_head": safe_git_head(project_root),
            "branch": safe_git_branch(project_root),
            "changed_paths": safe_git_changed_paths(project_root),
            "validation_result": validation_result,
            "benchmark_result": None,
            "budget_consumed": True,
            "stop_reason": stop_reason,
        },
    )


def recover_diagnostic_wave(
    project_root: Path,
    request: dict[str, object],
    policy: dict[str, object],
    state: dict[str, object],
    missing_required: list[str],
    active_wave_paths: list[str],
) -> int:
    wave_label = f"{state['request_id']}/wave-{state['current_wave']}"
    summary = "missing required wave edit target(s): " + ", ".join(missing_required)
    notes = build_missing_required_notes(missing_required, active_wave_paths)
    append_wave_history_entry(
        project_root,
        policy,
        build_diagnostic_log_entry(wave_label=wave_label, summary=summary, notes=notes),
    )
    next_state = next_wave_state(
        state,
        last_result={
            "kind": "wave_diagnostic",
            "wave": wave_label,
            "summary": summary,
            "details": {
                "category": "controller",
                "reason": summary,
                "notes": notes,
                "changed_paths": safe_git_changed_paths(project_root),
            },
            "benchmark_result": None,
            "new_best": False,
        },
    )
    persist_recovered_next_state(
        project_root,
        state,
        next_state,
        event_type="wave_recovery_diagnostic",
        validation_result="diagnosis_only",
        stop_reason=summary,
    )
    print(
        f"[wave-recover] recovered diagnosis-only wave {state['current_wave']} for request {request['request_id']}; "
        f"status={next_state['status']} remaining_waves={next_state['remaining_waves']}"
    )
    return 0


def recover_verified_wave(
    project_root: Path,
    request: dict[str, object],
    policy: dict[str, object],
    state: dict[str, object],
) -> int:
    wave_label = f"{state['request_id']}/wave-{state['current_wave']}"
    next_state = next_wave_state(
        state,
        last_result={
            "kind": "wave_exact_verified",
            "wave": wave_label,
            "verification_command": str(policy["verification"]["exact_command"]),
            "benchmark_result": None,
        },
    )
    persist_recovered_next_state(
        project_root,
        state,
        next_state,
        event_type="wave_recovery_exact_verified",
        validation_result="exact_verified",
        stop_reason=None,
    )
    print(
        f"[wave-recover] recovered verified wave {state['current_wave']} for request {request['request_id']}; "
        f"status={next_state['status']} remaining_waves={next_state['remaining_waves']}"
    )
    return 0


def main() -> int:
    project_root = resolve_project_root(Path.cwd())
    try:
        state = load_state(project_root)
        request, request_sha = load_request(project_root)
        policy, policy_sha = load_project_policy(project_root)
    except ValueError as exc:
        return fail(str(exc))

    if request is None or request_sha is None:
        return fail("cannot recover without an active wave request")
    if state["status"] not in {"running", "validating"}:
        return fail(f"cannot recover while controller state is {state['status']}")
    if state["request_id"] != request["request_id"]:
        return fail(f"request mismatch: state={state['request_id']} request={request['request_id']}")
    if state["request_sha256"] != request_sha:
        return fail("wave_request.json changed during active campaign; reinitialize instead")
    if state.get("project_policy_sha256") != policy_sha:
        return fail("wave_project.json changed during active campaign; reinitialize instead")
    if state["base_branch"] != git_branch(project_root):
        return fail(f"campaign branch changed from {state['base_branch']} to {git_branch(project_root)}")
    if state["base_head"] != git_head(project_root):
        return fail(f"campaign HEAD changed from {state['base_head']} to {git_head(project_root)}")

    active_wave_paths, disallowed_paths, missing_required = classify_wave_targets(
        project_root,
        state["baseline_snapshot"],
        policy,
    )
    if disallowed_paths:
        return requeue_current_wave(
            project_root,
            state,
            "disallowed modified files during recovery: " + ", ".join(disallowed_paths),
        )
    if missing_required:
        if policy["diagnosis_only"]["enabled"]:
            return recover_diagnostic_wave(project_root, request, policy, state, missing_required, active_wave_paths)
        return requeue_current_wave(
            project_root,
            state,
            "missing required wave edit target(s) during recovery: " + ", ".join(missing_required),
        )

    exact_verify_ok, exact_verify_reason = require_exact_verify(project_root, policy)
    if not exact_verify_ok:
        return requeue_current_wave(project_root, state, exact_verify_reason)
    return recover_verified_wave(project_root, request, policy, state)


if __name__ == "__main__":
    raise SystemExit(main())
