"""European whole-of-fund distribution waterfall.

The model implemented here is the one that dominates European private
equity, and Luxembourg with it: all contributions come back first, at the
level of the fund as a whole, before the carried interest partner sees
anything. Its mechanics follow the cumulative cash bucket: at any date, the
bucket holds the cash already distributed plus the residual value of the
fund, and that bucket is poured down four steps.

    1. Return of capital     100 % to the partners, until every contribution
                             drawn since inception has been repaid.
    2. Preferred return      100 % to the partners, up to the hurdle earned
                             on their outstanding contributions.
    3. Catch-up              100 % to the carried interest partner, until it
                             has caught up with the partners on that hurdle.
                             For an 80:20 split that is 25 % of the preferred
                             return, which is simply the 20 % grossed up.
    4. Residual split        80 % to the partners, 20 % as carried interest.

The carried interest is the sum of steps 3 and 4 — forgetting the catch-up
is the classic mistake, and it understates the carry by a third.

The preferred return itself is accrued day by day on the contributions not
yet repaid, and capitalised on each anniversary of the first drawdown. The
alternative found in some agreements — solving an IRR on the partner cash
flows — gives a close result but shows nothing of how it got there.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd

from src import config


# --------------------------------------------------------------------------
# Preferred return
# --------------------------------------------------------------------------
@dataclass
class PreferredReturn:
    """Result of the daily accrual."""

    earned: float
    unpaid: float
    schedule: pd.DataFrame = field(repr=False, default_factory=pd.DataFrame)


def preferred_return(contributions: pd.Series, distributions: pd.Series,
                     as_of, rate: float = config.PREFERRED_RETURN_RATE,
                     first_drawdown: date | None = None,
                     with_schedule: bool = False) -> PreferredReturn:
    """Accrue the hurdle day by day on the contributions not yet repaid.

    ``contributions`` and ``distributions`` are amounts indexed by date.
    Distributions repay capital first, then the hurdle already accrued;
    anything beyond that is profit and does not reduce the base.
    """
    as_of = pd.Timestamp(as_of).date()
    events: dict[date, float] = {}
    for when, amount in contributions.items():
        key = pd.Timestamp(when).date()
        events[key] = events.get(key, 0.0) + float(amount)
    for when, amount in distributions.items():
        key = pd.Timestamp(when).date()
        events[key] = events.get(key, 0.0) - float(amount)

    if not events:
        return PreferredReturn(earned=0.0, unpaid=0.0, schedule=pd.DataFrame())

    start = min(events)
    first_drawdown = first_drawdown or start
    anniversaries = set()
    year = first_drawdown.year + 1
    while date(year, first_drawdown.month, first_drawdown.day) <= as_of:
        anniversaries.add(date(year, first_drawdown.month, first_drawdown.day))
        year += 1

    outstanding = 0.0      # contributions not yet repaid
    capitalised = 0.0      # hurdle accrued and capitalised, still unpaid
    pending = 0.0          # hurdle accrued since the last anniversary
    earned = 0.0           # hurdle earned since inception, never reduced
    rows = []

    current = start
    while current <= as_of:
        movement = events.get(current, 0.0)
        if movement > 0:
            outstanding += movement
        elif movement < 0:
            left = -movement
            repaid = min(left, outstanding)
            outstanding -= repaid
            left -= repaid
            paid_pending = min(left, pending)
            pending -= paid_pending
            left -= paid_pending
            capitalised -= min(left, capitalised)

        interest = (outstanding + capitalised) * rate / config.PREFERRED_RETURN_DAY_COUNT
        pending += interest
        earned += interest

        if current in anniversaries:
            capitalised += pending
            pending = 0.0

        if with_schedule and (movement or current in anniversaries or current == as_of):
            rows.append({
                "date": pd.Timestamp(current),
                "mouvement": round(movement, 2),
                "contributions_non_remboursees": round(outstanding, 2),
                "hurdle_capitalise": round(capitalised, 2),
                "hurdle_courant": round(pending, 2),
                "hurdle_cumule": round(earned, 2),
            })

        current += timedelta(days=1)

    return PreferredReturn(earned=round(earned, 2),
                           unpaid=round(capitalised + pending, 2),
                           schedule=pd.DataFrame(rows))


# --------------------------------------------------------------------------
# The cascade
# --------------------------------------------------------------------------
@dataclass
class WaterfallResult:
    bucket: float
    contributions: float
    distributions: float
    nav: float
    preferred: float
    return_of_capital: float
    preferred_paid: float
    catch_up: float
    split_partners: float
    split_carry: float
    carried_interest: float
    to_partners: float
    steps: pd.DataFrame = field(repr=False, default_factory=pd.DataFrame)


def run_waterfall(contributions: float, distributions: float, nav: float,
                  preferred: float, carry_split: float = config.CARRY_SPLIT,
                  catch_up_rate: float | None = None) -> WaterfallResult:
    """Pour the cumulative bucket down the four steps.

    ``nav`` is the residual value of the fund: the cash the partners would
    receive if everything were liquidated on the calculation date. Adding it
    to the distributions already made is what makes the carried interest an
    accrual rather than a payment.
    """
    if catch_up_rate is None:
        catch_up_rate = carry_split / (1 - carry_split)

    bucket = round(distributions + nav, 2)
    remaining = bucket

    return_of_capital = round(min(remaining, contributions), 2)
    remaining = round(remaining - return_of_capital, 2)

    preferred_paid = round(min(remaining, preferred), 2)
    remaining = round(remaining - preferred_paid, 2)

    catch_up = round(min(remaining, catch_up_rate * preferred_paid), 2)
    remaining = round(remaining - catch_up, 2)

    split_carry = round(remaining * carry_split, 2)
    split_partners = round(remaining - split_carry, 2)

    carried_interest = round(catch_up + split_carry, 2)
    to_partners = round(return_of_capital + preferred_paid + split_partners, 2)

    steps = pd.DataFrame([
        {"etape": 0, "clause": "Cumulative cash bucket",
         "detail": "distributions cumulees + valeur residuelle",
         "aux_associes": 0.0, "au_cip": 0.0, "solde_du_bucket": bucket},
        {"etape": 1, "clause": "Retour du capital",
         "detail": "100 % aux associes jusqu'au remboursement des contributions",
         "aux_associes": return_of_capital, "au_cip": 0.0,
         "solde_du_bucket": round(bucket - return_of_capital, 2)},
        {"etape": 2, "clause": "Preferred return (hurdle 8 %)",
         "detail": "100 % aux associes, a hauteur du hurdle acquis",
         "aux_associes": preferred_paid, "au_cip": 0.0,
         "solde_du_bucket": round(bucket - return_of_capital - preferred_paid, 2)},
        {"etape": 3, "clause": "Catch-up",
         "detail": f"100 % au CIP, soit {catch_up_rate:.0%} du preferred return",
         "aux_associes": 0.0, "au_cip": catch_up,
         "solde_du_bucket": remaining},
        {"etape": 4, "clause": f"Partage {1 - carry_split:.0%}/{carry_split:.0%}",
         "detail": "solde partage entre associes et carried interest",
         "aux_associes": split_partners, "au_cip": split_carry,
         "solde_du_bucket": 0.0},
        {"etape": 5, "clause": "TOTAL", "detail": "controle : total = bucket",
         "aux_associes": to_partners, "au_cip": carried_interest,
         "solde_du_bucket": round(bucket - to_partners - carried_interest, 2)},
    ])

    return WaterfallResult(
        bucket=bucket, contributions=round(contributions, 2),
        distributions=round(distributions, 2), nav=round(nav, 2),
        preferred=round(preferred, 2), return_of_capital=return_of_capital,
        preferred_paid=preferred_paid, catch_up=catch_up,
        split_partners=split_partners, split_carry=split_carry,
        carried_interest=carried_interest, to_partners=to_partners, steps=steps)


def carry_accrual_series(contributions: pd.Series, distributions: pd.Series,
                         nav_by_quarter: pd.Series,
                         rate: float = config.PREFERRED_RETURN_RATE,
                         carry_split: float = config.CARRY_SPLIT) -> pd.DataFrame:
    """Run the cascade at every quarter end to follow the carry accrual."""
    rows = []
    for quarter, nav in nav_by_quarter.items():
        quarter = pd.Timestamp(quarter)
        called = float(contributions.loc[contributions.index <= quarter].sum())
        paid = float(distributions.loc[distributions.index <= quarter].sum())
        hurdle = preferred_return(
            contributions.loc[contributions.index <= quarter],
            distributions.loc[distributions.index <= quarter],
            quarter, rate=rate)
        result = run_waterfall(called, paid, float(nav), hurdle.earned,
                               carry_split=carry_split)
        rows.append({
            "trimestre": quarter,
            "contributions_cumulees": result.contributions,
            "distributions_cumulees": result.distributions,
            "valeur_residuelle": result.nav,
            "bucket": result.bucket,
            "preferred_return_acquis": result.preferred,
            "retour_du_capital": result.return_of_capital,
            "preferred_return_paye": result.preferred_paid,
            "catch_up": result.catch_up,
            "carried_interest": result.carried_interest,
            "revenant_aux_associes": result.to_partners,
        })
    return pd.DataFrame(rows)
