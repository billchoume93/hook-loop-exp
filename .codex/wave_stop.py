#!/usr/bin/env python3
import json
import re
import sys
from pathlib import Path

import fcntl

COUNT_FILE = "count.md"
LOCK_FILE = ".codex/wave.lock"
COUNT_RE = re.compile(r"wave_count\s*=\s*(\d+)")


def emit(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False))


def resolve_project_root(cwd: Path) -> Path:
    for directory in (cwd, *cwd.parents):
        if (directory / ".codex" / "hooks.json").exists():
            return directory
        if (directory / COUNT_FILE).exists():
            return directory
    return cwd


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
