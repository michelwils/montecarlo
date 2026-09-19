from datetime import date

from montecarlo.dates import next_monday, parse_date


class TestParseDate:
    def test_iso_format(self):
        assert parse_date("2026-03-20") == date(2026, 3, 20)

    def test_slash_format(self):
        assert parse_date("2026/03/20") == date(2026, 3, 20)

    def test_kanban_zone_format(self):
        assert parse_date("03-20-2026 14:30") == date(2026, 3, 20)

    def test_am_pm_format(self):
        assert parse_date("03/20/2026 02:30 PM") == date(2026, 3, 20)

    def test_strips_whitespace(self):
        assert parse_date("  2026-03-20  ") == date(2026, 3, 20)

    def test_empty_string_returns_none(self):
        assert parse_date("") is None
        assert parse_date("   ") is None

    def test_garbage_returns_none(self):
        assert parse_date("not a date") is None

    def test_ambiguous_partial_match_rejected(self):
        # A format that only partially matches must not silently succeed.
        assert parse_date("2026-03") is None


class TestNextMonday:
    def test_returns_same_day_when_already_monday(self):
        monday = date(2026, 3, 16)  # a Monday
        assert next_monday(monday) == monday

    def test_returns_upcoming_monday(self):
        wednesday = date(2026, 3, 18)
        assert next_monday(wednesday) == date(2026, 3, 23)

    def test_sunday_rolls_to_next_day(self):
        sunday = date(2026, 3, 22)
        assert next_monday(sunday) == date(2026, 3, 23)
