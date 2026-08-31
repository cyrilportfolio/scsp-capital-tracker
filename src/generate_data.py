"""Builds the synthetic dataset of a Luxembourg SCSp private equity fund.

The scenario is written by hand rather than drawn at random: a fund's
history has to hold together — calls must cover the cash needs, an exit must
follow an acquisition, marks must move for a reason. A designed scenario is
also stable, which is what lets the README quote figures that stay true.

Four files are produced:

* ``investors.csv``  — the partners and their commitments;
* ``portfolio.csv``  — the investments, their cost and their exit;
* ``marks.csv``      — quarterly fair values, investment by investment;
* ``cashflows.csv``  — every movement on the fund's bank account.

Nothing here comes from a real fund.
"""

from __future__ import annotations

import argparse
import csv
from datetime import date
from pathlib import Path

from src import config

# --------------------------------------------------------------------------
# The partners
# --------------------------------------------------------------------------
INVESTORS = [
    # code, name, type, country, commitment
    ("LP01", "PENSIONSKASSE NORDLICHT", "LP", "DE", 15_000_000),
    ("LP02", "ASSURANCE VIE MOSELLE SA", "LP", "LU", 12_000_000),
    ("LP03", "FONDATION VAN DER MEULEN", "LP", "NL", 10_000_000),
    ("LP04", "FAMILY OFFICE BELVAL SARL", "LP", "LU", 7_000_000),
    ("LP05", "CAISSE DE RETRAITE DES ARDENNES", "LP", "BE", 5_500_000),
    ("GP01", "DEMO LUX PE GP SARL", "GP", "LU", 500_000),
]

# --------------------------------------------------------------------------
# The portfolio
# --------------------------------------------------------------------------
# code, company, sector, country, acquisition, cost, annual mark growth,
# exit date, exit proceeds
PORTFOLIO = [
    ("PC01", "ARDENNE LOGISTICS SA", "Transport et logistique", "LU",
     date(2022, 3, 31), 8_000_000, 0.16, None, None),
    ("PC02", "MOSELLE MEDTECH SAS", "Sante", "FR",
     date(2022, 9, 30), 6_500_000, 0.42, date(2025, 6, 30), 18_200_000),
    ("PC03", "KIRCHBERG SAAS SA", "Logiciel", "LU",
     date(2023, 3, 31), 9_000_000, 0.12, None, None),
    ("PC04", "SURE INDUSTRIES NV", "Industrie", "BE",
     date(2023, 9, 30), 7_500_000, -0.05, None, None),
    ("PC05", "ALZETTE RENEWABLES SA", "Energie", "LU",
     date(2024, 6, 30), 6_000_000, 0.03, None, None),
]

QUARTERLY_FUND_EXPENSE = 30_000
DISTRIBUTION_DATE = date(2025, 6, 30)
DISTRIBUTION_AMOUNT = 17_500_000
CALL_ROUNDING = 10_000
CASH_BUFFER = 50_000


