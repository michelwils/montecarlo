#!/usr/bin/env python3
"""
Monte Carlo simulation for software delivery forecasting.
Usage: python monte_carlo.py [options]

This script and its documentation were generated with the assistance of a
generative artificial intelligence and reviewed by a human.
"""

import argparse
import csv
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib.gridspec import GridSpec, GridSpecFromSubplotSpec
import numpy as np

matplotlib.use("Agg")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# SCORES keys must remain in French: they match Kanban Zone's 'CF Envergure' values.
SCORES = {"Petit": 1, "Moyen": 3, "Grand": 5, "Très grand": 8}

N_SIMULATIONS = 10_000
DEFAULT_FILE             = "data/kanban_zone.csv"
DEFAULT_THROUGHPUT_TXT   = "data/Throughput.txt"
DEFAULT_ANNOTATIONS_FILE = "data/annotations.csv"
DEFAULT_OUTPUT_DIR       = "output"
DATE_FORMATS = ["%m-%d-%Y %H:%M", "%Y/%m/%d", "%Y-%m-%d"]


# ---------------------------------------------------------------------------
# Chart string tables
# ---------------------------------------------------------------------------
# All user-visible text in the generated chart is looked up from this dict,
# keyed by language code. Add a new key here to support another language,
# then pass it with --lang.

