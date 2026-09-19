import io
from datetime import date
from pathlib import Path

import pytest

from montecarlo.cli import (
    _ensure_utf8_streams,
    build_parser,
    compute_target_score,
    main,
    resolve_data_file,
    resolve_start_date,
    resolve_window,
)
from montecarlo.strings import CHART_STRINGS

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_KANBAN_CSV = str(REPO_ROOT / "exemples" / "kanban_zone.csv")
EN = CHART_STRINGS["en"]


class TestEnsureUtf8Streams:
    def test_reconfigures_stdout_and_stderr_to_utf8(self, monkeypatch):
        fake_out = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        fake_err = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        monkeypatch.setattr("sys.stdout", fake_out)
        monkeypatch.setattr("sys.stderr", fake_err)

        _ensure_utf8_streams()

        assert fake_out.encoding.lower() == "utf-8"
        assert fake_err.encoding.lower() == "utf-8"

    def test_emoji_no_longer_raises_on_a_legacy_encoding(self, monkeypatch):
        # Reproduces the crash this fix addresses: printing status emoji
        # (📋 🔄 🎯 ⚠️ ✅) to a stream whose native encoding can't
        # represent them used to raise UnicodeEncodeError.
        fake_out = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
        monkeypatch.setattr("sys.stdout", fake_out)
        monkeypatch.setattr("sys.stderr", io.TextIOWrapper(io.BytesIO(), encoding="cp1252"))

        _ensure_utf8_streams()
        print("📋 Configuration")  # must not raise
        fake_out.flush()

    def test_tolerates_streams_without_reconfigure(self, monkeypatch):
        class NoReconfigure:
            pass

        monkeypatch.setattr("sys.stdout", NoReconfigure())
        monkeypatch.setattr("sys.stderr", NoReconfigure())
        _ensure_utf8_streams()  # must not raise


class TestBuildParser:
    def test_weeks_defaults_to_none(self):
        args = build_parser().parse_args([])
        assert args.weeks is None

    def test_certainties_default_to_80(self):
        args = build_parser().parse_args([])
        assert args.certainties == [80]

    def test_parses_tiny_and_window_options(self):
        args = build_parser().parse_args([
            "-t", "3", "-w", "8", "--window-start", "2026-01-01", "--window-end", "2026-03-31",
        ])
        assert args.tiny == 3
        assert args.weeks == 8
        assert args.window_start == "2026-01-01"
        assert args.window_end == "2026-03-31"


class TestComputeTargetScore:
    def test_sums_weighted_items_and_direct_points(self):
        args = build_parser().parse_args([
            "-w", "1", "-t", "2", "-s", "1", "-m", "1", "-l", "1", "-x", "1", "-p", "3",
        ])
        # 2*0.5 + 1*1 + 1*3 + 1*5 + 1*8 + 3 direct = 21
        assert compute_target_score(args) == 21.0

    def test_zero_when_nothing_requested(self):
        args = build_parser().parse_args(["-w", "1"])
        assert compute_target_score(args) == 0.0


class TestResolveWindow:
    def test_returns_none_none_when_unset(self):
        parser = build_parser()
        assert resolve_window(parser.parse_args(["-w", "1"]), parser) == (None, None)

    def test_parses_a_valid_range(self):
        parser = build_parser()
        args = parser.parse_args([
            "-w", "1", "--window-start", "2026-01-01", "--window-end", "2026-01-31",
        ])
        assert resolve_window(args, parser) == (date(2026, 1, 1), date(2026, 1, 31))

    def test_window_and_window_start_together_exits(self):
        parser = build_parser()
        args = parser.parse_args([
            "-w", "1", "-W", "4",
            "--window-start", "2026-01-01", "--window-end", "2026-01-31",
        ])
        with pytest.raises(SystemExit):
            resolve_window(args, parser)

    def test_start_without_end_exits(self):
        parser = build_parser()
        args = parser.parse_args(["-w", "1", "--window-start", "2026-01-01"])
        with pytest.raises(SystemExit):
            resolve_window(args, parser)

    def test_invalid_date_format_exits(self):
        parser = build_parser()
        args = parser.parse_args([
            "-w", "1", "--window-start", "nope", "--window-end", "2026-01-31",
        ])
        with pytest.raises(SystemExit):
            resolve_window(args, parser)

    def test_end_before_start_exits(self):
        parser = build_parser()
        args = parser.parse_args([
            "-w", "1", "--window-start", "2026-02-01", "--window-end", "2026-01-01",
        ])
        with pytest.raises(SystemExit):
            resolve_window(args, parser)


