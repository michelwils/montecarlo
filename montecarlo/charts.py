"""Chart rendering: the parameters panel plus the three Monte Carlo charts."""
from datetime import date, datetime, timedelta
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib.gridspec import GridSpec, GridSpecFromSubplotSpec
import numpy as np

matplotlib.use("Agg")

from .constants import DEFAULT_OUTPUT_DIR
from .loaders import get_loader, load_throughput_auto
from .simulation import simulate, weekly_samples
from .strings import CHART_STRINGS
from .theme import (
    BG, BG_AX, C_ANNOT, C_CURVE, C_FILL, C_GRID, C_PERCENTILE,
    C_SUBTEXT, C_TARGET, C_TEXT, CERT_COLORS,
)


def _style_axis(ax) -> None:
    ax.set_facecolor(BG_AX)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(C_GRID)
    ax.tick_params(colors=C_SUBTEXT, labelsize=9)
    ax.xaxis.label.set_color(C_SUBTEXT)
    ax.yaxis.label.set_color(C_SUBTEXT)
    ax.title.set_color(C_TEXT)


def _draw_params_panel(
    ax_params,
    s: dict[str, str],
    *,
    file_str: str,
    format_str: str,
    target_score: float,
    mix_str: str,
    duration_str: str,
    n_workdays: int,
    days_off_str: str,
    unplanned_str: str,
    fenetre_str: str,
    display_str: str,
    certainties_str: str,
    n_simulations: int,
    annot_str: str,
) -> None:
    ax_params.set_facecolor("#1E2336")
    ax_params.set_xticks([])
    ax_params.set_yticks([])
    for spine in ax_params.spines.values():
        spine.set_edgecolor(C_GRID)

    params = [
        (s["param_file"],        file_str),
        (s["param_format"],      format_str),
        (s["param_target"],      f"{target_score:g} pts"),
        (s["param_mix"],         mix_str),
        (s["param_duration"],    duration_str),
        (s["param_workdays"],    str(n_workdays)),
        (s["param_holidays"],    days_off_str),
        (s["param_unplanned"],   unplanned_str),
        (s["param_window"],      fenetre_str),
        (s["param_chart"],       display_str),
        (s["param_certainties"], certainties_str),
        (s["param_simulations"], f"{n_simulations:,}"),
        (s["param_annotations"], annot_str),
    ]

    n_params  = len(params)
    mix_lines = mix_str.count("\n") + 1
    # 0.012 * 12 is the label→value line height in row units (see offset below);
    # extra Mix lines each cost one such line, not a full row's worth of padding.
    line_unit = 0.012 * 12
    extra     = (mix_lines - 1) * line_unit
    n_slots   = n_params + extra  # multi-line Mix consumes extra vertical space

    slot = 0.0
    for i, (label, value) in enumerate(params):
        row_span = 1 + extra if label == s["param_mix"] else 1
        y = 1.0 - (slot + 0.35) / n_slots
        ax_params.text(0.08, y, label,
                       transform=ax_params.transAxes,
                       ha="left", va="center",
                       fontsize=8, color=C_SUBTEXT,
                       fontfamily="monospace", fontweight="bold")
        ax_params.text(0.08, y - 0.012 * (12 / n_slots), value,
                       transform=ax_params.transAxes,
                       ha="left", va="top",
                       fontsize=8.5, color=C_TEXT,
                       fontfamily="monospace")
        if i < n_params - 1:
            sep_y = 1.0 - (slot + row_span - 0.15) / n_slots
            line = plt.Line2D([0.04, 0.96], [sep_y, sep_y],
                               transform=ax_params.transAxes,
                               color=C_GRID, linewidth=0.5, clip_on=False)
            ax_params.add_line(line)
        slot += row_span


