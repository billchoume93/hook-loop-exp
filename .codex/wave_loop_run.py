#!/usr/bin/env python3
"""Compatibility shim for the old runner-driven entrypoint."""

from wave_start import main as wave_start_main


if __name__ == "__main__":
    print("[wave-loop-run] deprecated: use `python3 .codex/wave_start.py` for hook-driven campaigns")
    raise SystemExit(wave_start_main())
