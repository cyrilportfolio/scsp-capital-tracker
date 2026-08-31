"""Valuation of the portfolio and net asset value of the fund.

The fund is an investment entity: its investments are carried at fair value
and every change in that value goes through the result of the period. The
result of a quarter therefore breaks down into three pieces — the net gain
on investments, the management fee, and the operating expenses of the fund.

The net gain is computed on the whole portfolio at once rather than line by
line, which avoids double counting when an investment is sold during the
quarter:

    net gain = (closing fair value + proceeds received)
             - (opening fair value + cost of acquisitions)
"""

from __future__ import annotations

import pandas as pd

from src import config
from src.ingest import FundData


def portfolio_value(fund: FundData, as_of) -> float:
    """Fair value of the investments still held at a date."""
    as_of = pd.Timestamp(as_of)
    marks = fund.marks.loc[fund.marks["date_valorisation"] == as_of]
    return round(float(marks["juste_valeur"].sum()), 2)


def portfolio_detail(fund: FundData, as_of) -> pd.DataFrame:
    """One row per investment: cost, fair value, unrealised gain, multiple."""
    as_of = pd.Timestamp(as_of)
    marks = (fund.marks.loc[fund.marks["date_valorisation"] == as_of]
             .set_index("code")["juste_valeur"])

    rows = []
    for _, item in fund.portfolio.iterrows():
        if pd.notna(item["date_acquisition"]) and item["date_acquisition"] > as_of:
            continue
        sold = pd.notna(item["date_cession"]) and item["date_cession"] <= as_of
        fair_value = 0.0 if sold else float(marks.get(item["code"], 0.0))
        proceeds = float(item["produit_cession"]) if sold else 0.0
        cost = float(item["cout_acquisition"])
        total = fair_value + proceeds
        rows.append({
            "code": item["code"],
            "societe": item["societe"],
            "secteur": item["secteur"],
            "pays": item["pays"],
            "date_acquisition": item["date_acquisition"],
            "cout_acquisition": round(cost, 2),
            "statut": "Cedee" if sold else "Detenue",
            "juste_valeur": round(fair_value, 2),
            "produit_cession": round(proceeds, 2),
            "plus_value_latente": round(fair_value - (0.0 if sold else cost), 2),
            "plus_value_realisee": round(proceeds - cost, 2) if sold else 0.0,
            "multiple": round(total / cost, 3) if cost else 0.0,
        })
    return pd.DataFrame(rows)


def cash_balance(cashflows: pd.DataFrame, as_of) -> float:
    """Cash held by the fund at a date."""
    as_of = pd.Timestamp(as_of)
    upto = cashflows.loc[cashflows["date"] <= as_of]
    inflow = upto.loc[upto["type"].isin(config.INFLOWS), "montant"].sum()
    outflow = upto.loc[upto["type"].isin(config.OUTFLOWS), "montant"].sum()
    return round(float(inflow - outflow), 2)


def _sum_between(cashflows: pd.DataFrame, kind: str, start, end) -> float:
    mask = ((cashflows["type"] == kind)
            & (cashflows["date"] > pd.Timestamp(start))
            & (cashflows["date"] <= pd.Timestamp(end)))
    return round(float(cashflows.loc[mask, "montant"].sum()), 2)


def quarterly_nav(fund: FundData, quarters: list) -> pd.DataFrame:
    """Fund level figures, quarter by quarter, before carried interest."""
    rows = []
    previous = None
    for quarter in quarters:
        start = previous if previous is not None else pd.Timestamp(quarter) - pd.Timedelta(days=1)
        opening_value = portfolio_value(fund, previous) if previous is not None else 0.0
        closing_value = portfolio_value(fund, quarter)

        acquisitions = _sum_between(fund.cashflows, config.INVESTMENT, start, quarter)
        proceeds = _sum_between(fund.cashflows, config.EXIT_PROCEEDS, start, quarter)
        fee = _sum_between(fund.cashflows, config.MANAGEMENT_FEE, start, quarter)
        expenses = _sum_between(fund.cashflows, config.FUND_EXPENSE, start, quarter)
        calls = _sum_between(fund.cashflows, config.CAPITAL_CALL, start, quarter)
        distributions = _sum_between(fund.cashflows, config.DISTRIBUTION, start, quarter)

        gain = round((closing_value + proceeds) - (opening_value + acquisitions), 2)
        result = round(gain - fee - expenses, 2)
        cash = cash_balance(fund.cashflows, quarter)
        nav = round(closing_value + cash, 2)

        rows.append({
            "trimestre": pd.Timestamp(quarter),
            "juste_valeur_portefeuille": closing_value,
            "tresorerie": cash,
            "nav_avant_carried": nav,
            "appels": calls,
            "distributions": distributions,
            "gain_net_investissements": gain,
            "commission_gestion": fee,
            "frais_de_fonctionnement": expenses,
            "resultat_net": result,
        })
        previous = pd.Timestamp(quarter)

    frame = pd.DataFrame(rows)
    frame["nav_ouverture"] = frame["nav_avant_carried"].shift(1).fillna(0.0)
    frame["variation_nav"] = (frame["nav_avant_carried"] - frame["nav_ouverture"]).round(2)
    # The identity every fund accountant checks: the change in NAV is the
    # result of the period plus what came in, less what went out.
    frame["ecart_reconciliation"] = (
        frame["variation_nav"]
        - (frame["resultat_net"] + frame["appels"] - frame["distributions"])
    ).round(2)
    return frame


def management_fee_basis(fund: FundData, as_of) -> dict:
    """Which base the fee is charged on, and what it comes to for a year.

    During the investment period the fee is charged on total commitments;
    once that period is over it steps down to the acquisition cost of the
    investments still held. Forgetting that step-down is one of the classic
    overcharges an investor's accountant looks for.
    """
    as_of = pd.Timestamp(as_of)
    in_investment_period = as_of <= pd.Timestamp(config.INVESTMENT_PERIOD_END)
    if in_investment_period:
        basis = fund.total_commitments
        label = config.FEE_BASIS_INVESTMENT_PERIOD
    else:
        held = fund.portfolio.loc[
            fund.portfolio["date_cession"].isna()
            | (fund.portfolio["date_cession"] > as_of)]
        basis = round(float(held["cout_acquisition"].sum()), 2)
        label = config.FEE_BASIS_AFTER
    return {
        "date": as_of,
        "periode_investissement": in_investment_period,
        "assiette": label,
        "montant_assiette": basis,
        "taux": config.MANAGEMENT_FEE_RATE,
        "commission_annuelle": round(basis * config.MANAGEMENT_FEE_RATE, 2),
    }
