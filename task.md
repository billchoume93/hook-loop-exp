# Task Lock

This repository is set up for iterative optimization of one file only:
`pi_algo_improve-by-agent.py`.

## Allowed Edit Target

- Only modify `pi_algo_improve-by-agent.py` during normal optimization waves.

## Files That Must Not Be Modified During Normal Optimization Waves

- `pi_algo_org.py`
- `run_verify_timed.py`
- `verify_pi_bin.py`
- `pi_65536.bin`
- `.codex/hooks.json`
- `.codex/wave_stop.py`
- `task.md`
- `init_prompt.md`
- `INIT_PROMPT.md`
- `README.md`

## Correctness Rules

- Do not use cross-validation between two algorithms.
- Correctness must be checked against the pinned binary file `pi_65536.bin`.
- Python verification must stay independent from the implementation being tested.
- Use `verify_pi_bin.py` or `run_verify_timed.py` for validation.

## Benchmark Rules

- Compare `pi_algo_improve-by-agent.py` against `pi_algo_org.py`.
- Both implementations must pass independent binary verification before timing
  comparison is considered valid.

## Override Rule

- Only break these rules when the user explicitly asks to modify other files.
