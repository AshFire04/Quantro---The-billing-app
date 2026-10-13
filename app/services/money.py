"""Money is stored as whole paise (integers) so rounding never drifts."""
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
