"""Performance measurement: multiples and internal rate of return.

The four multiples below are the ones an investor reads first, in the form
the industry has settled on:

    PIC  = paid-in capital / committed capital     how far the fund is drawn
    DPI  = distributions / paid-in capital          what has come back in cash
    RVPI = residual value / paid-in capital         what is still in the fund
    TVPI = (residual value + distributions) / paid-in capital

TVPI is simply DPI plus RVPI. A fund can show a flattering TVPI while
having returned nothing at all, which is exactly why DPI is quoted next to
it.

The rate of return is money-weighted and computed on the dated flows, the
equivalent of Excel's XIRR: in private equity the investor does not choose
when the money moves, so a time-weighted return would measure the wrong
thing.
"""

from __future__ import annotations

import pandas as pd


MAX_ITERATIONS = 200
PRECISION = 1e-9


def _net_present_value(rate: float, amounts, days) -> float:
    return sum(amount / (1 + rate) ** (day / 365.0)
               for amount, day in zip(amounts, days))


def xirr(flows: pd.Series, guess: float = 0.1) -> float | None:
    """Money-weighted rate of return on dated cash flows.

    Sign convention: money leaving the investor is negative, money coming
    back is positive. Returns None when the flows do not change sign, since
    no rate exists in that case.
    """
    flows = flows.groupby(level=0).sum().sort_index()
    flows = flows[flows != 0]
    if len(flows) < 2:
        return None
    amounts = list(flows.values)
    if min(amounts) >= 0 or max(amounts) <= 0:
        return None

    origin = pd.Timestamp(flows.index[0])
    days = [(pd.Timestamp(when) - origin).days for when in flows.index]

    # Bisection on a wide bracket: slower than Newton, but it cannot diverge
    # on the irregular flows a fund produces.
    low, high = -0.9999, 10.0
    value_low = _net_present_value(low, amounts, days)
    value_high = _net_present_value(high, amounts, days)
    if value_low * value_high > 0:
        return None

    for _ in range(MAX_ITERATIONS):
        middle = (low + high) / 2
        value = _net_present_value(middle, amounts, days)
        if abs(value) < PRECISION or (high - low) < PRECISION:
            return round(middle, 6)
        if value_low * value < 0:
            high, value_high = middle, value
        else:
            low, value_low = middle, value
    return round((low + high) / 2, 6)


def multiples(commitment: float, paid_in: float, distributions: float,
              residual_value: float) -> dict:
    """The four standard ratios, guarded against a nil paid-in capital."""
    def ratio(numerator: float, denominator: float) -> float | None:
        return round(numerator / denominator, 4) if denominator else None

    return {
        "PIC": ratio(paid_in, commitment),
        "DPI": ratio(distributions, paid_in),
        "RVPI": ratio(residual_value, paid_in),
        "TVPI": ratio(residual_value + distributions, paid_in),
    }


def investor_performance(commitments: pd.Series, contributions: pd.DataFrame,
                         distributions: pd.DataFrame,
                         closing_balances: pd.Series, as_of) -> pd.DataFrame:
    """One row per partner: amounts, multiples and net rate of return.

    The rate of return is computed on the partner's own flows — capital paid
    in, cash received back — closed by the current value of the interest, as
    if it were sold at its net asset value on the reporting date.
    """
    as_of = pd.Timestamp(as_of)
    rows = []
    for code, commitment in commitments.items():
        paid = contributions.loc[contributions["code"] == code]
        paid = paid.loc[paid["date"] <= as_of]
        received = distributions.loc[distributions["code"] == code]
        received = received.loc[received["date"] <= as_of]

        paid_in = round(float(paid["montant"].sum()), 2)
        given_back = round(float(received["montant"].sum()), 2)
        residual = round(float(closing_balances.get(code, 0.0)), 2)

        flows = pd.concat([
            pd.Series(-paid["montant"].values, index=paid["date"].values),
            pd.Series(received["montant"].values, index=received["date"].values),
            pd.Series([residual], index=[as_of]),
        ])
        rate = xirr(flows) if paid_in else None

        row = {
            "code": code,
            "engagement": round(float(commitment), 2),
            "capital_appele": paid_in,
            "distributions_recues": given_back,
            "valeur_residuelle": residual,
            "valeur_totale": round(given_back + residual, 2),
            "tri_net": rate,
        }
        row.update(multiples(float(commitment), paid_in, given_back, residual))
        rows.append(row)

    frame = pd.DataFrame(rows)
    return frame.sort_values("engagement", ascending=False).reset_index(drop=True)


def fund_performance(fund_commitments: float, paid_in: float,
                     distributions: float, nav: float,
                     flows: pd.Series) -> dict:
    """Fund level ratios and rate of return."""
    result = {
        "engagements": round(fund_commitments, 2),
        "capital_appele": round(paid_in, 2),
        "distributions": round(distributions, 2),
        "valeur_residuelle": round(nav, 2),
        "tri_net": xirr(flows),
    }
    result.update(multiples(fund_commitments, paid_in, distributions, nav))
    return result
