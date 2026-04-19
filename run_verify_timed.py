#!/usr/bin/env python3

import runpy
from pathlib import Path


def main() -> None:
    target = Path(__file__).resolve().parent / "tools" / "run_verify_timed.py"
    runpy.run_path(str(target), run_name="__main__")


if __name__ == "__main__":
    main()
