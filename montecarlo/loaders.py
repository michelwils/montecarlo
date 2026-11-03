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
import re
import sys
import unicodedata
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
        uniform_size: float | None = None,
        owner_filter: "OwnerFilter | None" = None,
    ) -> dict[date, float]:
        """
        Load throughput from filepath.
        Returns {week_monday: weekly_score_total}.
        When window_weeks is set, only the last N weeks are kept.
        When window_start and window_end are set, only dates in that
        inclusive range are kept.
        uniform_size, where applicable, counts every completed item as
        this many points instead of reading a size field (for boards
        with no size categorization at all — see KanbanZoneCSVLoader).
        owner_filter, when active, keeps only the cards it accepts
        (see OwnerFilter); loaders without card ownership raise
        OwnerFilterError.
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


def apply_window_weeks(
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
# 'CF Exception' isn't always a boolean checkbox — on some boards it's a
# multi-select reason tag ('Doublon', 'Incomplet', 'Annulé', 'Abandonné',
# 'Reporté'...), whose exported value looks like "['Doublon']" rather than
# "true". Enumerating every possible tag would be brittle, so instead any
# value other than an explicit "no" is treated as flagged — a denylist
# instead of an allowlist.
_UNPLANNED_FALSY = {"", "false", "non", "0"}


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
    return _get_field(row, _UNPLANNED_COLUMNS).lower() not in _UNPLANNED_FALSY


# Columns (CSV export) and keys (API cards) that name a card's owners.
OWNER_COLUMNS = ("Owners", "Owner", "Members")
OWNER_KEYS    = ("owners", "owner", "members")


class OwnerFilterError(ValueError):
    """--owners/--xowners can't be applied to this data source."""


def owner_labels(value) -> list[str]:
    """
    Owner identifiers (names, emails, ids) found in one CSV cell or API
    value: a comma-separated string, an owner object, a list of either,
    or a bare id such as a number.
    """
    if value is None or value is False:
        return []
    if isinstance(value, str):
        return [name.strip() for name in next(csv.reader([value]), []) if name.strip()]
    if isinstance(value, dict):
        labels = [
            str(value[key]).strip()
            for key in ("name", "fullName", "displayName", "email", "id", "_id", "publicId")
            if value.get(key) not in (None, "")
        ]
        full_name = " ".join(str(value.get(key) or "").strip() for key in ("firstName", "lastName"))
        if full_name.strip():
            labels.append(full_name.strip())
        return [label for label in labels if label]
    if isinstance(value, (list, tuple, set)):
        return [label for item in value for label in owner_labels(item)]
    return [str(value)]


def card_owner_labels(record: dict, fields: tuple[str, ...]) -> list[str]:
    """owner_labels() of every listed field of a CSV row or API card."""
    return [label for field in fields for label in owner_labels(record.get(field))]


