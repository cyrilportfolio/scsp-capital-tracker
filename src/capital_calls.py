"""Capital calls, drawn commitments and what is left uncalled.

The notice at the end of this module is the document the partner actually
receives, and the ILPA template fixes what it has to carry: the reference
and the two dates that matter, each partner's commitment with the drawn and
unfunded amounts before and after the call, and — the part investors read
first — what the money is being called for.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from src import allocations, config


def call_schedule(cashflows: pd.DataFrame, investors: pd.DataFrame) -> pd.DataFrame:
    """One row per call and per partner, with the amount drawn from each."""
    calls = cashflows.loc[cashflows["type"] == config.CAPITAL_CALL]
    rows = []
    for number, (_, call) in enumerate(calls.iterrows(), start=1):
        split = allocations.allocate(float(call["montant"]), investors)
        for code, amount in split.items():
            rows.append({
                "appel": f"AC-{call['date']:%Y}-{number:02d}",
                "date": call["date"],
                "code": code,
                "montant_appel_total": round(float(call["montant"]), 2),
                "montant": round(float(amount), 2),
            })
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(columns=["appel", "date", "code",
                                     "montant_appel_total", "montant"])
    return frame


def distribution_schedule(cashflows: pd.DataFrame,
                          investors: pd.DataFrame) -> pd.DataFrame:
    """One row per distribution and per partner.

    Distributions are shared here on the same commitment basis; the split
    between return of capital, preferred return and carried interest is the
    waterfall's business, not this function's.
    """
    distributions = cashflows.loc[cashflows["type"] == config.DISTRIBUTION]
    rows = []
    for number, (_, item) in enumerate(distributions.iterrows(), start=1):
        split = allocations.allocate(float(item["montant"]), investors)
        for code, amount in split.items():
            rows.append({
                "distribution": f"DI-{item['date']:%Y}-{number:02d}",
                "date": item["date"],
                "code": code,
                "montant_total": round(float(item["montant"]), 2),
                "montant": round(float(amount), 2),
            })
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(columns=["distribution", "date", "code",
                                     "montant_total", "montant"])
    return frame


def commitment_status(investors: pd.DataFrame, calls: pd.DataFrame,
                      as_of) -> pd.DataFrame:
    """Commitment, amount drawn and remaining unfunded commitment."""
    as_of = pd.Timestamp(as_of)
    drawn = (calls.loc[calls["date"] <= as_of].groupby("code")["montant"].sum()
             if not calls.empty else pd.Series(dtype=float))

    frame = investors[["code", "nom", "type", "engagement"]].copy()
    frame["appele"] = frame["code"].map(drawn).fillna(0.0).round(2)
    frame["non_appele"] = (frame["engagement"] - frame["appele"]).round(2)
    frame["pct_appele"] = (frame["appele"] / frame["engagement"]).round(6)
    return frame.sort_values("engagement", ascending=False).reset_index(drop=True)


@dataclass
class CallNotice:
    """One capital call, as it goes out to the partners."""

    reference: str
    notice_date: pd.Timestamp
    funding_date: pd.Timestamp
    amount: float
    allocation: pd.DataFrame = field(repr=False, default_factory=pd.DataFrame)
    purpose: pd.DataFrame = field(repr=False, default_factory=pd.DataFrame)


def call_references(calls: pd.DataFrame, as_of=None) -> list[str]:
    """Every call reference, oldest first, up to a date."""
    if calls.empty:
        return []
    selected = calls if as_of is None else calls.loc[calls["date"] <= pd.Timestamp(as_of)]
    return list(selected.sort_values("date")["appel"].unique())


def call_purpose(cashflows: pd.DataFrame, when, amount: float) -> pd.DataFrame:
    """What the call funds, reconciled to the amount called.

    A call is sized on the quarter's outgoings, less the cash already in the
    account, plus the operating buffer the administrator keeps. Laying the
    three out is what makes the notice auditable: the lines add back exactly
    to the amount called, so an investor can see that the fund is not
    drawing more than it needs.
    """
    when = pd.Timestamp(when)
    same_day = cashflows.loc[cashflows["date"] == when]

    def total(kind: str) -> float:
        return round(float(same_day.loc[same_day["type"] == kind, "montant"].sum()), 2)

    investments = total(config.INVESTMENT)
    fee = total(config.MANAGEMENT_FEE)
    expenses = total(config.FUND_EXPENSE)
    needs = round(investments + fee + expenses, 2)

    # Cash held the day before the call: it reduces what has to be drawn.
    previous = cashflows.loc[cashflows["date"] < when]
    opening = round(float(
        previous.loc[previous["type"].isin(config.INFLOWS), "montant"].sum()
        - previous.loc[previous["type"].isin(config.OUTFLOWS), "montant"].sum()), 2)

    working_capital = round(amount - needs + opening, 2)

    rows = [
        ("Investissements du trimestre", investments),
        ("Commission de gestion", fee),
        ("Frais de fonctionnement", expenses),
        ("Besoins de tresorerie du trimestre", needs),
        ("Tresorerie disponible a l'ouverture", -opening),
        ("Fonds de roulement laisse au fonds", working_capital),
        ("TOTAL APPELE", round(amount, 2)),
    ]
    return pd.DataFrame(rows, columns=["poste", "montant"])


def call_notice(calls: pd.DataFrame, investors: pd.DataFrame,
                cashflows: pd.DataFrame, reference: str) -> CallNotice:
    """The notice sent to each partner for one capital call.

    Each partner sees the same four figures an ILPA notice carries: what was
    already drawn on the commitment, what this call draws, what that brings
    the total to, and what is left uncalled afterwards.
    """
    selected = calls.loc[calls["appel"] == reference]
    if selected.empty:
        raise ValueError(f"appel inconnu : {reference}")

    funding_date = pd.Timestamp(selected["date"].iloc[0])
    notice_date = funding_date - pd.tseries.offsets.BusinessDay(
        config.CALL_NOTICE_BUSINESS_DAYS)
    amount = round(float(selected["montant_appel_total"].iloc[0]), 2)

    earlier = calls.loc[calls["date"] < funding_date]
    drawn_before = (earlier.groupby("code")["montant"].sum()
                    if not earlier.empty else pd.Series(dtype=float))
    this_call = selected.set_index("code")["montant"]

    frame = investors[["code", "nom", "engagement"]].copy()
    frame["appele_avant"] = frame["code"].map(drawn_before).fillna(0.0).round(2)
    frame["montant_appele"] = frame["code"].map(this_call).fillna(0.0).round(2)
    frame["appele_apres"] = (frame["appele_avant"] + frame["montant_appele"]).round(2)
    frame["non_appele"] = (frame["engagement"] - frame["appele_apres"]).round(2)
    frame["pct_appele"] = (frame["appele_apres"] / frame["engagement"]).round(6)
    frame["date_avis"] = notice_date
    frame["date_de_reglement"] = funding_date
    frame = frame.sort_values("engagement", ascending=False).reset_index(drop=True)

    return CallNotice(
        reference=reference, notice_date=notice_date, funding_date=funding_date,
        amount=amount, allocation=frame,
        purpose=call_purpose(cashflows, funding_date, amount))
