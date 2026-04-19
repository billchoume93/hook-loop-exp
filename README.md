# hook_loop_exp

This repository contains two Python implementations for computing pi with the
same Machin-formula approach, a pinned binary verifier, and a benchmark runner
that executes both implementations, verifies both outputs independently, and
compares timing results.

## Files

- `pi_algo_org.py`: original Machin-formula implementation
- `pi_algo_improve-by-agent.py`: alternate implementation to compare
- `verify_pi_bin.py`: direct byte-for-byte verification against `pi_65536.bin`
- `run_verify_timed.py`: benchmark runner with repeated execution and summary
- `pi_65536.bin`: pinned reference output used for correctness verification
- `.codex/`: local Codex hook and wave-loop files kept in the repository

## Usage

Run the benchmark and verify both implementations:

```bash
python3 run_verify_timed.py 512 --repeats 3
```

Show both generated outputs as well:

```bash
python3 run_verify_timed.py 100 --repeats 3 --show-pi
```