def _normalize(text: str) -> str:
    """Casefold and strip accents, so 'Sébastien' matches 'sebastien'."""
    decomposed = unicodedata.normalize("NFKD", text.strip().casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _name_tokens(normalized: str) -> frozenset[str]:
    """
    The words of a name, or of an email's local part:
    'sebastien.verreault.1@ulaval.ca' -> {'sebastien', 'verreault'}.
    """
    return frozenset(re.findall(r"[^\W\d_]+", normalized.split("@")[0]))


class OwnerFilter:
    """
    --owners/--xowners, normalized once and applied to each card's owner
    labels. A term matches an owner when it is the same name or email
    (ignoring case and accents), or when all its words appear in the
    owner's name or email local part: 'Sébastien Verreault' and
    'verreault' both match 'sebastien.verreault.1@ulaval.ca'. A term
    that is itself an email only matches that exact email.

    It also records which terms matched and which owners were seen, so
    the caller can warn about a term that matched nothing.
    """

    def __init__(self, owners: list[str] | None = None, xowners: list[str] | None = None):
        self.owners  = list(owners or [])
        self.xowners = list(xowners or [])
        self._included = [self._term(t) for t in self.owners]
        self._excluded = [self._term(t) for t in self.xowners]
        self._matched: set[tuple[str, int]] = set()  # (flag, index) of matched terms
        self.seen: dict[str, str] = {}   # normalized owner -> first label seen

    def __bool__(self) -> bool:
        return bool(self._included or self._excluded)

    @staticmethod
    def _term(raw: str) -> tuple[str, frozenset[str] | None]:
        normalized = _normalize(raw)
        return normalized, None if "@" in normalized else _name_tokens(normalized)

    def keeps(self, labels: list[str]) -> bool:
        """True if a card with these owner labels passes the filter. Unowned cards always do."""
        if not labels:
            return True
        names = []
        for label in labels:
            normalized = _normalize(label)
            self.seen.setdefault(normalized, label)
            names.append((normalized, _name_tokens(normalized)))
        included = self._hits("--owners", self._included, names)
        excluded = self._hits("--xowners", self._excluded, names)
        return (not self._included or included) and not excluded

    def _hits(self, flag: str, terms, names) -> bool:
        hit = False
        for index, (normalized, tokens) in enumerate(terms):
            if any(normalized == name or (tokens and tokens <= name_tokens)
                   for name, name_tokens in names):
                self._matched.add((flag, index))
                hit = True
        return hit

    def unmatched(self) -> list[tuple[str, str]]:
        """(flag, term) for every term that matched no owner seen so far."""
        return [
            (flag, raw)
            for flag, raws in (("--owners", self.owners), ("--xowners", self.xowners))
            for index, raw in enumerate(raws)
            if (flag, index) not in self._matched
        ]


class KanbanZoneCSVLoader(ThroughputLoader):
    """
    Loader for Kanban Zone CSV exports.
    Required columns: 'Done At' and a size field ('CF Size' or
    'CF Envergure') — unless the caller passes uniform_size to load(),
    for boards with no size categorization at all. Header inspection is
    used for detection to avoid ambiguity with other CSV formats (Jira,
    Linear, etc.).

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
        uniform_size: float | None = None,
        owner_filter: OwnerFilter | None = None,
    ) -> dict[date, float]:
        daily: dict[date, float] = defaultdict(float)
        with open(filepath, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if owner_filter and not set(OWNER_COLUMNS).intersection(reader.fieldnames or []):
                raise OwnerFilterError("--owners/--xowners require an Owners, Owner, or Members CSV column")
            for row in reader:
                if owner_filter and not owner_filter.keeps(card_owner_labels(row, OWNER_COLUMNS)):
                    continue
                done_raw = row.get("Done At", "").strip()
                if not done_raw:
                    continue
                if uniform_size is not None:
                    points = uniform_size
                else:
                    envergure = _get_field(row, _SIZE_COLUMNS)
                    if envergure not in ALL_SCORES:
                        continue
                    points = ALL_SCORES[envergure]
                d = parse_date(done_raw)
                if d is None:
                    continue
                if window_start is not None and d < window_start:
                    continue
                if window_end is not None and d > window_end:
                    continue
                if _is_unplanned(row):
                    continue
                daily[d] += points

        if not daily:
            print("⚠️  No throughput data found.", file=sys.stderr)
            return {}

        # Aggregate by calendar week (key = Monday)
        weekly: dict[date, float] = defaultdict(float)
        for d, v in daily.items():
            monday = d - timedelta(days=d.weekday())
            weekly[monday] += v

        weekly = _fill_zero_weeks(weekly, start=window_start, end=window_end)
        weekly = apply_window_weeks(weekly, window_weeks)

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
        uniform_size: float | None = None,  # not applicable: values are pre-aggregated
        owner_filter: OwnerFilter | None = None,
    ) -> dict[date, float]:
        if owner_filter:
            raise OwnerFilterError("--owners/--xowners require card data (CSV or --board), not TXT totals")
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
        return apply_window_weeks(weekly, window_weeks)


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


def drop_excluded_weeks(
    weekly: dict[date, float], periods: list[tuple[date, date]] | None,
) -> dict[date, float]:
    """Remove every calendar week touched by one of the inclusive date ranges."""
    if not periods:
        return weekly
    excluded_weeks = [
        (start - timedelta(days=start.weekday()), end - timedelta(days=end.weekday()))
        for start, end in periods
    ]
    return {
        monday: points for monday, points in weekly.items()
        if not any(start <= monday <= end for start, end in excluded_weeks)
    }


def load_throughput_auto(
    filepath: str,
    window_weeks: int | None,
    window_start: date | None = None,
    window_end: date | None = None,
    uniform_size: float | None = None,
    owner_filter: OwnerFilter | None = None,
    exclude_periods: list[tuple[date, date]] | None = None,
) -> dict[date, float]:
    """
    Unified entry point: auto-detect the format and load throughput.
    Prints a warning if no loader matches.

    exclude_periods removes every calendar week touched by the inclusive
    date ranges after window selection, without backfilling older history.

    uniform_size forces the Kanban Zone CSV loader regardless of
    header-based detection: a board with no size custom field at all
    won't match KanbanZoneCSVLoader.match() (which requires one), but
    the caller has explicitly said every item should count as a fixed
    number of points, which only that loader's 'Done At'/CF Exception
    handling makes sense for.
    """
    loader = KanbanZoneCSVLoader() if uniform_size is not None else get_loader(filepath)
    if loader is None:
        ext = Path(filepath).suffix.lower()
        supported = sorted({e for ldr in LOADERS for e in ldr.EXTENSIONS})
        print(
            f"⚠️  Unsupported format: '{ext}'. "
            f"Recognized extensions: {', '.join(supported)}",
            file=sys.stderr,
        )
        return {}
    weekly = loader.load(filepath, window_weeks, window_start, window_end, uniform_size,
                         owner_filter=owner_filter)
    return drop_excluded_weeks(weekly, exclude_periods)
