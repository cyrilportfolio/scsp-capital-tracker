"""Valuation, capital accounts, performance and the whole pipeline."""

from __future__ import annotations

import pandas as pd
import pytest

from src import checks, config, main, nav, performance, statements, waterfall

REPORTING_DATE = pd.Timestamp(config.REPORTING_END)


# --------------------------------------------------------------------------
# Valuation
# --------------------------------------------------------------------------
def test_nav_is_portfolio_plus_cash(fund, pipeline):
    row = pipeline["nav"].loc[pipeline["nav"]["trimestre"] == REPORTING_DATE].iloc[0]
    expected = round(nav.portfolio_value(fund, REPORTING_DATE)
                     + nav.cash_balance(fund.cashflows, REPORTING_DATE), 2)
    assert row["nav_avant_carried"] == expected


def test_the_change_in_nav_is_explained_every_quarter(pipeline):
    assert (pipeline["nav"]["ecart_reconciliation"].abs()
            <= config.TOLERANCE).all()


def test_cash_never_goes_negative(fund, quarters):
    for quarter in quarters:
        assert nav.cash_balance(fund.cashflows, quarter) >= -config.TOLERANCE


def test_a_sold_investment_leaves_the_portfolio(fund):
    sold = fund.portfolio.loc[fund.portfolio["cede"]].iloc[0]
    after = pd.Timestamp(sold["date_cession"]) + pd.offsets.QuarterEnd()
    detail = nav.portfolio_detail(fund, after)
    line = detail.loc[detail["code"] == sold["code"]].iloc[0]
    assert line["statut"] == "Cedee"
    assert line["juste_valeur"] == 0.0
    assert line["plus_value_realisee"] == round(
        sold["produit_cession"] - sold["cout_acquisition"], 2)


def test_the_fee_basis_steps_down_after_the_investment_period(fund):
    during = nav.management_fee_basis(fund, config.INVESTMENT_PERIOD_END)
    after = nav.management_fee_basis(
        fund, pd.Timestamp(config.INVESTMENT_PERIOD_END) + pd.Timedelta(days=1))
    assert during["assiette"] == config.FEE_BASIS_INVESTMENT_PERIOD
    assert after["assiette"] == config.FEE_BASIS_AFTER
    assert after["montant_assiette"] < during["montant_assiette"]


# --------------------------------------------------------------------------
# Capital accounts
# --------------------------------------------------------------------------
def test_capital_accounts_tie_back_to_the_nav(pipeline):
    assert pipeline["reconciliation"]["equilibre"].all()


def test_each_account_moves_from_opening_to_closing(pipeline):
    accounts = pipeline["accounts"]
    computed = (accounts["solde_ouverture"] + accounts["contributions"]
                - accounts["distributions"] + accounts["quote_part_gain_net"]
                + accounts["quote_part_commission"] + accounts["quote_part_frais"]
                + accounts["carried_interest"])
    assert (computed - accounts["solde_cloture"]).abs().max() <= 0.02


def test_the_carry_leaves_the_partners_and_reaches_the_cip(pipeline):
    accounts = pipeline["accounts"]
    partners = accounts.loc[accounts["role"] == "ASSOCIE", "carried_interest"].sum()
    cip = accounts.loc[accounts["role"] == "CARRIED INTEREST",
                       "carried_interest"].sum()
    assert round(partners + cip, 2) == 0.0
    assert cip > 0


def test_the_statement_covers_every_partner(fund, pipeline):
    statement = statements.capital_account_statement(
        pipeline["accounts"], REPORTING_DATE)
    assert len(statement) == len(fund.investors) + 1  # partners plus the CIP


def test_an_unknown_partner_is_refused(pipeline):
    with pytest.raises(ValueError, match="associe inconnu"):
        statements.statement_for(pipeline["accounts"], "INCONNU")


# --------------------------------------------------------------------------
# Performance
# --------------------------------------------------------------------------
def test_tvpi_is_dpi_plus_rvpi():
    ratios = performance.multiples(commitment=100.0, paid_in=80.0,
                                   distributions=30.0, residual_value=70.0)
    assert ratios["DPI"] == 0.375
    assert ratios["RVPI"] == 0.875
    assert round(ratios["DPI"] + ratios["RVPI"], 4) == ratios["TVPI"]


def test_multiples_survive_a_fund_with_nothing_drawn():
    ratios = performance.multiples(100.0, 0.0, 0.0, 0.0)
    assert ratios["DPI"] is None


def test_the_rate_of_return_on_a_doubling_over_a_year():
    flows = pd.Series([-1_000_000.0, 2_000_000.0],
                      index=[pd.Timestamp("2022-01-01"), pd.Timestamp("2023-01-01")])
    assert abs(performance.xirr(flows) - 1.0) < 0.01


def test_flows_of_one_sign_have_no_rate_of_return():
    flows = pd.Series([-100.0, -200.0],
                      index=[pd.Timestamp("2022-01-01"), pd.Timestamp("2023-01-01")])
    assert performance.xirr(flows) is None


def test_every_partner_gets_the_same_multiples(fund, pipeline):
    """The allocation rule is uniform, so the ratios must be too."""
    closing = (pipeline["accounts"]
               .loc[pipeline["accounts"]["trimestre"] == REPORTING_DATE]
               .set_index("code")["solde_cloture"])
    table = performance.investor_performance(
        fund.investors.set_index("code")["engagement"], pipeline["calls"],
        pipeline["distributions"], closing, REPORTING_DATE)
    assert table["TVPI"].nunique() == 1
    assert table["PIC"].nunique() == 1


# --------------------------------------------------------------------------
# End to end
# --------------------------------------------------------------------------
def test_the_dataset_raises_no_anomaly(fund, quarters, pipeline):
    contributions = pipeline["contributions"]
    distributions = pipeline["paid"]
    fund_nav = float(pipeline["nav"].loc[
        pipeline["nav"]["trimestre"] == REPORTING_DATE, "nav_avant_carried"].iloc[0])
    hurdle = waterfall.preferred_return(contributions, distributions,
                                        REPORTING_DATE)
    result = waterfall.run_waterfall(float(contributions.sum()),
                                     float(distributions.sum()), fund_nav,
                                     hurdle.earned)
    anomalies = checks.run_all(fund, quarters, pipeline["status"],
                               pipeline["nav"], pipeline["reconciliation"],
                               result)
    assert anomalies.empty, anomalies.to_string()


def test_the_command_line_writes_its_outputs(tmp_path):
    code = main.main(["--output", str(tmp_path), "--silencieux"])
    assert code == 0
    assert (tmp_path / "reporting_20251231.xlsx").exists()
    assert (tmp_path / "reporting_20251231.txt").exists()


def test_the_workbook_holds_the_investor_sheets(tmp_path):
    main.main(["--output", str(tmp_path), "--silencieux"])
    workbook = pd.ExcelFile(tmp_path / "reporting_20251231.xlsx")
    for sheet in ("Synthese", "Cascade", "Etat de compte", "Performance",
                  "Preferred return", "Controles"):
        assert sheet in workbook.sheet_names


def test_an_earlier_reporting_date_shows_no_carry_yet(tmp_path):
    """Early in a fund's life the bucket does not reach the hurdle."""
    code = main.main(["--output", str(tmp_path), "--date", "2022-12-31",
                      "--silencieux"])
    assert code == 0
    workbook = pd.ExcelFile(tmp_path / "reporting_20221231.xlsx")
    cascade = workbook.parse("Cascade")
    assert cascade.loc[cascade["etape"] == 5, "au_cip"].iloc[0] == 0.0