class TestResolveDataFile:
    def test_returns_explicit_file_when_it_exists(self):
        args = build_parser().parse_args(["-w", "1", "-f", SAMPLE_KANBAN_CSV])
        assert resolve_data_file(args, EN) == SAMPLE_KANBAN_CSV

    def test_explicit_missing_file_exits(self):
        args = build_parser().parse_args(["-w", "1", "-f", "does/not/exist.csv"])
        with pytest.raises(SystemExit):
            resolve_data_file(args, EN)


class TestResolveStartDate:
    def test_defaults_to_next_monday(self):
        args = build_parser().parse_args(["-w", "1"])
        assert resolve_start_date(args, EN).weekday() == 0

    def test_parses_explicit_date(self):
        args = build_parser().parse_args(["-w", "1", "-d", "2026-03-20"])
        assert resolve_start_date(args, EN) == date(2026, 3, 20)

    def test_invalid_date_exits(self):
        args = build_parser().parse_args(["-w", "1", "-d", "not-a-date"])
        with pytest.raises(SystemExit):
            resolve_start_date(args, EN)


class TestMainValidation:
    def test_no_target_prints_help_and_exits(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["monte_carlo.py", "-w", "5"])
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 1
        assert "usage" in capsys.readouterr().out.lower()

    def test_window_and_window_start_are_mutually_exclusive(self, monkeypatch):
        monkeypatch.setattr("sys.argv", [
            "monte_carlo.py", "-s", "5", "-w", "8", "-W", "4",
            "--window-start", "2026-01-01", "--window-end", "2026-03-31",
        ])
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 2

    def test_window_start_requires_window_end(self, monkeypatch):
        monkeypatch.setattr("sys.argv", [
            "monte_carlo.py", "-s", "5", "-w", "8", "--window-start", "2026-01-01",
        ])
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 2

    def test_invalid_window_start_format_rejected(self, monkeypatch):
        monkeypatch.setattr("sys.argv", [
            "monte_carlo.py", "-s", "5", "-w", "8",
            "--window-start", "not-a-date", "--window-end", "2026-03-31",
        ])
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 2

    def test_window_end_before_start_rejected(self, monkeypatch):
        monkeypatch.setattr("sys.argv", [
            "monte_carlo.py", "-s", "5", "-w", "8",
            "--window-start", "2026-03-31", "--window-end", "2026-01-01",
        ])
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 2

    def test_missing_file_exits(self, monkeypatch):
        monkeypatch.setattr("sys.argv", [
            "monte_carlo.py", "-f", "does/not/exist.csv", "-s", "5", "-w", "8",
        ])
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 1


class TestMainEndToEnd:
    def test_full_run_produces_a_chart(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", [
            "monte_carlo.py",
            "-f", SAMPLE_KANBAN_CSV,
            "-s", "5", "-m", "3", "-w", "10",
            "-n", "200",  # keep the test fast
            "-o", str(tmp_path),
        ])
        main()
        out = capsys.readouterr().out
        assert "Probability of delivering" in out
        assert len(list(tmp_path.glob("*.png"))) == 1

    def test_formats_flag_lists_loaders_and_exits_cleanly(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["monte_carlo.py", "--formats"])
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0
        assert "kanban_zone" in capsys.readouterr().out

    def test_french_console_output_is_translated(self, tmp_path, monkeypatch, capsys):
        """
        Regression test: the console summary used to be hardcoded in
        English regardless of --lang, and its history-window line had
        the same "{start} to {end}" bug fixed on the chart panel.
        """
        monkeypatch.setattr("sys.argv", [
            "monte_carlo.py",
            "-f", SAMPLE_KANBAN_CSV,
            "-s", "5", "-w", "8",
            "--window-start", "2026-01-01", "--window-end", "2026-03-31",
            "-n", "200",
            "--lang", "fr",
            "-o", str(tmp_path),
        ])
        main()
        out = capsys.readouterr().out
        assert "Probabilité de livrer" in out
        assert "2026-01-01 au 2026-03-31" in out
        assert " to " not in out
