"""Terms of the simulated fund, in one place.

Everything here is what an LPA (limited partnership agreement) would fix.
Changing a term should never require touching the calculation code.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
OUTPUT_DIR = ROOT_DIR / "output"

INVESTORS_FILE = DATA_DIR / "investors.csv"
PORTFOLIO_FILE = DATA_DIR / "portfolio.csv"
MARKS_FILE = DATA_DIR / "marks.csv"
CASHFLOWS_FILE = DATA_DIR / "cashflows.csv"

CSV_SEPARATOR = ";"
DATE_FORMAT = "%Y-%m-%d"

# --------------------------------------------------------------------------
# The fund
# --------------------------------------------------------------------------
FUND_NAME = "DEMO LUX PE SCSp"
FUND_LEGAL_FORM = "Societe en commandite speciale (SCSp)"
FUND_RCS = "B999999"
CURRENCY = "EUR"

FIRST_CLOSING = date(2022, 1, 1)
FIRST_DRAWDOWN = date(2022, 1, 15)
INVESTMENT_PERIOD_END = date(2026, 12, 31)
FUND_TERM_END = date(2031, 12, 31)
REPORTING_START = date(2022, 3, 31)
REPORTING_END = date(2025, 12, 31)

# --------------------------------------------------------------------------
# Economic terms
# --------------------------------------------------------------------------
# Management fee, per year, charged quarterly in advance.
MANAGEMENT_FEE_RATE = 0.02
# During the investment period the fee is charged on total commitments;
# afterwards, on the acquisition cost of the investments still held.
FEE_BASIS_INVESTMENT_PERIOD = "COMMITMENTS"
FEE_BASIS_AFTER = "INVESTED_COST"

# Preferred return (hurdle) offered to the partners before any carry.
PREFERRED_RETURN_RATE = 0.08
# Accrued on the daily balance of outstanding contributions, compounded on
# the anniversary of the first drawdown. This is the method the LPA should
# prefer: it is transparent and it does not depend on an IRR solver.
PREFERRED_RETURN_DAY_COUNT = 365
PREFERRED_RETURN_COMPOUNDING = "ANNIVERSARY"

# Carried interest split above the hurdle.
CARRY_SPLIT = 0.20
# A 100 % catch-up: the carried interest partner catches up with the partners
# on the preferred return already paid. For an 80:20 split that is 25 % of
# the preferred return (0.20 / 0.80).
CATCH_UP_RATE = CARRY_SPLIT / (1 - CARRY_SPLIT)

# Allocation rule chosen in the LPA for contributions, income and expenses.
ALLOCATION_BASIS = "COMMITMENTS"

# --------------------------------------------------------------------------
# Tolerances
# --------------------------------------------------------------------------
# Rounding tolerance, in euros, on every reconciliation.
TOLERANCE = 0.05
# Tolerance on an allocation percentage total.
ALLOCATION_TOLERANCE = 1e-9

# --------------------------------------------------------------------------
# Cash flow types found in cashflows.csv
# --------------------------------------------------------------------------
CAPITAL_CALL = "CAPITAL_CALL"
INVESTMENT = "INVESTMENT"
MANAGEMENT_FEE = "MANAGEMENT_FEE"
FUND_EXPENSE = "FUND_EXPENSE"
EXIT_PROCEEDS = "EXIT_PROCEEDS"
DISTRIBUTION = "DISTRIBUTION"

INFLOWS = (CAPITAL_CALL, EXIT_PROCEEDS)
OUTFLOWS = (INVESTMENT, MANAGEMENT_FEE, FUND_EXPENSE, DISTRIBUTION)


@dataclass
class RunConfig:
    """Runtime options resolved from the command line."""

    reporting_date: date = REPORTING_END
    data_dir: Path = DATA_DIR
    output_dir: Path = OUTPUT_DIR
    preferred_return_rate: float = PREFERRED_RETURN_RATE
    carry_split: float = CARRY_SPLIT
    fund_name: str = FUND_NAME
    strict: bool = False


def quarter_ends(start: date, end: date) -> list[date]:
    """Every quarter end between two dates, inclusive."""
    out = []
    year, quarter = start.year, (start.month - 1) // 3 + 1
    while True:
        month = quarter * 3
        day = 31 if month in (3, 12) else 30
        current = date(year, month, day)
        if current > end:
            break
        if current >= start:
            out.append(current)
        quarter += 1
        if quarter == 5:
            quarter, year = 1, year + 1
    return out
