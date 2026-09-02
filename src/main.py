"""Command line entry point: value the fund, run the cascade, report."""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from src import (allocations, capital_calls, checks, config, ingest, nav,
                 performance, reports, statements, waterfall)


def _parse_date(value: str) -> date:
    for pattern in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, pattern).date()
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(
        f"date illisible : {value} (attendu AAAA-MM-JJ ou JJ/MM/AAAA)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scsp-tracker",
        description=("Comptabilite investisseurs d'un fonds de private equity "
                     "luxembourgeois (SCSp) : appels de capital, NAV, cascade "
                     "whole-of-fund et etats de compte."),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--data", type=Path, default=config.DATA_DIR,
                        help="repertoire des jeux de donnees")
    parser.add_argument("--output", type=Path, default=config.OUTPUT_DIR,
                        help="repertoire de sortie")
    parser.add_argument("--date", type=_parse_date, default=config.REPORTING_END,
                        help="date de reporting")
    parser.add_argument("--hurdle", type=float, default=config.PREFERRED_RETURN_RATE,
                        help="taux du preferred return")
    parser.add_argument("--carry", type=float, default=config.CARRY_SPLIT,
                        help="part de carried interest au-dela du hurdle")
    parser.add_argument("--associe", default=None,
                        help="code d'un associe dont detailler l'etat de compte")
    parser.add_argument("--avis", default=None,
                        help=("reference de l'appel dont editer l'avis "
                              "(par defaut, le dernier appel a la date de "
                              "reporting ; 'liste' affiche les references)"))
    parser.add_argument("--strict", action="store_true",
                        help="code de sortie 2 si une anomalie bloquante est detectee")
    parser.add_argument("--silencieux", action="store_true")
    return parser


def _print_table(frame: pd.DataFrame, columns: list[str]) -> None:
    widths = {c: max(len(c), int(frame[c].astype(str).str.len().max() or 0))
              for c in columns}
    header = "  ".join(c.ljust(widths[c]) for c in columns)
    print("  " + header)
    print("  " + "-" * len(header))
    for _, row in frame.iterrows():
        print("  " + "  ".join(str(row[c]).ljust(widths[c]) for c in columns))


