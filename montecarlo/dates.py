"""Date parsing helpers shared by the loaders, annotations, and the CLI."""
from datetime import date, datetime, timedelta

from .constants import DATE_FORMATS


def parse_date(s: str) -> date | None:
    """Try each known date format and return a date, or None on failure."""
    s = s.strip()
    if not s:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def next_monday(today: date | None = None) -> date:
    """Return the coming Monday (or today if today is already Monday)."""
    d = today or date.today()
    days_ahead = (7 - d.weekday()) % 7  # 0 if already Monday
    return d + timedelta(days=days_ahead)
