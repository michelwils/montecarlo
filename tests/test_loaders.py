import csv as csvmod
from datetime import date

import pytest

from montecarlo.loaders import (
    KanbanZoneCSVLoader,
    LOADERS,
    ThroughputLoader,
    TxtLoader,
    _fill_zero_weeks,
    _get_field,
    _is_unplanned,
    get_loader,
    load_throughput_auto,
)


class TestFillZeroWeeks:
    """
    Regression coverage for the zero-throughput-week bug: a calendar week
    with no completions must be counted as 0.0, not silently dropped —
    dropping it inflates average throughput and destabilizes small
    history-window sampling (see montecarlo/loaders.py docstring).
    """

    def test_empty_input_without_bounds_returns_empty(self):
        assert _fill_zero_weeks({}) == {}

    def test_no_gaps_returned_unchanged(self):
        weekly = {date(2026, 1, 5): 8.0, date(2026, 1, 12): 5.0}
        assert _fill_zero_weeks(weekly) == weekly

    def test_fills_interior_gap_with_zero(self):
        # Week of 2026-01-12 has no data of its own between two real weeks.
        weekly = {date(2026, 1, 5): 8.0, date(2026, 1, 19): 8.0}
        filled = _fill_zero_weeks(weekly)
        assert filled[date(2026, 1, 12)] == 0.0
        assert filled[date(2026, 1, 5)] == 8.0
        assert filled[date(2026, 1, 19)] == 8.0
        assert len(filled) == 3

    def test_does_not_overwrite_existing_values(self):
        weekly = {date(2026, 1, 5): 8.0, date(2026, 1, 12): 3.0}
        filled = _fill_zero_weeks(weekly)
        assert filled[date(2026, 1, 12)] == 3.0

    def test_explicit_start_fills_leading_zero_week(self):
        # Real data starts a week after the requested start date.
        weekly = {date(2026, 1, 12): 8.0}
        filled = _fill_zero_weeks(weekly, start=date(2026, 1, 5))
        assert filled[date(2026, 1, 5)] == 0.0
        assert filled[date(2026, 1, 12)] == 8.0

    def test_explicit_end_fills_trailing_zero_week(self):
        # Real data ends a week before the requested end date.
        weekly = {date(2026, 1, 5): 8.0}
        filled = _fill_zero_weeks(weekly, end=date(2026, 1, 12))
        assert filled[date(2026, 1, 5)] == 8.0
        assert filled[date(2026, 1, 12)] == 0.0

    def test_start_and_end_are_normalized_to_monday(self):
        # A Thursday start / Tuesday end should still bucket to full weeks.
        weekly = {date(2026, 1, 5): 8.0}
        filled = _fill_zero_weeks(
            weekly, start=date(2026, 1, 1), end=date(2026, 1, 13)
        )
        assert date(2025, 12, 29) in filled  # Monday of the week containing Jan 1
        assert date(2026, 1, 12) in filled   # Monday of the week containing Jan 13

    def test_start_beyond_existing_data_builds_full_range(self):
        filled = _fill_zero_weeks({}, start=date(2026, 1, 5), end=date(2026, 1, 19))
        assert filled == {
            date(2026, 1, 5): 0.0,
            date(2026, 1, 12): 0.0,
            date(2026, 1, 19): 0.0,
        }


class TestThroughputLoaderBase:
    def test_match_uses_extension_allowlist(self):
        loader = ThroughputLoader()
        loader.EXTENSIONS = [".csv"]
        assert loader.match("data.csv") is True
        assert loader.match("data.txt") is False

    def test_load_not_implemented(self):
        loader = ThroughputLoader()
        with pytest.raises(NotImplementedError):
            loader.load("data.csv", window_weeks=None)


