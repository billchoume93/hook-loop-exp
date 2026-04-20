#!/usr/bin/env python3
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional, Tuple

ALLOWED_WAVE_EDIT_TARGETS = {
    "algorithms/pi_algo_improve-by-agent.py",
    "log.md",
}
ALLOWED_CONTROL_PLANE_DIRTY_TARGETS = {
    ".codex/hooks.json",
    ".codex/wave-control-init.py",
    ".codex/wave_control_init.py",
    ".codex/wave_stop.py",
    "README.md",
    "docs/init_prompt.md",
    "docs/task.md",
    "tools/verify_pi_bin.py",
}
REQUEST_FILE = ".codex/wave_request.json"
STATE_FILE = ".codex/wave_state.json"
LOCK_FILE = ".codex/wave.lock"
LOCAL_JOURNAL_FILE = ".codex/local/wave_events.jsonl"
PROMPT_DIR = ".codex/local/prompts"
TASK_FILE = "docs/task.md"
INIT_PROMPT_FILE = "docs/init_prompt.md"
LOG_FILE = "log.md"
REFERENCE_FILE = "reference/pi_65536.bin"
VERIFY_SCRIPT = "tools/verify_pi_bin.py"
ORG_SCRIPT = "algorithms/pi_algo_org.py"
IMPROVE_SCRIPT = "algorithms/pi_algo_improve-by-agent.py"
FIXED_VERIFY_COMMAND = f"python3 {IMPROVE_SCRIPT} 65536 | python3 {VERIFY_SCRIPT}"
FIXED_BENCHMARK_COMMAND = "python3 run_verify_timed.py 65536 --repeats 1"
FIXED_DIGITS = 65536
ACTIVE_STATUSES = {"queued", "running", "validating"}
TERMINAL_STATUSES = {"idle", "completed", "failed", "aborted"}
TRUSTED_BENCHMARK_ROUNDS = (("org", "improve"), ("improve", "org"), ("org", "improve"))
STOP_HOOK_TIMEOUT_SECONDS = 180
STOP_HOOK_SAFETY_MARGIN_SECONDS = 15
IGNORED_PATH_PREFIXES = (
    "__pycache__/",
    "algorithms/__pycache__/",
    "tools/__pycache__/",
    ".codex/local/",
)
IGNORED_PATHS = {
    LOCK_FILE,
    REQUEST_FILE,
    STATE_FILE,
}
CURRENT_BEST_PATTERN = re.compile(r"^- execution ratio vs `org`: (.+)$", re.MULTILINE)


