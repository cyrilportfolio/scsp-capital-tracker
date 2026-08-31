"""Fixtures shared by the test suite."""

from __future__ import annotations

import pandas as pd
import pytest

from src import capital_calls, config, ingest, nav, statements, waterfall


@pytest.fixture(scope="session")
def fund():
    return ingest.load()


@pytest.fixture(scope="session")
def quarters():
    return [pd.Timestamp(q) for q in
            config.quarter_ends(config.REPORTING_START, config.REPORTING_END)]


@pytest.fixture
def small_investors():
    """Three partners whose shares do not divide cleanly."""
    return pd.DataFrame({
        "code": ["A", "B", "C"],
        "nom": ["Alpha", "Beta", "Gamma"],
        "type": ["LP", "LP", "GP"],
        "pays": ["LU", "FR", "LU"],
        "engagement": [1_000_000.0, 1_000_000.0, 1_000_000.0],
    })


@pytest.fixture(scope="session")
def pipeline(fund, quarters):
    """The whole chain run once, as the command line runs it."""
    calls = capital_calls.call_schedule(fund.cashflows, fund.investors)
    paid = capital_calls.distribution_schedule(fund.cashflows, fund.investors)
    nav_by_quarter = nav.quarterly_nav(fund, quarters)
    contributions = calls.groupby("date")["montant"].sum()
    distributions = paid.groupby("date")["montant"].sum()
    carry = waterfall.carry_accrual_series(
        contributions, distributions,
        nav_by_quarter.set_index("trimestre")["nav_avant_carried"])
    accounts = statements.build_capital_accounts(
        fund.investors, nav_by_quarter, calls, paid, carry)
    return {
        "calls": calls, "distributions": paid, "nav": nav_by_quarter,
        "contributions": contributions, "paid": distributions,
        "carry": carry, "accounts": accounts,
        "status": capital_calls.commitment_status(
            fund.investors, calls, config.REPORTING_END),
        "reconciliation": statements.partners_capital_reconciliation(
            accounts, nav_by_quarter),
    }