class TestKanbanZoneCSVLoader:
    def test_match_requires_header_columns(self, tmp_path):
        loader = KanbanZoneCSVLoader()
        good = tmp_path / "good.csv"
        good.write_text("Done At,CF Envergure\n03-20-2026 10:00,Petit\n", encoding="utf-8")
        assert loader.match(str(good)) is True

        bad = tmp_path / "bad.csv"
        bad.write_text("Date,Points\n2026-03-20,3\n", encoding="utf-8")
        assert loader.match(str(bad)) is False

    def test_match_accepts_english_size_column(self, tmp_path):
        loader = KanbanZoneCSVLoader()
        path = tmp_path / "english.csv"
        path.write_text("Done At,CF Size\n03-20-2026 10:00,Petit\n", encoding="utf-8")
        assert loader.match(str(path)) is True

    def test_match_rejects_wrong_extension(self, kanban_csv):
        loader = KanbanZoneCSVLoader()
        assert loader.match("data.txt") is False

    def test_match_missing_file_returns_false(self):
        loader = KanbanZoneCSVLoader()
        assert loader.match("does/not/exist.csv") is False

    def test_aggregates_same_week_items(self, kanban_csv):
        path = kanban_csv([
            ("03-16-2026 09:00", "Petit"),   # Monday, 1 pt
            ("03-18-2026 09:00", "Moyen"),   # same week, 3 pts
            ("03-23-2026 09:00", "Grand"),   # next week, 5 pts
        ])
        weekly = KanbanZoneCSVLoader().load(path, window_weeks=None)
        assert weekly[date(2026, 3, 16)] == 4.0
        assert weekly[date(2026, 3, 23)] == 5.0

    def test_skips_unknown_envergure(self, kanban_csv):
        path = kanban_csv([
            ("03-16-2026 09:00", "Petit"),
            ("03-16-2026 09:00", "Inconnu"),
        ])
        weekly = KanbanZoneCSVLoader().load(path, window_weeks=None)
        assert weekly[date(2026, 3, 16)] == 1.0

    def test_skips_blank_done_at(self, kanban_csv):
        path = kanban_csv([("", "Petit"), ("03-16-2026 09:00", "Petit")])
        weekly = KanbanZoneCSVLoader().load(path, window_weeks=None)
        assert weekly == {date(2026, 3, 16): 1.0}

    def test_no_matching_rows_returns_empty_dict(self, kanban_csv, capsys):
        path = kanban_csv([("", "Petit")])
        weekly = KanbanZoneCSVLoader().load(path, window_weeks=None)
        assert weekly == {}
        assert "No throughput data found" in capsys.readouterr().err

    def test_tiny_score_is_half_point(self, kanban_csv):
        path = kanban_csv([("03-16-2026 09:00", "Très petit")])
        weekly = KanbanZoneCSVLoader().load(path, window_weeks=None)
        assert weekly[date(2026, 3, 16)] == 0.5

    def test_window_weeks_keeps_only_most_recent(self, kanban_csv):
        path = kanban_csv([
            ("01-05-2026 09:00", "Grand"),   # week 1
            ("01-12-2026 09:00", "Grand"),   # week 2
            ("01-19-2026 09:00", "Grand"),   # week 3 (most recent)
        ])
        weekly = KanbanZoneCSVLoader().load(path, window_weeks=1)
        assert weekly == {date(2026, 1, 19): 5.0}

    def test_window_start_end_filters_and_fills_zero_boundary(self, kanban_csv):
        # Only one item, in the middle of the requested range: the weeks
        # before and after it must still show up as explicit zeros.
        path = kanban_csv([("01-12-2026 09:00", "Petit")])
        weekly = KanbanZoneCSVLoader().load(
            path, window_weeks=None,
            window_start=date(2026, 1, 5), window_end=date(2026, 1, 19),
        )
        assert weekly == {
            date(2026, 1, 5): 0.0,
            date(2026, 1, 12): 1.0,
            date(2026, 1, 19): 0.0,
        }

    def test_window_start_end_excludes_items_outside_range(self, kanban_csv):
        path = kanban_csv([
            ("01-01-2026 09:00", "Grand"),   # before range
            ("01-12-2026 09:00", "Petit"),   # inside range
            ("02-01-2026 09:00", "Grand"),   # after range
        ])
        weekly = KanbanZoneCSVLoader().load(
            path, window_weeks=None,
            window_start=date(2026, 1, 5), window_end=date(2026, 1, 19),
        )
        assert sum(weekly.values()) == 1.0

    def test_excludes_cards_flagged_cf_prioritaire(self, tmp_path):
        path = tmp_path / "kanban_zone.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csvmod.writer(f)
            writer.writerow(["Done At", "CF Envergure", "CF Prioritaire"])
            writer.writerow(["03-16-2026 09:00", "Grand", ""])      # planned, 5 pts
            writer.writerow(["03-16-2026 10:00", "Moyen", "true"])  # ad hoc, excluded

        weekly = KanbanZoneCSVLoader().load(str(path), window_weeks=None)
        assert weekly == {date(2026, 3, 16): 5.0}

    def test_no_cf_prioritaire_column_is_backward_compatible(self, kanban_csv):
        # No 'CF Prioritaire' column at all (older exports, or the
        # committed exemples/ file): nothing should be excluded.
        path = kanban_csv([("03-16-2026 09:00", "Grand")])
        weekly = KanbanZoneCSVLoader().load(path, window_weeks=None)
        assert weekly == {date(2026, 3, 16): 5.0}

    def test_reads_french_value_from_english_column_name(self, tmp_path):
        # Custom field names are set per-board; a board created in an
        # English UI may export 'CF Size' instead of 'CF Envergure', but
        # still carry over French values if the board itself is French.
        path = tmp_path / "kanban_zone.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csvmod.writer(f)
            writer.writerow(["Done At", "CF Size"])
            writer.writerow(["03-16-2026 09:00", "Grand"])
        weekly = KanbanZoneCSVLoader().load(str(path), window_weeks=None)
        assert weekly == {date(2026, 3, 16): 5.0}

    def test_reads_english_size_values(self, tmp_path):
        # A fully English board: 'CF Size' column with English values.
        path = tmp_path / "kanban_zone.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csvmod.writer(f)
            writer.writerow(["Done At", "CF Size"])
            writer.writerow(["03-16-2026 09:00", "Large"])
            writer.writerow(["03-16-2026 10:00", "X-Small"])
        weekly = KanbanZoneCSVLoader().load(str(path), window_weeks=None)
        assert weekly == {date(2026, 3, 16): 5.5}  # Large (5) + X-Small (0.5)

    def test_excludes_cards_flagged_cf_exception(self, tmp_path):
        # English equivalent of 'CF Prioritaire'.
        path = tmp_path / "kanban_zone.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csvmod.writer(f)
            writer.writerow(["Done At", "CF Envergure", "CF Exception"])
            writer.writerow(["03-16-2026 09:00", "Grand", ""])
            writer.writerow(["03-16-2026 10:00", "Moyen", "true"])
        weekly = KanbanZoneCSVLoader().load(str(path), window_weeks=None)
        assert weekly == {date(2026, 3, 16): 5.0}

    def test_uniform_size_counts_cards_with_no_size_column(self, tmp_path):
        # A board with no size field at all: every card counts as
        # uniform_size points instead of being skipped.
        path = tmp_path / "kanban_zone.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csvmod.writer(f)
            writer.writerow(["Done At", "Card Title"])
            writer.writerow(["03-16-2026 09:00", "Task A"])
            writer.writerow(["03-16-2026 10:00", "Task B"])
        weekly = KanbanZoneCSVLoader().load(str(path), window_weeks=None, uniform_size=1.0)
        assert weekly == {date(2026, 3, 16): 2.0}

    def test_uniform_size_overrides_a_present_size_column(self, kanban_csv):
        # Explicit uniform_size takes precedence even if a size field
        # does exist and would otherwise be readable.
        path = kanban_csv([("03-16-2026 09:00", "Grand")])
        weekly = KanbanZoneCSVLoader().load(path, window_weeks=None, uniform_size=2.0)
        assert weekly == {date(2026, 3, 16): 2.0}

    def test_uniform_size_still_excludes_unplanned_cards(self, tmp_path):
        path = tmp_path / "kanban_zone.csv"
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csvmod.writer(f)
            writer.writerow(["Done At", "CF Exception"])
            writer.writerow(["03-16-2026 09:00", ""])
            writer.writerow(["03-16-2026 10:00", "true"])
        weekly = KanbanZoneCSVLoader().load(str(path), window_weeks=None, uniform_size=1.0)
        assert weekly == {date(2026, 3, 16): 1.0}


