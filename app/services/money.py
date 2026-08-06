"""
Money pipeline: parse user input to integer minor units and format back to display.

Design rules:
- NEVER use float arithmetic for money — use Decimal throughout.
- JPY and IDR have 0 minor-unit decimal places (1500 yen = 1500 minor units).
- All other supported currencies (SGD, USD, MYR, EUR, THB) have 2 decimal places.
- ROUND_HALF_UP used for all rounding (e.g. 1.005 SGD -> 101 cents).
"""

from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN, InvalidOperation

CURRENCY_DECIMALS: dict[str, int] = {
    "SGD": 2,
    "USD": 2,
    "MYR": 2,
    "EUR": 2,
    "JPY": 0,
    "IDR": 0,
    "THB": 2,
}


def parse_to_minor_units(amount_str: str, currency: str) -> int:
    """
    Parse a user-entered amount string to integer minor units.

    Examples:
        parse_to_minor_units("12.50", "SGD") -> 1250
        parse_to_minor_units("1500", "JPY")  -> 1500  (NOT 150000)
        parse_to_minor_units("1.005", "SGD") -> 101   (ROUND_HALF_UP)

    Raises:
        ValueError: if amount is non-numeric, zero, or negative.
        KeyError: if currency is not in CURRENCY_DECIMALS.
    """
    decimals = CURRENCY_DECIMALS[currency]
    try:
        d = Decimal(amount_str)
    except InvalidOperation:
        raise ValueError(f"Invalid amount: {amount_str!r}")
    if d <= 0:
        raise ValueError("Amount must be greater than zero")
    factor = Decimal(10 ** decimals)
    minor = (d * factor).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(minor)


def format_from_minor_units(minor_units: int, currency: str) -> str:
    """
    Format integer minor units back to a human-readable amount string.

    Examples:
        format_from_minor_units(1250, "SGD") -> "12.50"
        format_from_minor_units(1500, "JPY") -> "1500"

    Raises:
        KeyError: if currency is not in CURRENCY_DECIMALS.
    """
    decimals = CURRENCY_DECIMALS[currency]
    factor = Decimal(10 ** decimals)
    value = Decimal(minor_units) / factor
    if decimals > 0:
        return str(value.quantize(Decimal("0." + "0" * decimals)))
    else:
        # JPY: no decimal places — return as plain integer string
        return str(int(value))


def allocate_shares(total_minor: int, weights: list[Decimal]) -> list[int]:
    """Largest-remainder (Hamilton) apportionment on integer minor units.
    Shares always sum EXACTLY to the total. Currency-agnostic (operates on
    already-parsed integer minor units; never touches CURRENCY_DECIMALS)."""
    if total_minor < 0:
        raise ValueError("total_minor must be >= 0")
    if not weights or any(w <= 0 for w in weights):
        raise ValueError("weights must be non-empty and all positive")
    weight_sum = sum(weights)
    n = len(weights)
    raw = [Decimal(total_minor) * w / weight_sum for w in weights]
    floors = [int(r.to_integral_value(rounding=ROUND_DOWN)) for r in raw]
    remainders = [r - f for r, f in zip(raw, floors)]
    leftover = total_minor - sum(floors)
    order = sorted(range(n), key=lambda i: (-remainders[i], i))
    shares = floors[:]
    for i in order[:leftover]:
        shares[i] += 1
    assert sum(shares) == total_minor
    return shares
