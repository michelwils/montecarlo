"""Shared pytest fixtures for the montecarlo test suite."""
import csv

import pytest


@pytest.fixture
def kanban_csv(tmp_path):
    """
    Return a factory that writes a minimal Kanban Zone CSV to a temp file
    and returns its path. rows is a list of (done_at, envergure) tuples.
    """
    def _write(rows, name="kanban_zone.csv"):
        path = tmp_path / name
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Done At", "CF Envergure"])
            writer.writerows(rows)
        return str(path)

    return _write


@pytest.fixture
def txt_file(tmp_path):
    """Return a factory that writes a plain-text weekly throughput file."""
    def _write(values, name="throughput.txt"):
        path = tmp_path / name
        path.write_text(", ".join(str(v) for v in values), encoding="utf-8")
        return str(path)

    return _write
