#!/usr/bin/env python3

import argparse
import sys
from pathlib import Path

REFERENCE_PATH = Path(__file__).with_name("pi_65536.bin")
MAX_VERIFIED_DIGITS = 65536


def verify_against_binary(pi_text: str, reference_path: Path) -> None:
    if not reference_path.exists():
        raise FileNotFoundError(f"reference binary not found: {reference_path}")

    expected = reference_path.read_bytes()
    actual = pi_text.encode("ascii")

    if len(actual) > len(expected):
        raise ValueError(
            f"reference only covers {MAX_VERIFIED_DIGITS} digits, got {len(actual) - 2}"
        )

    if actual == expected[: len(actual)]:
        return

    for idx, (lhs, rhs) in enumerate(zip(actual, expected), start=1):
        if lhs != rhs:
            raise AssertionError(
                f"pi mismatch at byte {idx}: got {chr(lhs)!r}, expected {chr(rhs)!r}"
            )

    raise AssertionError("pi mismatch: actual output is not a prefix of reference")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify pi output directly against the pinned binary reference."
    )
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        help="Optional text file containing pi output. Reads stdin when omitted.",
    )
    parser.add_argument(
        "--reference",
        type=Path,
        default=REFERENCE_PATH,
        help="Pinned binary file used for direct byte verification.",
    )
    return parser.parse_args()


def read_input(input_path: Path | None) -> str:
    if input_path is None:
        return sys.stdin.read().strip()
    return input_path.read_text(encoding="ascii").strip()


def main() -> None:
    args = parse_args()
    pi_text = read_input(args.input)
    verify_against_binary(pi_text, args.reference)
    print("OK")


if __name__ == "__main__":
    main()
