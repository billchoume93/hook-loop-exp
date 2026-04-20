# Optimization Log

This file records trusted benchmark results across request-driven waves.

## Current Best

- Wave: 2026-04-19-2339/wave-3
- Compatibility benchmark command: `python3 run_verify_timed.py 65536 --repeats 1`
- Decision benchmark command: `controller median of order-balanced direct runs (org/improve, improve/org, org/improve)`
- `improve` execution_ms: 121.739
- `org` execution_ms: 27304.017
- execution ratio vs `org`: 0.004460
- New best: yes
- Notes: Controller-validated wave for request 2026-04-19-2339.

## Wave History

### Template

- Wave: `wave-N`
- Compatibility benchmark command: `python3 run_verify_timed.py 65536 --repeats 1`
- Decision benchmark command: `controller median of order-balanced direct runs (org/improve, improve/org, org/improve)`
- Compatibility `improve` execution_ms: `...`
- Compatibility `org` execution_ms: `...`
- Compatibility execution ratio vs `org`: `...`
- Decision `improve` execution_ms: `...`
- Decision `org` execution_ms: `...`
- Decision execution ratio vs `org`: `...`
- New best: `yes/no`
- Notes: `what changed in algorithms/pi_algo_improve-by-agent.py`

### 2026-04-19-2339/wave-1

- Compatibility benchmark command: `python3 run_verify_timed.py 65536 --repeats 1`
- Decision benchmark command: `controller median of order-balanced direct runs (org/improve, improve/org, org/improve)`
- Compatibility `improve` execution_ms: `245.264`
- Compatibility `org` execution_ms: `30516.942`
- Compatibility execution ratio vs `org`: `0.008037`
- Decision `improve` execution_ms: `125.927`
- Decision `org` execution_ms: `27500.439`
- Decision execution ratio vs `org`: `0.004598`
- New best: `yes`
- Notes: Controller-validated wave for request 2026-04-19-2339.

### 2026-04-19-2339/wave-2

- Compatibility benchmark command: `python3 run_verify_timed.py 65536 --repeats 1`
- Decision benchmark command: `controller median of order-balanced direct runs (org/improve, improve/org, org/improve)`
- Compatibility `improve` execution_ms: `250.600`
- Compatibility `org` execution_ms: `30914.427`
- Compatibility execution ratio vs `org`: `0.008106`
- Decision `improve` execution_ms: `123.930`
- Decision `org` execution_ms: `27370.196`
- Decision execution ratio vs `org`: `0.004530`
- New best: `yes`
- Notes: Controller-validated wave for request 2026-04-19-2339.

### 2026-04-19-2339/wave-3

- Compatibility benchmark command: `python3 run_verify_timed.py 65536 --repeats 1`
- Decision benchmark command: `controller median of order-balanced direct runs (org/improve, improve/org, org/improve)`
- Compatibility `improve` execution_ms: `246.157`
- Compatibility `org` execution_ms: `30628.034`
- Compatibility execution ratio vs `org`: `0.008037`
- Decision `improve` execution_ms: `121.739`
- Decision `org` execution_ms: `27304.017`
- Decision execution ratio vs `org`: `0.004460`
- New best: `yes`
- Notes: Controller-validated wave for request 2026-04-19-2339.

### 2026-04-20-0010/wave-1

- Compatibility benchmark command: `python3 run_verify_timed.py 65536 --repeats 1`
- Decision benchmark command: `controller median of order-balanced direct runs (org/improve, improve/org, org/improve)`
- Compatibility `improve` execution_ms: `125.212`
- Compatibility `org` execution_ms: `26791.087`
- Compatibility execution ratio vs `org`: `0.004674`
- Decision `improve` execution_ms: `pending controller`
- Decision `org` execution_ms: `pending controller`
- Decision execution ratio vs `org`: `pending controller`
- New best: `no`
- Notes: Replaced the Decimal-based Machin series with an integer Chudnovsky binary-splitting implementation. Full binary verification passed for both `org` and `improve`, but the fixed benchmark did not beat the current trusted best.

### 2026-04-20-0032/wave-1

- Compatibility benchmark command: `python3 run_verify_timed.py 65536 --repeats 1`
- Decision benchmark command: `controller median of order-balanced direct runs (org/improve, improve/org, org/improve)`
- Compatibility `improve` execution_ms: `120.239`
- Compatibility `org` execution_ms: `26588.526`
- Compatibility execution ratio vs `org`: `0.004522`
- Decision `improve` execution_ms: `pending controller`
- Decision `org` execution_ms: `pending controller`
- Decision execution ratio vs `org`: `pending controller`
- New best: `pending controller`
- Notes: Restored the single-core integer Chudnovsky binary-splitting implementation and reduced guard-digit overhead while preserving exact binary verification.
