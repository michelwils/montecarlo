"""
Throughput data loaders.

To add a new input format (e.g. Jira, Azure DevOps, Linear…):

1. Create a subclass of ThroughputLoader.
2. Set FORMAT_NAME, DESCRIPTION, and EXTENSIONS.
3. Override match() when extension alone is not enough to identify the
   format — the typical case when multiple CSV dialects share .csv
   (Kanban Zone, Jira, Linear, etc.).
4. Implement load() with the format-specific reading logic.
5. Append an instance to LOADERS below.
   Order matters: the first loader whose match() returns True wins.
"""
import csv
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from .constants import ALL_SCORES
from .dates import parse_date


class ThroughputLoader:
    """Base class for throughput data loaders."""

    FORMAT_NAME: str = ""
    DESCRIPTION: str = ""
    EXTENSIONS: list[str] = []

    def match(self, filepath: str) -> bool:
        """Return True if this loader can handle the given file."""
        return Path(filepath).suffix.lower() in self.EXTENSIONS

    def load(
        self,
        filepath: str,
        window_weeks: int | None,
        window_start: date | None = None,
        window_end: date | None = None,
    ) -> dict[date, float]:
        """
        Load throughput from filepath.
        Returns {week_monday: weekly_score_total}.
        When window_weeks is set, only the last N weeks are kept.
        When window_start and window_end are set, only dates in that
        inclusive range are kept.
        """
        raise NotImplementedError


def _fill_zero_weeks(
    weekly: dict[date, float],
    start: date | None = None,
    end: date | None = None,
) -> dict[date, float]:
    """
    Insert an explicit 0.0 entry for every calendar week with no
    completions of its own, between `start` and `end` (each defaulting to
    the first/last recorded week when omitted).
    Without this, weeks with zero throughput are simply absent from the
    dict instead of counting as zero, which silently skews the average
    throughput upward and destabilizes small history-window sampling.
    Explicit `start`/`end` matter because a requested date range can have
    empty weeks at its edges, before/after the first/last week that has
    any data of its own — those would otherwise be dropped from the range
    entirely instead of counting as zero.
    """
    if not weekly and start is None:
        return weekly
    filled = dict(weekly)
    monday = start - timedelta(days=start.weekday()) if start is not None else min(weekly)
    last   = end - timedelta(days=end.weekday()) if end is not None else max(weekly)
    while monday <= last:
        filled.setdefault(monday, 0.0)
        monday += timedelta(weeks=1)
    return filled


def _apply_window_weeks(
    weekly: dict[date, float], window_weeks: int | None
) -> dict[date, float]:
    """Keep only the most recent `window_weeks` weeks, if set."""
    if window_weeks is None:
        return weekly
    cutoff = max(weekly.keys()) - timedelta(weeks=window_weeks - 1)
    return {k: v for k, v in weekly.items() if k >= cutoff}


# Kanban Zone custom field names are set by whoever created the board, so
# English names are accepted, along with the French names this project's
# own team's board actually uses.
_SIZE_COLUMNS      = ("CF Size", "CF Envergure")
_UNPLANNED_COLUMNS = ("CF Exception", "CF Prioritaire")
_UNPLANNED_TRUTHY  = {"true", "1", "yes", "oui"}


def _get_field(row: dict[str, str], columns: tuple[str, ...]) -> str:
    """Return the first non-empty value among the given column names."""
    for col in columns:
        val = row.get(col, "").strip()
        if val:
            return val
    return ""


def _is_unplanned(row: dict[str, str]) -> bool:
    """
    True if the row is flagged via Kanban Zone's 'CF Exception'/
    'CF Prioritaire' field — an exception that bypassed the normal planning
    process. Such cards consume real team capacity but can't be forecast
    in advance, so they are excluded from the throughput used to project
    planned work.
    """
    return _get_field(row, _UNPLANNED_COLUMNS).lower() in _UNPLANNED_TRUTHY


