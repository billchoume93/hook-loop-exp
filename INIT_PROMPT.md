# Continuous Optimization Init Prompt

Before starting each optimization wave, read `task.md` and follow it strictly.

Wave goal:

- Optimize only `pi_algo_improve-by-agent.py`.
- Do not modify any other repository file unless the user explicitly asks for it.

Validation policy:

- Never validate by comparing one algorithm against the other.
- Always validate with the pinned binary reference `pi_65536.bin`.
- Keep Python verification independent from the implementation under test.

Benchmark policy:

- Use `run_verify_timed.py` to compare `pi_algo_improve-by-agent.py` against
  `pi_algo_org.py`.
- Treat a timing result as valid only if both implementations pass independent
  binary verification.

Output policy for each wave:

- Make one scoped improvement only.
- End with a short summary of what changed, what was verified, and the next
  optimization direction.
