#!/usr/bin/env python3
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional, Tuple

STATE_VERSION = 3
REQUEST_VERSION = 2
PROJECT_POLICY_VERSION = 1

REQUEST_FILE = ".codex/wave_request.json"
STATE_FILE = ".codex/wave_state.json"
PROJECT_POLICY_FILE = ".codex/wave_project.json"
LOCK_FILE = ".codex/wave.lock"
LOCAL_JOURNAL_FILE = ".codex/local/wave_events.jsonl"
PROMPT_DIR = ".codex/local/prompts"
HOOKS_FILE = ".codex/hooks.json"

ACTIVE_STATUSES = {"queued", "running", "validating"}
TERMINAL_STATUSES = {"idle", "completed", "failed", "aborted"}
DEFAULT_STOP_HOOK_TIMEOUT_SECONDS = 180

DEFAULT_IGNORED_PATH_PREFIXES = (
    "__pycache__/",
    ".codex/local/",
)
DEFAULT_IGNORED_PATHS = {
    LOCK_FILE,
    REQUEST_FILE,
    STATE_FILE,
}


def emit(obj: dict[str, object]) -> None:
    print(json.dumps(obj, ensure_ascii=False))


def emit_block(*, reason: str, stop_reason: str, system_message: str | None = None) -> None:
    emit(
        {
            "decision": "block",
            "reason": reason,
            "stopReason": stop_reason,
            "systemMessage": system_message or reason,
        }
    )


def load_hook_payload() -> dict[str, object]:
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def resolve_project_root(cwd: Path) -> Path:
    for directory in (cwd, *cwd.parents):
        if (directory / ".codex" / "hooks.json").exists():
            return directory
    return cwd


