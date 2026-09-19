import io
from pathlib import Path

import pytest

from montecarlo.cli import _ensure_utf8_streams, build_parser, main

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_KANBAN_CSV = str(REPO_ROOT / "exemples" / "kanban_zone.csv")


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
