from datetime import date, datetime

from montecarlo.naming import (
    DEFAULT_FILENAME_FORMAT,
    render_filename,
    validate_filename_format,
)


class TestValidateFilenameFormat:
    def test_default_template_is_valid(self):
        assert validate_filename_format(DEFAULT_FILENAME_FORMAT) is None

    def test_unknown_placeholder_reported(self):
        error = validate_filename_format("{bogus}")
        assert error is not None
        assert "bogus" in error

    def test_bad_format_spec_reported(self):
        error = validate_filename_format("{target:%Y}")
        assert error is not None

    def test_every_documented_placeholder_is_accepted(self):
        template = "{prefix}_{date}_{target}_{prob}_{timestamp}_{weeks}_{simulations}"
        assert validate_filename_format(template) is None


class TestRenderFilename:
    def test_default_template_renders_expected_shape(self):
        stem = render_filename(
            DEFAULT_FILENAME_FORMAT,
            prefix="monte_carlo",
            date=date(2026, 11, 23),
            target=5.0,
            prob=100.0,
            timestamp=datetime(2026, 9, 22, 9, 52, 7),
            weeks=8,
            simulations=200,
        )
        assert stem == "monte_carlo_2026-11-23_5pts_100pct_20260922_095207"

    def test_custom_template_with_own_format_specs(self):
        stem = render_filename(
            "{timestamp:%Y%m%d_%H%M%S}_{weeks}w_{simulations}sims",
            prefix="monte_carlo",
            date=date(2026, 11, 23),
            target=5.0,
            prob=100.0,
            timestamp=datetime(2026, 9, 22, 9, 52, 7),
            weeks=8,
            simulations=200,
        )
        assert stem == "20260922_095207_8w_200sims"

    def test_illegal_filename_characters_are_stripped(self):
        stem = render_filename(
            "{timestamp:%H:%M}_report",
            prefix="p", date=date(2026, 1, 1), target=1.0, prob=1.0,
            timestamp=datetime(2026, 9, 22, 9, 52, 7), weeks=1, simulations=1,
        )
        assert ":" not in stem
