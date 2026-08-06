"""
FX rate service: fetch from Frankfurter, cache in fx_rates table, and convert
original minor-unit amounts to SGD minor units.

Design rules:
- SGD is the base currency; get_rate_for_date always short-circuits for SGD.
- All lookups use the user-entered calendar date (occurred_on), never datetime.now().
- Cache-first: query fx_rates before hitting the network.
- One Frankfurter call stores ALL supported currencies (USD, MYR, EUR, JPY) so
  subsequent lookups for other currencies on the same date are also cache hits.
- ROUND_HALF_UP Decimal arithmetic for conversion; never float arithmetic.
"""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

import httpx
from sqlalchemy.orm import Session

from app.models.fx_rate import FxRate
from app.services.money import CURRENCY_DECIMALS

FRANKFURTER_BASE = "https://api.frankfurter.dev/v1"
SUPPORTED_SYMBOLS = "USD,MYR,EUR,JPY"  # SGD is the base; no SGD→SGD needed


def get_rate_for_date(
    expense_date: date,
    from_currency: str,
    db: Session,
) -> tuple[float, date]:
    """
    Return (rate, actual_rate_date) for the given expense date and currency.

    rate: how many `from_currency` units equal 1 SGD
         (Frankfurter base=SGD convention, e.g. JPY 109.5 per SGD).
    actual_rate_date: the calendar date the rate is from — may differ from
        expense_date when a weekend/holiday is requested (Frankfurter returns
        the nearest prior business day automatically).

    SGD→SGD always returns (1.0, expense_date) with zero network calls.

    Raises ValueError if from_currency is not in the Frankfurter response.
    """
    # SGD short-circuit — no network call needed
    if from_currency == "SGD":
        return 1.0, expense_date

    # Cache check — query for the exact (base=SGD, quote=from_currency, date)
    cached = (
        db.query(FxRate)
        .filter(
            FxRate.base_currency == "SGD",
            FxRate.quote_currency == from_currency,
            FxRate.as_of_date == expense_date,
        )
        .first()
    )
    if cached:
        return cached.rate, cached.as_of_date

    # Cache miss — fetch from Frankfurter
    resp = httpx.get(
        f"{FRANKFURTER_BASE}/{expense_date.isoformat()}",
        params={"base": "SGD", "symbols": SUPPORTED_SYMBOLS},
        timeout=10.0,
    )
    resp.raise_for_status()
    data = resp.json()
    actual_date = date.fromisoformat(data["date"])
    rates = data["rates"]

    # Store all returned rates in cache (one API call covers all currencies)
    for currency, rate_value in rates.items():
        existing = (
            db.query(FxRate)
            .filter(
                FxRate.base_currency == "SGD",
                FxRate.quote_currency == currency,
                FxRate.as_of_date == actual_date,
            )
            .first()
        )
        if not existing:
            db.add(
                FxRate(
                    base_currency="SGD",
                    quote_currency=currency,
                    rate=rate_value,
                    as_of_date=actual_date,
                )
            )
    db.commit()

    rate = rates.get(from_currency)
    if rate is None:
        raise ValueError(f"Currency {from_currency!r} not in Frankfurter response")
    return rate, actual_date


def compute_base_amount_minor(
    original_minor: int,
    original_currency: str,
    rate_sgd_per_unit: float,
) -> int:
    """
    Convert original_minor (in original_currency's minor units) to SGD minor units.

    rate_sgd_per_unit: how many original_currency units equal 1 SGD
        (Frankfurter base=SGD convention — e.g. 109.5 for JPY means 109.5 JPY per SGD).

    SGD always has 2 decimal places (100 cents per dollar).

    Examples:
        compute_base_amount_minor(1500, "JPY", 109.5)  -> 1370  (¥1500 ÷ 109.5 ≈ S$13.70)
        compute_base_amount_minor(1000, "USD", 0.74)   -> 1351  ($10.00 ÷ 0.74 ≈ S$13.51)
        compute_base_amount_minor(1250, "SGD", 1.0)    -> 1250
    """
    decimals = CURRENCY_DECIMALS[original_currency]
    factor = Decimal(10 ** decimals)
    original_in_units = Decimal(original_minor) / factor
    sgd_in_units = original_in_units / Decimal(str(rate_sgd_per_unit))
    sgd_minor = (sgd_in_units * Decimal(100)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(sgd_minor)
