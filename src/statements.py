"""Partners' capital accounts and the investor reporting built on them.

The capital account statement is the document a limited partner actually
reads. It answers four questions in one page: what did I pay in, what came
back, what is my share worth today, and what did the manager take.

Each quarter moves a partner's account like this:

    opening balance
    + contributions of the quarter
    - distributions of the quarter
    + share of the result of the fund
    - share of the carried interest accrued over the quarter
    = closing balance

The carried interest is not an expense of the fund: it is a reallocation of
equity from the partners to the carried interest partner. It therefore
leaves the fund's net asset value untouched, which is the control applied
at the end of this module.
"""

from __future__ import annotations

import pandas as pd

from src import allocations, config

CIP_CODE = "CIP"
CIP_NAME = "Carried interest partner (GP)"

MOVEMENT_COLUMNS = [
    "solde_ouverture", "contributions", "distributions",
    "quote_part_gain_net", "quote_part_commission", "quote_part_frais",
    "carried_interest", "solde_cloture",
]


def build_capital_accounts(investors: pd.DataFrame, nav_by_quarter: pd.DataFrame,
                           calls: pd.DataFrame, distributions: pd.DataFrame,
                           carry: pd.DataFrame) -> pd.DataFrame:
    """Walk every quarter and every partner, and return the movements."""
    names = investors.set_index("code")["nom"]
    codes = list(investors["code"])

    balances = {code: 0.0 for code in codes}
    balances[CIP_CODE] = 0.0
    carry_previous = 0.0
    rows = []

    carry_by_quarter = carry.set_index("trimestre")["carried_interest"]

    for _, quarter in nav_by_quarter.iterrows():
        when = pd.Timestamp(quarter["trimestre"])

        gain = allocations.allocate(float(quarter["gain_net_investissements"]),
                                    investors)
        fee = allocations.allocate(float(quarter["commission_gestion"]), investors)
        costs = allocations.allocate(float(quarter["frais_de_fonctionnement"]),
                                     investors)

        called = (calls.loc[calls["date"] == when].set_index("code")["montant"]
                  if not calls.empty else pd.Series(dtype=float))
        paid = (distributions.loc[distributions["date"] == when]
                .set_index("code")["montant"]
                if not distributions.empty else pd.Series(dtype=float))

        carry_total = float(carry_by_quarter.get(when, 0.0))
        carry_movement = round(carry_total - carry_previous, 2)
        carry_previous = carry_total
        carry_share = allocations.allocate(carry_movement, investors)

        for code in codes:
            opening = balances[code]
            contribution = round(float(called.get(code, 0.0)), 2)
            distribution = round(float(paid.get(code, 0.0)), 2)
            closing = round(opening + contribution - distribution
                            + float(gain[code]) - float(fee[code])
                            - float(costs[code]) - float(carry_share[code]), 2)
            rows.append({
                "trimestre": when,
                "code": code,
                "nom": names.get(code, code),
                "role": "ASSOCIE",
                "solde_ouverture": round(opening, 2),
                "contributions": contribution,
                "distributions": distribution,
                "quote_part_gain_net": round(float(gain[code]), 2),
                "quote_part_commission": round(-float(fee[code]), 2),
                "quote_part_frais": round(-float(costs[code]), 2),
                "carried_interest": round(-float(carry_share[code]), 2),
                "solde_cloture": closing,
            })
            balances[code] = closing

        opening = balances[CIP_CODE]
        closing = round(opening + carry_movement, 2)
        rows.append({
            "trimestre": when, "code": CIP_CODE, "nom": CIP_NAME,
            "role": "CARRIED INTEREST",
            "solde_ouverture": round(opening, 2), "contributions": 0.0,
            "distributions": 0.0, "quote_part_gain_net": 0.0,
            "quote_part_commission": 0.0, "quote_part_frais": 0.0,
            "carried_interest": carry_movement, "solde_cloture": closing,
        })
        balances[CIP_CODE] = closing

    return pd.DataFrame(rows)


def capital_account_statement(accounts: pd.DataFrame, as_of) -> pd.DataFrame:
    """The statement itself: one row per partner, since inception."""
    as_of = pd.Timestamp(as_of)
    upto = accounts.loc[accounts["trimestre"] <= as_of]
    if upto.empty:
        return pd.DataFrame()

    grouped = upto.groupby(["code", "nom", "role"], as_index=False).agg(
        contributions=("contributions", "sum"),
        distributions=("distributions", "sum"),
        quote_part_gain_net=("quote_part_gain_net", "sum"),
        quote_part_commission=("quote_part_commission", "sum"),
        quote_part_frais=("quote_part_frais", "sum"),
        carried_interest=("carried_interest", "sum"),
    )
    closing = (upto.loc[upto["trimestre"] == upto["trimestre"].max()]
               .set_index("code")["solde_cloture"])
    grouped["solde_cloture"] = grouped["code"].map(closing).round(2)
    for column in ("contributions", "distributions", "quote_part_gain_net",
                   "quote_part_commission", "quote_part_frais",
                   "carried_interest"):
        grouped[column] = grouped[column].round(2)
    grouped["resultat_net_attribue"] = (
        grouped["quote_part_gain_net"] + grouped["quote_part_commission"]
        + grouped["quote_part_frais"]).round(2)
    return grouped.sort_values("solde_cloture", ascending=False).reset_index(drop=True)


def statement_for(accounts: pd.DataFrame, code: str) -> pd.DataFrame:
    """The quarter-by-quarter statement of one partner."""
    selected = accounts.loc[accounts["code"] == code].copy()
    if selected.empty:
        raise ValueError(f"associe inconnu : {code}")
    return selected.sort_values("trimestre")[
        ["trimestre"] + MOVEMENT_COLUMNS].reset_index(drop=True)


def partners_capital_reconciliation(accounts: pd.DataFrame,
                                    nav_by_quarter: pd.DataFrame) -> pd.DataFrame:
    """Sum of the capital accounts against the fund's net asset value."""
    totals = (accounts.groupby("trimestre", as_index=False)["solde_cloture"].sum()
              .rename(columns={"solde_cloture": "total_comptes_associes"}))
    merged = totals.merge(
        nav_by_quarter[["trimestre", "nav_avant_carried"]], on="trimestre",
        how="left")
    merged["ecart"] = (merged["total_comptes_associes"]
                       - merged["nav_avant_carried"]).round(2)
    merged["equilibre"] = merged["ecart"].abs() <= config.TOLERANCE
    return merged