CHART_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        # Figure title
        "title":             "Monte Carlo Simulation",
        # Parameters panel labels
        "param_file":        "File",
        "param_format":      "Format",
        "param_target":      "Target",
        "param_mix":         "Mix",
        "param_duration":    "Duration",
        "param_workdays":    "Work days",
        "param_holidays":    "Days off",
        "param_window":      "Hist. window",
        "param_chart":       "Chart",
        "param_certainties": "Certainties",
        "param_simulations": "Simulations",
        "param_annotations": "Annotations",
        # Parameters panel values
        "window_full":       "full",
        "display_all":       "all",
        "none_val":          "none",
        "weeks_abbr":        "w.",        # long form (e.g. "12 w.")
        "weeks_short":       "w",         # short form used inside labels (e.g. "3.0w")
        "days_abbr":         "d.",
        # Size names (must parallel SCORES key order)
        "size_small":        "Small",
        "size_medium":       "Medium",
        "size_large":        "Large",
        "size_xlarge":       "X-Large",
        # Chart 1 — weeks distribution
        "ax1_title":         "Distribution of weeks required\n({pct:.1f}% of {n:,} simulations reach the target)",
        "ax1_xlabel":        "Weeks required to deliver the target",
        "ax1_ylabel":        "Number of simulations",
        "ax1_objective":     "Target\n{n}w",
        # Chart 2 — volume distribution
        "ax2_title":         "Volume delivered in {n_weeks} weeks ({n_workdays} work days)\n({pct:.1f}% of {n:,} simulations reach the target)",
        "ax2_xlabel":        "Points delivered in {n_weeks} weeks",
        "ax2_ylabel":        "Number of simulations",
        "ax2_target":        "Target\n{target:.0f} pts",
        # Chart 3 — sensitivity
        "ax3_title":         "Sensitivity to history window\n(deliver {target:.0f} pts in {n_weeks} w.)",
        "ax3_xlabel":        "History window (weeks) — left: full history, right: recent only",
        "ax3_ylabel":        "Probability of delivering target (%)",
        "ax3_bar_ylabel":    "Throughput (pts / week)",
        "all_label":         "All",
        "active_marker":     "↑ {n}w",
        "active_marker_all": "↑ All",
        "no_data":           "Insufficient data",
    },
    "fr": {
        # Titre de la figure
        "title":             "Simulation Monte Carlo",
        # Étiquettes du panneau de paramètres
        "param_file":        "Fichier",
        "param_format":      "Format",
        "param_target":      "Cible",
        "param_mix":         "Mix",
        "param_duration":    "Durée",
        "param_workdays":    "Jours trav.",
        "param_holidays":    "Jours off",
        "param_window":      "Fenêtre hist.",
        "param_chart":       "Graphique",
        "param_certainties": "Certitudes",
        "param_simulations": "Simulations",
        "param_annotations": "Annotations",
        # Valeurs du panneau de paramètres
        "window_full":       "complète",
        "display_all":       "tout",
        "none_val":          "aucun",
        "weeks_abbr":        "sem.",
        "weeks_short":       "s",
        "days_abbr":         "j.",
        # Noms des tailles (parallèle aux clés de SCORES)
        "size_small":        "Petit",
        "size_medium":       "Moyen",
        "size_large":        "Grand",
        "size_xlarge":       "Très grand",
        # Graphique 1 — distribution des semaines
        "ax1_title":         "Distribution du nombre de semaines requises\n({pct:.1f} % des {n:,} simulations atteignent la cible)",
        "ax1_xlabel":        "Semaines requises pour livrer la cible",
        "ax1_ylabel":        "Nombre de simulations",
        "ax1_objective":     "Objectif\n{n}s",
        # Graphique 2 — distribution du volume
        "ax2_title":         "Distribution du volume livré en {n_weeks} semaines ({n_workdays} j. trav.)\n({pct:.1f} % des {n:,} simulations atteignent la cible)",
        "ax2_xlabel":        "Points livrés en {n_weeks} semaines",
        "ax2_ylabel":        "Nombre de simulations",
        "ax2_target":        "Cible\n{target:.0f} pts",
        # Graphique 3 — sensibilité
        "ax3_title":         "Sensibilité à la fenêtre d'historique\n(livrer {target:.0f} pts en {n_weeks} sem.)",
        "ax3_xlabel":        "Fenêtre d'historique (semaines) — gauche : tout l'historique, droite : récent seulement",
        "ax3_ylabel":        "Probabilité de livrer la cible (%)",
        "ax3_bar_ylabel":    "Throughput (pts / semaine)",
        "all_label":         "Tout",
        "active_marker":     "↑ {n}s",
        "active_marker_all": "↑ Tout",
        "no_data":           "Données insuffisantes",
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_date(s: str) -> date | None:
    """Try each known date format and return a date, or None on failure."""
    s = s.strip()
    if not s:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


def next_monday(today: date | None = None) -> date:
    """Return the coming Monday (or today if today is already Monday)."""
    d = today or date.today()
    days_ahead = (7 - d.weekday()) % 7  # 0 if already Monday
    return d + timedelta(days=days_ahead)


# ---------------------------------------------------------------------------
# Loader registry
# ---------------------------------------------------------------------------

class ThroughputLoader:
    """
    Base class for throughput data loaders.

    To add a new input format (e.g. Jira, Azure DevOps, Linear…):

    1. Create a subclass of ThroughputLoader.
    2. Set FORMAT_NAME, DESCRIPTION, and EXTENSIONS.
    3. Override match() when extension alone is not enough to identify the
       format — the typical case when multiple CSV dialects share .csv
       (Kanban Zone, Jira, Linear, etc.).
    4. Implement load() with the format-specific reading logic.
    5. Append an instance to LOADERS below.
       Order matters: the first loader whose match() returns True wins.
    """

    FORMAT_NAME: str = ""
    DESCRIPTION: str = ""
    EXTENSIONS: list[str] = []

    def match(self, filepath: str) -> bool:
        """Return True if this loader can handle the given file."""
        return Path(filepath).suffix.lower() in self.EXTENSIONS

    def load(self, filepath: str, window_weeks: int | None) -> dict[date, float]:
        """
        Load throughput from filepath.
        Returns {week_monday: weekly_score_total}.
        When window_weeks is set, only the last N weeks are kept.
        """
        raise NotImplementedError


class KanbanZoneCSVLoader(ThroughputLoader):
    """
    Loader for Kanban Zone CSV exports.
    Required columns: 'Done At' and 'CF Envergure'.
    Header inspection is used for detection to avoid ambiguity with other
    CSV formats (Jira, Linear, etc.).
    """

    FORMAT_NAME = "kanban_zone"
    DESCRIPTION = "Kanban Zone CSV export (columns 'Done At' and 'CF Envergure')"
    EXTENSIONS = [".csv"]
    _REQUIRED_COLS = {"Done At", "CF Envergure"}

    def match(self, filepath: str) -> bool:
        if Path(filepath).suffix.lower() not in self.EXTENSIONS:
            return False
        # Inspect headers to confirm the format
        try:
            with open(filepath, newline="", encoding="utf-8-sig") as f:
                headers = set(next(csv.reader(f)))
            return self._REQUIRED_COLS.issubset(headers)
        except Exception:
            return False

    def load(self, filepath: str, window_weeks: int | None) -> dict[date, float]:
        daily: dict[date, float] = defaultdict(float)
        with open(filepath, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                done_raw  = row.get("Done At", "").strip()
                envergure = row.get("CF Envergure", "").strip()
                if not done_raw or envergure not in SCORES:
                    continue
                d = parse_date(done_raw)
                if d is None:
                    continue
                daily[d] += SCORES[envergure]

        if not daily:
            print("⚠️  No throughput data found.", file=sys.stderr)
            return {}

        # Aggregate by calendar week (key = Monday)
        weekly: dict[date, float] = defaultdict(float)
        for d, v in daily.items():
            monday = d - timedelta(days=d.weekday())
            weekly[monday] += v

        if window_weeks is not None:
            cutoff = max(weekly.keys()) - timedelta(weeks=window_weeks - 1)
            weekly = {k: v for k, v in weekly.items() if k >= cutoff}

        return dict(weekly)


class TxtLoader(ThroughputLoader):
    """
    Loader for plain-text weekly throughput files.
    Format: comma-separated numeric values, oldest to most recent.
    Synthetic Monday dates are assigned retroactively from last week's Monday.
    """

    FORMAT_NAME = "txt"
    DESCRIPTION = "Plain-text weekly throughput file (comma-separated values)"
    EXTENSIONS = [".txt"]

    def load(self, filepath: str, window_weeks: int | None) -> dict[date, float]:
        with open(filepath, encoding="utf-8-sig") as f:
            raw = f.read()
        values = [float(v.strip()) for v in raw.split(",") if v.strip() != ""]
        if not values:
            print("⚠️  No data found in text file.", file=sys.stderr)
            return {}
        today = date.today()
        # Anchor on the Monday of the previous week (always complete)
        last_monday = today - timedelta(days=today.weekday()) - timedelta(weeks=1)
        weekly: dict[date, float] = {}
        for i, v in enumerate(reversed(values)):
            monday = last_monday - timedelta(weeks=i)
            weekly[monday] = v
        if window_weeks is not None:
            cutoff = max(weekly.keys()) - timedelta(weeks=window_weeks - 1)
            weekly = {k: v for k, v in weekly.items() if k >= cutoff}
        return weekly


# Loader registry — order matters: first match() wins.
# Append a new instance here to register a new format.
LOADERS: list[ThroughputLoader] = [
    KanbanZoneCSVLoader(),
    TxtLoader(),
]


def get_loader(filepath: str) -> ThroughputLoader | None:
    """Return the first compatible loader, or None if unrecognized."""
    for loader in LOADERS:
        if loader.match(filepath):
            return loader
    return None


def load_throughput_auto(filepath: str, window_weeks: int | None) -> dict[date, float]:
    """
    Unified entry point: auto-detect the format and load throughput.
    Prints a warning if no loader matches.
    """
    loader = get_loader(filepath)
    if loader is None:
        ext = Path(filepath).suffix.lower()
        supported = sorted({e for ldr in LOADERS for e in ldr.EXTENSIONS})
        print(
            f"⚠️  Unsupported format: '{ext}'. "
            f"Recognized extensions: {', '.join(supported)}",
            file=sys.stderr,
        )
        return {}
    return loader.load(filepath, window_weeks)


# ---------------------------------------------------------------------------
# Annotations
# ---------------------------------------------------------------------------

def load_annotations(filepath: str | None) -> dict[date, list[str]]:
    """
    Load annotations from a CSV file with columns Date and Note.
    Returns {date: [note, ...]} or {} if the file is absent / not specified.
    """
    path = filepath or (
        DEFAULT_ANNOTATIONS_FILE if Path(DEFAULT_ANNOTATIONS_FILE).exists() else None
    )
    if path is None:
        return {}
    if not Path(path).exists():
        print(f"⚠️  Annotations file not found: {path}", file=sys.stderr)
        return {}
    try:
        result: dict[date, list[str]] = defaultdict(list)
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                d_raw = row.get("Date", "").strip()
                n     = row.get("Note", "").strip()
                if not d_raw or not n:
                    continue
                d = parse_date(d_raw)
                if d is not None:
                    result[d].append(n)
        return dict(result)
    except Exception as e:
        print(f"⚠️  Error reading annotations: {e}", file=sys.stderr)
        return {}


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

def weekly_samples(weekly: dict[date, float]) -> np.ndarray:
    """Return an array of weekly throughput values."""
    return np.array(list(weekly.values()), dtype=float)


def simulate(
    samples: np.ndarray,
    target_score: float,
    n_workdays: int,
    n_sim: int = N_SIMULATIONS,
    rng: np.random.Generator | None = None,
    n_weeks: int | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Run Monte Carlo simulations.

    Returns:
        weeks_to_deliver — weeks needed to reach the target score
        items_delivered  — points delivered within the n_workdays window
    """
    if rng is None:
        rng = np.random.default_rng()

    # Holiday factor: uniformly scales weekly throughput to reflect
    # non-working days spread across the calendar window.
    # E.g. 10 holidays over 15 weeks → each week is worth (75-10)/(15×5) = 86.7%
    n_weeks_window = n_weeks if n_weeks is not None else (n_workdays // 5)
    days_off_factor = n_workdays / (n_weeks_window * 5) if n_weeks_window > 0 else 1.0

    totals         = np.zeros(n_sim)
    items_delivered = np.zeros(n_sim)
    weeks_needed   = np.zeros(n_sim, dtype=int)
    done           = np.zeros(n_sim, dtype=bool)
    week           = 0
    while not done.all():
        draw = rng.choice(samples, size=n_sim, replace=True) * days_off_factor
        totals += draw
        week   += 1
        if week <= n_weeks_window:
            items_delivered += draw
        newly_done = ~done & (totals >= target_score)
        weeks_needed[newly_done] = week
        done |= newly_done

    return weeks_needed.astype(float), items_delivered


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def make_charts(
    weeks_arr: np.ndarray,
    items_arr: np.ndarray,
    target_score: float,
    n_weeks: int,
    window_weeks: int | None,
    n_workdays: int,
    filepath: str,
    certainties: list[int] | None = None,
    annotations: dict[date, list[str]] | None = None,
    display_window: int | None = 26,
    days_off: int = 0,
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
) -> None:
    if certainties is None:
        certainties = [80]
    if annotations is None:
        annotations = {}

    s = CHART_STRINGS[lang]  # active string table

    n_sim         = len(weeks_arr)
    pct_delivered = 100 * np.sum(weeks_arr <= n_weeks) / n_sim

    # ---------------------------------------------------------------------------
    # Colour palette (dark background, neon accents)
    # ---------------------------------------------------------------------------
    BG           = "#0F1117"
    BG_AX        = "#181C27"
    C_CURVE      = "#38BDF8"
    C_FILL       = "#38BDF8"
    C_PERCENTILE = "#FACC15"
    C_TARGET     = "#F472B6"
    C_GRID       = "#2A2F45"
    C_TEXT       = "#E2E8F0"
    C_SUBTEXT    = "#94A3B8"
    CERT_COLORS  = ["#A78BFA", "#34D399", "#FACC15", "#F87171", "#FB923C"]

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

    # --- Parameters panel ---
    ax_params.set_facecolor("#1E2336")
    ax_params.set_xticks([])
    ax_params.set_yticks([])
    for spine in ax_params.spines.values():
        spine.set_edgecolor(C_GRID)

    mix_parts = []
    if small:  mix_parts.append(f"{small} × {s['size_small']}")
    if medium: mix_parts.append(f"{medium} × {s['size_medium']}")
    if large:  mix_parts.append(f"{large} × {s['size_large']}")
    if xlarge: mix_parts.append(f"{xlarge} × {s['size_xlarge']}")
    if points: mix_parts.append(f"{points} pts")
    mix_str = ("\n    + ".join(mix_parts)) if mix_parts else "—"

    loader     = get_loader(filepath)
    format_str = loader.FORMAT_NAME if loader else Path(filepath).suffix.lstrip(".")

    fenetre_str    = s["window_full"] if window_weeks is None else f"{window_weeks} {s['weeks_abbr']}"
    display_str    = s["display_all"] if display_window is None else f"{display_window} {s['weeks_abbr']}"
    certainties_str = ", ".join(f"{c}%" for c in certainties)
    days_off_str   = f"{days_off} {s['days_abbr']}" if days_off else s["none_val"]
    annot_str      = Path(annot_file).name if annot_file else s["none_val"]

    params = [
        (s["param_file"],        Path(filepath).name),
        (s["param_format"],      format_str),
        (s["param_target"],      f"{target_score:.0f} pts"),
        (s["param_mix"],         mix_str),
        (s["param_duration"],    f"{n_weeks} {s['weeks_abbr']}"),
        (s["param_workdays"],    str(n_workdays)),
        (s["param_holidays"],    days_off_str),
        (s["param_window"],      fenetre_str),
        (s["param_chart"],       display_str),
        (s["param_certainties"], certainties_str),
        (s["param_simulations"], f"{n_simulations:,}"),
        (s["param_annotations"], annot_str),
    ]

    n_params = len(params)
    for i, (label, value) in enumerate(params):
        y = 1.0 - (i + 0.35) / n_params
        ax_params.text(0.08, y, label,
                       transform=ax_params.transAxes,
                       ha="left", va="center",
                       fontsize=8, color=C_SUBTEXT,
                       fontfamily="monospace", fontweight="bold")
        ax_params.text(0.08, y - 0.012 * (12 / n_params), value,
                       transform=ax_params.transAxes,
                       ha="left", va="top",
                       fontsize=8.5, color=C_TEXT,
                       fontfamily="monospace")
        if i < n_params - 1:
            sep_y = 1.0 - (i + 0.85) / n_params
            line = plt.Line2D([0.04, 0.96], [sep_y, sep_y],
                               transform=ax_params.transAxes,
                               color=C_GRID, linewidth=0.5, clip_on=False)
            ax_params.add_line(line)

    def style_ax(ax):
        ax.set_facecolor(BG_AX)
        ax.spines[["top", "right"]].set_visible(False)
        ax.spines[["left", "bottom"]].set_color(C_GRID)
        ax.tick_params(colors=C_SUBTEXT, labelsize=9)
        ax.xaxis.label.set_color(C_SUBTEXT)
        ax.yaxis.label.set_color(C_SUBTEXT)
        ax.title.set_color(C_TEXT)

    # --- Chart 1: Distribution of weeks required ---
    style_ax(ax1)
    max_w = max(weeks_arr.max(), n_weeks + 1.5)
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
        val = np.percentile(weeks_arr, p)
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

    # --- Chart 2: Distribution of volume delivered ---
    style_ax(ax2)
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

    # --- Chart 3: Probability vs. history window ---
    style_ax(ax3)

    all_daily = load_throughput_auto(filepath, window_weeks=None)
    if all_daily:
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
            d = load_throughput_auto(filepath, window_weeks=w)
            if not d:
                probs.append(0.0)
                continue
            samp = weekly_samples(d)
            wk, _ = simulate(samp, target_score, n_workdays, n_sim=2000,
                              rng=rng_chart, n_weeks=n_weeks)
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
            C_ANNOT = "#FB923C"
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
    else:
        ax3.text(0.5, 0.5, s["no_data"], ha="center", va="center",
                 transform=ax3.transAxes, color=C_SUBTEXT)

    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    out = (out_path / f"monte_carlo_{ts}.png").resolve()
    plt.savefig(out, dpi=150, bbox_inches="tight", facecolor=BG)
    plt.close()
    print(f"✅ Chart saved: {out}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Monte Carlo simulation for software delivery forecasting.",
        epilog="Dependencies: pip install -r requirements.txt",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("-f", "--file", default=None,
                   help=f"Data file (CSV or TXT). Default: {DEFAULT_FILE} then {DEFAULT_THROUGHPUT_TXT}")
    p.add_argument("-w", "--weeks", type=int, default=None,
                   help="Simulation duration in weeks (required)")
    p.add_argument("-W", "--window", type=int, default=None,
                   help="Number of most recent history weeks to use (default: all)")
    p.add_argument("-G", "--chart-weeks", type=int, default=26,
                   metavar="N",
                   help="Weeks shown in the bottom chart (default: 26 ≈ 6 months, 0 = all)")
    p.add_argument("-s", "--small", type=int, default=0,
                   help="Number of Small items to deliver")
    p.add_argument("-m", "--medium", type=int, default=0,
                   help="Number of Medium items to deliver")
    p.add_argument("-l", "--large", type=int, default=0,
                   help="Number of Large items to deliver")
    p.add_argument("-x", "--xlarge", type=int, default=0,
                   help="Number of X-Large items to deliver")
    p.add_argument("-p", "--points", type=int, default=0,
                   help="Extra points added directly to the target")
    p.add_argument("-d", "--start-date", type=str, default=None,
               help="Simulation start date (format: YYYY-MM-DD)")
    p.add_argument("-v", "--days-off", type=int, default=0,
                   help="Non-working days to subtract (vacation, sick leave, public holidays…)")
    p.add_argument("-n", "--simulations", type=int, default=N_SIMULATIONS,
                   metavar="N",
                   help=f"Number of Monte Carlo simulations (default: {N_SIMULATIONS:,})")
    p.add_argument("-c", "--certainties", type=int, nargs="+", default=[80],
                   metavar="PCT",
                   help="Certainty levels to display, e.g. --certainties 80 90 95 (default: 80)")
    p.add_argument("-a", "--annotations", default=None,
                   help=f"CSV annotations file (default: {DEFAULT_ANNOTATIONS_FILE} if present)")
    p.add_argument("-o", "--output-dir", default=DEFAULT_OUTPUT_DIR,
                   help=f"Directory for generated charts (default: {DEFAULT_OUTPUT_DIR})")
    p.add_argument("--lang", choices=list(CHART_STRINGS.keys()), default="en",
                   help="Language for the generated chart (default: en)")
    p.add_argument("-T", "--title", type=str, default=None,
                   help="Custom chart title (default: language-specific title)")
    p.add_argument("--formats", action="store_true",
                   help="List supported data formats and exit")
    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # List supported formats
    if args.formats:
        print("\n📋 Supported data formats:\n")
        for loader in LOADERS:
            exts = ", ".join(loader.EXTENSIONS)
            print(f"  [{loader.FORMAT_NAME}]  {exts}")
            print(f"  {loader.DESCRIPTION}\n")
        sys.exit(0)

    # Target score
    target_score = (
        args.small   * SCORES["Petit"]
        + args.medium  * SCORES["Moyen"]
        + args.large   * SCORES["Grand"]
        + args.xlarge  * SCORES["Très grand"]
        + args.points
    )

    if target_score == 0 or args.weeks is None:
        parser.print_help()
        sys.exit(1)

    # Resolve data file
    if args.file is not None:
        fpath = args.file
        if not Path(fpath).exists():
            print(f"\n❌ File not found: {fpath}", file=sys.stderr)
            sys.exit(1)
    else:
        candidates = []
        if Path(DEFAULT_FILE).exists():
            candidates.append(DEFAULT_FILE)
        if Path(DEFAULT_THROUGHPUT_TXT).exists():
            candidates.append(DEFAULT_THROUGHPUT_TXT)
        if not candidates:
            print(
                f"\n❌ No data file found ({DEFAULT_FILE} or {DEFAULT_THROUGHPUT_TXT}).",
                file=sys.stderr,
            )
            sys.exit(1)
        fpath = None
        for candidate in candidates:
            if load_throughput_auto(candidate, window_weeks=None):
                fpath = candidate
                break
        if fpath is None:
            print("\n❌ No valid data file found.", file=sys.stderr)
            sys.exit(1)

    # Simulation window
    if args.start_date is not None:
        start_date = parse_date(args.start_date)
        if start_date is None:
            print("❌ Invalid date format.", file=sys.stderr)
            sys.exit(1)
    else:
        start_date = next_monday()

    n_workdays  = args.weeks * 5 - args.days_off
    if n_workdays <= 0:
        print("❌ Work day count is zero or negative.", file=sys.stderr)
        sys.exit(1)

    # Load throughput
    daily = load_throughput_auto(fpath, window_weeks=args.window)
    if not daily:
        print("❌ Could not load throughput data.", file=sys.stderr)
        sys.exit(1)

    samples = weekly_samples(daily)

    # Summary
    loader       = get_loader(fpath)
    format_label = loader.FORMAT_NAME if loader else "?"
    print(f"\n📋 Configuration")
    print(f"   File         : {fpath}  [{format_label}]")
    print(f"   Sim. start   : {start_date} (Monday)")
    print(f"   Duration     : {args.weeks} weeks")
    print(f"   Days off     : {args.days_off} days")
    print(f"   Work days    : {n_workdays}")
    print(f"   Hist. window : {'full' if args.window is None else f'{args.window} weeks'}")
    print(f"   Certainties  : {', '.join(str(c)+'%' for c in sorted(args.certainties))}")
    mix = f"{args.small}×Small + {args.medium}×Medium + {args.large}×Large + {args.xlarge}×X-Large"
    if args.points:
        mix += f" + {args.points} direct pts"
    print(f"   Target       : {target_score} pts  ({mix})")
    print(f"   Source weeks : {len(daily)} wk., avg. throughput: {np.mean(samples):.1f} pts/wk.\n")

    # Run simulation
    print(f"🔄 Running {args.simulations:,} simulations…")
    rng = np.random.default_rng()
    weeks_arr, items_arr = simulate(
        samples, target_score, n_workdays, args.simulations, rng, n_weeks=args.weeks
    )

    # Statistics
    pct_ok = 100 * np.sum(weeks_arr <= args.weeks) / args.simulations
    for p in sorted(args.certainties):
        val = np.nanpercentile(weeks_arr, p)
        print(f"   {p:3d}% : deliver target in ≤ {val:.1f} weeks")
    print(f"\n   🎯 Probability of delivering in ≤ {args.weeks} wk.: {pct_ok:.1f}%\n")

    # Annotations
    annots = load_annotations(args.annotations)
    if annots:
        print(f"   📌 {len(annots)} annotation date(s) loaded")

    # Charts
    display_window = None if args.chart_weeks == 0 else args.chart_weeks
    make_charts(
        weeks_arr, items_arr, target_score, args.weeks,
        args.window, n_workdays, fpath, sorted(args.certainties), annots,
        display_window,
        days_off=args.days_off,
        small=args.small, medium=args.medium, large=args.large,
        xlarge=args.xlarge, points=args.points,
        annot_file=args.annotations,
        n_simulations=args.simulations,
        lang=args.lang,
        output_dir=args.output_dir,
        title=args.title,
    )


if __name__ == "__main__":
    main()
