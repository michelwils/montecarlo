"""Command-line interface: argument parsing and the main entry point."""
import argparse
import sys
from pathlib import Path

import numpy as np

from .annotations import load_annotations
from .charts import make_charts
from .constants import (
    DEFAULT_ANNOTATIONS_FILE,
    DEFAULT_FILE,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_THROUGHPUT_TXT,
    N_SIMULATIONS,
    SCORES,
)
from .dates import next_monday, parse_date
from .loaders import LOADERS, get_loader, load_throughput_auto
from .simulation import simulate, weekly_samples
from .strings import CHART_STRINGS


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
    p.add_argument("--window-start", type=str, default=None,
                   help="First completion date included in historical data (YYYY-MM-DD)")
    p.add_argument("--window-end", type=str, default=None,
                   help="Last completion date included in historical data (YYYY-MM-DD)")
    p.add_argument("-G", "--chart-weeks", type=int, default=26,
                   metavar="N",
                   help="Weeks shown in the bottom chart (default: 26 ≈ 6 months, 0 = all)")
    p.add_argument("-t", "--tiny", type=int, default=0,
                   help="Number of Very Small items to deliver")
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
    p.add_argument("-D", "--description", type=str, default=None,
                   help="Optional subtitle/description shown below the chart title")
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
        args.tiny * SCORES["Très petit"]
        + args.small * SCORES["Petit"]
        + args.medium * SCORES["Moyen"]
        + args.large * SCORES["Grand"]
        + args.xlarge * SCORES["Très grand"]
        + args.points
    )

    if target_score == 0 or args.weeks is None:
        parser.print_help()
        sys.exit(1)

    if (args.window_start is None) != (args.window_end is None):
        parser.error("--window-start and --window-end must be used together")
    if args.window is not None and args.window_start is not None:
        parser.error("--window cannot be used with --window-start/--window-end")

    window_start = parse_date(args.window_start) if args.window_start else None
    window_end   = parse_date(args.window_end) if args.window_end else None
    if args.window_start and window_start is None:
        parser.error("Invalid --window-start date format; use YYYY-MM-DD")
    if args.window_end and window_end is None:
        parser.error("Invalid --window-end date format; use YYYY-MM-DD")
    if window_start is not None and window_end is not None and window_end < window_start:
        parser.error("--window-end must be on or after --window-start")

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
    daily = load_throughput_auto(
        fpath,
        window_weeks=args.window,
        window_start=window_start,
        window_end=window_end,
    )
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
    history_window = (
        f"{window_start} to {window_end}"
        if window_start is not None and window_end is not None
        else ('full' if args.window is None else f'{args.window} weeks')
    )
    print(f"   Hist. window : {history_window}")
    print(f"   Certainties  : {', '.join(str(c)+'%' for c in sorted(args.certainties))}")
    mix = f"{args.tiny}×Very Small + {args.small}×Small + {args.medium}×Medium + {args.large}×Large + {args.xlarge}×X-Large"
    if args.points:
        mix += f" + {args.points} direct pts"
    print(f"   Target       : {target_score:g} pts  ({mix})")
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
        args.window, window_start, window_end, n_workdays, fpath, sorted(args.certainties), annots,
        display_window,
        days_off=args.days_off,
        tiny=args.tiny, small=args.small, medium=args.medium, large=args.large,
        xlarge=args.xlarge, points=args.points,
        annot_file=args.annotations,
        n_simulations=args.simulations,
        lang=args.lang,
        output_dir=args.output_dir,
        title=args.title,
        description=args.description,
    )