def run_shell_command(project_root: Path, command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", "-lc", command],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        tmp.write(text)
        tmp.flush()
        os.fsync(tmp.fileno())
        temp_path = Path(tmp.name)
    temp_path.replace(path)


def append_journal(project_root: Path, event: dict[str, object]) -> None:
    journal_path = project_root / LOCAL_JOURNAL_FILE
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    with journal_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def safe_subprocess_text(args: list[str], project_root: Path) -> str:
    try:
        completed = subprocess.run(
            args,
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        return f"unavailable: {exc}"
    return completed.stdout.strip()


def safe_git_head(project_root: Path) -> str:
    return safe_subprocess_text(["git", "rev-parse", "HEAD"], project_root)


def safe_git_branch(project_root: Path) -> str:
    return safe_subprocess_text(["git", "rev-parse", "--abbrev-ref", "HEAD"], project_root)


def safe_git_changed_paths(project_root: Path) -> list[str]:
    try:
        return git_changed_paths(project_root)
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        return [f"unavailable: {exc}"]


def git_head(project_root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def git_branch(project_root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def normalize_json_bytes(obj: dict[str, object]) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_hex(obj: dict[str, object]) -> str:
    return hashlib.sha256(normalize_json_bytes(obj)).hexdigest()


def sha256_file_hex(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_required_text(project_root: Path, relative_path: str) -> str:
    path = project_root / relative_path
    if not path.exists():
        raise ValueError(f"required prompt context file is missing: {relative_path}")
    return path.read_text(encoding="utf-8").strip()


def require_exact_keys(data: dict[str, object], required_keys: set[str], *, name: str) -> None:
    if set(data) != required_keys:
        raise ValueError(f"{name} keys must be exactly {sorted(required_keys)}")


def require_string_list(value: object, *, name: str, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise ValueError(f"{name} must be a list of non-empty strings")
    if not allow_empty and not value:
        raise ValueError(f"{name} must not be empty")
    return list(value)


def inactive_request(data: dict[str, object]) -> bool:
    return (
        data.get("request_id") in (None, "")
        and data.get("requested_waves") in (None, 0)
        and data.get("goal") in (None, "")
        and data.get("created_at") in (None, "")
    )


def load_request(project_root: Path) -> Tuple[Optional[dict[str, object]], Optional[str]]:
    path = project_root / REQUEST_FILE
    if not path.exists():
        return (None, None)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {REQUEST_FILE}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{REQUEST_FILE} must contain a JSON object")
    if inactive_request(data):
        return (None, None)
    required_keys = {
        "version",
        "request_id",
        "requested_waves",
        "goal",
        "continue_command",
        "created_at",
    }
    require_exact_keys(data, required_keys, name=REQUEST_FILE)
    if data["version"] != REQUEST_VERSION:
        raise ValueError(f"{REQUEST_FILE} version must be {REQUEST_VERSION}")
    if not isinstance(data["request_id"], str) or not data["request_id"].strip():
        raise ValueError(f"{REQUEST_FILE} request_id must be a non-empty string")
    if not isinstance(data["requested_waves"], int) or data["requested_waves"] < 1:
        raise ValueError(f"{REQUEST_FILE} requested_waves must be an integer >= 1")
    if not isinstance(data["goal"], str) or not data["goal"].strip():
        raise ValueError(f"{REQUEST_FILE} goal must be a non-empty string")
    if not isinstance(data["continue_command"], str) or not data["continue_command"].strip():
        raise ValueError(f"{REQUEST_FILE} continue_command must be a non-empty string")
    if not isinstance(data["created_at"], str) or not data["created_at"].strip():
        raise ValueError(f"{REQUEST_FILE} created_at must be a non-empty string")
    return (data, sha256_hex(data))


def validate_project_policy(data: dict[str, object]) -> dict[str, object]:
    required_keys = {
        "version",
        "allowed_wave_edit_targets",
        "required_wave_edit_targets",
        "ignored_paths",
        "ignored_path_prefixes",
        "prompt_context_files",
        "log_file",
        "verification",
        "benchmark",
        "diagnosis_only",
    }
    require_exact_keys(data, required_keys, name=PROJECT_POLICY_FILE)
    if data["version"] != PROJECT_POLICY_VERSION:
        raise ValueError(f"{PROJECT_POLICY_FILE} version must be {PROJECT_POLICY_VERSION}")

    policy = dict(data)
    policy["allowed_wave_edit_targets"] = require_string_list(
        data["allowed_wave_edit_targets"],
        name=f"{PROJECT_POLICY_FILE} allowed_wave_edit_targets",
        allow_empty=False,
    )
    policy["required_wave_edit_targets"] = require_string_list(
        data["required_wave_edit_targets"],
        name=f"{PROJECT_POLICY_FILE} required_wave_edit_targets",
    )
    policy["ignored_paths"] = require_string_list(data["ignored_paths"], name=f"{PROJECT_POLICY_FILE} ignored_paths")
    policy["ignored_path_prefixes"] = require_string_list(
        data["ignored_path_prefixes"],
        name=f"{PROJECT_POLICY_FILE} ignored_path_prefixes",
    )
    policy["prompt_context_files"] = require_string_list(
        data["prompt_context_files"],
        name=f"{PROJECT_POLICY_FILE} prompt_context_files",
        allow_empty=False,
    )
    if not isinstance(data["log_file"], str) or not data["log_file"]:
        raise ValueError(f"{PROJECT_POLICY_FILE} log_file must be a non-empty string")

    verification = data["verification"]
    if not isinstance(verification, dict):
        raise ValueError(f"{PROJECT_POLICY_FILE} verification must be an object")
    require_exact_keys(verification, {"exact_command"}, name=f"{PROJECT_POLICY_FILE} verification")
    if not isinstance(verification["exact_command"], str) or not verification["exact_command"].strip():
        raise ValueError(f"{PROJECT_POLICY_FILE} verification.exact_command must be a non-empty string")

    benchmark = data["benchmark"]
    if not isinstance(benchmark, dict):
        raise ValueError(f"{PROJECT_POLICY_FILE} benchmark must be an object")
    require_exact_keys(
        benchmark,
        {"compatibility_command", "decision_command_label", "heavy_command_policy", "subsequent_wave_guidance"},
        name=f"{PROJECT_POLICY_FILE} benchmark",
    )
    if not isinstance(benchmark["compatibility_command"], str):
        raise ValueError(f"{PROJECT_POLICY_FILE} benchmark.compatibility_command must be a string")
    if not isinstance(benchmark["decision_command_label"], str):
        raise ValueError(f"{PROJECT_POLICY_FILE} benchmark.decision_command_label must be a string")
    if benchmark["heavy_command_policy"] != "first_wave_only":
        raise ValueError(f"{PROJECT_POLICY_FILE} benchmark.heavy_command_policy must be first_wave_only")
    if not isinstance(benchmark["subsequent_wave_guidance"], str) or not benchmark["subsequent_wave_guidance"]:
        raise ValueError(f"{PROJECT_POLICY_FILE} benchmark.subsequent_wave_guidance must be a non-empty string")

    diagnosis_only = data["diagnosis_only"]
    if not isinstance(diagnosis_only, dict):
        raise ValueError(f"{PROJECT_POLICY_FILE} diagnosis_only must be an object")
    require_exact_keys(diagnosis_only, {"enabled"}, name=f"{PROJECT_POLICY_FILE} diagnosis_only")
    if not isinstance(diagnosis_only["enabled"], bool):
        raise ValueError(f"{PROJECT_POLICY_FILE} diagnosis_only.enabled must be a boolean")

    allowed = set(policy["allowed_wave_edit_targets"])
    missing_allowed = [path for path in policy["required_wave_edit_targets"] if path not in allowed]
    if missing_allowed:
        raise ValueError(
            f"{PROJECT_POLICY_FILE} required_wave_edit_targets must be allowed targets: "
            + ", ".join(missing_allowed)
        )
    return policy


def load_project_policy(project_root: Path) -> tuple[dict[str, object], str]:
    path = project_root / PROJECT_POLICY_FILE
    if not path.exists():
        raise ValueError(f"required project policy is missing: {PROJECT_POLICY_FILE}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {PROJECT_POLICY_FILE}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{PROJECT_POLICY_FILE} must contain a JSON object")
    policy = validate_project_policy(data)
    return (policy, sha256_hex(policy))


def policy_ignored_paths(policy: dict[str, object] | None) -> set[str]:
    if policy is None:
        return set(DEFAULT_IGNORED_PATHS)
    return set(policy["ignored_paths"])


def policy_ignored_prefixes(policy: dict[str, object] | None) -> tuple[str, ...]:
    if policy is None:
        return DEFAULT_IGNORED_PATH_PREFIXES
    return tuple(policy["ignored_path_prefixes"])


def git_changed_paths(project_root: Path, policy: dict[str, object] | None = None) -> list[str]:
    completed = subprocess.run(
        ["git", "status", "--short"],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    )
    ignored_paths = policy_ignored_paths(policy)
    ignored_prefixes = policy_ignored_prefixes(policy)
    changed_paths: list[str] = []
    for line in completed.stdout.splitlines():
        if not line:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path in ignored_paths:
            continue
        if any(path.startswith(prefix) for prefix in ignored_prefixes):
            continue
        changed_paths.append(path)
    return changed_paths


def capture_worktree_snapshot(project_root: Path, policy: dict[str, object] | None = None) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for relative_path in git_changed_paths(project_root, policy):
        abs_path = project_root / relative_path
        if abs_path.is_dir():
            snapshot[relative_path] = "directory"
        else:
            snapshot[relative_path] = sha256_file_hex(abs_path) if abs_path.exists() else "missing"
    return snapshot


def default_state(project_root: Path) -> dict[str, object]:
    return {
        "version": STATE_VERSION,
        "request_id": None,
        "request_sha256": None,
        "project_policy_sha256": None,
        "status": "idle",
        "requested_waves": 0,
        "attempted_waves": 0,
        "successful_waves": 0,
        "remaining_waves": 0,
        "current_wave": 0,
        "baseline_dirty_paths": [],
        "baseline_snapshot": {},
        "base_head": None,
        "base_branch": None,
        "worktree_path": str(project_root),
        "last_result": None,
        "last_stop_reason": None,
        "created_at": None,
        "updated_at": None,
    }


def load_state(project_root: Path) -> dict[str, object]:
    path = project_root / STATE_FILE
    if not path.exists():
        return default_state(project_root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {STATE_FILE}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{STATE_FILE} must contain a JSON object")
    if "baseline_snapshot" not in data:
        data = dict(data)
        data["baseline_snapshot"] = {}

    version = data.get("version")
    common_keys = {
        "version",
        "request_id",
        "request_sha256",
        "status",
        "requested_waves",
        "attempted_waves",
        "successful_waves",
        "remaining_waves",
        "current_wave",
        "baseline_dirty_paths",
        "baseline_snapshot",
        "base_head",
        "base_branch",
        "worktree_path",
        "last_result",
        "last_stop_reason",
        "created_at",
        "updated_at",
    }
    required_keys = common_keys | {"project_policy_sha256"} if version == STATE_VERSION else common_keys
    require_exact_keys(data, required_keys, name=STATE_FILE)
    if version not in {2, STATE_VERSION}:
        raise ValueError(f"{STATE_FILE} version must be 2 or {STATE_VERSION}")
    if data["status"] not in {"idle", "queued", "running", "validating", "completed", "failed", "aborted"}:
        raise ValueError(f"{STATE_FILE} status is invalid")
    for key in ("requested_waves", "attempted_waves", "successful_waves", "remaining_waves", "current_wave"):
        if not isinstance(data[key], int) or data[key] < 0:
            raise ValueError(f"{STATE_FILE} {key} must be an integer >= 0")
    if data["successful_waves"] > data["requested_waves"]:
        raise ValueError(f"{STATE_FILE} successful_waves cannot exceed requested_waves")
    if data["remaining_waves"] > data["requested_waves"]:
        raise ValueError(f"{STATE_FILE} remaining_waves cannot exceed requested_waves")
    if data["successful_waves"] + data["remaining_waves"] != data["requested_waves"]:
        raise ValueError(f"{STATE_FILE} requested_waves must equal successful_waves + remaining_waves")
    if data["attempted_waves"] < data["successful_waves"]:
        raise ValueError(f"{STATE_FILE} attempted_waves cannot be less than successful_waves")
    if not isinstance(data["baseline_dirty_paths"], list) or any(
        not isinstance(path, str) for path in data["baseline_dirty_paths"]
    ):
        raise ValueError(f"{STATE_FILE} baseline_dirty_paths must be a list of strings")
    if not isinstance(data["baseline_snapshot"], dict) or any(
        not isinstance(path, str) or not isinstance(digest, str)
        for path, digest in data["baseline_snapshot"].items()
    ):
        raise ValueError(f"{STATE_FILE} baseline_snapshot must be an object of path->digest strings")
    if data["status"] != "idle":
        if not isinstance(data["request_id"], str) or not data["request_id"]:
            raise ValueError(f"{STATE_FILE} request_id must be a non-empty string outside idle state")
        if not isinstance(data["request_sha256"], str) or not data["request_sha256"]:
            raise ValueError(f"{STATE_FILE} request_sha256 must be set outside idle state")
    if data["worktree_path"] != str(project_root):
        raise ValueError(f"{STATE_FILE} worktree_path mismatch: {data['worktree_path']}")
    return data


def persist_state(project_root: Path, state: dict[str, object]) -> None:
    atomic_write_text(project_root / STATE_FILE, json.dumps(state, ensure_ascii=False, indent=2) + "\n")


def load_stop_hook_timeout_seconds(project_root: Path) -> int:
    hooks_path = project_root / HOOKS_FILE
    if not hooks_path.exists():
        return DEFAULT_STOP_HOOK_TIMEOUT_SECONDS
    try:
        data = json.loads(hooks_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return DEFAULT_STOP_HOOK_TIMEOUT_SECONDS
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return DEFAULT_STOP_HOOK_TIMEOUT_SECONDS
    stop_entries = hooks.get("Stop")
    if not isinstance(stop_entries, list):
        return DEFAULT_STOP_HOOK_TIMEOUT_SECONDS
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
    return DEFAULT_STOP_HOOK_TIMEOUT_SECONDS


def parse_utc_timestamp(value: object) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def is_stale_active_state(project_root: Path, state: dict[str, object]) -> bool:
    if state["status"] not in {"running", "validating"}:
        return False
    updated_at = parse_utc_timestamp(state.get("updated_at"))
    if updated_at is None:
        return True
    stale_after_seconds = load_stop_hook_timeout_seconds(project_root)
    age_seconds = (dt.datetime.now(dt.timezone.utc) - updated_at).total_seconds()
    return age_seconds >= stale_after_seconds


def compute_active_wave_paths(
    project_root: Path,
    baseline_snapshot: dict[str, str],
    policy: dict[str, object],
) -> list[str]:
    current_snapshot = capture_worktree_snapshot(project_root, policy)
    active_paths: list[str] = []
    for path in sorted(set(current_snapshot) | set(baseline_snapshot)):
        if baseline_snapshot.get(path) != current_snapshot.get(path):
            active_paths.append(path)
    return active_paths


def classify_wave_targets(
    project_root: Path,
    baseline_snapshot: dict[str, str],
    policy: dict[str, object],
) -> tuple[list[str], list[str], list[str]]:
    active_wave_paths = compute_active_wave_paths(project_root, baseline_snapshot, policy)
    allowed_targets = set(policy["allowed_wave_edit_targets"])
    required_targets = set(policy["required_wave_edit_targets"])
    disallowed = [path for path in active_wave_paths if path not in allowed_targets]
    missing_required = [path for path in sorted(required_targets) if path not in active_wave_paths]
    return (active_wave_paths, disallowed, missing_required)


def require_exact_verify(project_root: Path, policy: dict[str, object]) -> tuple[bool, str]:
    command = str(policy["verification"]["exact_command"])
    completed = run_shell_command(project_root, command)
    if completed.returncode != 0:
        details = completed.stderr.strip() or completed.stdout.strip() or "exact verification failed"
        return (False, f"exact verify command failed: {command}; {details}")
    return (True, "")


def append_wave_history_entry(project_root: Path, policy: dict[str, object], entry: str) -> None:
    log_path = project_root / str(policy["log_file"])
    existing_text = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    history_match = re.search(r"## Wave History\n\n(.*)\Z", existing_text, re.S)
    if history_match is None:
        prefix = existing_text.rstrip() or "# Optimization Log\n\n## Wave History"
        rewritten = f"{prefix.rstrip()}\n\n{entry.strip()}\n"
    else:
        prefix = existing_text[: history_match.start(1)].rstrip()
        history_body = history_match.group(1).strip()
        next_history = f"{history_body}\n\n{entry.strip()}" if history_body else entry.strip()
        rewritten = f"{prefix}\n\n{next_history}\n"
    atomic_write_text(log_path, rewritten)


def build_diagnostic_log_entry(*, wave_label: str, summary: str, notes: str) -> str:
    return "\n".join(
        [
            f"### {wave_label}",
            "",
            "- Compatibility benchmark command: `n/a`",
            "- Decision benchmark command: `n/a`",
            "- Compatibility result: `n/a`",
            "- Decision result: `n/a`",
            "- New best: `no`",
            f"- Notes: {summary} {notes}".strip(),
        ]
    )


def build_missing_required_notes(missing_required: list[str], active_wave_paths: list[str]) -> str:
    if not active_wave_paths:
        return (
            "No file changed relative to the campaign baseline. "
            f"Next wave should make a concrete edit to: {', '.join(missing_required)}."
        )
    return (
        "Active wave changes did not include required target(s) "
        f"({', '.join(missing_required)}). Changed paths: {', '.join(active_wave_paths)}."
    )


def build_next_wave_prompt(project_root: Path, request: dict[str, object], state: dict[str, object]) -> str:
    policy, _policy_sha = load_project_policy(project_root)
    request_text = json.dumps(request, ensure_ascii=False, indent=2)
    state_text = json.dumps(state, ensure_ascii=False, indent=2, default=str)
    policy_text = json.dumps(policy, ensure_ascii=False, indent=2)
    context_parts = []
    for relative_path in policy["prompt_context_files"]:
        context_parts.append(f"[{relative_path}]\n{read_required_text(project_root, relative_path)}")
    last_result = state["last_result"] or "none yet"
    allowed_targets = ", ".join(policy["allowed_wave_edit_targets"])
    required_targets = ", ".join(policy["required_wave_edit_targets"]) or "none"
    benchmark_policy = policy["benchmark"]
    wave_number = int(state["current_wave"])
    benchmark_guidance = (
        "- Heavy compatibility benchmark policy: this is wave 1, so one full compatibility command "
        f"may be run if needed to establish campaign evidence: `{benchmark_policy['compatibility_command']}`.\n"
        if wave_number == 1
        else "- Heavy compatibility benchmark policy: do not run the full compatibility command by default on this wave. "
        f"{benchmark_policy['subsequent_wave_guidance']}\n"
    )
    return (
        f"Continue hook-driven wave campaign `{state['request_id']}`.\n"
        f"Wave {state['current_wave']} of {state['requested_waves']} is active now.\n"
        f"Remaining waves after this one: {max(int(state['remaining_waves']) - 1, 0)}.\n"
        "Execute exactly one optimization wave in this turn, then stop naturally so the Stop hook can validate it.\n\n"
        f"[{REQUEST_FILE}]\n{request_text}\n\n"
        f"[{STATE_FILE}]\n{state_text}\n\n"
        f"[{PROJECT_POLICY_FILE}]\n{policy_text}\n\n"
        + "\n\n".join(context_parts)
        + "\n\n"
        f"[last_result]\n{last_result}\n\n"
        "Constraints for this turn:\n"
        "- Execute exactly one wave only.\n"
        f"- Allowed wave edit targets: {allowed_targets}.\n"
        f"- Required wave edit targets for a normal wave: {required_targets}.\n"
        f"{benchmark_guidance}"
        "- Keep project-specific constraints from the prompt context.\n"
        "- Do not start another Codex process yourself; the Stop hook will continue the campaign if waves remain.\n"
    )


def materialize_wave_prompt(project_root: Path, request: dict[str, object], state: dict[str, object]) -> Path:
    prompt_text = build_next_wave_prompt(project_root, request, state)
    prompt_path = project_root / PROMPT_DIR / str(request["request_id"]) / f"wave-{state['current_wave']}.md"
    atomic_write_text(prompt_path, prompt_text)
    return prompt_path


def continue_command_env(
    project_root: Path,
    request: dict[str, object],
    state: dict[str, object],
    prompt_path: Path,
) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "PROJECT_ROOT": str(project_root),
            "REQUEST_ID": str(request["request_id"]),
            "REQUEST_FILE": str(project_root / REQUEST_FILE),
            "STATE_FILE": str(project_root / STATE_FILE),
            "PROJECT_POLICY_FILE": str(project_root / PROJECT_POLICY_FILE),
            "TASK_FILE": str(prompt_path),
            "WAVE_NUMBER": str(state["current_wave"]),
            "REQUESTED_WAVES": str(state["requested_waves"]),
            "REMAINING_WAVES": str(state["remaining_waves"]),
        }
    )
    return env


def make_stop_state(
    project_root: Path,
    state: dict[str, object],
    *,
    status: str,
    reason: str,
    request_id: Optional[str] = None,
) -> dict[str, object]:
    updated = dict(state)
    updated["status"] = status
    updated["last_stop_reason"] = reason
    updated["updated_at"] = now_utc()
    if request_id is not None:
        updated["request_id"] = request_id
    persist_state(project_root, updated)
    return updated


def fail_campaign(project_root: Path, state: dict[str, object], reason: str) -> int:
    failed_state = dict(state)
    if failed_state["status"] in ACTIVE_STATUSES:
        failed_state["attempted_waves"] += 1
        failed_state["last_result"] = {
            "kind": "campaign_failed",
            "wave": f"{failed_state['request_id']}/wave-{failed_state['current_wave']}",
            "summary": reason,
            "benchmark_result": None,
        }
    failed_state = make_stop_state(project_root, failed_state, status="failed", reason=reason)
    append_journal(
        project_root,
        {
            "timestamp": now_utc(),
            "request_id": failed_state["request_id"],
            "wave": failed_state["current_wave"],
            "event_type": "campaign_failed",
            "git_head": safe_git_head(project_root),
            "branch": safe_git_branch(project_root),
            "changed_paths": safe_git_changed_paths(project_root),
            "validation_result": "failed",
            "benchmark_result": None,
            "budget_consumed": False,
            "stop_reason": reason,
        },
    )
    emit_block(reason=reason, stop_reason="campaign_failed", system_message=reason)
    return 0


def block_current_wave(project_root: Path, state: dict[str, object], reason: str, *, stop_reason: str) -> int:
    blocked_state = dict(state)
    blocked_state["status"] = "running"
    blocked_state["last_stop_reason"] = reason
    blocked_state["updated_at"] = now_utc()
    persist_state(project_root, blocked_state)
    append_journal(
        project_root,
        {
            "timestamp": now_utc(),
            "request_id": state["request_id"],
            "wave": state["current_wave"],
            "event_type": "wave_blocked",
            "git_head": safe_git_head(project_root),
            "branch": safe_git_branch(project_root),
            "changed_paths": safe_git_changed_paths(project_root),
            "validation_result": "blocked",
            "benchmark_result": None,
            "budget_consumed": False,
            "stop_reason": reason,
        },
    )
    emit_block(reason=reason, stop_reason=stop_reason, system_message=reason)
    return 0


def next_wave_state(state: dict[str, object], *, last_result: dict[str, object]) -> dict[str, object]:
    next_state = dict(state)
    next_state["attempted_waves"] += 1
    next_state["successful_waves"] += 1
    next_state["remaining_waves"] -= 1
    next_state["last_result"] = last_result
    next_state["last_stop_reason"] = None
    next_state["current_wave"] = (
        next_state["successful_waves"] + 1 if next_state["remaining_waves"] > 0 else next_state["current_wave"]
    )
    next_state["updated_at"] = now_utc()
    next_state["status"] = "completed" if next_state["remaining_waves"] == 0 else "running"
    return next_state


def emit_next_wave_block(
    project_root: Path,
    request: dict[str, object],
    next_state: dict[str, object],
    *,
    validated_wave: int,
    diagnosis_only: bool,
) -> None:
    prompt_path = materialize_wave_prompt(project_root, request, next_state)
    reason = (
        f"Validated request {request['request_id']} wave {validated_wave}; "
        f"remaining_waves={next_state['remaining_waves']}. Continue now with wave "
        f"{next_state['current_wave']} using prompt file {prompt_path}. Read that prompt file "
        "and execute exactly one wave before stopping naturally."
    )
    emit_block(
        reason=reason,
        stop_reason="wave_diagnostic_continue" if diagnosis_only else "wave_validated_continue",
        system_message="Wave validated; continuing hook-driven request campaign.",
    )


def complete_diagnostic_wave(
    project_root: Path,
    request: dict[str, object],
    policy: dict[str, object],
    state: dict[str, object],
    *,
    summary: str,
    notes: str,
    changed_paths: list[str],
) -> int:
    wave_label = f"{state['request_id']}/wave-{state['current_wave']}"
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
                "changed_paths": changed_paths,
            },
            "benchmark_result": None,
            "new_best": False,
        },
    )
    persist_state(project_root, next_state)
    append_journal(
        project_root,
        {
            "timestamp": now_utc(),
            "request_id": state["request_id"],
            "wave": state["current_wave"],
            "event_type": "wave_diagnostic_no_required_change",
            "git_head": git_head(project_root),
            "branch": git_branch(project_root),
            "changed_paths": changed_paths,
            "validation_result": "diagnosis_only",
            "benchmark_result": None,
            "budget_consumed": True,
            "stop_reason": summary,
        },
    )
    if next_state["remaining_waves"] > 0:
        emit_next_wave_block(
            project_root,
            request,
            next_state,
            validated_wave=int(state["current_wave"]),
            diagnosis_only=True,
        )
    return 0


def complete_verified_wave(
    project_root: Path,
    request: dict[str, object],
    policy: dict[str, object],
    state: dict[str, object],
) -> int:
    wave_label = f"{state['request_id']}/wave-{state['current_wave']}"
    command = str(policy["verification"]["exact_command"])
    next_state = next_wave_state(
        state,
        last_result={
            "kind": "wave_exact_verified",
            "wave": wave_label,
            "verification_command": command,
            "benchmark_result": None,
        },
    )
    persist_state(project_root, next_state)
    append_journal(
        project_root,
        {
            "timestamp": now_utc(),
            "request_id": state["request_id"],
            "wave": state["current_wave"],
            "event_type": "wave_exact_verified",
            "git_head": safe_git_head(project_root),
            "branch": safe_git_branch(project_root),
            "changed_paths": safe_git_changed_paths(project_root),
            "validation_result": "exact_verified",
            "benchmark_result": None,
            "budget_consumed": True,
            "stop_reason": None,
        },
    )
    if next_state["remaining_waves"] > 0:
        emit_next_wave_block(
            project_root,
            request,
            next_state,
            validated_wave=int(state["current_wave"]),
            diagnosis_only=False,
        )
    return 0


def validate_active_bindings(
    project_root: Path,
    request: dict[str, object],
    request_sha: str,
    policy_sha: str,
    state: dict[str, object],
) -> Optional[str]:
    if state.get("version") != STATE_VERSION:
        return f"{STATE_FILE} must be reinitialized to version {STATE_VERSION}; run `python3 .codex/wave_control_init.py`"
    if request["request_id"] != state["request_id"]:
        return f"active request_id mismatch: state={state['request_id']} request={request['request_id']}"
    if request_sha != state["request_sha256"]:
        return f"{REQUEST_FILE} changed during an active campaign"
    if policy_sha != state.get("project_policy_sha256"):
        return f"{PROJECT_POLICY_FILE} changed during an active campaign; run `python3 .codex/wave_control_init.py`"
    current_branch = git_branch(project_root)
    current_head = git_head(project_root)
    if current_branch != state["base_branch"]:
        return f"campaign branch changed from {state['base_branch']} to {current_branch}"
    if current_head != state["base_head"]:
        return f"campaign HEAD changed from {state['base_head']} to {current_head}"
    if state["worktree_path"] != str(project_root):
        return f"campaign worktree changed from {state['worktree_path']} to {project_root}"
    return None


def main() -> int:
    payload = load_hook_payload()
    cwd = Path(str(payload.get("cwd", os.getcwd()))).resolve()
    project_root = resolve_project_root(cwd)
    lock_path = project_root / LOCK_FILE
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with lock_path.open("w", encoding="utf-8") as lockf:
            fcntl.flock(lockf, fcntl.LOCK_EX)

            try:
                state = load_state(project_root)
                request, request_sha = load_request(project_root)
                policy, policy_sha = load_project_policy(project_root)
            except ValueError as exc:
                emit_block(reason=str(exc), stop_reason="controller_state_invalid")
                return 0

            if request is None or request_sha is None:
                if state["status"] in ACTIVE_STATUSES:
                    return fail_campaign(project_root, state, f"active campaign requires {REQUEST_FILE}")
                return 0

            if state["status"] in TERMINAL_STATUSES:
                if state["request_id"] == request["request_id"] and state["status"] == "completed":
                    return 0
                emit_block(
                    reason=(
                        f"Request {request['request_id']} is not initialized in {STATE_FILE}. "
                        "Run `python3 .codex/wave_control_init.py` before starting wave 1."
                    ),
                    stop_reason="campaign_requires_initialization",
                )
                return 0

            if state["status"] == "queued":
                emit_block(
                    reason=(
                        f"Request {request['request_id']} is queued for wave {state['current_wave']}; "
                        "run `python3 .codex/wave_start.py` to start the hook-driven foreground campaign."
                    ),
                    stop_reason="no_running_wave",
                )
                return 0
            if state["status"] == "validating":
                emit_block(
                    reason=(
                        f"Request {request['request_id']} wave {state['current_wave']} is already validating; "
                        "wait for validation to finish or recover by rerunning initialization if it is stale."
                    ),
                    stop_reason="wave_validation_in_progress",
                )
                return 0
            if state["status"] != "running":
                return fail_campaign(
                    project_root,
                    state,
                    f"unexpected controller state before Stop validation: status={state['status']}",
                )

            binding_error = validate_active_bindings(project_root, request, request_sha, policy_sha, state)
            if binding_error is not None:
                return fail_campaign(project_root, state, binding_error)

            validating_state = dict(state)
            validating_state["status"] = "validating"
            validating_state["updated_at"] = now_utc()
            persist_state(project_root, validating_state)

            active_wave_paths, disallowed_paths, missing_required = classify_wave_targets(
                project_root,
                validating_state["baseline_snapshot"],
                policy,
            )
            if disallowed_paths:
                allowed_reason = (
                    "disallowed modified files: "
                    + ", ".join(disallowed_paths)
                    + "; allowed wave edit targets are "
                    + ", ".join(policy["allowed_wave_edit_targets"])
                )
                return block_current_wave(project_root, validating_state, allowed_reason, stop_reason="disallowed_wave_files")

            if missing_required:
                if not policy["diagnosis_only"]["enabled"]:
                    reason = "missing required wave edit target(s): " + ", ".join(missing_required)
                    return block_current_wave(project_root, validating_state, reason, stop_reason="missing_required_wave_files")
                summary = "missing required wave edit target(s): " + ", ".join(missing_required)
                notes = build_missing_required_notes(missing_required, active_wave_paths)
                return complete_diagnostic_wave(
                    project_root,
                    request,
                    policy,
                    validating_state,
                    summary=summary,
                    notes=notes,
                    changed_paths=safe_git_changed_paths(project_root),
                )

            exact_verify_ok, exact_verify_reason = require_exact_verify(project_root, policy)
            if not exact_verify_ok:
                return block_current_wave(project_root, validating_state, exact_verify_reason, stop_reason="exact_verify_failed")
            return complete_verified_wave(project_root, request, policy, validating_state)
    except Exception as exc:
        current_state = locals().get("state")
        reason = f"Stop hook crashed: {type(exc).__name__}: {exc}"
        if isinstance(current_state, dict):
            return fail_campaign(project_root, current_state, reason)
        emit_block(reason=reason, stop_reason="stop_hook_crashed")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
