import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CODEX_ROOT = REPO_ROOT / ".codex"


def run_command(args: list[str], cwd: Path, *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )


def run_script(repo: Path, script_name: str, *, input_obj: dict[str, object] | None = None) -> subprocess.CompletedProcess[str]:
    input_text = None if input_obj is None else json.dumps(input_obj)
    return run_command([sys.executable, str(repo / ".codex" / script_name)], repo, input_text=input_text)


class WaveControlTests(unittest.TestCase):
    def make_repo(
        self,
        tmp: Path,
        *,
        requested_waves: int = 2,
        with_policy: bool = True,
        child_code: str | None = None,
        exact_command: str = "python3 verify_ok.py",
        with_config: bool = True,
        config_enabled: bool = True,
    ) -> Path:
        repo = tmp / "repo"
        (repo / ".codex").mkdir(parents=True)
        (repo / "docs").mkdir()
        for script in ("wave_stop.py", "wave_control_init.py", "wave_start.py", "wave_loop_run.py", "wave_recover.py"):
            shutil.copy(CODEX_ROOT / script, repo / ".codex" / script)
        if with_config:
            (repo / ".codex" / "config.toml").write_text(
                "[features]\n"
                f"codex_hooks = {'true' if config_enabled else 'false'}\n",
                encoding="utf-8",
            )
        (repo / ".codex" / "hooks.json").write_text(
            json.dumps(
                {
                    "hooks": {
                        "Stop": [
                            {
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "python3 .codex/wave_stop.py",
                                        "timeout": 120,
                                    }
                                ]
                            }
                        ]
                    }
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        if with_policy:
            (repo / ".codex" / "wave_project.json").write_text(
                json.dumps(
                    {
                        "version": 1,
                        "allowed_wave_edit_targets": ["target.txt", "log.md"],
                        "required_wave_edit_targets": ["target.txt"],
                        "ignored_paths": [
                            ".codex/wave.lock",
                            ".codex/wave_request.json",
                            ".codex/wave_state.json",
                        ],
                        "ignored_path_prefixes": [".codex/local/", ".codex/__pycache__/", "__pycache__/"],
                        "prompt_context_files": ["docs/init_prompt.md", "docs/task.md", "log.md"],
                        "log_file": "log.md",
                        "verification": {"exact_command": exact_command},
                        "benchmark": {
                            "compatibility_command": "python3 bench.py",
                            "decision_command_label": "test decision benchmark",
                            "heavy_command_policy": "first_wave_only",
                            "subsequent_wave_guidance": "Skip slow org benchmark after wave 1.",
                        },
                        "diagnosis_only": {"enabled": True},
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        (repo / ".codex" / "wave_request.json").write_text(
            json.dumps(
                {
                    "version": 2,
                    "request_id": "test-request",
                    "requested_waves": requested_waves,
                    "goal": "test hook-driven waves",
                    "continue_command": "python3 child.py",
                    "created_at": "2026-04-21T00:00:00Z",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        (repo / "docs" / "init_prompt.md").write_text("init prompt\n", encoding="utf-8")
        (repo / "docs" / "task.md").write_text("task prompt\n", encoding="utf-8")
        (repo / "log.md").write_text("# Optimization Log\n\n## Wave History\n\n", encoding="utf-8")
        (repo / "target.txt").write_text("baseline\n", encoding="utf-8")
        (repo / "verify_ok.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
        (repo / "child.py").write_text(
            child_code
            or "from pathlib import Path\nPath('target.txt').write_text('changed\\n', encoding='utf-8')\n",
            encoding="utf-8",
        )
        run_command(["git", "init"], repo)
        run_command(["git", "config", "user.email", "test@example.com"], repo)
        run_command(["git", "config", "user.name", "Test User"], repo)
        run_command(["git", "add", "."], repo)
        commit = run_command(["git", "commit", "-m", "initial"], repo)
        self.assertEqual(commit.returncode, 0, commit.stderr)
        return repo

    def read_state(self, repo: Path) -> dict[str, object]:
        return json.loads((repo / ".codex" / "wave_state.json").read_text(encoding="utf-8"))

    def write_state(self, repo: Path, state: dict[str, object]) -> None:
        (repo / ".codex" / "wave_state.json").write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    def set_running_state(self, repo: Path) -> dict[str, object]:
        state = self.read_state(repo)
        state["status"] = "running"
        state["last_stop_reason"] = None
        self.write_state(repo, state)
        return state

    def simulated_hook_completion_child(self) -> str:
        return "\n".join(
            [
                "import json",
                "from pathlib import Path",
                "Path('target.txt').write_text('changed\\n', encoding='utf-8')",
                "state_path = Path('.codex/wave_state.json')",
                "state = json.loads(state_path.read_text(encoding='utf-8'))",
                "state['attempted_waves'] += 1",
                "state['successful_waves'] += 1",
                "state['remaining_waves'] -= 1",
                "state['status'] = 'completed' if state['remaining_waves'] == 0 else 'running'",
                "state['current_wave'] = state['successful_waves'] + 1 if state['remaining_waves'] > 0 else state['current_wave']",
                "state['last_result'] = {'kind': 'simulated_stop_hook'}",
                "state_path.write_text(json.dumps(state, indent=2) + '\\n', encoding='utf-8')",
            ]
        )

    def test_initializer_requires_project_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = self.make_repo(Path(temp_dir), with_policy=False)
            result = run_script(repo, "wave_control_init.py")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(".codex/wave_project.json", result.stdout)

    def test_initializer_creates_v3_state_and_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = self.make_repo(Path(temp_dir))
            result = run_script(repo, "wave_control_init.py")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            state = self.read_state(repo)
            self.assertEqual(state["version"], 3)
            self.assertEqual(state["status"], "queued")
            self.assertIsInstance(state["project_policy_sha256"], str)
            self.assertIn("wave_start.py", result.stdout)
            self.assertTrue((repo / ".codex" / "local" / "prompts" / "test-request" / "wave-1.md").exists())

    def test_initializer_rebootstrap_same_queued_request_without_abort(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = self.make_repo(Path(temp_dir))
            first = run_script(repo, "wave_control_init.py")
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            second = run_script(repo, "wave_control_init.py")
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            self.assertNotIn("active campaign conflict detected", second.stdout)
            self.assertNotIn("aborted active campaign", second.stdout)
            self.assertIn("reinitialized queued request test-request", second.stdout)
            state = self.read_state(repo)
            self.assertEqual(state["status"], "queued")
            self.assertEqual(state["current_wave"], 1)

    def test_initializer_allows_same_request_content_update_while_queued(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = self.make_repo(Path(temp_dir))
            self.assertEqual(run_script(repo, "wave_control_init.py").returncode, 0)
            request_path = repo / ".codex" / "wave_request.json"
            request = json.loads(request_path.read_text(encoding="utf-8"))
            request["requested_waves"] = 3
            request_path.write_text(json.dumps(request, indent=2) + "\n", encoding="utf-8")
            result = run_script(repo, "wave_control_init.py")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertNotIn("aborted active campaign", result.stdout)
            state = self.read_state(repo)
            self.assertEqual(state["requested_waves"], 3)
            self.assertEqual(state["remaining_waves"], 3)

    def test_initializer_run_starts_wave_in_one_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = self.make_repo(Path(temp_dir), requested_waves=1, child_code=self.simulated_hook_completion_child())
            result = run_command([sys.executable, str(repo / ".codex" / "wave_control_init.py"), "--run"], repo)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("[wave-start] launching request=test-request wave=1/1", result.stdout)
            state = self.read_state(repo)
            self.assertEqual(state["status"], "completed")
            self.assertEqual((repo / "target.txt").read_text(encoding="utf-8"), "changed\n")

    def test_wave_start_requires_codex_hooks_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = self.make_repo(Path(temp_dir), with_config=False)
            self.assertEqual(run_script(repo, "wave_control_init.py").returncode, 0)
            result = run_script(repo, "wave_start.py")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("codex_hooks = true", result.stdout)

    def test_wave_start_rejects_disabled_codex_hooks_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = self.make_repo(Path(temp_dir), config_enabled=False)
            self.assertEqual(run_script(repo, "wave_control_init.py").returncode, 0)
            result = run_script(repo, "wave_start.py")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("codex_hooks = true", result.stdout)

    def test_wave_start_returns_success_when_hook_advances_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = self.make_repo(Path(temp_dir), requested_waves=1, child_code=self.simulated_hook_completion_child())
            self.assertEqual(run_script(repo, "wave_control_init.py").returncode, 0)
            result = run_script(repo, "wave_start.py")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            state = self.read_state(repo)
            self.assertEqual(state["status"], "completed")
            self.assertEqual((repo / "target.txt").read_text(encoding="utf-8"), "changed\n")

    def test_wave_start_requeues_if_child_exits_without_hook_state_advance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = self.make_repo(Path(temp_dir))
            self.assertEqual(run_script(repo, "wave_control_init.py").returncode, 0)
            result = run_script(repo, "wave_start.py")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Stop hook did not complete state transition", result.stderr)
            state = self.read_state(repo)
            self.assertEqual(state["status"], "queued")
            self.assertEqual(state["current_wave"], 1)
            self.assertIn("Stop hook did not complete state transition", state["last_stop_reason"])

    def test_stop_success_blocks_next_wave(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = self.make_repo(Path(temp_dir), requested_waves=2)
            self.assertEqual(run_script(repo, "wave_control_init.py").returncode, 0)
            (repo / "target.txt").write_text("changed\n", encoding="utf-8")
            self.set_running_state(repo)
            result = run_script(repo, "wave_stop.py", input_obj={"cwd": str(repo)})
            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual(output["decision"], "block")
            self.assertEqual(output["stopReason"], "wave_validated_continue")
            self.assertIn("wave-2.md", output["reason"])
            state = self.read_state(repo)
            self.assertEqual(state["status"], "running")
            self.assertEqual(state["current_wave"], 2)
            self.assertEqual(state["remaining_waves"], 1)
            prompt = (repo / ".codex" / "local" / "prompts" / "test-request" / "wave-2.md").read_text(
                encoding="utf-8"
            )
            self.assertIn("do not run the full compatibility command by default", prompt)
            self.assertIn("Skip slow org benchmark after wave 1.", prompt)

    def test_final_wave_allows_stop(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = self.make_repo(Path(temp_dir), requested_waves=1)
            self.assertEqual(run_script(repo, "wave_control_init.py").returncode, 0)
            (repo / "target.txt").write_text("changed\n", encoding="utf-8")
            self.set_running_state(repo)
            result = run_script(repo, "wave_stop.py", input_obj={"cwd": str(repo)})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "")
            state = self.read_state(repo)
            self.assertEqual(state["status"], "completed")
            self.assertEqual(state["remaining_waves"], 0)

    def test_policy_hash_mismatch_requires_reinit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = self.make_repo(Path(temp_dir))
            self.assertEqual(run_script(repo, "wave_control_init.py").returncode, 0)
            policy_path = repo / ".codex" / "wave_project.json"
            policy = json.loads(policy_path.read_text(encoding="utf-8"))
            policy["verification"]["exact_command"] = "python3 missing.py"
            policy_path.write_text(json.dumps(policy, indent=2) + "\n", encoding="utf-8")
            result = run_script(repo, "wave_start.py")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("wave_project.json changed after initialization", result.stdout)

    def test_disallowed_path_blocks_current_wave(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = self.make_repo(Path(temp_dir))
            self.assertEqual(run_script(repo, "wave_control_init.py").returncode, 0)
            (repo / "forbidden.txt").write_text("nope\n", encoding="utf-8")
            self.set_running_state(repo)
            result = run_script(repo, "wave_stop.py", input_obj={"cwd": str(repo)})
            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual(output["decision"], "block")
            self.assertEqual(output["stopReason"], "disallowed_wave_files")
            state = self.read_state(repo)
            self.assertEqual(state["status"], "running")
            self.assertEqual(state["current_wave"], 1)
            self.assertIn("disallowed modified files", state["last_stop_reason"])

    def test_diagnosis_only_advances_and_blocks_next_wave(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = self.make_repo(Path(temp_dir))
            self.assertEqual(run_script(repo, "wave_control_init.py").returncode, 0)
            self.set_running_state(repo)
            result = run_script(repo, "wave_stop.py", input_obj={"cwd": str(repo)})
            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual(output["decision"], "block")
            self.assertEqual(output["stopReason"], "wave_diagnostic_continue")
            state = self.read_state(repo)
            self.assertEqual(state["status"], "running")
            self.assertEqual(state["current_wave"], 2)
            self.assertEqual(state["last_result"]["kind"], "wave_diagnostic")

    def test_recover_stuck_running_verified_wave_to_next_queued_wave(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = self.make_repo(Path(temp_dir), requested_waves=2)
            self.assertEqual(run_script(repo, "wave_control_init.py").returncode, 0)
            (repo / "target.txt").write_text("changed\n", encoding="utf-8")
            self.set_running_state(repo)
            result = run_script(repo, "wave_recover.py")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            state = self.read_state(repo)
            self.assertEqual(state["status"], "queued")
            self.assertEqual(state["current_wave"], 2)
            self.assertEqual(state["remaining_waves"], 1)
            self.assertEqual(state["last_result"]["kind"], "wave_exact_verified")

    def test_recover_stuck_final_wave_to_completed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = self.make_repo(Path(temp_dir), requested_waves=1)
            self.assertEqual(run_script(repo, "wave_control_init.py").returncode, 0)
            (repo / "target.txt").write_text("changed\n", encoding="utf-8")
            self.set_running_state(repo)
            result = run_script(repo, "wave_recover.py")
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            state = self.read_state(repo)
            self.assertEqual(state["status"], "completed")
            self.assertEqual(state["remaining_waves"], 0)

    def test_recover_verify_failure_requeues_same_wave(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = self.make_repo(Path(temp_dir), exact_command="python3 missing_verify.py")
            self.assertEqual(run_script(repo, "wave_control_init.py").returncode, 0)
            (repo / "target.txt").write_text("changed\n", encoding="utf-8")
            self.set_running_state(repo)
            result = run_script(repo, "wave_recover.py")
            self.assertNotEqual(result.returncode, 0)
            state = self.read_state(repo)
            self.assertEqual(state["status"], "queued")
            self.assertEqual(state["current_wave"], 1)
            self.assertIn("exact verify command failed", state["last_stop_reason"])

    def test_initializer_run_recovers_stuck_running_then_starts_next_wave(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = self.make_repo(Path(temp_dir), requested_waves=2, child_code=self.simulated_hook_completion_child())
            self.assertEqual(run_script(repo, "wave_control_init.py").returncode, 0)
            (repo / "target.txt").write_text("changed\n", encoding="utf-8")
            self.set_running_state(repo)
            result = run_command([sys.executable, str(repo / ".codex" / "wave_control_init.py"), "--run"], repo)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("recovering stale running request test-request wave 1", result.stdout)
            state = self.read_state(repo)
            self.assertEqual(state["status"], "completed")
            self.assertEqual(state["remaining_waves"], 0)

    def test_initializer_run_refuses_duplicate_when_runtime_is_live(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = self.make_repo(Path(temp_dir))
            self.assertEqual(run_script(repo, "wave_control_init.py").returncode, 0)
            self.set_running_state(repo)
            sleeper = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    "import time; time.sleep(30)",
                    str(repo),
                    ".codex/wave_start.py",
                ]
            )
            try:
                result = run_command([sys.executable, str(repo / ".codex" / "wave_control_init.py"), "--run"], repo)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("refusing to start a duplicate campaign", result.stdout)
            finally:
                sleeper.terminate()
                sleeper.wait(timeout=10)


if __name__ == "__main__":
    unittest.main()
