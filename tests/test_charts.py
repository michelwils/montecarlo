from pathlib import Path

import numpy as np

from montecarlo.charts import make_charts
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
