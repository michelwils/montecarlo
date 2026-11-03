from datetime import date
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from montecarlo.charts import _draw_sensitivity_chart, make_charts
from montecarlo.loaders import OwnerFilter
from montecarlo.simulation import weekly_samples
from montecarlo.strings import CHART_STRINGS

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_KANBAN_CSV = str(REPO_ROOT / "exemples" / "kanban_zone.csv")


class TestChartStrings:
    def test_all_languages_define_the_same_keys(self):
        """
        Every language table must expose the exact same keys — a key
        added for one language and forgotten for another would raise a
        KeyError only when that specific --lang is used, easy to miss.
        """
        key_sets = {lang: set(table.keys()) for lang, table in CHART_STRINGS.items()}
        reference_lang, reference_keys = next(iter(key_sets.items()))
        for lang, keys in key_sets.items():
            assert keys == reference_keys, (
                f"{lang} keys differ from {reference_lang}: "
                f"missing={reference_keys - keys}, extra={keys - reference_keys}"
            )

    def test_size_keys_exist_for_every_score_tier(self):
        for lang, table in CHART_STRINGS.items():
            for key in ("size_tiny", "size_small", "size_medium", "size_large", "size_xlarge"):
                assert key in table, f"{lang} table is missing '{key}'"


class TestSensitivityExclusions:
    def test_exclusions_preserve_calendar_anchor(self, kanban_csv, monkeypatch):
        from montecarlo.loaders import load_throughput_auto

        path = kanban_csv([
            ("2026-01-05", "Small"), ("2026-01-12", "Medium"), ("2026-01-19", "Large"),
        ])
        periods = [(date(2026, 1, 19), date(2026, 1, 19))]
        loads, histories = [], []

        def capture_load(filepath, window_weeks, **kwargs):
            loads.append(window_weeks)
            return load_throughput_auto(filepath, window_weeks, **kwargs)

        def capture_samples(weekly):
            histories.append(weekly)
            return weekly_samples(weekly)

        monkeypatch.setattr("montecarlo.charts.load_throughput_auto", capture_load)
        monkeypatch.setattr("montecarlo.charts.weekly_samples", capture_samples)
        figure, axis = plt.subplots()
        try:
            _draw_sensitivity_chart(
                axis, CHART_STRINGS["en"], filepath=path,
                window_weeks=2, window_start=None, window_end=None,
                target_score=1, n_workdays=5, n_weeks=1,
                display_window=None, certainties=[80], annotations={},
                exclude_periods=periods,
            )
            # The file is read once; windows (All, 3, 2, 1 weeks) are cut in
            # memory. The 1-week window is fully excluded, so it isn't simulated.
            assert loads == [None]
            assert histories == [
                {date(2026, 1, 5): 1.0, date(2026, 1, 12): 3.0},
                {date(2026, 1, 5): 1.0, date(2026, 1, 12): 3.0},
                {date(2026, 1, 12): 3.0},
            ]
            assert axis.get_xticklabels()[-1].get_text() == "2026-01-19"
            assert len(figure.axes[1].patches) == 2
        finally:
            plt.close(figure)

    def test_owner_filter_applies_to_sensitivity_history(self, tmp_path, monkeypatch):
        path = tmp_path / "owners.csv"
        path.write_text(
            "Done At,CF Size,Members\n"
            "2026-01-05,Small,Alice\n2026-01-05,Large,Bob\n2026-01-12,Medium,Alice\n",
            encoding="utf-8",
        )
        histories = []

        def capture_samples(weekly):
            histories.append(weekly)
            return weekly_samples(weekly)

        monkeypatch.setattr("montecarlo.charts.weekly_samples", capture_samples)
        figure, axis = plt.subplots()
        try:
            _draw_sensitivity_chart(
                axis, CHART_STRINGS["en"], filepath=str(path),
                window_weeks=None, window_start=None, window_end=None,
                target_score=1, n_workdays=5, n_weeks=1,
                display_window=None, certainties=[80], annotations={},
                owner_filter=OwnerFilter(["alice"]),
            )
            assert histories[0] == {date(2026, 1, 5): 1.0, date(2026, 1, 12): 3.0}
        finally:
            plt.close(figure)

    def test_annotations_stay_anchored_when_the_last_week_is_excluded(self, kanban_csv):
        path = kanban_csv([
            ("2026-01-05", "Small"), ("2026-01-12", "Medium"), ("2026-01-19", "Large"),
        ])
        figure, axis = plt.subplots()
        try:
            _draw_sensitivity_chart(
                axis, CHART_STRINGS["en"], filepath=path,
                window_weeks=None, window_start=None, window_end=None,
                target_score=1, n_workdays=5, n_weeks=1,
                display_window=None, certainties=[80],
                annotations={date(2026, 1, 7): ["Kickoff"]},
                exclude_periods=[(date(2026, 1, 19), date(2026, 1, 19))],
            )
            # Windows are [All, 3, 2, 1] weeks ending on 2026-01-19, the last
            # week of the full history even though it's excluded. Jan 7 is
            # ~2.3 weeks before that week's Friday, so it's drawn at the
            # 2-week window (index 2); anchoring on the last remaining week
            # (2026-01-12) would put it ~1.3 weeks back, at index 3.
            note = next(text for text in axis.texts if text.get_text() == "Kickoff")
            assert note.get_position()[0] == 2 + 0.15
        finally:
            plt.close(figure)


class TestMakeCharts:
    def _run(self, tmp_path, weeks_arr, items_arr, **overrides):
        kwargs = dict(
            weeks_arr=weeks_arr,
            items_arr=items_arr,
            target_score=25.0,
            n_weeks=5,
            window_weeks=None,
            window_start=None,
            window_end=None,
            n_workdays=25,
            filepath=SAMPLE_KANBAN_CSV,
            certainties=[80],
            output_dir=str(tmp_path),
        )
        kwargs.update(overrides)
        make_charts(**kwargs)
        return list(tmp_path.glob("*.png"))

    def test_writes_a_png_file(self, tmp_path):
        weeks_arr = np.array([3.0, 4.0, 5.0, 6.0])
        items_arr = np.array([30.0, 28.0, 26.0, 24.0])
        files = self._run(tmp_path, weeks_arr, items_arr)
        assert len(files) == 1
        assert files[0].stat().st_size > 0

    def test_all_nan_weeks_do_not_crash(self, tmp_path):
        """
        Regression test: when every simulation hits simulate()'s
        MAX_SIM_WEEKS ceiling (target never reached), weeks_arr is all
        NaN. The weeks histogram and its percentile markers must degrade
        gracefully instead of raising.
        """
        weeks_arr = np.full(50, np.nan)
        items_arr = np.zeros(50)
        files = self._run(tmp_path, weeks_arr, items_arr)
        assert len(files) == 1

    def test_french_language_renders_without_error(self, tmp_path):
        weeks_arr = np.array([3.0, 4.0, 5.0])
        items_arr = np.array([30.0, 28.0, 26.0])
        files = self._run(tmp_path, weeks_arr, items_arr, lang="fr")
        assert len(files) == 1
