#!/usr/bin/env python3
from pathlib import Path
import runpy


if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).with_name("wave_control_init.py")), run_name="__main__")
