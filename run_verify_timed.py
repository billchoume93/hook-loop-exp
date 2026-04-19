#!/usr/bin/env python3

import argparse
import statistics
import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
VERIFY_SCRIPT = BASE_DIR / "verify_pi_bin.py"
TARGET_SCRIPTS = {
    "org": BASE_DIR / "pi_algo_org.py",
    "improve": BASE_DIR / "pi_algo_improve-by-agent.py",
}


def elapsed_ms(start_ns: int, end_ns: int) -> float:
    return (end_ns - start_ns) / 1_000_000


def run_script(script_path: Path, digits: int) -> tuple[str, float]:
    started_ns = time.perf_counter_ns()
    completed = subprocess.run(
        [sys.executable, str(script_path), str(digits)],
        check=True,
        capture_output=True,
        text=True,
    )
    ended_ns = time.perf_counter_ns()
    return completed.stdout.strip(), elapsed_ms(started_ns, ended_ns)


def run_verify(pi_text: str) -> float:
    started_ns = time.perf_counter_ns()
    subprocess.run(
        [sys.executable, str(VERIFY_SCRIPT)],
        input=pi_text,
        check=True,
        capture_output=True,
        text=True,
    )
    ended_ns = time.perf_counter_ns()
    return elapsed_ms(started_ns, ended_ns)


def run_case(name: str, script_path: Path, digits: int) -> dict[str, object]:
    total_started_ns = time.perf_counter_ns()
    pi_text, execution_ms = run_script(script_path, digits)
    verification_ms = run_verify(pi_text)
    total_ended_ns = time.perf_counter_ns()

    return {
        "name": name,
        "script_path": script_path,
        "pi_text": pi_text,
        "execution_ms": execution_ms,
        "verification_ms": verification_ms,
        "total_ms": elapsed_ms(total_started_ns, total_ended_ns),
    }


def summarize_runs(name: str, script_path: Path, runs: list[dict[str, object]]) -> dict[str, object]:
    execution_values = [run["execution_ms"] for run in runs]
    verification_values = [run["verification_ms"] for run in runs]
    total_values = [run["total_ms"] for run in runs]

    return {
        "name": name,
        "script_path": script_path,
        "runs": runs,
        "execution_avg_ms": statistics.mean(execution_values),
        "execution_median_ms": statistics.median(execution_values),
        "verification_avg_ms": statistics.mean(verification_values),
        "verification_median_ms": statistics.median(verification_values),
        "total_avg_ms": statistics.mean(total_values),
        "total_median_ms": statistics.median(total_values),
        "pi_text": runs[-1]["pi_text"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run both pi implementations, verify both outputs independently, "
            "and compare timings in milliseconds."
        )
    )
    parser.add_argument("digits", nargs="?", type=int, default=65536)
    parser.add_argument(
        "--repeats",
        type=int,
        default=5,
        help="Number of benchmark repetitions per implementation.",
    )
    parser.add_argument(
        "--show-pi",
        action="store_true",
        help="Print both generated pi outputs after the timing summary.",
    )
    return parser.parse_args()


def print_case_summary(result: dict[str, object]) -> None:
    print(f"[{result['name']}]")
    print(f"script={Path(result['script_path']).name}")
    print(f"runs={len(result['runs'])}")
    print(f"execution_avg_ms={result['execution_avg_ms']:.3f}")
    print(f"execution_median_ms={result['execution_median_ms']:.3f}")
    print(f"verification_avg_ms={result['verification_avg_ms']:.3f}")
    print(f"verification_median_ms={result['verification_median_ms']:.3f}")
    print(f"total_avg_ms={result['total_avg_ms']:.3f}")
    print(f"total_median_ms={result['total_median_ms']:.3f}")
    print("status=OK")

    for index, run in enumerate(result["runs"], start=1):
        print(
            f"run_{index}_ms="
            f"{run['execution_ms']:.3f}/"
            f"{run['verification_ms']:.3f}/"
            f"{run['total_ms']:.3f}"
        )


def print_comparison(org_result: dict[str, object], improve_result: dict[str, object]) -> None:
    execution_avg_delta_ms = improve_result["execution_avg_ms"] - org_result["execution_avg_ms"]
    execution_median_delta_ms = (
        improve_result["execution_median_ms"] - org_result["execution_median_ms"]
    )
    total_avg_delta_ms = improve_result["total_avg_ms"] - org_result["total_avg_ms"]
    total_median_delta_ms = improve_result["total_median_ms"] - org_result["total_median_ms"]

    print("[comparison]")
    print(f"execution_avg_delta_ms={execution_avg_delta_ms:.3f}")
    print(f"execution_median_delta_ms={execution_median_delta_ms:.3f}")
    print(f"total_avg_delta_ms={total_avg_delta_ms:.3f}")
    print(f"total_median_delta_ms={total_median_delta_ms:.3f}")

    if org_result["execution_avg_ms"] != 0:
        execution_avg_ratio = improve_result["execution_avg_ms"] / org_result["execution_avg_ms"]
        print(f"execution_avg_ratio_vs_org={execution_avg_ratio:.6f}")

    if org_result["execution_median_ms"] != 0:
        execution_median_ratio = (
            improve_result["execution_median_ms"] / org_result["execution_median_ms"]
        )
        print(f"execution_median_ratio_vs_org={execution_median_ratio:.6f}")

    if org_result["total_avg_ms"] != 0:
        total_avg_ratio = improve_result["total_avg_ms"] / org_result["total_avg_ms"]
        print(f"total_avg_ratio_vs_org={total_avg_ratio:.6f}")

    if org_result["total_median_ms"] != 0:
        total_median_ratio = improve_result["total_median_ms"] / org_result["total_median_ms"]
        print(f"total_median_ratio_vs_org={total_median_ratio:.6f}")


def main() -> None:
    args = parse_args()
    if args.repeats < 1:
        raise ValueError("--repeats must be >= 1")

    org_runs = [
        run_case("org", TARGET_SCRIPTS["org"], args.digits)
        for _ in range(args.repeats)
    ]
    improve_runs = [
        run_case("improve", TARGET_SCRIPTS["improve"], args.digits)
        for _ in range(args.repeats)
    ]
    org_result = summarize_runs("org", TARGET_SCRIPTS["org"], org_runs)
    improve_result = summarize_runs("improve", TARGET_SCRIPTS["improve"], improve_runs)

    print(f"digits={args.digits}")
    print(f"repeats={args.repeats}")
    print_case_summary(org_result)
    print_case_summary(improve_result)
    print_comparison(org_result, improve_result)

    if args.show_pi:
        print("[org_pi]")
        print(org_result["pi_text"])
        print("[improve_pi]")
        print(improve_result["pi_text"])


if __name__ == "__main__":
    main()
