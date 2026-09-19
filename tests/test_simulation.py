import time
from datetime import date

import numpy as np

from montecarlo.simulation import simulate, weekly_samples


class TestWeeklySamples:
    def test_converts_dict_values_to_array(self):
        weekly = {date(2026, 1, 5): 8.0, date(2026, 1, 12): 3.0}
        arr = weekly_samples(weekly)
        assert isinstance(arr, np.ndarray)
        assert sorted(arr.tolist()) == [3.0, 8.0]

    def test_empty_dict_returns_empty_array(self):
        assert weekly_samples({}).size == 0


class TestSimulate:
    def test_constant_throughput_is_deterministic(self):
        # A single-value sample pool removes all randomness: every
        # simulated trajectory takes the same number of weeks.
        samples = np.array([10.0])
        rng = np.random.default_rng(0)
        weeks_arr, items_arr = simulate(
            samples, target_score=25.0, n_workdays=25, n_sim=50, rng=rng, n_weeks=5,
        )
        # 10, 20, 30 >= 25 -> 3 weeks for every simulation.
        assert np.all(weeks_arr == 3.0)
        assert np.all(items_arr == 30.0)

    def test_target_reached_immediately_when_zero(self):
        samples = np.array([5.0])
        rng = np.random.default_rng(0)
        weeks_arr, _ = simulate(
            samples, target_score=0.0, n_workdays=25, n_sim=10, rng=rng, n_weeks=5,
        )
        assert np.all(weeks_arr == 1.0)

    def test_all_zero_samples_do_not_hang_and_return_nan(self):
        """
        Regression test: a sample pool of all zeros used to make the
        `while not done.all():` loop in simulate() spin forever, since
        totals could never reach a positive target. It must now hit the
        MAX_SIM_WEEKS ceiling quickly and report those runs as NaN
        ("never delivers") instead of hanging.
        """
        samples = np.array([0.0])
        rng = np.random.default_rng(0)

        start = time.time()
        weeks_arr, items_arr = simulate(
            samples, target_score=5.0, n_workdays=20, n_sim=200, rng=rng, n_weeks=4,
        )
        elapsed = time.time() - start

        assert elapsed < 5.0, "simulate() should hit its iteration cap quickly, not hang"
        assert np.all(np.isnan(weeks_arr))
        assert np.all(items_arr == 0.0)

    def test_mixed_zero_and_positive_samples_eventually_complete(self):
        samples = np.array([0.0, 10.0])
        rng = np.random.default_rng(1)
        weeks_arr, _ = simulate(
            samples, target_score=10.0, n_workdays=25, n_sim=500, rng=rng, n_weeks=5,
        )
        # With a 50% chance of drawing 10.0 each week, everyone reaches
        # a target of 10 well within the MAX_SIM_WEEKS ceiling.
        assert np.all(np.isfinite(weeks_arr))

    def test_days_off_factor_scales_down_weekly_throughput(self):
        # 25 work days over 5 weeks with no holidays -> factor 1.0.
        # 20 work days over the same 5 weeks -> factor 0.8, so it takes
        # longer to reach the same target.
        samples = np.array([10.0])
        full = simulate(samples, 30.0, n_workdays=25, n_sim=5,
                         rng=np.random.default_rng(0), n_weeks=5)[0]
        reduced = simulate(samples, 30.0, n_workdays=20, n_sim=5,
                            rng=np.random.default_rng(0), n_weeks=5)[0]
        assert np.all(reduced >= full)