def _draw_weeks_histogram(
    ax1,
    s: dict[str, str],
    *,
    weeks_arr: np.ndarray,
    n_weeks: int,
    certainties: list[int],
    pct_delivered: float,
    n_sim: int,
) -> None:
    """Chart 1: distribution of weeks required to reach the target."""
    _style_axis(ax1)
    finite_weeks = weeks_arr[np.isfinite(weeks_arr)]
    max_w = max(finite_weeks.max() if finite_weeks.size else 0, n_weeks + 1.5)
    bins = np.arange(0, max_w + 0.5, 0.5)
    _, bin_edges, patches = ax1.hist(weeks_arr, bins=bins,
                                     edgecolor=BG_AX, linewidth=0.5)
    norm = plt.Normalize(vmin=0, vmax=len(patches))
    cmap = matplotlib.colormaps["cool"]
    for i, patch in enumerate(patches):
        if bin_edges[i] >= n_weeks:
            patch.set_facecolor("#EF4444")
            patch.set_alpha(0.85)
        else:
            patch.set_facecolor(cmap(norm(i)))
    for i, p in enumerate(certainties):
        val = np.nanpercentile(weeks_arr, p)
        col = CERT_COLORS[i % len(CERT_COLORS)]
        ax1.axvline(val, color=col, linewidth=1.8, linestyle="--", alpha=0.90)
        ax1.text(val + 0.05, ax1.get_ylim()[1] * (0.95 - i * 0.12),
                 f"{p}%\n{val:.1f}{s['weeks_short']}",
                 fontsize=8, color=col, va="top", fontweight="bold")
    ax1.axvline(n_weeks, color=C_TARGET, linewidth=1.8, linestyle=":")
    ax1.text(n_weeks + 0.05, ax1.get_ylim()[1] * 0.70,
             s["ax1_objective"].format(n=n_weeks),
             fontsize=8, color=C_TARGET, va="top", fontweight="bold")
    ax1.set_xlabel(s["ax1_xlabel"], fontsize=10)
    ax1.set_ylabel(s["ax1_ylabel"], fontsize=10)
    ax1.set_title(s["ax1_title"].format(pct=pct_delivered, n=n_sim), fontsize=10)
    ax1.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
    ax1.grid(axis="y", color=C_GRID, linewidth=0.6, linestyle="--")


def _draw_volume_histogram(
    ax2,
    s: dict[str, str],
    *,
    items_arr: np.ndarray,
    target_score: float,
    n_weeks: int,
    n_workdays: int,
    certainties: list[int],
    pct_delivered: float,
    n_sim: int,
) -> None:
    """Chart 2: distribution of volume (points) delivered."""
    _style_axis(ax2)
    bins2 = np.linspace(items_arr.min(), items_arr.max(), 50)
    _, _, patches2 = ax2.hist(items_arr, bins=bins2, edgecolor=BG_AX, linewidth=0.5)
    norm2 = plt.Normalize(vmin=0, vmax=len(patches2))
    cmap2 = matplotlib.colormaps["summer_r"]
    for i, patch in enumerate(patches2):
        patch.set_facecolor(cmap2(norm2(i)))
    ax2.axvline(target_score, color=C_TARGET, linewidth=1.8, linestyle=":")
    ax2.text(target_score, ax2.get_ylim()[1] * 0.95,
             s["ax2_target"].format(target=target_score),
             fontsize=8, color=C_TARGET, ha="left", va="top", fontweight="bold")
    for i, p in enumerate(certainties):
        val = np.percentile(items_arr, 100 - p)
        col = CERT_COLORS[i % len(CERT_COLORS)]
        ax2.axvline(val, color=col, linewidth=1.8, linestyle="--", alpha=0.90)
        ax2.text(val, ax2.get_ylim()[1] * (0.95 - i * 0.12), f"{p}%\n{val:.0f}",
                 fontsize=8, color=col, va="top", ha="right", fontweight="bold")
    ax2.set_xlabel(s["ax2_xlabel"].format(n_weeks=n_weeks), fontsize=10)
    ax2.set_ylabel(s["ax2_ylabel"], fontsize=10)
    ax2.set_title(
        s["ax2_title"].format(n_weeks=n_weeks, n_workdays=n_workdays,
                              pct=pct_delivered, n=n_sim),
        fontsize=10,
    )
    ax2.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
    ax2.grid(axis="y", color=C_GRID, linewidth=0.6, linestyle="--")


