# Repo Instructions

These instructions apply to the entire repository.

## Optimization Scope

- During normal optimization waves, only modify `pi_algo_improve-by-agent.py`.
- Do not modify other files unless the user explicitly requests it.

## Validation Rules

- Do not use dual-algorithm or cross-algorithm validation.
- Correctness must be verified against the pinned binary file `pi_65536.bin`.
- Keep the Python verifier independent from the implementation being tested.
- Use `verify_pi_bin.py` or `run_verify_timed.py` for validation.

## Benchmark Rules

- Benchmark comparisons must compare `pi_algo_improve-by-agent.py` against
  `pi_algo_org.py`.
- Both implementations must pass independent binary verification before a
  benchmark result is treated as valid.

## Process

- Read `task.md` and `init_prompt.md` before starting a new optimization wave.