class KanbanZoneCSVLoader(ThroughputLoader):
    """
    Loader for Kanban Zone CSV exports.
    Required columns: 'Done At' and a size field ('CF Size' or
    'CF Envergure'). Header inspection is used for detection to avoid
    ambiguity with other CSV formats (Jira, Linear, etc.).

    If an optional 'CF Exception'/'CF Prioritaire' column is present,
    cards flagged true are excluded from throughput — see _is_unplanned().
    """

    FORMAT_NAME = "kanban_zone"
    DESCRIPTION = "Kanban Zone CSV export (columns 'Done At' and 'CF Size'/'CF Envergure')"
    EXTENSIONS = [".csv"]
    _REQUIRED_COLS = {"Done At"}

    def match(self, filepath: str) -> bool:
        if Path(filepath).suffix.lower() not in self.EXTENSIONS:
            return False
        # Inspect headers to confirm the format
        try:
            with open(filepath, newline="", encoding="utf-8-sig") as f:
                headers = set(next(csv.reader(f)))
            if not self._REQUIRED_COLS.issubset(headers):
                return False
            return any(col in headers for col in _SIZE_COLUMNS)
        except Exception:
            return False

    def load(
        self,
        filepath: str,
        window_weeks: int | None,
        window_start: date | None = None,
        window_end: date | None = None,
    ) -> dict[date, float]:
        daily: dict[date, float] = defaultdict(float)
        with open(filepath, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                done_raw  = row.get("Done At", "").strip()
                envergure = _get_field(row, _SIZE_COLUMNS)
                if not done_raw or envergure not in ALL_SCORES:
                    continue
                d = parse_date(done_raw)
                if d is None:
                    continue
                if window_start is not None and d < window_start:
                    continue
                if window_end is not None and d > window_end:
                    continue
                if _is_unplanned(row):
                    continue
                daily[d] += ALL_SCORES[envergure]

        if not daily:
            print("⚠️  No throughput data found.", file=sys.stderr)
            return {}

        # Aggregate by calendar week (key = Monday)
        weekly: dict[date, float] = defaultdict(float)
        for d, v in daily.items():
            monday = d - timedelta(days=d.weekday())
            weekly[monday] += v

        weekly = _fill_zero_weeks(weekly, start=window_start, end=window_end)
        weekly = _apply_window_weeks(weekly, window_weeks)

        return dict(weekly)


class TxtLoader(ThroughputLoader):
    """
    Loader for plain-text weekly throughput files.
    Format: comma-separated numeric values, oldest to most recent.
    Synthetic Monday dates are assigned retroactively from last week's Monday.
    """

    FORMAT_NAME = "txt"
    DESCRIPTION = "Plain-text weekly throughput file (comma-separated values)"
    EXTENSIONS = [".txt"]

    def load(
        self,
        filepath: str,
        window_weeks: int | None,
        window_start: date | None = None,
        window_end: date | None = None,
    ) -> dict[date, float]:
        with open(filepath, encoding="utf-8-sig") as f:
            raw = f.read()
        values = [float(v.strip()) for v in raw.split(",") if v.strip() != ""]
        if not values:
            print("⚠️  No data found in text file.", file=sys.stderr)
            return {}
        today = date.today()
        # Anchor on the Monday of the previous week (always complete)
        last_monday = today - timedelta(days=today.weekday()) - timedelta(weeks=1)
        weekly: dict[date, float] = {}
        for i, v in enumerate(reversed(values)):
            monday = last_monday - timedelta(weeks=i)
            weekly[monday] = v
        if window_start is not None or window_end is not None:
            weekly = {
                monday: value
                for monday, value in weekly.items()
                if (window_start is None or monday >= window_start)
                and (window_end is None or monday <= window_end)
            }
        return _apply_window_weeks(weekly, window_weeks)


# Loader registry — order matters: first match() wins.
# Append a new instance here to register a new format.
LOADERS: list[ThroughputLoader] = [
    KanbanZoneCSVLoader(),
    TxtLoader(),
]


def get_loader(filepath: str) -> ThroughputLoader | None:
    """Return the first compatible loader, or None if unrecognized."""
    for loader in LOADERS:
        if loader.match(filepath):
            return loader
    return None


def load_throughput_auto(
    filepath: str,
    window_weeks: int | None,
    window_start: date | None = None,
    window_end: date | None = None,
) -> dict[date, float]:
    """
    Unified entry point: auto-detect the format and load throughput.
    Prints a warning if no loader matches.
    """
    loader = get_loader(filepath)
    if loader is None:
        ext = Path(filepath).suffix.lower()
        supported = sorted({e for ldr in LOADERS for e in ldr.EXTENSIONS})
        print(
            f"⚠️  Unsupported format: '{ext}'. "
            f"Recognized extensions: {', '.join(supported)}",
            file=sys.stderr,
        )
        return {}
    return loader.load(filepath, window_weeks, window_start, window_end)
