# Continuous Optimization Init Prompt

Before starting each optimization wave, read `docs/task.md` and follow it
strictly.
Also read `log.md` to understand the current best known performance.

Wave goal:

- Optimize only `algorithms/pi_algo_improve-by-agent.py`.
- Update `log.md` after a successful wave to preserve the latest benchmark
  result and whether it improved on the best known result.
- Optimize for faster computation of the 65536-digit pi value.
- Keep the implementation in single-core execution mode.
- Do not modify any other repository file unless the user explicitly asks for it.

Validation policy:

- Never validate by comparing one algorithm against the other.
- Always validate with the pinned binary reference `reference/pi_65536.bin`.
- Keep Python verification independent from the implementation under test.
- Validation must pass before an optimization attempt is accepted.
- The required full verification command is:
  `python3 algorithms/pi_algo_improve-by-agent.py 65536 | python3 tools/verify_pi_bin.py`

Benchmark policy:

- Use `tools/run_verify_timed.py` to compare
  `algorithms/pi_algo_improve-by-agent.py` against
  `algorithms/pi_algo_org.py`.
- Treat a timing result as valid only if both implementations pass independent
  binary verification.
- The required fixed benchmark command is:
  `python3 run_verify_timed.py 65536 --repeats 1`
- A wave only consumes `count.md` budget after the file-scope check, the
  required full verification command, and the required fixed benchmark command
  all pass.

Output policy for each wave:

- Make one scoped improvement only.
- Record the successful benchmark result in `log.md`.
- End with a short summary of what changed, what was verified, and the next
  optimization direction.
