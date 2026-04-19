#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import os
from decimal import Decimal, ROUND_FLOOR, getcontext

# 盡量限制底層函式庫不要開多執行緒
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

DEFAULT_DIGITS = 512
MAX_VERIFIED_DIGITS = 65536


def arctan(x: Decimal, eps: Decimal) -> Decimal:
    """
    用 Taylor series 計算 arctan(x):
        arctan(x) = x - x^3/3 + x^5/5 - x^7/7 + ...
    當新增項小於 eps 時停止
    """
    x2 = x * x
    term = x
    total = term
    n = 1
    sign = -1

    while True:
        term *= x2
        add = term / Decimal(2 * n + 1)
        if abs(add) < eps:
            break

        if sign > 0:
            total += add
        else:
            total -= add

        sign *= -1
        n += 1

    return total


def machin_pi(digits: int = DEFAULT_DIGITS) -> Decimal:
    """
    使用 Machin formula:
        pi/4 = 4*atan(1/5) - atan(1/239)
    """
    getcontext().prec = digits + 20

    eps = Decimal(10) ** (-(digits + 10))

    atan_1_5 = arctan(Decimal(1) / Decimal(5), eps)
    atan_1_239 = arctan(Decimal(1) / Decimal(239), eps)

    return Decimal(4) * (Decimal(4) * atan_1_5 - atan_1_239)


def truncate_decimal(x: Decimal, digits: int) -> str:
    quant = Decimal("1." + "0" * digits)
    return format(x.quantize(quant, rounding=ROUND_FLOOR), "f")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pi generator using the original Machin formula implementation."
    )
    parser.add_argument("digits", nargs="?", type=int, default=DEFAULT_DIGITS)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pi_val = machin_pi(args.digits)
    print(truncate_decimal(pi_val, args.digits))


if __name__ == "__main__":
    main()
