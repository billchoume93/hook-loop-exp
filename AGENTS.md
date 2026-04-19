# Repo Instructions

These instructions apply to the entire repository.

## Optimization Scope

- During normal optimization waves, only modify
  `algorithms/pi_algo_improve-by-agent.py`.
- Do not modify other files unless the user explicitly requests it.
- Optimize for faster computation of the 65536-digit pi value.
- Keep the implementation in single-core execution mode.

## Validation Rules

- Do not use dual-algorithm or cross-algorithm validation.
- Correctness must be verified against the pinned binary file
  `reference/pi_65536.bin`.
- Keep the Python verifier independent from the implementation being tested.
- Validation must pass before an optimization result is treated as valid.
- Use `tools/verify_pi_bin.py` or `tools/run_verify_timed.py` for validation.

## Benchmark Rules

- Benchmark comparisons must compare
  `algorithms/pi_algo_improve-by-agent.py` against
  `algorithms/pi_algo_org.py`.
- Both implementations must pass independent binary verification before a
  benchmark result is treated as valid.

## Process

- Read `docs/task.md` and `docs/init_prompt.md` before starting a new
  optimization wave.
