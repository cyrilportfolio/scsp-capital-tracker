"""The cascade, checked against a published worked example.

The reference case comes from Mariya Stefanova, *Private Equity Accounting,
Investor Reporting, and Beyond*, chapter 8, "Carried Interest and Carried
Interest Modelling", Example 2: a fund with USD 100m of commitments fully
drawn, USD 70m of cumulative distributions and USD 100m of residual value on
the calculation date, an 8 % preferred return worked out at approximately
USD 26m, and an 80:20 split.

The book gives the answer step by step: USD 100m returned as capital,
USD 26m of preferred return, a USD 6.5m catch-up, then USD 30m to the
partners and USD 7.5m to the carried interest partner — a total carried
interest of USD 14m. Reproducing a published figure is the cheapest
credible proof that the implementation is right.
"""

from __future__ import annotations

import pandas as pd

from src import config, waterfall


def test_reference_case_from_the_literature():
    result = waterfall.run_waterfall(
        contributions=100_000_000, distributions=70_000_000,
        nav=100_000_000, preferred=26_000_000)

    assert result.bucket == 170_000_000
    assert result.return_of_capital == 100_000_000
    assert result.preferred_paid == 26_000_000
    assert result.catch_up == 6_500_000
    assert result.split_partners == 30_000_000
    assert result.split_carry == 7_500_000
    assert result.carried_interest == 14_000_000


def test_the_bucket_is_fully_distributed():
    result = waterfall.run_waterfall(40_000_000, 12_000_000, 35_000_000,
                                     6_400_000)
    assert round(result.to_partners + result.carried_interest, 2) == result.bucket


def test_carried_interest_is_catch_up_plus_split():
    result = waterfall.run_waterfall(40_000_000, 12_000_000, 35_000_000,
                                     6_400_000)
    assert result.carried_interest == round(
        result.catch_up + result.split_carry, 2)


def test_catch_up_grosses_up_the_carry_share():
    """For an 80:20 split the catch-up is 25 % of the preferred return."""
    result = waterfall.run_waterfall(10_000_000, 0, 30_000_000, 2_000_000)
    assert result.catch_up == 500_000
    assert config.CATCH_UP_RATE == 0.25


def test_no_carry_before_capital_is_returned():
    """A fund under water pays nothing to the carried interest partner."""
    result = waterfall.run_waterfall(50_000_000, 0, 30_000_000, 9_000_000)
    assert result.return_of_capital == 30_000_000
    assert result.preferred_paid == 0
    assert result.carried_interest == 0
    assert result.to_partners == 30_000_000


def test_no_carry_while_the_hurdle_is_not_fully_served():
    result = waterfall.run_waterfall(50_000_000, 0, 54_000_000, 9_000_000)
    assert result.return_of_capital == 50_000_000
    assert result.preferred_paid == 4_000_000
    assert result.carried_interest == 0


def test_a_different_split_changes_the_catch_up():
    result = waterfall.run_waterfall(100_000_000, 70_000_000, 100_000_000,
                                     26_000_000, carry_split=0.10)
    # 10 % carry means a catch-up of 1/9 of the preferred return.
    assert result.catch_up == round(26_000_000 / 9, 2)


# --------------------------------------------------------------------------
# Preferred return
# --------------------------------------------------------------------------
def test_hurdle_on_a_single_contribution_over_one_year():
    contributions = pd.Series([1_000_000.0], index=[pd.Timestamp("2022-01-01")])
    distributions = pd.Series(dtype=float)
    result = waterfall.preferred_return(contributions, distributions,
                                        "2022-12-31", rate=0.08,
                                        first_drawdown=pd.Timestamp("2022-01-01").date())
    # 365 days of accrual at 8 % on a million, to the day.
    assert 79_000 < result.earned < 80_100


def test_hurdle_compounds_on_the_anniversary():
    contributions = pd.Series([1_000_000.0], index=[pd.Timestamp("2022-01-01")])
    distributions = pd.Series(dtype=float)
    one_year = waterfall.preferred_return(
        contributions, distributions, "2022-12-31", rate=0.08,
        first_drawdown=pd.Timestamp("2022-01-01").date()).earned
    two_years = waterfall.preferred_return(
        contributions, distributions, "2023-12-31", rate=0.08,
        first_drawdown=pd.Timestamp("2022-01-01").date()).earned
    # With compounding the second year earns more than the first.
    assert two_years > 2 * one_year


def test_repaying_capital_stops_the_accrual():
    contributions = pd.Series([1_000_000.0], index=[pd.Timestamp("2022-01-01")])
    repaid = pd.Series([1_000_000.0], index=[pd.Timestamp("2022-06-30")])
    with_repayment = waterfall.preferred_return(
        contributions, repaid, "2022-12-31", rate=0.08,
        first_drawdown=pd.Timestamp("2022-01-01").date()).earned
    without = waterfall.preferred_return(
        contributions, pd.Series(dtype=float), "2022-12-31", rate=0.08,
        first_drawdown=pd.Timestamp("2022-01-01").date()).earned
    assert with_repayment < without


def test_no_contribution_means_no_hurdle():
    result = waterfall.preferred_return(pd.Series(dtype=float),
                                        pd.Series(dtype=float), "2025-12-31")
    assert result.earned == 0.0
