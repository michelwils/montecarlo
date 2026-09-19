import io
from datetime import date
from pathlib import Path

import pytest

from montecarlo.cli import (
    _ConfigArgumentParser,
    _ensure_utf8_streams,
    build_parser,
    compute_target_score,
    main,
    resolve_data_file,
    resolve_start_date,
    resolve_weeks,
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

    def test_output_prefix_defaults_to_none(self):
        args = build_parser().parse_args([])
        assert args.output_prefix is None

    def test_configs_defaults_to_none(self):
        args = build_parser().parse_args([])
        assert args.configs is None

    def test_configs_accepts_multiple_files(self):
        args = build_parser().parse_args(["--configs", "a.conf", "b.conf", "--lang", "fr"])
        assert args.configs == ["a.conf", "b.conf"]
        assert args.lang == "fr"


class TestConfigArgumentParser:
    def setup_method(self):
        self.parser = build_parser()
        assert isinstance(self.parser, _ConfigArgumentParser)

    def test_blank_and_comment_lines_are_ignored(self):
        assert self.parser.convert_arg_line_to_args("") == []
        assert self.parser.convert_arg_line_to_args("   ") == []
        assert self.parser.convert_arg_line_to_args("# a comment") == []

    def test_flag_and_value_on_one_line(self):
        assert self.parser.convert_arg_line_to_args("-m 5") == ["-m", "5"]
        assert self.parser.convert_arg_line_to_args("--lang fr") == ["--lang", "fr"]

    def test_bare_flag_with_no_value(self):
        assert self.parser.convert_arg_line_to_args("--formats") == ["--formats"]

    def test_multi_value_option_splits_into_separate_tokens(self):
        assert self.parser.convert_arg_line_to_args("-c 80 90 95") == ["-c", "80", "90", "95"]

    def test_quoted_value_with_spaces_stays_one_token(self):
        assert self.parser.convert_arg_line_to_args(
            '-D "My subtitle here"'
        ) == ["-D", "My subtitle here"]

    def test_windows_backslash_path_is_preserved(self):
        # Regression guard: shlex.split() would treat backslashes as
        # escape characters and mangle a pasted Windows path (e.g.
        # "C:\Users\x\file.csv" -> "C:Usersxfile.csv"). This parser
        # must not do that.
        line = r"-f C:\Users\test\data\kanban_zone.csv"
        assert self.parser.convert_arg_line_to_args(line) == [
            "-f", r"C:\Users\test\data\kanban_zone.csv",
        ]

    def test_path_with_spaces_must_be_quoted(self):
        # A path with spaces splits into multiple tokens if unquoted —
        # same rule as a shell command line. Quoting keeps it together.
        unquoted = self.parser.convert_arg_line_to_args(
            r"-f C:\OneDrive - Team\data.csv"
        )
        assert unquoted != ["-f", r"C:\OneDrive - Team\data.csv"]

        quoted = self.parser.convert_arg_line_to_args(
            '-f "C:\\OneDrive - Team\\data.csv"'
        )
        assert quoted == ["-f", r"C:\OneDrive - Team\data.csv"]

    def test_reads_options_from_an_at_file(self, tmp_path):
        config = tmp_path / "run.conf"
        config.write_text(
            "# a comment\n\n-m 5\n-l 2\n--lang fr\n", encoding="utf-8",
        )
        args = self.parser.parse_args([f"@{config}", "-w", "8"])
        assert args.medium == 5
        assert args.large == 2
        assert args.lang == "fr"
        assert args.weeks == 8

    def test_command_line_overrides_config_file_value(self, tmp_path):
        config = tmp_path / "run.conf"
        config.write_text("-m 5\n-w 4\n", encoding="utf-8")
        args = self.parser.parse_args([f"@{config}", "-w", "9"])
        assert args.weeks == 9  # the later, explicit -w wins


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


class TestResolveWeeks:
    def test_uses_weeks_directly_when_no_target_date(self):
        parser = build_parser()
        args = parser.parse_args(["-w", "7"])
        assert resolve_weeks(args, parser, date(2026, 1, 5)) == (7, None)

    def test_derives_weeks_from_target_date_ceiling(self):
        # 2026-01-05 (Mon) -> 2026-01-19 (Mon) is exactly 14 days = 2 weeks.
        parser = build_parser()
        args = parser.parse_args(["--target-date", "2026-01-19"])
        weeks, target_date = resolve_weeks(args, parser, date(2026, 1, 5))
        assert weeks == 2
        assert target_date == date(2026, 1, 19)

    def test_partial_week_rounds_up(self):
        # 15 days -> 2.14 weeks -> ceil to 3.
        parser = build_parser()
        args = parser.parse_args(["--target-date", "2026-01-20"])
        weeks, _ = resolve_weeks(args, parser, date(2026, 1, 5))
        assert weeks == 3

    def test_target_date_on_start_date_is_rejected(self):
        parser = build_parser()
        args = parser.parse_args(["--target-date", "2026-01-05"])
        with pytest.raises(SystemExit):
            resolve_weeks(args, parser, date(2026, 1, 5))

    def test_target_date_before_start_date_is_rejected(self):
        parser = build_parser()
        args = parser.parse_args(["--target-date", "2026-01-01"])
        with pytest.raises(SystemExit):
            resolve_weeks(args, parser, date(2026, 1, 5))

    def test_invalid_target_date_format_is_rejected(self):
        parser = build_parser()
        args = parser.parse_args(["--target-date", "not-a-date"])
        with pytest.raises(SystemExit):
            resolve_weeks(args, parser, date(2026, 1, 5))


class TestResolveDataFile:
    def test_returns_explicit_file_when_it_exists(self):
        args = build_parser().parse_args(["-w", "1", "-f", SAMPLE_KANBAN_CSV])
        assert resolve_data_file(args, EN) == SAMPLE_KANBAN_CSV

    def test_explicit_missing_file_exits(self):
        args = build_parser().parse_args(["-w", "1", "-f", "does/not/exist.csv"])
        with pytest.raises(SystemExit):
            resolve_data_file(args, EN)

    def test_board_and_file_together_exits(self, monkeypatch):
        monkeypatch.delenv("KANBAN_ZONE_API_KEY", raising=False)
        args = build_parser().parse_args([
            "-w", "1", "-f", SAMPLE_KANBAN_CSV, "--board", "abc123", "--api-key", "k",
        ])
        with pytest.raises(SystemExit):
            resolve_data_file(args, EN)

    def test_board_without_api_key_exits(self, monkeypatch):
        monkeypatch.delenv("KANBAN_ZONE_API_KEY", raising=False)
        args = build_parser().parse_args(["-w", "1", "--board", "abc123"])
        with pytest.raises(SystemExit):
            resolve_data_file(args, EN)

    def test_board_fetches_and_writes_temp_csv(self, monkeypatch, tmp_path):
        fake_path = str(tmp_path / "fetched.csv")
        fake_path_file = Path(fake_path)
        fake_path_file.write_text("Done At\n", encoding="utf-8")

        captured = {}

        def fake_fetch_cards(board, api_key, include_archived=False):
            captured["board"] = board
            captured["api_key"] = api_key
            captured["include_archived"] = include_archived
            return ["card1"]

        monkeypatch.setattr("montecarlo.cli.fetch_cards", fake_fetch_cards)
        monkeypatch.setattr("montecarlo.cli.write_cards_as_csv", lambda cards: fake_path)

        args = build_parser().parse_args([
            "-w", "1", "--board", "abc123", "--api-key", "my-key", "--include-archived",
        ])
        result = resolve_data_file(args, EN)

        assert result == fake_path
        assert captured == {"board": "abc123", "api_key": "my-key", "include_archived": True}

    def test_board_uses_env_var_when_no_explicit_key(self, monkeypatch, tmp_path):
        monkeypatch.setenv("KANBAN_ZONE_API_KEY", "env-key")
        captured = {}
        monkeypatch.setattr(
            "montecarlo.cli.fetch_cards",
            lambda board, api_key, include_archived=False: captured.update(api_key=api_key) or [],
        )
        monkeypatch.setattr("montecarlo.cli.write_cards_as_csv", lambda cards: str(tmp_path / "x.csv"))
        (tmp_path / "x.csv").write_text("Done At\n", encoding="utf-8")

        args = build_parser().parse_args(["-w", "1", "--board", "abc123"])
        resolve_data_file(args, EN)
        assert captured["api_key"] == "env-key"

    def test_board_api_error_exits(self, monkeypatch):
        from montecarlo.kanbanzone_api import KanbanZoneAPIError

        def raise_error(board, api_key, include_archived=False):
            raise KanbanZoneAPIError("boom")

        monkeypatch.setattr("montecarlo.cli.fetch_cards", raise_error)
        args = build_parser().parse_args(["-w", "1", "--board", "abc123", "--api-key", "k"])
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

    def test_no_weeks_and_no_target_date_prints_help_and_exits(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["monte_carlo.py", "-s", "5"])
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 1
        assert "usage" in capsys.readouterr().out.lower()

    def test_weeks_and_target_date_together_are_rejected(self, monkeypatch):
        monkeypatch.setattr("sys.argv", [
            "monte_carlo.py", "-s", "5", "-w", "8", "--target-date", "2026-12-31",
        ])
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 2

    def test_unplanned_ratio_of_one_is_rejected(self, monkeypatch):
        monkeypatch.setattr("sys.argv", [
            "monte_carlo.py", "-s", "5", "-w", "8", "-u", "1.0",
        ])
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 2

    def test_negative_unplanned_ratio_is_rejected(self, monkeypatch):
        monkeypatch.setattr("sys.argv", [
            "monte_carlo.py", "-s", "5", "-w", "8", "-u", "-0.1",
        ])
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 2

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

    def test_output_prefix_names_the_chart_file(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", [
            "monte_carlo.py",
            "-f", SAMPLE_KANBAN_CSV,
            "-m", "3", "-w", "8", "-n", "200",
            "-P", "my_prefix",
            "-o", str(tmp_path),
        ])
        main()
        files = list(tmp_path.glob("*.png"))
        assert len(files) == 1
        assert files[0].name.startswith("my_prefix_")

    def test_configs_runs_each_file_with_its_own_prefix(self, tmp_path, monkeypatch, capsys):
        config_a = tmp_path / "team_a.conf"
        config_a.write_text(f'-f "{SAMPLE_KANBAN_CSV}"\n-m 3\n-w 8\n', encoding="utf-8")
        config_b = tmp_path / "team_b.conf"
        config_b.write_text(f'-f "{SAMPLE_KANBAN_CSV}"\n-s 4\n-w 6\n', encoding="utf-8")

        out_dir = tmp_path / "out"
        monkeypatch.setattr("sys.argv", [
            "monte_carlo.py",
            "--configs", str(config_a), str(config_b),
            "-n", "200", "--lang", "fr",  # shared flags applied to both runs
            "-o", str(out_dir),
        ])
        main()
        out = capsys.readouterr().out

        # Each run is announced and uses French (the shared flag).
        assert str(config_a) in out
        assert str(config_b) in out
        assert out.count("Exécution de 200 simulations") == 2

        files = sorted(p.name for p in out_dir.glob("*.png"))
        assert len(files) == 2
        assert files[0].startswith("team_a_")
        assert files[1].startswith("team_b_")

    def test_configs_with_explicit_prefix_applies_to_all_runs(self, tmp_path, monkeypatch, capsys):
        config_a = tmp_path / "team_a.conf"
        config_a.write_text(f'-f "{SAMPLE_KANBAN_CSV}"\n-m 3\n-w 8\n', encoding="utf-8")
        config_b = tmp_path / "team_b.conf"
        config_b.write_text(f'-f "{SAMPLE_KANBAN_CSV}"\n-s 4\n-w 6\n', encoding="utf-8")

        out_dir = tmp_path / "out"
        monkeypatch.setattr("sys.argv", [
            "monte_carlo.py",
            "--configs", str(config_a), str(config_b),
            "-P", "shared_name", "-n", "200",
            "-o", str(out_dir),
        ])
        main()
        files = sorted(p.name for p in out_dir.glob("*.png"))
        assert len(files) == 2
        assert all(f.startswith("shared_name_") for f in files)

    def test_runs_from_the_api_and_cleans_up_the_temp_file(self, tmp_path, monkeypatch, capsys):
        cards = [
            {
                "doneAt": f"2026-0{m}-0{d}T10:00:00.000Z",
                "customFields": [{"label": "Envergure", "value": "Moyen"}],
            }
            for m, d in [(1, 5), (2, 2), (3, 2), (4, 6), (5, 4)]
        ]
        monkeypatch.setattr("montecarlo.cli.fetch_cards", lambda *a, **kw: cards)

        written_path = {}

        def fake_write(cards):
            # Use the real row-building logic, but write to our own
            # tracked path so we can assert it gets cleaned up.
            import csv as csvmod
            from montecarlo.kanbanzone_api import cards_to_csv_rows
            path = tmp_path / "board_fetch.csv"
            rows = cards_to_csv_rows(cards)
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csvmod.DictWriter(f, fieldnames=["Done At", "CF Envergure"])
                writer.writeheader()
                writer.writerows(rows)
            written_path["path"] = str(path)
            return str(path)

        monkeypatch.setattr("montecarlo.cli.write_cards_as_csv", fake_write)

        monkeypatch.setattr("sys.argv", [
            "monte_carlo.py",
            "--board", "abc123", "--api-key", "test-key",
            "-m", "1", "-w", "4", "-n", "200",
            "-o", str(tmp_path),
        ])
        main()
        out = capsys.readouterr().out
        assert "Kanban Zone API (board abc123)" in out
        assert len(list(tmp_path.glob("*.png"))) == 1
        assert not Path(written_path["path"]).exists(), "temp CSV should be deleted after the run"

    def test_runs_from_an_at_config_file(self, tmp_path, monkeypatch, capsys):
        config = tmp_path / "run.conf"
        # Quoted because SAMPLE_KANBAN_CSV (an absolute repo path) may
        # itself contain spaces, same as any unquoted value with spaces.
        config.write_text(
            f'-f "{SAMPLE_KANBAN_CSV}"\n'
            "-m 3\n"
            "-w 10\n"
            "-n 200\n",
            encoding="utf-8",
        )
        monkeypatch.setattr("sys.argv", [
            "monte_carlo.py", f"@{config}", "-o", str(tmp_path),
        ])
        main()
        out = capsys.readouterr().out
        assert "Probability of delivering" in out
        assert len(list(tmp_path.glob("*.png"))) == 1

    def test_target_date_derives_weeks_and_shows_in_summary(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", [
            "monte_carlo.py",
            "-f", SAMPLE_KANBAN_CSV,
            "-m", "3", "-d", "2026-01-05", "--target-date", "2026-01-19",
            "-n", "200",
            "-o", str(tmp_path),
        ])
        main()
        out = capsys.readouterr().out
        label_width = 14  # must match montecarlo.cli's console label column width
        assert f"{EN['param_duration']:<{label_width}}: 2 weeks (until 2026-01-19)" in out
        assert len(list(tmp_path.glob("*.png"))) == 1

    def test_unplanned_ratio_shown_and_lowers_probability(self, tmp_path, monkeypatch, capsys):
        common_args = [
            "monte_carlo.py",
            "-f", SAMPLE_KANBAN_CSV,
            "-m", "8", "-w", "6",
            "-n", "500",
        ]

        label_width = 14  # must match montecarlo.cli's console label column width

        monkeypatch.setattr("sys.argv", common_args + ["-o", str(tmp_path / "baseline")])
        main()
        baseline_out = capsys.readouterr().out
        assert f"{EN['param_unplanned']:<{label_width}}: {EN['none_val']}" in baseline_out

        monkeypatch.setattr(
            "sys.argv", common_args + ["-u", "0.4", "-o", str(tmp_path / "discounted")]
        )
        main()
        discounted_out = capsys.readouterr().out
        assert f"{EN['param_unplanned']:<{label_width}}: 40%" in discounted_out

        def probability(out: str) -> float:
            line = next(l for l in out.splitlines() if "Probability of delivering" in l)
            return float(line.split(":")[-1].strip().rstrip("%"))

        assert probability(discounted_out) <= probability(baseline_out)

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
