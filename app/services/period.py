"""The date range a calendar filter starts with: the 1st of this month up to today."""
from datetime import date


def date_range(args, today=None):
    """(from, to) as 'YYYY-MM-DD' strings from a page's date_from / date_to.

    When the page was opened with no dates at all, this month so far. Once the owner has
    applied the filter, what they chose is used as it is, and a blank box means no limit
    on that side (so clearing both boxes shows everything).
    """
    if "date_from" in args or "date_to" in args:
        return args.get("date_from", "").strip(), args.get("date_to", "").strip()
    today = today or date.today()
    return today.replace(day=1).isoformat(), today.isoformat()