class TestGetField:
    def test_returns_first_non_empty_value(self):
        assert _get_field({"A": "", "B": "x"}, ("A", "B")) == "x"

    def test_prefers_earlier_column_when_both_set(self):
        assert _get_field({"A": "x", "B": "y"}, ("A", "B")) == "x"

    def test_returns_empty_string_when_none_present(self):
        assert _get_field({}, ("A", "B")) == ""


class TestIsUnplanned:
    @pytest.mark.parametrize("value", ["true", "True", "TRUE", "1", "yes", "oui"])
    def test_truthy_values(self, value):
        assert _is_unplanned({"CF Prioritaire": value}) is True

    @pytest.mark.parametrize("value", ["", "false", "non", "0", "  "])
    def test_falsy_values(self, value):
        assert _is_unplanned({"CF Prioritaire": value}) is False

    def test_missing_column_is_falsy(self):
        assert _is_unplanned({}) is False


class TestTxtLoader:
    def test_assigns_consecutive_mondays_oldest_first(self, txt_file):
        path = txt_file([3, 8, 5])
        weekly = TxtLoader().load(path, window_weeks=None)
        values_in_chronological_order = [v for _, v in sorted(weekly.items())]
        assert values_in_chronological_order == [3.0, 8.0, 5.0]

    def test_empty_file_returns_empty_dict(self, txt_file, capsys):
        path = txt_file([])
        weekly = TxtLoader().load(path, window_weeks=None)
        assert weekly == {}
        assert "No data found" in capsys.readouterr().err

    def test_window_weeks_keeps_most_recent(self, txt_file):
        path = txt_file([3, 8, 5])
        weekly = TxtLoader().load(path, window_weeks=1)
        assert list(weekly.values()) == [5.0]

    def test_window_start_end_filters(self, txt_file):
        path = txt_file([3, 8, 5, 2])
        full = TxtLoader().load(path, window_weeks=None)
        mondays = sorted(full.keys())
        weekly = TxtLoader().load(
            path, window_weeks=None, window_start=mondays[1], window_end=mondays[2],
        )
        assert weekly == {mondays[1]: full[mondays[1]], mondays[2]: full[mondays[2]]}


