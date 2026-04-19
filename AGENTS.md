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
- `.codex/wave_state.json` is controller-owned runtime state and must not be
  edited during an active campaign.
- Campaign start must be clean outside the tracked control files under
  `.codex/`.
- The local append-only audit journal lives at `.codex/local/wave_events.jsonl`
  and is intentionally untracked.

## Validation Rules

- Do not use dual-algorithm or cross-algorithm validation.
- Correctness must be verified against the pinned binary file
  `reference/pi_65536.bin`.
- Keep the Python verifier independent from the implementation being tested.
- Validation must pass before an optimization result is treated as valid.
- Use `tools/verify_pi_bin.py` or `tools/run_verify_timed.py` for validation.
- The required full verification command is:
  `python3 algorithms/pi_algo_improve-by-agent.py 65536 | python3 tools/verify_pi_bin.py`
- The required fixed benchmark command is:
  `python3 run_verify_timed.py 65536 --repeats 1`

## Benchmark Rules

- Benchmark comparisons must compare
  `algorithms/pi_algo_improve-by-agent.py` against
  `algorithms/pi_algo_org.py`.
- Both implementations must pass independent binary verification before a
  benchmark result is treated as valid.
- A wave only consumes controller-owned wave budget after the file-scope check,
  the fixed 65536-digit verification, the exact binary match check, and the
  fixed benchmark command all pass.
- `Current Best` in `log.md` is decided by the controller's trusted
  order-balanced benchmark, not by the fixed benchmark alone.

## Process

- Read `docs/task.md` and `docs/init_prompt.md` before starting a new
  optimization wave.
- Read `log.md` before starting a new optimization wave.
- After a successful wave, update `log.md` with the latest measured result and
  whether it improved on the current best result.