def emit(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False))


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
    env = os.environ.copy()
    return subprocess.run(
        ["sh", "-lc", command],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def run_python_command(project_root: Path, args: list[str], *, input_text: Optional[str] = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=project_root,
        check=False,
        capture_output=True,
        text=True,
        input=input_text,
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


def capture_worktree_snapshot(project_root: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for relative_path in git_changed_paths(project_root):
        abs_path = project_root / relative_path
        snapshot[relative_path] = sha256_file_hex(abs_path) if abs_path.exists() else "missing"
    return snapshot


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


def read_required_text(project_root: Path, relative_path: str) -> str:
    path = project_root / relative_path
    return path.read_text(encoding="utf-8").strip()


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
    if set(data) != required_keys:
        raise ValueError(f"{REQUEST_FILE} keys must be exactly {sorted(required_keys)}")
    if data["version"] != 2:
        raise ValueError(f"{REQUEST_FILE} version must be 2")
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


def default_state(project_root: Path) -> dict[str, object]:
    return {
        "version": 2,
        "request_id": None,
        "request_sha256": None,
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
    if data.get("version") == 2 and "baseline_snapshot" not in data:
        data = dict(data)
        data["baseline_snapshot"] = {}
    required_keys = {
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
    if set(data) != required_keys:
        raise ValueError(f"{STATE_FILE} keys must be exactly {sorted(required_keys)}")
    if data["version"] != 2:
        raise ValueError(f"{STATE_FILE} version must be 2")
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


def compare_exact_bytes(actual_text: str, expected: bytes) -> tuple[bool, str]:
    actual = actual_text.encode("ascii")
    if len(actual) != len(expected):
        return (
            False,
            f"exact verification requires {len(expected) - 2} digits, got {len(actual) - 2}",
        )
    if actual == expected:
        return (True, "")
    for idx, (lhs, rhs) in enumerate(zip(actual, expected), start=1):
        if lhs != rhs:
            return (
                False,
                f"pi mismatch at byte {idx}: got {chr(lhs)!r}, expected {chr(rhs)!r}",
            )
    return (False, "pi mismatch against reference binary")


def compute_active_wave_paths(project_root: Path, baseline_snapshot: dict[str, str]) -> list[str]:
    current_snapshot = capture_worktree_snapshot(project_root)
    active_paths: list[str] = []
    for path in sorted(set(current_snapshot) | set(baseline_snapshot)):
        if baseline_snapshot.get(path) != current_snapshot.get(path):
            active_paths.append(path)
    return active_paths


def require_only_allowed_wave_targets(project_root: Path, baseline_snapshot: dict[str, str]) -> tuple[bool, str]:
    active_wave_paths = compute_active_wave_paths(project_root, baseline_snapshot)
    disallowed = [path for path in active_wave_paths if path not in ALLOWED_WAVE_EDIT_TARGETS]
    if disallowed:
        return (
            False,
            "disallowed modified files: "
            + ", ".join(disallowed)
            + "; only "
            + ", ".join(sorted(ALLOWED_WAVE_EDIT_TARGETS))
            + " may change during a normal wave",
        )
    if IMPROVE_SCRIPT not in active_wave_paths:
        return (
            False,
            f"expected a change in {IMPROVE_SCRIPT} before consuming a wave",
        )
    return (True, "")


def require_fixed_verify(project_root: Path) -> tuple[bool, str]:
    completed = run_shell_command(project_root, FIXED_VERIFY_COMMAND)
    if completed.returncode != 0:
        details = completed.stderr.strip() or completed.stdout.strip() or "verification failed"
        return (False, f"fixed verify command failed: {FIXED_VERIFY_COMMAND}; {details}")
    return (True, "")


def parse_fixed_benchmark_output(output: str) -> Tuple[dict[str, float], Optional[str]]:
    if "digits=65536" not in output:
        return ({}, f"benchmark output missing digits=65536: {FIXED_BENCHMARK_COMMAND}")
    if output.count("status=OK") < 2:
        return ({}, "benchmark output did not show both implementations passing verification")
    sections: dict[str, dict[str, str]] = {}
    current: Optional[str] = None
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
            sections.setdefault(current, {})
            continue
        if current is None or "=" not in line:
            continue
        key, value = line.split("=", 1)
        sections[current][key] = value
    for name in ("org", "improve"):
        if name not in sections or "execution_avg_ms" not in sections[name]:
            return ({}, f"benchmark output missing {name} execution_avg_ms")
    parsed = {
        "org_execution_ms": float(sections["org"]["execution_avg_ms"]),
        "improve_execution_ms": float(sections["improve"]["execution_avg_ms"]),
    }
    parsed["execution_ratio_vs_org"] = parsed["improve_execution_ms"] / parsed["org_execution_ms"]
    return (parsed, None)


def require_fixed_benchmark(project_root: Path) -> Tuple[bool, Optional[dict[str, float]], str]:
    completed = run_shell_command(project_root, FIXED_BENCHMARK_COMMAND)
    if completed.returncode != 0:
        details = completed.stderr.strip() or completed.stdout.strip() or "benchmark failed"
        return (False, None, f"fixed benchmark command failed: {FIXED_BENCHMARK_COMMAND}; {details}")
    parsed, error = parse_fixed_benchmark_output(completed.stdout)
    if error is not None:
        return (False, None, error)
    return (True, parsed, "")


def run_script_capture(project_root: Path, relative_path: str, digits: int) -> tuple[str, float]:
    started_ns = time.perf_counter_ns()
    completed = run_python_command(project_root, [relative_path, str(digits)])
    ended_ns = time.perf_counter_ns()
    if completed.returncode != 0:
        details = completed.stderr.strip() or completed.stdout.strip() or "script failed"
        raise RuntimeError(f"{relative_path} failed: {details}")
    return (completed.stdout.strip(), (ended_ns - started_ns) / 1_000_000)


def run_trusted_benchmark(project_root: Path, reference_bytes: bytes) -> Tuple[Optional[dict[str, float]], Optional[str]]:
    round_ratios: list[float] = []
    org_values: list[float] = []
    improve_values: list[float] = []
    scripts = {"org": ORG_SCRIPT, "improve": IMPROVE_SCRIPT}
    try:
        for order in TRUSTED_BENCHMARK_ROUNDS:
            round_times: dict[str, float] = {}
            for name in order:
                output, execution_ms = run_script_capture(project_root, scripts[name], FIXED_DIGITS)
                ok, reason = compare_exact_bytes(output, reference_bytes)
                if not ok:
                    raise RuntimeError(f"{name} exact verification failed during trusted benchmark: {reason}")
                round_times[name] = execution_ms
            org_values.append(round_times["org"])
            improve_values.append(round_times["improve"])
            round_ratios.append(round_times["improve"] / round_times["org"])
    except RuntimeError as exc:
        return (None, str(exc))
    return (
        {
            "org_execution_ms": statistics.median(org_values),
            "improve_execution_ms": statistics.median(improve_values),
            "execution_ratio_vs_org": statistics.median(round_ratios),
        },
        None,
    )


def should_run_trusted_benchmark(
    compatibility_result: dict[str, float],
    *,
    started_at: float,
) -> tuple[bool, Optional[str]]:
    elapsed = time.perf_counter() - started_at
    remaining_budget = STOP_HOOK_TIMEOUT_SECONDS - STOP_HOOK_SAFETY_MARGIN_SECONDS - elapsed
    estimated_trusted_seconds = (
        len(TRUSTED_BENCHMARK_ROUNDS)
        * (compatibility_result["org_execution_ms"] + compatibility_result["improve_execution_ms"])
        / 1000.0
    )
    if remaining_budget <= 0:
        return (
            False,
            f"trusted benchmark skipped: no stop-hook budget remains (elapsed={elapsed:.3f}s)",
        )
    if estimated_trusted_seconds > remaining_budget:
        return (
            False,
            "trusted benchmark skipped: estimated "
            f"{estimated_trusted_seconds:.3f}s exceeds remaining stop-hook budget "
            f"{remaining_budget:.3f}s",
        )
    return (True, None)


def parse_current_best_ratio(log_text: str) -> Optional[float]:
    match = CURRENT_BEST_PATTERN.search(log_text)
    if match is None:
        return None
    value = match.group(1).strip()
    if value == "n/a":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def build_log_entry(
    *,
    wave_label: str,
    compatibility: dict[str, float],
    trusted: Optional[dict[str, float]],
    new_best: bool,
    notes: str,
) -> str:
    trusted_command = "controller median of order-balanced direct runs (org/improve, improve/org, org/improve)"
    lines = [
        f"### {wave_label}",
        "",
        f"- Compatibility benchmark command: `{FIXED_BENCHMARK_COMMAND}`",
        f"- Decision benchmark command: `{trusted_command if trusted else 'n/a'}`",
        f"- Compatibility `improve` execution_ms: `{compatibility['improve_execution_ms']:.3f}`",
        f"- Compatibility `org` execution_ms: `{compatibility['org_execution_ms']:.3f}`",
        f"- Compatibility execution ratio vs `org`: `{compatibility['execution_ratio_vs_org']:.6f}`",
    ]
    if trusted is None:
        lines.extend(
            [
                "- Decision `improve` execution_ms: `pending controller`",
                "- Decision `org` execution_ms: `pending controller`",
                "- Decision execution ratio vs `org`: `pending controller`",
            ]
        )
    else:
        lines.extend(
            [
                f"- Decision `improve` execution_ms: `{trusted['improve_execution_ms']:.3f}`",
                f"- Decision `org` execution_ms: `{trusted['org_execution_ms']:.3f}`",
                f"- Decision execution ratio vs `org`: `{trusted['execution_ratio_vs_org']:.6f}`",
            ]
        )
    lines.extend([f"- New best: `{'yes' if new_best else 'no'}`", f"- Notes: {notes}"])
    return "\n".join(lines) + "\n"


def update_log(
    project_root: Path,
    *,
    wave_label: str,
    compatibility: dict[str, float],
    trusted: Optional[dict[str, float]],
    notes: str,
) -> bool:
    log_path = project_root / LOG_FILE
    existing_text = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    current_best_ratio = parse_current_best_ratio(existing_text)
    trusted_ratio = None if trusted is None else trusted["execution_ratio_vs_org"]
    new_best = trusted_ratio is not None and (current_best_ratio is None or trusted_ratio < current_best_ratio)
    if new_best:
        current_best_block = (
            "## Current Best\n\n"
            f"- Wave: {wave_label}\n"
            f"- Compatibility benchmark command: `{FIXED_BENCHMARK_COMMAND}`\n"
            "- Decision benchmark command: "
            "`controller median of order-balanced direct runs (org/improve, improve/org, org/improve)`\n"
            f"- `improve` execution_ms: {trusted['improve_execution_ms']:.3f}\n"
            f"- `org` execution_ms: {trusted['org_execution_ms']:.3f}\n"
            f"- execution ratio vs `org`: {trusted['execution_ratio_vs_org']:.6f}\n"
            "- New best: yes\n"
            f"- Notes: {notes}\n"
        )
    else:
        current_best_match = re.search(r"## Current Best\n\n.*?\n## Wave History\n", existing_text, re.S)
        if current_best_match is not None:
            current_best_block = current_best_match.group(0).replace("## Wave History\n", "").strip() + "\n"
        else:
            current_best_block = (
                "## Current Best\n\n"
                "- Wave: none yet\n"
                f"- Compatibility benchmark command: `{FIXED_BENCHMARK_COMMAND}`\n"
                "- Decision benchmark command: "
                "`controller median of order-balanced direct runs (org/improve, improve/org, org/improve)`\n"
                "- `improve` execution_ms: n/a\n"
                "- `org` execution_ms: n/a\n"
                "- execution ratio vs `org`: n/a\n"
                "- New best: n/a\n"
                "- Notes: initialize this file on the first trusted new best\n"
            )
    entry = build_log_entry(
        wave_label=wave_label,
        compatibility=compatibility,
        trusted=trusted,
        new_best=new_best,
        notes=notes,
    )
    history_match = re.search(r"## Wave History\n\n(.*)\Z", existing_text, re.S)
    history_body = "" if history_match is None else history_match.group(1).strip()
    if history_body:
        history_body = history_body + "\n\n" + entry.strip() + "\n"
    else:
        history_body = entry.strip() + "\n"
    current_best_text = current_best_block
    rewritten = (
        "# Optimization Log\n\n"
        "This file records trusted benchmark results across request-driven waves.\n\n"
        f"{current_best_text}\n"
        "## Wave History\n\n"
        f"{history_body}"
    )
    atomic_write_text(log_path, rewritten)
    return new_best


def build_next_wave_prompt(project_root: Path, request: dict[str, object], state: dict[str, object]) -> str:
    task_text = read_required_text(project_root, TASK_FILE)
    init_prompt_text = read_required_text(project_root, INIT_PROMPT_FILE)
    log_text = read_required_text(project_root, LOG_FILE)
    request_text = json.dumps(request, ensure_ascii=False, indent=2)
    last_result = state["last_result"] or "none yet"
    return (
        f"Continue request-driven wave campaign `{state['request_id']}`.\n"
        f"Wave {state['current_wave']} of {state['requested_waves']} is next.\n"
        f"Remaining waves after this one: {max(state['remaining_waves'] - 1, 0)}.\n"
        "Execute exactly one optimization wave in this turn.\n"
        "Before starting, read the request, task, init prompt, and log again.\n\n"
        f"[{REQUEST_FILE}]\n{request_text}\n\n"
        f"[{INIT_PROMPT_FILE}]\n{init_prompt_text}\n\n"
        f"[{TASK_FILE}]\n{task_text}\n\n"
        f"[{LOG_FILE}]\n{log_text}\n\n"
        f"[last_result]\n{last_result}\n\n"
        "Constraints for this turn:\n"
        "- Execute exactly one wave only.\n"
        "- Read .codex/wave_request.json, docs/task.md, docs/init_prompt.md, and log.md before editing.\n"
        "- During a normal wave, only modify algorithms/pi_algo_improve-by-agent.py and optionally log.md.\n"
        "- Keep the implementation single-core.\n"
        "- At the end of the wave, write a short summary and stop naturally.\n"
        "- Do not start another wave by yourself; the Stop hook will decide.\n"
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
            "TASK_FILE": str(prompt_path),
            "WAVE_NUMBER": str(state["current_wave"]),
            "REQUESTED_WAVES": str(state["requested_waves"]),
            "REMAINING_WAVES": str(state["remaining_waves"]),
        }
    )
    return env


def launch_continue_command(project_root: Path, request: dict[str, object], state: dict[str, object]) -> int:
    prompt_path = materialize_wave_prompt(project_root, request, state)
    env = continue_command_env(project_root, request, state, prompt_path)
    remaining_after_launch = max(int(state["remaining_waves"]) - 1, 0)
    try:
        subprocess.Popen(
            ["sh", "-lc", str(request["continue_command"])],
            cwd=project_root,
            env=env,
            start_new_session=True,
        )
    except OSError as exc:
        emit(
            {
                "continue": False,
                "stopReason": "Continue command failed to launch",
                "systemMessage": (
                    f"Failed to launch continue_command for request {request['request_id']}: {exc}"
                ),
            }
        )
        return 0
    emit(
        {
            "continue": False,
            "stopReason": "Launched next wave",
            "systemMessage": (
                f"Launched request {request['request_id']} wave {state['current_wave']}/"
                f"{state['requested_waves']} using {prompt_path}; "
                f"remaining_waves_after_this={remaining_after_launch}."
            ),
        }
    )
    return 0


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


def fail_run(project_root: Path, state: dict[str, object], reason: str, *, request_id: Optional[str] = None) -> int:
    failed_state = dict(state)
    if failed_state["status"] in ACTIVE_STATUSES:
        failed_state["attempted_waves"] += 1
        failed_state["last_result"] = {
            "kind": "wave_failed",
            "wave": (
                f"{failed_state['request_id']}/wave-{failed_state['current_wave']}"
                if failed_state["request_id"] is not None and failed_state["current_wave"] > 0
                else None
            ),
            "summary": reason,
            "details": {"category": "controller", "reason": reason},
            "benchmark_result": None,
        }
    failed_state = make_stop_state(
        project_root,
        failed_state,
        status="failed",
        reason=reason,
        request_id=request_id,
    )
    append_journal(
        project_root,
        {
            "timestamp": now_utc(),
            "request_id": failed_state["request_id"],
            "wave": failed_state["current_wave"],
            "event_type": "wave_failed",
            "git_head": git_head(project_root),
            "branch": git_branch(project_root),
            "changed_paths": git_changed_paths(project_root),
            "validation_result": "failed",
            "benchmark_result": None,
            "budget_consumed": False,
            "stop_reason": reason,
        },
    )
    emit({"continue": False, "stopReason": reason, "systemMessage": reason})
    return 0


def bootstrap_run(project_root: Path, request: dict[str, object], request_sha: str) -> int:
    clean_ok, clean_reason = require_campaign_start_clean(project_root)
    if not clean_ok:
        idle_state = default_state(project_root)
        persist_state(project_root, idle_state)
        emit({"continue": False, "stopReason": "Campaign start rejected", "systemMessage": clean_reason})
        return 0
    started_at = now_utc()
    state = {
        "version": 2,
        "request_id": request["request_id"],
        "request_sha256": request_sha,
        "status": "queued",
        "requested_waves": request["requested_waves"],
        "attempted_waves": 0,
        "successful_waves": 0,
        "remaining_waves": request["requested_waves"],
        "current_wave": 1,
        "baseline_dirty_paths": sorted(
            path
            for path in git_changed_paths(project_root)
            if path in ALLOWED_CONTROL_PLANE_DIRTY_TARGETS
        ),
        "baseline_snapshot": capture_worktree_snapshot(project_root),
        "base_head": git_head(project_root),
        "base_branch": git_branch(project_root),
        "worktree_path": str(project_root),
        "last_result": None,
        "last_stop_reason": None,
        "created_at": started_at,
        "updated_at": started_at,
    }
    persist_state(project_root, state)
    append_journal(
        project_root,
        {
            "timestamp": started_at,
            "request_id": request["request_id"],
            "wave": 0,
            "event_type": "run_initialized",
            "git_head": state["base_head"],
            "branch": state["base_branch"],
            "changed_paths": git_changed_paths(project_root),
            "validation_result": "n/a",
            "benchmark_result": None,
            "budget_consumed": False,
            "stop_reason": None,
        },
    )
    return launch_continue_command(project_root, request, state)


def resume_failed_campaign(project_root: Path, request: dict[str, object], request_sha: str, state: dict[str, object]) -> int:
    resumed = dict(state)
    resumed["version"] = 2
    resumed["request_sha256"] = request_sha
    resumed["status"] = "queued"
    resumed["current_wave"] = resumed["successful_waves"] + 1 if resumed["remaining_waves"] > 0 else 0
    resumed["last_stop_reason"] = None
    resumed["updated_at"] = now_utc()
    persist_state(project_root, resumed)
    return launch_continue_command(project_root, request, resumed)


def validate_active_bindings(project_root: Path, request: dict[str, object], request_sha: str, state: dict[str, object]) -> Optional[str]:
    if request["request_id"] != state["request_id"]:
        return f"active request_id mismatch: state={state['request_id']} request={request['request_id']}"
    if request_sha != state["request_sha256"]:
        return f"{REQUEST_FILE} changed during an active campaign"
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
    hook_started_at = time.perf_counter()
    payload = load_hook_payload()
    cwd = Path(str(payload.get("cwd", os.getcwd()))).resolve()
    project_root = resolve_project_root(cwd)
    lock_path = project_root / LOCK_FILE
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    pending_continue: Optional[Tuple[dict[str, object], dict[str, object]]] = None

    with lock_path.open("w", encoding="utf-8") as lockf:
        fcntl.flock(lockf, fcntl.LOCK_EX)

        try:
            state = load_state(project_root)
            request, request_sha = load_request(project_root)
        except ValueError as exc:
            emit({"continue": False, "stopReason": "Controller state invalid", "systemMessage": str(exc)})
            return 0

        if request is None:
            if state["status"] in ACTIVE_STATUSES:
                return fail_run(project_root, state, f"active campaign requires {REQUEST_FILE}")
            emit(
                {
                    "continue": False,
                    "stopReason": "No active wave request",
                    "systemMessage": f"Set a new request_id and requested_waves in {REQUEST_FILE} to start a campaign.",
                }
            )
            return 0

        if state["status"] in TERMINAL_STATUSES:
            if state["request_id"] == request["request_id"] and state["status"] == "completed":
                emit(
                    {
                        "continue": False,
                        "stopReason": "Campaign already terminal",
                        "systemMessage": (
                            f"Request {request['request_id']} is already {state['status']}. "
                            f"Create a new request_id in {REQUEST_FILE} to start another campaign."
                        ),
                    }
                )
                return 0
            if state["request_id"] == request["request_id"] and state["status"] in {"failed", "aborted"}:
                emit(
                    {
                        "continue": False,
                        "stopReason": "Campaign requires initialization",
                        "systemMessage": (
                            f"Request {request['request_id']} is {state['status']}. "
                            f"Run `python3 .codex/wave-control-init.py` to reinitialize wave 1."
                        ),
                    }
                )
                return 0
            emit(
                {
                    "continue": False,
                    "stopReason": "Campaign requires initialization",
                    "systemMessage": (
                        f"Request {request['request_id']} is not initialized in {STATE_FILE}. "
                        f"Run `python3 .codex/wave-control-init.py` before starting wave 1."
                    ),
                }
            )
            return 0

        binding_error = validate_active_bindings(project_root, request, request_sha, state)
        if binding_error is not None:
            return fail_run(project_root, state, binding_error)

        validating_state = dict(state)
        validating_state["status"] = "validating"
        validating_state["updated_at"] = now_utc()
        persist_state(project_root, validating_state)

        allowed_ok, allowed_reason = require_only_allowed_wave_targets(
            project_root,
            validating_state["baseline_snapshot"],
        )
        if not allowed_ok:
            return fail_run(project_root, validating_state, allowed_reason)

        reference_bytes = (project_root / REFERENCE_FILE).read_bytes()
        improve_output, _ = run_script_capture(project_root, IMPROVE_SCRIPT, FIXED_DIGITS)
        exact_ok, exact_reason = compare_exact_bytes(improve_output, reference_bytes)
        if not exact_ok:
            return fail_run(project_root, validating_state, exact_reason)

        verify_ok, verify_reason = require_fixed_verify(project_root)
        if not verify_ok:
            return fail_run(project_root, validating_state, verify_reason)

        benchmark_ok, compatibility_result, benchmark_reason = require_fixed_benchmark(project_root)
        if not benchmark_ok or compatibility_result is None:
            return fail_run(project_root, validating_state, benchmark_reason)

        trusted_result = None
        trusted_error = None
        run_trusted, skip_reason = should_run_trusted_benchmark(
            compatibility_result,
            started_at=hook_started_at,
        )
        if run_trusted:
            trusted_result, trusted_error = run_trusted_benchmark(project_root, reference_bytes)
        else:
            trusted_error = skip_reason
        notes = (
            f"Controller-validated wave for request {state['request_id']}."
            if trusted_error is None
            else f"Controller-validated wave for request {state['request_id']}; trusted benchmark unavailable: {trusted_error}"
        )
        wave_label = f"{state['request_id']}/wave-{state['current_wave']}"
        new_best = update_log(
            project_root,
            wave_label=wave_label,
            compatibility=compatibility_result,
            trusted=trusted_result,
            notes=notes,
        )

        next_state = dict(validating_state)
        next_state["attempted_waves"] += 1
        next_state["successful_waves"] += 1
        next_state["remaining_waves"] -= 1
        next_state["last_result"] = {
            "wave": wave_label,
            "compatibility": compatibility_result,
            "trusted": trusted_result,
            "trusted_error": trusted_error,
            "new_best": new_best,
        }
        next_state["last_stop_reason"] = None
        next_state["current_wave"] = (
            next_state["successful_waves"] + 1 if next_state["remaining_waves"] > 0 else next_state["current_wave"]
        )
        next_state["updated_at"] = now_utc()
        next_state["status"] = "completed" if next_state["remaining_waves"] == 0 else "queued"
        persist_state(project_root, next_state)

        append_journal(
            project_root,
            {
                "timestamp": now_utc(),
                "request_id": state["request_id"],
                "wave": state["current_wave"],
                "event_type": "wave_valid_new_best" if new_best else "wave_valid_no_improvement",
                "git_head": git_head(project_root),
                "branch": git_branch(project_root),
                "changed_paths": git_changed_paths(project_root),
                "validation_result": "passed",
                "benchmark_result": {
                    "compatibility": compatibility_result,
                    "trusted": trusted_result,
                    "trusted_error": trusted_error,
                },
                "budget_consumed": True,
                "stop_reason": None,
            },
        )

        if next_state["remaining_waves"] == 0:
            emit(
                {
                    "continue": False,
                    "stopReason": "Completed final wave",
                    "systemMessage": f"Request {state['request_id']} completed all {state['requested_waves']} waves.",
                }
            )
            return 0

        pending_continue = (request, next_state)

    if pending_continue is not None:
        continue_request, continue_state = pending_continue
        return launch_continue_command(project_root, continue_request, continue_state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