def _draw_sensitivity_chart(
    ax3,
    s: dict[str, str],
    *,
    filepath: str,
    window_weeks: int | None,
    window_start: date | None,
    window_end: date | None,
    target_score: float,
    n_workdays: int,
    n_weeks: int,
    display_window: int | None,
    certainties: list[int],
    annotations: dict[date, list[str]],
    unplanned_ratio: float = 0.0,
) -> None:
    """Chart 3: probability of delivering vs. history window used."""
    _style_axis(ax3)

    all_daily = load_throughput_auto(
        filepath, window_weeks=None, window_start=window_start, window_end=window_end
    )
    if not all_daily:
        ax3.text(0.5, 0.5, s["no_data"], ha="center", va="center",
                 transform=ax3.transAxes, color=C_SUBTEXT)
        return

    max_possible_weeks = int(
        (max(all_daily.keys()) - min(all_daily.keys())).days / 7
    ) + 1
    display_weeks = (
        min(max_possible_weeks, display_window)
        if display_window is not None
        else max_possible_weeks
    )
    # window_range: [None, display_weeks, display_weeks-1, …, 1]
    # None represents the full history.
    window_range = [None] + list(range(display_weeks, 0, -1))
    probs = []
    rng_chart = np.random.default_rng(42)
    for w in window_range:
        d = load_throughput_auto(
            filepath, window_weeks=w, window_start=window_start, window_end=window_end
        )
        if not d:
            probs.append(0.0)
            continue
        samp = weekly_samples(d)
        wk, _ = simulate(samp, target_score, n_workdays, n_sim=2000,
                          rng=rng_chart, n_weeks=n_weeks,
                          unplanned_ratio=unplanned_ratio)
        probs.append(100 * np.sum(wk <= n_weeks) / 2000)

    x_labels = [s["all_label"] if w is None else str(w) for w in window_range]
    x_pos    = list(range(len(window_range)))

    max_date = max(all_daily.keys())
    bar_x, bar_h = [], []
    for monday, tp in all_daily.items():
        weeks_from_end = round((max_date - monday).days / 7) + 1
        if weeks_from_end in window_range:
            bar_x.append(window_range.index(weeks_from_end))
            bar_h.append(tp)

    ax3_bar = ax3.twinx()
    ax3_bar.set_facecolor(BG_AX)
    ax3_bar.bar(bar_x, bar_h, width=0.7, color="#334155", alpha=0.55,
                zorder=1)
    ax3_bar.set_ylabel(s["ax3_bar_ylabel"], fontsize=9, color=C_SUBTEXT)
    ax3_bar.tick_params(axis="y", colors=C_SUBTEXT, labelsize=8)
    ax3_bar.spines[["top", "left"]].set_visible(False)
    ax3_bar.spines["right"].set_color(C_GRID)
    ax3_bar.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.0f}"))
    # Keep the probability curve in front of the bars
    ax3.set_zorder(ax3_bar.get_zorder() + 1)
    ax3.patch.set_visible(False)

    ax3.fill_between(x_pos, probs, alpha=0.18, color=C_FILL)
    ax3.plot(x_pos, probs, color=C_CURVE, linewidth=2.5,
             marker="o", markersize=5, markerfacecolor=BG_AX,
             markeredgecolor=C_CURVE, markeredgewidth=1.5, zorder=3)
    ax3.set_xticks(x_pos)
    ax3.set_xticklabels(x_labels, rotation=45, ha="right", fontsize=8)
    ax3.set_xlabel(s["ax3_xlabel"], fontsize=9)
    ax3.set_ylabel(s["ax3_ylabel"], fontsize=10)
    ax3.set_title(
        s["ax3_title"].format(target=target_score, n_weeks=n_weeks),
        fontsize=10,
    )
    ax3.set_ylim(0, 110)
    ax3.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:.0f}%"))
    ax3.grid(axis="y", color=C_GRID, linewidth=0.6, linestyle="--")

    for i, p in enumerate(certainties):
        col = CERT_COLORS[i % len(CERT_COLORS)]
        ax3.axhline(p, color=col, linewidth=1.4, linestyle="--", alpha=0.80)
        ax3.text(0.3, p + 1.5, f"{p}%",
                 fontsize=8, color=col, va="bottom", ha="left", fontweight="bold")

    # Marker for the active window (--window / -w).
    # Falls back to "All" if window_weeks exceeds display_weeks (-w > -G).
    if window_weeks is not None and window_weeks in window_range:
        active_idx = window_range.index(window_weeks)
        label_txt  = s["active_marker"].format(n=window_weeks)
    else:
        active_idx = window_range.index(None)
        label_txt  = s["active_marker_all"]
    ax3.axvline(active_idx, color=C_PERCENTILE, linewidth=1.8, linestyle="--", alpha=0.85)
    ax3.text(active_idx, 105, label_txt, ha="center", fontsize=8,
             color=C_PERCENTILE, fontweight="bold")

    # Annotations: vertical lines at the corresponding week positions
    if annotations:
        last_monday     = max(all_daily.keys())
        ref_date        = last_monday + timedelta(days=4)  # Friday of the last week
        numeric_windows = [w for w in window_range if w is not None]
        max_window      = max(numeric_windows) if numeric_windows else 0
        stagger         = [88, 76, 64, 52, 40]
        stagger_idx     = 0
        for annot_date, notes in sorted(annotations.items()):
            weeks_from_end = (ref_date - annot_date).days / 7.0
            if not numeric_windows or weeks_from_end > max_window:
                continue
            closest = min(numeric_windows, key=lambda w: abs(w - weeks_from_end))
            x_idx   = window_range.index(closest)
            y_lbl   = stagger[stagger_idx % len(stagger)]
            stagger_idx += 1
            ax3.axvline(x_idx, color=C_ANNOT, linewidth=1.2, linestyle=":", alpha=0.75)
            ax3.text(x_idx + 0.15, y_lbl, "\n".join(notes),
                     fontsize=7.5, color=C_ANNOT,
                     va="center", ha="left", fontstyle="italic",
                     bbox=dict(boxstyle="round,pad=0.3", facecolor=BG_AX,
                               edgecolor=C_ANNOT, alpha=0.85, linewidth=0.8))


