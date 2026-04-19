# hook_loop_exp

This repository contains two Python implementations for computing pi with the
same Machin-formula approach, a pinned binary verifier, and a benchmark runner
that executes both implementations, verifies both outputs independently, and
compares timing results.

## Directory Layout

- `algorithms/`: baseline and optimized pi implementations
- `tools/`: verification and benchmark entry points
- `reference/`: pinned binary fixture for correctness checks
- `docs/`: optimization scope and wave-start prompt files
- `.codex/`: wave-loop hooks and local Codex control files
- root files: repo-wide instructions, high-level docs, best-result log, and
  wave counter

## Key Files

- `algorithms/pi_algo_org.py`: original baseline implementation
- `algorithms/pi_algo_improve-by-agent.py`: implementation targeted for optimization
- `tools/verify_pi_bin.py`: direct byte-for-byte verification against `reference/pi_65536.bin`
- `tools/run_verify_timed.py`: benchmark runner with repeated execution and summary
- `docs/task.md`: optimization scope, validation policy, and benchmark rules
- `docs/init_prompt.md`: prompt used to initialize each optimization wave
- `log.md`: running record of the best known benchmark result across waves
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
