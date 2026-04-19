# Continuous Optimization Init Prompt

Before starting each optimization wave, read `docs/task.md` and follow it
strictly.

Wave goal:

- Optimize only `algorithms/pi_algo_improve-by-agent.py`.
- Optimize for faster computation of the 65536-digit pi value.
- Keep the implementation in single-core execution mode.
- Do not modify any other repository file unless the user explicitly asks for it.

Validation policy:

- Never validate by comparing one algorithm against the other.
- Always validate with the pinned binary reference `reference/pi_65536.bin`.
- Keep Python verification independent from the implementation under test.
- Validation must pass before an optimization attempt is accepted.

Benchmark policy:

- Use `tools/run_verify_timed.py` to compare
  `algorithms/pi_algo_improve-by-agent.py` against
  `algorithms/pi_algo_org.py`.
- Treat a timing result as valid only if both implementations pass independent
  binary verification.

Output policy for each wave:

- Make one scoped improvement only.
- End with a short summary of what changed, what was verified, and the next
  optimization direction.