def make_charts(
    weeks_arr: np.ndarray,
    items_arr: np.ndarray,
    target_score: float,
    n_weeks: int,
    window_weeks: int | None,
    window_start: date | None,
    window_end: date | None,
    n_workdays: int,
    filepath: str,
    certainties: list[int] | None = None,
    annotations: dict[date, list[str]] | None = None,
    display_window: int | None = 26,
    days_off: int = 0,
    target_date: date | None = None,
    unplanned_ratio: float = 0.0,
    source_label: str | None = None,
    tiny: int = 0,
    small: int = 0,
    medium: int = 0,
    large: int = 0,
    xlarge: int = 0,
    points: int = 0,
    annot_file: str | None = None,
    n_simulations: int = 10_000,
    lang: str = "en",
    output_dir: str = DEFAULT_OUTPUT_DIR,
    title: str | None = None,
    description: str | None = None,
) -> None:
    if certainties is None:
        certainties = [80]
    if annotations is None:
        annotations = {}

    s = CHART_STRINGS[lang]  # active string table

    n_sim         = len(weeks_arr)
    pct_delivered = 100 * np.sum(weeks_arr <= n_weeks) / n_sim

    plt.rcParams.update({
        "text.color":       C_TEXT,
        "axes.labelcolor":  C_SUBTEXT,
        "xtick.color":      C_SUBTEXT,
        "ytick.color":      C_SUBTEXT,
        "font.family":      "DejaVu Sans",
    })

    fig = plt.figure(figsize=(19.2, 10.8), facecolor=BG)  # 16:9

    # Narrow left column (parameters) + wide right column (charts)
    gs_root = GridSpec(1, 2, figure=fig,
                       width_ratios=[0.20, 1],
                       left=0.02, right=0.97,
                       wspace=0.18)
    ax_params = fig.add_subplot(gs_root[0, 0])
    gs_charts = GridSpecFromSubplotSpec(2, 2, subplot_spec=gs_root[0, 1],
                                        hspace=0.60, wspace=0.38,
                                        height_ratios=[1, 1])
    ax1 = fig.add_subplot(gs_charts[0, 0])
    ax2 = fig.add_subplot(gs_charts[0, 1])
    ax3 = fig.add_subplot(gs_charts[1, :])

    fig.suptitle(title or s["title"], fontsize=14, fontweight="bold", y=0.98, color=C_TEXT)
    if description:
        fig.text(0.5, 0.955, description, ha="center", va="top",
                  fontsize=9.5, color=C_SUBTEXT)

    mix_parts = []
    if tiny:   mix_parts.append(f"{tiny} × {s['size_tiny']}")
    if small:  mix_parts.append(f"{small} × {s['size_small']}")
    if medium: mix_parts.append(f"{medium} × {s['size_medium']}")
    if large:  mix_parts.append(f"{large} × {s['size_large']}")
    if xlarge: mix_parts.append(f"{xlarge} × {s['size_xlarge']}")
    if points: mix_parts.append(f"{points} pts")
    if not mix_parts:
        mix_str = "—"
    elif len(mix_parts) == 1:
        mix_str = mix_parts[0]
    else:
        # Pad the first line with 2 spaces — the same width as the "+ "
        # prefix on every following line — so item counts/labels line up
        # instead of the first one sitting flush left of the rest.
        mix_str = "  " + mix_parts[0] + "".join(f"\n+ {p}" for p in mix_parts[1:])

    loader     = get_loader(filepath)
    format_str = loader.FORMAT_NAME if loader else Path(filepath).suffix.lstrip(".")

    if window_start is not None and window_end is not None:
        fenetre_str = s["window_range"].format(start=window_start, end=window_end)
    else:
        fenetre_str = s["window_full"] if window_weeks is None else f"{window_weeks} {s['weeks_abbr']}"
    display_str     = s["display_all"] if display_window is None else f"{display_window} {s['weeks_abbr']}"
    certainties_str = ", ".join(f"{c}%" for c in certainties)
    days_off_str    = f"{days_off} {s['days_abbr']}" if days_off else s["none_val"]
    unplanned_str   = f"{unplanned_ratio:.0%}" if unplanned_ratio else s["none_val"]
    annot_str       = Path(annot_file).name if annot_file else s["none_val"]
    duration_str    = f"{n_weeks} {s['weeks_abbr']}"
    if target_date is not None:
        duration_str += f" ({s['console_until'].format(date=target_date)})"

    file_str = source_label if source_label is not None else Path(filepath).name

    _draw_params_panel(
        ax_params, s,
        file_str=file_str, format_str=format_str, target_score=target_score,
        mix_str=mix_str, duration_str=duration_str, n_workdays=n_workdays,
        days_off_str=days_off_str, unplanned_str=unplanned_str,
        fenetre_str=fenetre_str, display_str=display_str,
        certainties_str=certainties_str, n_simulations=n_simulations, annot_str=annot_str,
    )

    _draw_weeks_histogram(
        ax1, s, weeks_arr=weeks_arr, n_weeks=n_weeks,
        certainties=certainties, pct_delivered=pct_delivered, n_sim=n_sim,
    )

    _draw_volume_histogram(
        ax2, s, items_arr=items_arr, target_score=target_score,
        n_weeks=n_weeks, n_workdays=n_workdays, certainties=certainties,
        pct_delivered=pct_delivered, n_sim=n_sim,
    )

    _draw_sensitivity_chart(
        ax3, s,
        filepath=filepath, window_weeks=window_weeks,
        window_start=window_start, window_end=window_end,
        target_score=target_score, n_workdays=n_workdays, n_weeks=n_weeks,
        display_window=display_window, certainties=certainties, annotations=annotations,
        unplanned_ratio=unplanned_ratio,
    )

    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    out = (out_path / f"monte_carlo_{ts}.png").resolve()
    plt.savefig(out, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close()
    print(f"✅ {s['console_chart_saved'].format(path=out)}")
