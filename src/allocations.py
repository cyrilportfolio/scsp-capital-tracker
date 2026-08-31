"""Allocation of amounts between partners.

The allocation rule is the backbone of private equity accounting: every
euro called, every euro of gain and every euro of fee reaches an investor
through it. Two things matter and are handled here.

*The rule itself* — under this fund's LPA, everything is shared in
proportion to commitments.

*The cents* — a share of 1/3 cannot be paid to the cent. Splitting an
amount by simple rounding leaves a residue, and a residue that nobody owns
is how a capital account drifts away from the fund's NAV over forty
quarters. The split below uses the largest-remainder method: the shares are
rounded down, and the cents left over go to the partners whose fractional
part was largest, so the allocation always adds back exactly to the amount.
"""

from __future__ import annotations

import pandas as pd

from src import config


def shares(investors: pd.DataFrame) -> pd.Series:
    """Share of each partner, indexed by partner code, summing to 1."""
    commitments = investors.set_index("code")["engagement"].astype(float)
    total = commitments.sum()
    if total <= 0:
        raise ValueError("le total des engagements doit etre strictement positif")
    return commitments / total


def allocate(amount: float, investors: pd.DataFrame) -> pd.Series:
    """Split an amount between partners, to the cent, without residue."""
    part = shares(investors)
    if amount == 0:
        return pd.Series(0.0, index=part.index)

    exact = part * amount
    cents = (exact * 100)
    floored = cents.apply(lambda v: int(v // 1) if v >= 0 else -int(-v // 1))
    residue = int(round(cents.sum() - floored.sum()))

    if residue:
        step = 1 if residue > 0 else -1
        order = (cents - floored).sort_values(ascending=(residue < 0)).index
        for code in list(order)[:abs(residue)]:
            floored[code] += step

    return (floored / 100).astype(float)


def allocation_table(investors: pd.DataFrame) -> pd.DataFrame:
    """One row per partner: commitment, share, and the rule applied."""
    part = shares(investors)
    frame = investors[["code", "nom", "type", "pays", "engagement"]].copy()
    frame["part"] = frame["code"].map(part)
    frame["part_pct"] = (frame["part"] * 100).round(6)
    frame["regle"] = config.ALLOCATION_BASIS
    return frame.sort_values("engagement", ascending=False).reset_index(drop=True)
