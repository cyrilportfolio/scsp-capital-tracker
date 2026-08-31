"""Reading and typing of the four source files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src import config


@dataclass
class FundData:
    """Everything the calculations need, already typed."""

    investors: pd.DataFrame
    portfolio: pd.DataFrame
    marks: pd.DataFrame
    cashflows: pd.DataFrame

    @property
    def total_commitments(self) -> float:
        return round(float(self.investors["engagement"].sum()), 2)

    def summary(self) -> str:
        return (f"{len(self.investors)} associes, "
                f"{self.total_commitments:,.0f} EUR d'engagements, "
                f"{len(self.portfolio)} participations, "
                f"{len(self.cashflows)} mouvements de tresorerie")


def _read(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, sep=config.CSV_SEPARATOR, dtype=str,
                        keep_default_na=False, encoding="utf-8")
    frame.columns = [c.strip().lower() for c in frame.columns]
    return frame


def _money(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.replace("", None), errors="coerce").fillna(0.0).round(2)


def _dates(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series.replace("", None), format=config.DATE_FORMAT,
                          errors="coerce")


def load(data_dir: Path | None = None) -> FundData:
    """Load the whole dataset and check it is internally consistent."""
    data_dir = Path(data_dir or config.DATA_DIR)

    investors = _read(data_dir / "investors.csv")
    investors["engagement"] = _money(investors["engagement"])
    investors["date_admission"] = _dates(investors["date_admission"])
    if investors["code"].duplicated().any():
        raise ValueError("investors.csv : codes en double")
    if (investors["engagement"] <= 0).any():
        raise ValueError("investors.csv : un engagement doit etre strictement positif")

    portfolio = _read(data_dir / "portfolio.csv")
    portfolio["cout_acquisition"] = _money(portfolio["cout_acquisition"])
    portfolio["produit_cession"] = _money(portfolio["produit_cession"])
    portfolio["date_acquisition"] = _dates(portfolio["date_acquisition"])
    portfolio["date_cession"] = _dates(portfolio["date_cession"])
    portfolio["cede"] = portfolio["date_cession"].notna()

    marks = _read(data_dir / "marks.csv")
    marks["juste_valeur"] = _money(marks["juste_valeur"])
    marks["date_valorisation"] = _dates(marks["date_valorisation"])

    unknown = set(marks["code"]) - set(portfolio["code"])
    if unknown:
        raise ValueError(f"marks.csv : participations inconnues {sorted(unknown)}")

    cashflows = _read(data_dir / "cashflows.csv")
    cashflows["montant"] = _money(cashflows["montant"])
    cashflows["date"] = _dates(cashflows["date"])
    cashflows["type"] = cashflows["type"].str.strip().str.upper()
    known_types = set(config.INFLOWS) | set(config.OUTFLOWS)
    strangers = set(cashflows["type"]) - known_types
    if strangers:
        raise ValueError(f"cashflows.csv : types inconnus {sorted(strangers)}")
    cashflows = cashflows.sort_values("date").reset_index(drop=True)

    return FundData(investors=investors, portfolio=portfolio, marks=marks,
                    cashflows=cashflows)
