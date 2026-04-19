# Task Lock

This repository is set up to optimize the speed of computing pi to 65536 digits.
All algorithm optimization work must happen in
`algorithms/pi_algo_improve-by-agent.py`.

## Allowed Edit Target

- Only modify `algorithms/pi_algo_improve-by-agent.py` during normal
  optimization waves.

## Optimization Goal

- Optimize the algorithm speed for producing the 65536-digit pi output value.
- Keep the implementation in single-core execution mode.
- Any speedup must preserve the single-core constraint.
- Keep the original comparison baseline in `algorithms/pi_algo_org.py`.
- Put all optimization changes in `algorithms/pi_algo_improve-by-agent.py`.

## Files That Must Not Be Modified During Normal Optimization Waves

- `algorithms/pi_algo_org.py`
- `tools/run_verify_timed.py`
- `tools/verify_pi_bin.py`
- `reference/pi_65536.bin`
- `.codex/hooks.json`
- `.codex/wave_stop.py`
- `docs/task.md`
- `docs/init_prompt.md`
- `README.md`

## Correctness Rules

- Do not use cross-validation between two algorithms.
- Correctness must be checked against the pinned binary file
  `reference/pi_65536.bin`.
- Python verification must stay independent from the implementation being tested.
- Validation must pass before an optimization result is accepted.
- Use `tools/verify_pi_bin.py` or `tools/run_verify_timed.py` for validation.
- The required full verification command is:
  `python3 algorithms/pi_algo_improve-by-agent.py 65536 | python3 tools/verify_pi_bin.py`

## Benchmark Rules

- Compare `algorithms/pi_algo_improve-by-agent.py` against
  `algorithms/pi_algo_org.py`.
- Both implementations must pass independent binary verification before timing
  comparison is considered valid.
- The required fixed benchmark command is:
  `python3 run_verify_timed.py 65536 --repeats 1`
- `count.md` may only be consumed after the file-scope check, the required full
  verification command, and the required fixed benchmark command all pass.

## Override Rule

- Only break these rules when the user explicitly asks to modify other files.
