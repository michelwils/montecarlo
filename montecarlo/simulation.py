"""Core Monte Carlo simulation."""
import numpy as np

from .constants import N_SIMULATIONS


def weekly_samples(weekly: dict) -> np.ndarray:
    """Return an array of weekly throughput values."""
    return np.array(list(weekly.values()), dtype=float)


def simulate(
    samples: np.ndarray,
    target_score: float,
    n_workdays: int,
    n_sim: int = N_SIMULATIONS,
    rng: np.random.Generator | None = None,
    n_weeks: int | None = None,
    unplanned_ratio: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Run Monte Carlo simulations.

    unplanned_ratio: fraction (0-1) of each week's throughput draw to
        discount, modeling capacity that will be consumed by ad hoc work
        that can't be planned for in advance (e.g. a plain-text
        throughput file with no per-card detail to derive this from
        automatically — Kanban Zone CSVs with a 'CF Prioritaire' field
        already exclude that work at the source; see loaders.py).

    Returns:
        weeks_to_deliver — weeks needed to reach the target score (NaN if
            the target is never reached within MAX_SIM_WEEKS)
        items_delivered  — points delivered within the n_workdays window
    """
    if rng is None:
        rng = np.random.default_rng()

    # Holiday factor: uniformly scales weekly throughput to reflect
    # non-working days spread across the calendar window.
    # E.g. 10 holidays over 15 weeks → each week is worth (75-10)/(15×5) = 86.7%
    n_weeks_window = n_weeks if n_weeks is not None else (n_workdays // 5)
    days_off_factor = n_workdays / (n_weeks_window * 5) if n_weeks_window > 0 else 1.0
    focus_factor    = 1.0 - unplanned_ratio

    # Hard ceiling on simulated weeks: if the historical sample is all
    # zeros (e.g. a narrow history window that lands on a genuine
    # zero-throughput week), totals never reach a positive target and
    # `done` would never become all-True, looping forever. Simulations
    # that hit this ceiling are marked as never delivering (NaN) rather
    # than looping indefinitely.
    MAX_SIM_WEEKS = 10_000

    totals         = np.zeros(n_sim)
    items_delivered = np.zeros(n_sim)
    weeks_needed   = np.full(n_sim, np.nan)
    done           = np.zeros(n_sim, dtype=bool)
    week           = 0
    while not done.all() and week < MAX_SIM_WEEKS:
        draw = rng.choice(samples, size=n_sim, replace=True) * days_off_factor * focus_factor
        totals += draw
        week   += 1
        if week <= n_weeks_window:
            items_delivered += draw
        newly_done = ~done & (totals >= target_score)
        weeks_needed[newly_done] = week
        done |= newly_done

    return weeks_needed, items_delivered
