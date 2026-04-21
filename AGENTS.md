# Repo Instructions

These instructions apply to the entire repository.

## Optimization Scope

- During normal optimization waves, only modify
  `algorithms/pi_algo_improve-by-agent.py`.
- `log.md` may also be updated to record the best known benchmark result for the
  latest successful wave.
- Do not modify other files unless the user explicitly requests it.
- Controller-maintenance work may modify `.codex/*`, `docs/*`, `README.md`,
  `tools/verify_pi_bin.py`, and related control-plane files when the user
  explicitly requests it.
- Optimize for faster computation of the 65536-digit pi value.
- Keep the implementation in single-core execution mode.

## Campaign Control Plane

- Multi-wave campaigns are started by editing `.codex/wave_request.json` with a
  new `request_id` and `requested_waves`.
- `.codex/wave_project.json` defines the project-specific policy for allowed
  wave edits, required edit targets, prompt context files, and exact
  verification. It is required for campaign initialization.
- `.codex/config.toml` must enable native hooks with
  `[features].codex_hooks = true`.
- `.codex/wave_state.json` is controller-owned runtime state and must not be
  edited during an active campaign.
- Campaign start may begin from an already-dirty worktree; the initializer
  snapshots that baseline and later waves are checked relative to it.
- The local append-only audit journal lives at `.codex/local/wave_events.jsonl`
  and is intentionally untracked.
- `.codex/wave_start.py` is the supported foreground bootstrap for wave 1.
- After wave 1 starts, `.codex/wave_stop.py` drives continuation by returning
  native Codex `decision: "block"` with the next materialized prompt path while
  `remaining_waves > 0`.
- If the Codex child exits without Stop hook state advancement, `wave_start.py`
  requeues the same wave and fails loudly.
- `.codex/wave_recover.py` repairs stale `running`/`validating` state after a
  lost Stop hook by validating the current wave and queueing the next wave when
  policy checks pass.
- `.codex/wave_loop_run.py` is deprecated compatibility for the old
  runner-driven flow.

## Validation Rules

- Do not use dual-algorithm or cross-algorithm validation.
- Correctness must be verified against the pinned binary file
  `reference/pi_65536.bin`.
- Keep the Python verifier independent from the implementation being tested.
- Validation must pass before an optimization result is treated as valid.
- Use `tools/verify_pi_bin.py` or `tools/run_verify_timed.py` for validation.
- The Stop hook gate uses:
  `python3 algorithms/pi_algo_improve-by-agent.py 65536 | python3 tools/verify_pi_bin.py --exact`
- Heavy benchmark comparison should not be deferred to the Stop hook.
- Do not run the full org/improve benchmark by default after wave 1; use exact
  verification plus improve-only timing unless full benchmark evidence is
  explicitly needed.

## Benchmark Rules

- Full benchmark comparisons must compare
  `algorithms/pi_algo_improve-by-agent.py` against
  `algorithms/pi_algo_org.py`.
- Both implementations must pass independent binary verification before a
  benchmark result is treated as valid.
- Because `algorithms/pi_algo_org.py` is slow, run the full fixed benchmark by
  default on wave 1 only. Later waves should reuse `log.md` for org/current-best
  context unless the improve-only timing suggests a possible new best.
- A wave consumes controller-owned wave budget after the file-scope check and
  the exact binary verification pass.
- `Current Best` in `log.md` should be decided by explicit benchmark evidence,
  not by the Stop hook.

## Process

- After `python3 .codex/wave_control_init.py`, run
  `python3 .codex/wave_start.py` to execute the hook-driven campaign in the
  foreground.
- For normal use after manually updating `.codex/wave_request.json`, prefer the
  one-command bootstrap: `python3 .codex/wave_control_init.py --run`.
- Read `docs/task.md` and `docs/init_prompt.md` before starting a new
  optimization wave.
- Read `log.md` before starting a new optimization wave.
- After a successful wave, update `log.md` with the latest measured result and
  whether it improved on the current best result.