class TestLoaderRegistry:
    def test_get_loader_detects_kanban_zone(self, kanban_csv):
        path = kanban_csv([("03-16-2026 09:00", "Petit")])
        assert isinstance(get_loader(path), KanbanZoneCSVLoader)

    def test_get_loader_detects_txt(self, txt_file):
        path = txt_file([3, 8])
        assert isinstance(get_loader(path), TxtLoader)

    def test_get_loader_returns_none_for_unrecognized(self, tmp_path):
        path = tmp_path / "data.xlsx"
        path.write_text("nope", encoding="utf-8")
        assert get_loader(str(path)) is None

    def test_loaders_registry_is_not_empty(self):
        assert len(LOADERS) >= 2

    def test_load_throughput_auto_delegates(self, kanban_csv):
        path = kanban_csv([("03-16-2026 09:00", "Petit")])
        weekly = load_throughput_auto(path, window_weeks=None)
        assert weekly == {date(2026, 3, 16): 1.0}

    def test_load_throughput_auto_warns_on_unsupported_format(self, tmp_path, capsys):
        path = tmp_path / "data.xlsx"
        path.write_text("nope", encoding="utf-8")
        weekly = load_throughput_auto(str(path), window_weeks=None)
        assert weekly == {}
        assert "Unsupported format" in capsys.readouterr().err

    def test_uniform_size_forces_kanban_zone_loader_without_a_size_column(self, tmp_path):
        # get_loader()'s own header-based match() would reject this file
        # (no CF Size/CF Envergure column), but uniform_size means the
        # caller already knows it's a Kanban Zone source.
        path = tmp_path / "no_size.csv"
        path.write_text(
            "Done At,Card Title\n03-16-2026 09:00,Task A\n", encoding="utf-8",
        )
        assert get_loader(str(path)) is None  # confirms normal detection fails
        weekly = load_throughput_auto(str(path), window_weeks=None, uniform_size=1.0)
        assert weekly == {date(2026, 3, 16): 1.0}
