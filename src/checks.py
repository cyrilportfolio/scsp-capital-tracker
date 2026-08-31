"""Consistency checks run on the fund before anything is reported.

A capital account statement that does not tie back to the fund's net asset
value is worse than no statement at all: it is wrong in a way the investor
cannot see. These checks are the ones a fund accountant runs before a
quarterly reporting pack leaves the office.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src import allocations, config, nav as nav_module

ANOMALY_COLUMNS = ["code_controle", "libelle_controle", "severite", "objet",
                   "date", "montant", "message"]


@dataclass(frozen=True)
class Severity:
    BLOCKING: str = "bloquant"
    MAJOR: str = "majeur"
    MINOR: str = "mineur"


SEVERITY = Severity()

CHECKS = {
    "ALLOCATION_TOTALE": ("Total des parts d'allocation egal a 100 %", SEVERITY.BLOCKING),
    "ALLOCATION_RESIDU": ("Allocation qui ne retombe pas sur le montant reparti", SEVERITY.BLOCKING),
    "COMPTES_ASSOCIES_NAV": ("Somme des comptes associes egale a la NAV", SEVERITY.BLOCKING),
    "NAV_RECONCILIATION": ("Variation de NAV expliquee par le resultat et les flux", SEVERITY.BLOCKING),
    "TRESORERIE_NEGATIVE": ("Tresorerie du fonds negative", SEVERITY.BLOCKING),
    "WATERFALL_BOUCLE": ("Cascade qui distribue exactement le bucket", SEVERITY.BLOCKING),
    "ENGAGEMENT_DEPASSE": ("Capital appele superieur a l'engagement", SEVERITY.MAJOR),
    "CARRY_COMPOSITION": ("Carried interest egal au catch-up plus le partage", SEVERITY.MAJOR),
    "CESSION_SANS_PRODUIT": ("Cession sans produit de cession", SEVERITY.MAJOR),
    "MARK_MANQUANT": ("Participation detenue sans valorisation au trimestre", SEVERITY.MAJOR),
    "CARRY_AVANT_HURDLE": ("Carried interest accru avant le hurdle", SEVERITY.MAJOR),
    "APPEL_APRES_PERIODE": ("Appel de capital apres la periode d'investissement", SEVERITY.MINOR),
    "COMMISSION_SANS_STEP_DOWN": ("Commission de gestion sans reduction d'assiette", SEVERITY.MINOR),
}


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=ANOMALY_COLUMNS)


def _finding(code: str, objet: str, when, montant: float, message: str) -> dict:
    libelle, severite = CHECKS[code]
    return {"code_controle": code, "libelle_controle": libelle,
            "severite": severite, "objet": objet, "date": when,
            "montant": round(float(montant), 2), "message": message}


def check_allocations(investors: pd.DataFrame) -> list[dict]:
    found = []
    total = float(allocations.shares(investors).sum())
    if abs(total - 1.0) > config.ALLOCATION_TOLERANCE:
        found.append(_finding("ALLOCATION_TOTALE", "referentiel", pd.NaT,
                              total - 1.0,
                              f"total des parts = {total:.10f} au lieu de 1"))
    for amount in (1.0, 12_345.67, 999_999.99, 1_000_000.0):
        split = allocations.allocate(amount, investors)
        residue = round(float(split.sum()) - amount, 2)
        if abs(residue) > 0.001:
            found.append(_finding("ALLOCATION_RESIDU", "referentiel", pd.NaT,
                                  residue,
                                  f"repartition de {amount:,.2f} EUR : "
                                  f"residu de {residue:.2f} EUR"))
    return found


def check_commitments(status: pd.DataFrame) -> list[dict]:
    found = []
    for _, row in status.iterrows():
        if row["non_appele"] < -config.TOLERANCE:
            found.append(_finding(
                "ENGAGEMENT_DEPASSE", row["code"], pd.NaT, row["non_appele"],
                f"{row['appele']:,.2f} EUR appeles pour un engagement de "
                f"{row['engagement']:,.2f} EUR"))
    return found


def check_nav_reconciliation(nav_by_quarter: pd.DataFrame) -> list[dict]:
    found = []
    for _, row in nav_by_quarter.iterrows():
        if abs(row["ecart_reconciliation"]) > config.TOLERANCE:
            found.append(_finding(
                "NAV_RECONCILIATION", "fonds", row["trimestre"],
                row["ecart_reconciliation"],
                f"variation de NAV {row['variation_nav']:,.2f} EUR contre "
                f"{row['resultat_net'] + row['appels'] - row['distributions']:,.2f} "
                "EUR attendus"))
    return found


def check_partners_capital(reconciliation: pd.DataFrame) -> list[dict]:
    found = []
    for _, row in reconciliation.iterrows():
        if not row["equilibre"]:
            found.append(_finding(
                "COMPTES_ASSOCIES_NAV", "fonds", row["trimestre"], row["ecart"],
                f"comptes associes {row['total_comptes_associes']:,.2f} EUR "
                f"contre une NAV de {row['nav_avant_carried']:,.2f} EUR"))
    return found


def check_cash(fund, quarters) -> list[dict]:
    found = []
    for quarter in quarters:
        cash = nav_module.cash_balance(fund.cashflows, quarter)
        if cash < -config.TOLERANCE:
            found.append(_finding("TRESORERIE_NEGATIVE", "fonds", quarter, cash,
                                  f"tresorerie de {cash:,.2f} EUR"))
    return found


def check_waterfall(result) -> list[dict]:
    found = []
    ecart = round(result.bucket - result.to_partners - result.carried_interest, 2)
    if abs(ecart) > config.TOLERANCE:
        found.append(_finding("WATERFALL_BOUCLE", "cascade", pd.NaT, ecart,
                              f"bucket de {result.bucket:,.2f} EUR reparti a "
                              f"{result.to_partners + result.carried_interest:,.2f} EUR"))
    composition = round(result.catch_up + result.split_carry
                        - result.carried_interest, 2)
    if abs(composition) > config.TOLERANCE:
        found.append(_finding("CARRY_COMPOSITION", "cascade", pd.NaT, composition,
                              "le carried interest ne vaut pas le catch-up "
                              "plus le partage"))
    if (result.carried_interest > config.TOLERANCE
            and result.preferred_paid + config.TOLERANCE < result.preferred):
        found.append(_finding("CARRY_AVANT_HURDLE", "cascade", pd.NaT,
                              result.carried_interest,
                              "du carried interest est accru alors que le "
                              "preferred return n'est pas servi en totalite"))
    return found


def check_portfolio(fund, quarters) -> list[dict]:
    found = []
    for _, item in fund.portfolio.iterrows():
        if item["cede"] and item["produit_cession"] <= 0:
            found.append(_finding("CESSION_SANS_PRODUIT", item["code"],
                                  item["date_cession"], 0.0,
                                  f"{item['societe']} est cedee sans produit"))
    marks = fund.marks.set_index(["code", "date_valorisation"]).index
    for quarter in quarters:
        stamp = pd.Timestamp(quarter)
        for _, item in fund.portfolio.iterrows():
            held = (item["date_acquisition"] <= stamp
                    and (pd.isna(item["date_cession"])
                         or item["date_cession"] > stamp))
            if held and (item["code"], stamp) not in marks:
                found.append(_finding("MARK_MANQUANT", item["code"], stamp, 0.0,
                                      f"{item['societe']} detenue sans "
                                      "valorisation a cette date"))
    return found


def check_fund_terms(fund) -> list[dict]:
    found = []
    late = fund.cashflows.loc[
        (fund.cashflows["type"] == config.CAPITAL_CALL)
        & (fund.cashflows["date"] > pd.Timestamp(config.INVESTMENT_PERIOD_END))]
    for _, row in late.iterrows():
        found.append(_finding("APPEL_APRES_PERIODE", "fonds", row["date"],
                              row["montant"],
                              "appel posterieur a la fin de la periode "
                              "d'investissement"))

    fees = fund.cashflows.loc[fund.cashflows["type"] == config.MANAGEMENT_FEE]
    after = fees.loc[fees["date"] > pd.Timestamp(config.INVESTMENT_PERIOD_END)]
    if not after.empty:
        expected = nav_module.management_fee_basis(
            fund, after["date"].max())["commission_annuelle"] / 4
        for _, row in after.iterrows():
            if row["montant"] > expected + config.TOLERANCE:
                found.append(_finding(
                    "COMMISSION_SANS_STEP_DOWN", "fonds", row["date"],
                    row["montant"] - expected,
                    f"commission de {row['montant']:,.2f} EUR pour une "
                    f"assiette reduite a {expected:,.2f} EUR"))
    return found


def run_all(fund, quarters, status, nav_by_quarter, reconciliation,
            waterfall_result) -> pd.DataFrame:
    findings: list[dict] = []
    findings += check_allocations(fund.investors)
    findings += check_commitments(status)
    findings += check_nav_reconciliation(nav_by_quarter)
    findings += check_partners_capital(reconciliation)
    findings += check_cash(fund, quarters)
    findings += check_waterfall(waterfall_result)
    findings += check_portfolio(fund, quarters)
    findings += check_fund_terms(fund)

    if not findings:
        return _empty()
    frame = pd.DataFrame(findings)[ANOMALY_COLUMNS]
    order = {SEVERITY.BLOCKING: 0, SEVERITY.MAJOR: 1, SEVERITY.MINOR: 2}
    frame["rang"] = frame["severite"].map(order).fillna(3)
    return (frame.sort_values(["rang", "code_controle"])
            .drop(columns="rang").reset_index(drop=True))


def summarise(anomalies: pd.DataFrame) -> pd.DataFrame:
    counts = (anomalies.groupby("code_controle").size()
              if not anomalies.empty else pd.Series(dtype=int))
    rows = [{"code_controle": code, "libelle_controle": libelle,
             "severite": severite, "anomalies": int(counts.get(code, 0)),
             "statut": "A CORRIGER" if counts.get(code, 0) else "OK"}
            for code, (libelle, severite) in CHECKS.items()]
    frame = pd.DataFrame(rows)
    order = {SEVERITY.BLOCKING: 0, SEVERITY.MAJOR: 1, SEVERITY.MINOR: 2}
    frame["rang"] = frame["severite"].map(order).fillna(3)
    return frame.sort_values(["rang", "code_controle"]).drop(
        columns="rang").reset_index(drop=True)


def has_blocking(anomalies: pd.DataFrame) -> bool:
    if anomalies.empty:
        return False
    return bool((anomalies["severite"] == SEVERITY.BLOCKING).any())
