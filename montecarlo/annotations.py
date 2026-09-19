"""Loading the optional annotations CSV shown on the sensitivity chart."""
import csv
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

from .constants import DEFAULT_ANNOTATIONS_FILE
from .dates import parse_date


def load_annotations(filepath: str | None) -> dict[date, list[str]]:
    """
    Load annotations from a CSV file with columns Date and Note.
    Returns {date: [note, ...]} or {} if the file is absent / not specified.
    """
    path = filepath or (
        DEFAULT_ANNOTATIONS_FILE if Path(DEFAULT_ANNOTATIONS_FILE).exists() else None
    )
    if path is None:
        return {}
    if not Path(path).exists():
        print(f"⚠️  Annotations file not found: {path}", file=sys.stderr)
        return {}
    try:
        result: dict[date, list[str]] = defaultdict(list)
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                d_raw = row.get("Date", "").strip()
                n     = row.get("Note", "").strip()
                if not d_raw or not n:
                    continue
                d = parse_date(d_raw)
                if d is not None:
                    result[d].append(n)
        return dict(result)
    except Exception as e:
        print(f"⚠️  Error reading annotations: {e}", file=sys.stderr)
        return {}
