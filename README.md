# hook_loop_exp

This repository contains a baseline and optimized Python implementation for
computing pi, a pinned binary verifier, a benchmark runner, and a request-driven
multi-wave hook controller for automated optimization campaigns.

## Directory Layout

- `algorithms/`: baseline and optimized pi implementations
- `tools/`: verification and benchmark entry points
- `reference/`: pinned binary fixture for correctness checks
- `docs/`: optimization scope and wave-start prompt files
- `.codex/`: wave-loop hooks and local Codex control files
- root files: repo-wide instructions, high-level docs, and best-result log

## Key Files

- `algorithms/pi_algo_org.py`: original baseline implementation
- `algorithms/pi_algo_improve-by-agent.py`: implementation targeted for optimization
- `tools/verify_pi_bin.py`: direct byte-for-byte verification against `reference/pi_65536.bin`
- `tools/run_verify_timed.py`: benchmark runner with repeated execution and summary
- `docs/task.md`: optimization scope, validation policy, and benchmark rules
- `docs/init_prompt.md`: prompt used to initialize each optimization wave
- `log.md`: running record of the best known benchmark result across waves
- `.codex/wave_request.json`: tracked campaign request file edited by the user
- `.codex/wave_state.json`: tracked controller-owned runtime snapshot
- `.codex/local/wave_events.jsonl`: local append-only audit journal
- `AGENTS.md`: repository-level instructions for Codex

## Usage

Run the benchmark and verify both implementations:

```bash
python3 run_verify_timed.py 65536
```

Show both generated outputs as well:

```bash
python3 tools/run_verify_timed.py 100 --repeats 3 --show-pi
```

For wave enforcement, the fixed commands are:

```bash
python3 algorithms/pi_algo_improve-by-agent.py 65536 | python3 tools/verify_pi_bin.py
python3 run_verify_timed.py 65536 --repeats 1
```

For exact byte-for-byte verification against the full pinned reference:

```bash
python3 algorithms/pi_algo_improve-by-agent.py 65536 | python3 tools/verify_pi_bin.py --exact
```

## Request-Driven Campaigns

Start a new multi-wave campaign by editing `.codex/wave_request.json` with:

- a new `request_id`
- `requested_waves`
- a non-empty `goal`
- `continue_command`
- `created_at`

Then initialize the control plane explicitly:

```bash
python3 .codex/wave-control-init.py
```

The initializer syncs `.codex/wave_state.json` to wave 1 in `queued` status,
captures the current worktree as the baseline snapshot for later wave-diff
checks, and materializes the exact prompt file that should be passed to the
next Codex CLI run.

If you want the initializer to launch the first Codex CLI process itself, use:

```bash
python3 .codex/wave-control-init.py --run
```

Campaign rules:

- `.codex/wave-control-init.py` is the supported bootstrap entrypoint for
  wave 1.
- After initialization, the Stop hook is the only auto-continue entrypoint for
  later waves.
- `.codex/wave_request.json` is immutable during an active campaign.
- `.codex/wave_state.json` is controller-owned and records the active or most
  recent campaign snapshot.
- The controller compares each wave against the initializer's baseline
  snapshot, so unrelated pre-existing dirty files do not block campaign start.
- `log.md` records validated performance history.
- `.codex/local/wave_events.jsonl` records local controller audit events.