def run(args) -> int:
    verbose = not args.silencieux
    as_of = pd.Timestamp(args.date)

    fund = ingest.load(args.data)
    quarters = [pd.Timestamp(q) for q in
                config.quarter_ends(config.REPORTING_START, args.date)]

    if verbose:
        print(f"Fonds     : {config.FUND_NAME} ({config.FUND_LEGAL_FORM})")
        print(f"Reporting : {as_of:%d/%m/%Y}")
        print(fund.summary())
        print()

    calls = capital_calls.call_schedule(fund.cashflows, fund.investors)
    paid = capital_calls.distribution_schedule(fund.cashflows, fund.investors)

    references = capital_calls.call_references(calls, as_of)
    if args.avis == "liste":
        print("APPELS DE CAPITAL")
        for reference in references:
            total = calls.loc[calls["appel"] == reference,
                              "montant_appel_total"].iloc[0]
            when = calls.loc[calls["appel"] == reference, "date"].iloc[0]
            print(f"  {reference}  {when:%d/%m/%Y}  {total:>14,.2f} EUR")
        return 0
    notice = None
    if references:
        notice = capital_calls.call_notice(
            calls, fund.investors, fund.cashflows, args.avis or references[-1])
    status = capital_calls.commitment_status(fund.investors, calls, as_of)
    nav_by_quarter = nav.quarterly_nav(fund, quarters)

    fund_contributions = calls.groupby("date")["montant"].sum()
    fund_distributions = (paid.groupby("date")["montant"].sum()
                          if not paid.empty else pd.Series(dtype=float))

    carry = waterfall.carry_accrual_series(
        fund_contributions, fund_distributions,
        nav_by_quarter.set_index("trimestre")["nav_avant_carried"],
        rate=args.hurdle, carry_split=args.carry)

    accounts = statements.build_capital_accounts(
        fund.investors, nav_by_quarter, calls, paid, carry)
    reconciliation = statements.partners_capital_reconciliation(
        accounts, nav_by_quarter)
    statement = statements.capital_account_statement(accounts, as_of)

    hurdle = waterfall.preferred_return(
        fund_contributions.loc[fund_contributions.index <= as_of],
        fund_distributions.loc[fund_distributions.index <= as_of]
        if not fund_distributions.empty else fund_distributions,
        as_of, rate=args.hurdle, with_schedule=True)

    paid_in = round(float(fund_contributions.loc[
        fund_contributions.index <= as_of].sum()), 2)
    given_back = round(float(fund_distributions.loc[
        fund_distributions.index <= as_of].sum()) if not fund_distributions.empty
        else 0.0, 2)
    fund_nav = float(nav_by_quarter.loc[
        nav_by_quarter["trimestre"] == as_of, "nav_avant_carried"].iloc[0])

    result = waterfall.run_waterfall(paid_in, given_back, fund_nav,
                                     hurdle.earned, carry_split=args.carry)

    closing = (accounts.loc[accounts["trimestre"] == as_of]
               .set_index("code")["solde_cloture"])
    investor_perf = performance.investor_performance(
        fund.investors.set_index("code")["engagement"], calls, paid, closing, as_of)

    fund_flows = pd.concat([
        pd.Series(-fund_contributions.values, index=fund_contributions.index),
        (pd.Series(fund_distributions.values, index=fund_distributions.index)
         if not fund_distributions.empty else pd.Series(dtype=float)),
        pd.Series([fund_nav], index=[as_of]),
    ])
    fund_perf = performance.fund_performance(
        fund.total_commitments, paid_in, given_back, fund_nav, fund_flows)

    anomalies = checks.run_all(fund, quarters, status, nav_by_quarter,
                               reconciliation, result)
    summary = checks.summarise(anomalies)

    context = {
        "fund": config.FUND_NAME, "legal_form": config.FUND_LEGAL_FORM,
        "currency": config.CURRENCY, "as_of": f"{as_of:%d/%m/%Y}",
        "run_date": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "commitments": fund.total_commitments, "paid_in": paid_in,
        "unfunded": round(fund.total_commitments - paid_in, 2),
        "distributions": given_back,
        "portfolio_value": nav.portfolio_value(fund, as_of),
        "cash": nav.cash_balance(fund.cashflows, as_of),
        "nav": fund_nav, "preferred": hurdle.earned,
        "carried": result.carried_interest,
        "nav_partners": round(fund_nav - result.carried_interest, 2),
        "DPI": fund_perf["DPI"], "RVPI": fund_perf["RVPI"],
        "TVPI": fund_perf["TVPI"],
        "irr": (f"{fund_perf['tri_net']:.2%}"
                if fund_perf["tri_net"] is not None else "n/a"),
        "anomalies": int(len(anomalies)),
        "blocking": int((anomalies["severite"] == checks.SEVERITY.BLOCKING).sum()
                        if not anomalies.empty else 0),
    }

    sheets = {
        "controles": summary,
        "anomalies": anomalies,
        "associes": allocations.allocation_table(fund.investors),
        "engagements": status,
        "appels": calls,
        **({"avis": notice.allocation, "avis_objet": notice.purpose}
           if notice is not None else {}),
        "portefeuille": nav.portfolio_detail(fund, as_of),
        "nav": nav_by_quarter,
        "comptes": accounts,
        "etat_de_compte": statement,
        "cascade": result.steps,
        "carry": carry,
        "performance": investor_perf,
        "hurdle": hurdle.schedule,
    }

    output_dir = Path(args.output)
    workbook = reports.write_workbook(
        output_dir / f"reporting_{as_of:%Y%m%d}.xlsx", sheets, context)
    text = reports.write_text_report(
        output_dir / f"reporting_{as_of:%Y%m%d}.txt", context, result.steps,
        summary, anomalies, statement)

    if verbose:
        print("CASCADE DE REPARTITION")
        _print_table(result.steps.assign(
            aux_associes=result.steps["aux_associes"].map("{:,.2f}".format),
            au_cip=result.steps["au_cip"].map("{:,.2f}".format),
            solde_du_bucket=result.steps["solde_du_bucket"].map("{:,.2f}".format)),
            ["etape", "clause", "aux_associes", "au_cip", "solde_du_bucket"])
        print()
        print("CONTROLES")
        _print_table(summary, ["statut", "severite", "anomalies", "libelle_controle"])
        print()
        print("SYNTHESE")
        print(f"  Engagements            : {context['commitments']:,.2f} EUR")
        print(f"  Capital appele         : {context['paid_in']:,.2f} EUR "
              f"({paid_in / fund.total_commitments:.1%})")
        print(f"  Distributions cumulees : {context['distributions']:,.2f} EUR")
        print(f"  NAV du fonds           : {context['nav']:,.2f} EUR")
        print(f"  Preferred return acquis: {context['preferred']:,.2f} EUR")
        print(f"  Carried interest accru : {context['carried']:,.2f} EUR")
        print(f"  DPI / RVPI / TVPI      : {context['DPI']} / "
              f"{context['RVPI']} / {context['TVPI']}")
        print(f"  TRI net du fonds       : {context['irr']}")
        print(f"  Anomalies              : {context['anomalies']} "
              f"(dont {context['blocking']} bloquantes)")
        if notice is not None and args.avis:
            print()
            print(f"AVIS D'APPEL DE CAPITAL — {notice.reference}")
            print(f"  Date de l'avis       : {notice.notice_date:%d/%m/%Y}")
            print(f"  Date de reglement    : {notice.funding_date:%d/%m/%Y}")
            print(f"  Montant appele       : {notice.amount:,.2f} EUR")
            print()
            _print_table(notice.purpose.assign(
                montant=notice.purpose["montant"].map("{:,.2f}".format)),
                ["poste", "montant"])
            print()
            _print_table(notice.allocation.assign(
                engagement=notice.allocation["engagement"].map("{:,.2f}".format),
                appele_avant=notice.allocation["appele_avant"].map("{:,.2f}".format),
                montant_appele=notice.allocation["montant_appele"].map("{:,.2f}".format),
                appele_apres=notice.allocation["appele_apres"].map("{:,.2f}".format),
                non_appele=notice.allocation["non_appele"].map("{:,.2f}".format)),
                ["code", "nom", "engagement", "appele_avant", "montant_appele",
                 "appele_apres", "non_appele"])
        if args.associe:
            print()
            print(f"ETAT DE COMPTE — {args.associe}")
            detail = statements.statement_for(accounts, args.associe)
            print(detail.to_string(index=False))
        print()
        print("SORTIES")
        for item in (workbook, text):
            print(f"  {item}")

    if args.strict and checks.has_blocking(anomalies):
        return 2
    return 0


def main(argv=None) -> int:
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