def _round_to(value: float, step: int) -> float:
    """Round up to the next step, the way a call notice is sized."""
    return float(step * -(-value // step))


def _years_between(start: date, end: date) -> float:
    return (end - start).days / 365.25


def build_marks() -> list[dict]:
    """Quarterly fair value of every investment still held."""
    rows = []
    for code, _, _, _, acquired, cost, growth, exit_date, _ in PORTFOLIO:
        for quarter in config.quarter_ends(config.REPORTING_START,
                                           config.REPORTING_END):
            if quarter < acquired:
                continue
            if exit_date and quarter >= exit_date:
                continue
            years = _years_between(acquired, quarter)
            value = cost * (1 + growth) ** years
            rows.append({
                "code": code,
                "date_valorisation": quarter.isoformat(),
                "juste_valeur": round(value, -3),
            })
    return rows


def build_cashflows() -> list[dict]:
    """Walk the fund quarter by quarter and call capital when cash is short.

    A capital call is issued at the start of a quarter, sized on the cash the
    quarter will consume, rounded up to the next EUR 10 000 and kept above a
    small operating buffer — which is how a fund administrator sizes one.
    """
    quarters = config.quarter_ends(config.REPORTING_START, config.REPORTING_END)
    fee_per_quarter = round(
        sum(i[4] for i in INVESTORS) * config.MANAGEMENT_FEE_RATE / 4, 2)

    flows: list[dict] = []
    cash = 0.0

    for quarter in quarters:
        planned: list[tuple[str, float, str, str]] = []

        for code, company, _, _, acquired, cost, _, exit_date, proceeds in PORTFOLIO:
            if acquired == quarter:
                planned.append((config.INVESTMENT, cost, code,
                                f"Acquisition {company}"))
        planned.append((config.MANAGEMENT_FEE, fee_per_quarter, "GP01",
                        "Commission de gestion du trimestre"))
        planned.append((config.FUND_EXPENSE, QUARTERLY_FUND_EXPENSE, "",
                        "Frais de fonctionnement du fonds"))

        needed = sum(amount for _, amount, _, _ in planned)
        if cash - needed < CASH_BUFFER:
            call = _round_to(needed - cash + CASH_BUFFER, CALL_ROUNDING)
            flows.append({"date": quarter.isoformat(), "type": config.CAPITAL_CALL,
                          "montant": call, "reference": "",
                          "libelle": "Appel de capital"})
            cash += call

        for kind, amount, reference, label in planned:
            flows.append({"date": quarter.isoformat(), "type": kind,
                          "montant": amount, "reference": reference,
                          "libelle": label})
            cash -= amount

        for code, company, _, _, _, _, _, exit_date, proceeds in PORTFOLIO:
            if exit_date == quarter:
                flows.append({"date": quarter.isoformat(),
                              "type": config.EXIT_PROCEEDS, "montant": proceeds,
                              "reference": code, "libelle": f"Cession {company}"})
                cash += proceeds

        if quarter == DISTRIBUTION_DATE:
            flows.append({"date": quarter.isoformat(), "type": config.DISTRIBUTION,
                          "montant": DISTRIBUTION_AMOUNT, "reference": "",
                          "libelle": "Distribution aux associes"})
            cash -= DISTRIBUTION_AMOUNT

    return flows


def _write(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames,
                                delimiter=config.CSV_SEPARATOR)
        writer.writeheader()
        writer.writerows(rows)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Genere les jeux de donnees synthetiques du fonds.")
    parser.add_argument("--out", type=Path, default=config.DATA_DIR)
    args = parser.parse_args(argv)

    _write(args.out / "investors.csv",
           [{"code": c, "nom": n, "type": t, "pays": p, "engagement": e,
             "date_admission": config.FIRST_CLOSING.isoformat()}
            for c, n, t, p, e in INVESTORS],
           ["code", "nom", "type", "pays", "engagement", "date_admission"])

    _write(args.out / "portfolio.csv",
           [{"code": c, "societe": s, "secteur": sec, "pays": p,
             "date_acquisition": a.isoformat(), "cout_acquisition": cost,
             "date_cession": (x.isoformat() if x else ""),
             "produit_cession": (pr if pr else "")}
            for c, s, sec, p, a, cost, _, x, pr in PORTFOLIO],
           ["code", "societe", "secteur", "pays", "date_acquisition",
            "cout_acquisition", "date_cession", "produit_cession"])

    marks = build_marks()
    _write(args.out / "marks.csv", marks,
           ["code", "date_valorisation", "juste_valeur"])

    flows = build_cashflows()
    _write(args.out / "cashflows.csv", flows,
           ["date", "type", "montant", "reference", "libelle"])

    called = sum(f["montant"] for f in flows if f["type"] == config.CAPITAL_CALL)
    committed = sum(i[4] for i in INVESTORS)
    print(f"investors.csv  : {len(INVESTORS)} associes, "
          f"{committed:,.0f} EUR d'engagements")
    print(f"portfolio.csv  : {len(PORTFOLIO)} participations")
    print(f"marks.csv      : {len(marks)} valorisations trimestrielles")
    print(f"cashflows.csv  : {len(flows)} mouvements, "
          f"{called:,.0f} EUR appeles ({called / committed:.1%} des engagements)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
