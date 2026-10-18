"""Money is stored as whole paise (integers) so rounding never drifts."""
from datetime import datetime
from decimal import Decimal, InvalidOperation


def rupees_to_paise(text):
    """'1250.50' -> 125050. Raises ValueError for anything that isn't a valid amount."""
    try:
        value = Decimal(str(text).strip().replace(",", ""))
    except InvalidOperation:
        raise ValueError("Enter the price as a number, like 450 or 450.50")
    if value < 0 or not value.is_finite():
        raise ValueError("The price can't be negative")
    return int((value * 100).to_integral_value())


def format_rupees(paise):
    """125050 -> '₹1,250.50'."""
    return f"₹{paise / 100:,.2f}"


def paise_to_input(paise):
    """125050 -> '1250.50' (for filling a form box)."""
    return f"{paise / 100:.2f}"

def take_percent_off(paise, pct):
    """Reduce an amount by a percentage (a Decimal with at most two decimal places).

    Whole-number maths, rounding half up to the nearest paisa, so the browser and the
    server always agree: take_percent_off(45000, Decimal("10")) -> 40500.
    """
    hundredths = int(pct * 100)                     # 12.5% -> 1250
    return (paise * (10000 - hundredths) + 5000) // 10000

def short_date(text):
    """'2026-10-10T14:30:05' -> '10/10/26' (DD/MM/YY)."""
    if not text:
        return ""
    return datetime.strptime(text[:10], "%Y-%m-%d").strftime("%d/%m/%y")


def format_date(text):
    """'2026-10-10' or '2026-10-10T14:30:05' -> '10 Oct 2026' (no time). Empty stays empty."""
    if not text:
        return ""
    return datetime.strptime(text[:10], "%Y-%m-%d").strftime("%d %b %Y")

