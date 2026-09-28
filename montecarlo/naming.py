"""Output chart filename templating, driven by --filename-format."""
import re
from datetime import date, datetime

# Fields are separated by " - ", which never occurs inside a value (prefixes
# and dates use "_" and "-"), and both dates share the ISO format, labelled
# so they can't be confused. Timestamp placed right after the delivery date,
# ahead of target/prob: the target volume changes from week to week as the
# backlog evolves, so keeping it out of the sort key lets an alphabetical
# listing group runs by prefix and delivery date, then order them
# chronologically. Minute resolution: a rerun of the same config within the
# same minute overwrites the previous chart.
DEFAULT_FILENAME_FORMAT = ("{prefix} - livr {date} - gen {timestamp:%Y-%m-%d %Hh%M}"
                           " - {target:g} pts - {prob:.0f} pct")

# Real types matching what render_filename() is called with at chart-save
# time, so a bad format spec (e.g. {target:%Y}) is caught while validating
# a user-supplied template, before the simulation runs.
_SAMPLE_FIELDS = {
    "prefix":      "monte_carlo",
    "date":        date(2000, 1, 1),
    "target":      0.0,
    "prob":        0.0,
    "timestamp":   datetime(2000, 1, 1),
    "weeks":       0,
    "simulations": 0,
}

_ILLEGAL_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def validate_filename_format(template: str) -> str | None:
    """Return an error message if template is invalid, else None."""
    try:
        template.format(**_SAMPLE_FIELDS)
    except KeyError as exc:
        return (f"unknown placeholder {{{exc.args[0]}}}; available: "
                f"{', '.join(sorted(_SAMPLE_FIELDS))}")
    except (ValueError, IndexError) as exc:
        return str(exc)
    return None


def render_filename(template: str, **fields) -> str:
    """
    Fill in a --filename-format template and strip any character illegal
    in a Windows/Unix filename (e.g. from a custom {timestamp:%H:%M} spec).
    """
    stem = template.format(**fields)
    return _ILLEGAL_FILENAME_CHARS.sub("-", stem)
