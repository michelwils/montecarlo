"""Output chart filename templating, driven by --filename-format."""
import re
from datetime import date, datetime

# Timestamp kept last (as it always was) so that, for a fixed
# prefix/date/target/prob combination, listing a directory alphabetically
# still orders repeated runs chronologically.
DEFAULT_FILENAME_FORMAT = "{prefix}_{date}_{target:g}pts_{prob:.0f}pct_{timestamp:%Y%m%d_%H%M%S}"

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
