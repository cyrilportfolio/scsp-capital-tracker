"""Capital calls, drawn commitments and what is left uncalled."""

from __future__ import annotations

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


def call_notice(calls: pd.DataFrame, investors: pd.DataFrame,
                reference: str) -> pd.DataFrame:
    """The notice sent to each partner for one capital call."""
    selected = calls.loc[calls["appel"] == reference]
    if selected.empty:
        raise ValueError(f"appel inconnu : {reference}")
    names = investors.set_index("code")["nom"]
    notice = selected[["code", "montant", "date", "montant_appel_total"]].copy()
    notice["nom"] = notice["code"].map(names)
    notice["date_limite_paiement"] = notice["date"] + pd.Timedelta(days=10)
    return notice[["code", "nom", "date", "date_limite_paiement",
                   "montant", "montant_appel_total"]].reset_index(drop=True)
