"""Command-line interface: argument parsing and the main entry point."""
import argparse
import os
import re
import sys
from datetime import date
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
from .kanbanzone_api import KanbanZoneAPIError, fetch_cards, write_cards_as_csv
from .loaders import LOADERS, get_loader, load_throughput_auto
from .simulation import simulate, weekly_samples
from .strings import CHART_STRINGS

API_KEY_ENV_VAR = "KANBAN_ZONE_API_KEY"


def _ensure_utf8_streams() -> None:
    """
    Force stdout/stderr to UTF-8 so the emoji used in status messages
    (📋 🔄 🎯 ⚠️ ✅) never raise UnicodeEncodeError on a legacy console
    codepage (e.g. cp1252 on Windows) or when output is redirected.
    `errors="replace"` is a last-resort safety net in case reconfiguring
    the encoding itself isn't enough to make some character encodable.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass  # stream doesn't support reconfigure (e.g. captured in tests)


def compute_target_score(args: argparse.Namespace) -> float:
    """Total point target implied by the requested item mix."""
    return (
        args.tiny * SCORES["Très petit"]
        + args.small * SCORES["Petit"]
        + args.medium * SCORES["Moyen"]
        + args.large * SCORES["Grand"]
        + args.xlarge * SCORES["Très grand"]
        + args.points
    )


def resolve_window(
    args: argparse.Namespace, parser: argparse.ArgumentParser
) -> tuple[date | None, date | None]:
    """
    Validate --window vs. --window-start/--window-end and parse the
    latter into dates. Calls parser.error() (which prints usage and
    exits) on any invalid combination or format.
    """
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

    return window_start, window_end


def resolve_weeks(
    args: argparse.Namespace, parser: argparse.ArgumentParser, start_date: date
) -> tuple[int, date | None]:
    """
    Return (weeks, target_date). Exactly one of --weeks/--target-date must
    be given; when --target-date is used, weeks is derived as
    ceil(days until the target / 7) — an approximation consistent with
    the rest of the tool treating a week as a fixed unit, not an exact
    business-day count.
    """
    if args.target_date is None:
        return args.weeks, None

    target_date = parse_date(args.target_date)
    if target_date is None:
        parser.error("Invalid --target-date format; use YYYY-MM-DD")
    if target_date <= start_date:
        parser.error("--target-date must be after the simulation start date")

    days_remaining = (target_date - start_date).days
    weeks = -(-days_remaining // 7)  # ceiling division
    return weeks, target_date


def resolve_data_file(args: argparse.Namespace, s: dict[str, str]) -> str:
    """
    Return the throughput file to use.

    If --board is given, fetch cards from the Kanban Zone API and
    materialize them as a temporary CSV file (see kanbanzone_api.py);
    the caller is responsible for deleting this file once done with it
    (main() does, via a try/finally keyed on args.board being set).
    Otherwise, use the explicit -f/--file if given (validated to
    exist), or the first working default candidate.

    Prints a translated error and exits (code 1) on any failure.
    """
    if args.board is not None:
        if args.file is not None:
            print(f"\n❌ {s['console_file_and_board']}", file=sys.stderr)
            sys.exit(1)
        api_key = args.api_key or os.environ.get(API_KEY_ENV_VAR)
        if not api_key:
            print(
                f"\n❌ {s['console_missing_api_key'].format(env_var=API_KEY_ENV_VAR)}",
                file=sys.stderr,
            )
            sys.exit(1)
        try:
            cards = fetch_cards(args.board, api_key, include_archived=args.include_archived)
        except KanbanZoneAPIError as e:
            print(f"\n❌ {s['console_api_error'].format(error=e)}", file=sys.stderr)
            sys.exit(1)
        return write_cards_as_csv(cards)

    if args.file is not None:
        if not Path(args.file).exists():
            print(f"\n❌ {s['console_file_not_found'].format(path=args.file)}", file=sys.stderr)
            sys.exit(1)
        return args.file

    candidates = []
    if Path(DEFAULT_FILE).exists():
        candidates.append(DEFAULT_FILE)
    if Path(DEFAULT_THROUGHPUT_TXT).exists():
        candidates.append(DEFAULT_THROUGHPUT_TXT)
    if not candidates:
        print(
            f"\n❌ {s['console_no_data_file'].format(a=DEFAULT_FILE, b=DEFAULT_THROUGHPUT_TXT)}",
            file=sys.stderr,
        )
        sys.exit(1)

    for candidate in candidates:
        if load_throughput_auto(candidate, window_weeks=None):
            return candidate
    print(f"\n❌ {s['console_no_valid_data_file']}", file=sys.stderr)
    sys.exit(1)


def resolve_start_date(args: argparse.Namespace, s: dict[str, str]) -> date:
    """Return the validated --start-date, or next Monday if omitted."""
    if args.start_date is None:
        return next_monday()
    start_date = parse_date(args.start_date)
    if start_date is None:
        print(f"❌ {s['console_invalid_date']}", file=sys.stderr)
        sys.exit(1)
    return start_date


# Matches one config-line token: a "..."/'...' quoted run (for values
# with spaces, e.g. a chart subtitle) or a run of non-space characters.
# Unlike shlex, backslashes are not treated as escapes, since these
# lines commonly hold Windows-style file paths (C:\Users\...).
_CONFIG_TOKEN_RE = re.compile(r'"([^"]*)"|\'([^\']*)\'|(\S+)')


class _ConfigArgumentParser(argparse.ArgumentParser):
    """
    ArgumentParser that also reads options from an @file (via the
    built-in fromfile_prefix_chars mechanism), one "flag [value...]"
    per line — e.g. "-m 5" or "--lang fr" — rather than argparse's
    default of one bare token per line. Blank lines and lines starting
    with '#' are ignored. See exemples/run.conf.
    """

    def convert_arg_line_to_args(self, arg_line: str) -> list[str]:
        line = arg_line.strip()
        if not line or line.startswith("#"):
            return []
        return [dbl or sgl or bare for dbl, sgl, bare in _CONFIG_TOKEN_RE.findall(line)]


def build_parser() -> argparse.ArgumentParser:
    p = _ConfigArgumentParser(
        description="Monte Carlo simulation for software delivery forecasting.",
        epilog="Dependencies: pip install -r requirements.txt\n"
               "Save frequently-used options in a file and reuse them with "
               "'@path/to/file' (see exemples/run.conf); combine with more "
               "flags on the command line to override just those.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        fromfile_prefix_chars="@",
    )
    p.add_argument("-f", "--file", default=None,
                   help=f"Data file (CSV or TXT). Default: {DEFAULT_FILE} then {DEFAULT_THROUGHPUT_TXT}. "
                        "Not used with --board.")
    p.add_argument("--board", type=str, default=None,
                   help="Fetch cards directly from the Kanban Zone API for this board's "
                        "publicId, instead of a CSV export. Requires an API key (see "
                        "--api-key). Not used with -f/--file.")
    p.add_argument("--api-key", type=str, default=None,
                   help=f"Kanban Zone API key, used with --board. Prefer setting the "
                        f"{API_KEY_ENV_VAR} environment variable instead of this flag, so the "
                        "key isn't stored in shell history or a config file.")
    p.add_argument("--include-archived", action="store_true",
                   help="With --board, also fetch archived cards (default: active cards only)")
    p.add_argument("-w", "--weeks", type=int, default=None,
                   help="Simulation duration in weeks (required, unless -e/--target-date is used)")
    p.add_argument("-e", "--target-date", type=str, default=None,
                   help="Target delivery date (YYYY-MM-DD) instead of -w/--weeks; "
                        "weeks is derived as the ceiling of (target date - start date) / 7 days")
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
                   help="Number of X-Small items to deliver")
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
    p.add_argument("-u", "--unplanned-ratio", type=float, default=0.0,
                   metavar="0-1",
                   help="Fraction of weekly throughput to discount for unplanned/ad hoc work "
                        "that can't be forecast (default: 0). Kanban Zone CSVs with a "
                        "'CF Prioritaire' field already exclude that work automatically; use "
                        "this for plain-text throughput files, or to add extra margin.")
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
    _ensure_utf8_streams()

    parser = build_parser()
    args = parser.parse_args()
    s = CHART_STRINGS[args.lang]  # console + chart string table

    # List supported formats
    if args.formats:
        print(f"\n📋 {s['console_formats_header']}\n")
        for loader in LOADERS:
            exts = ", ".join(loader.EXTENSIONS)
            print(f"  [{loader.FORMAT_NAME}]  {exts}")
            print(f"  {loader.DESCRIPTION}\n")
        sys.exit(0)

    target_score = compute_target_score(args)
    if target_score == 0 or (args.weeks is None and args.target_date is None):
        parser.print_help()
        sys.exit(1)

    if args.weeks is not None and args.target_date is not None:
        parser.error("--weeks and --target-date cannot be used together")

    if not (0.0 <= args.unplanned_ratio < 1.0):
        parser.error("--unplanned-ratio must be between 0 and 1 (exclusive of 1)")

    window_start, window_end = resolve_window(args, parser)
    fpath = resolve_data_file(args, s)
    source_label = (
        s["console_board_source"].format(board=args.board) if args.board is not None else fpath
    )
    try:
        start_date = resolve_start_date(args, s)
        weeks, target_date = resolve_weeks(args, parser, start_date)

        n_workdays  = weeks * 5 - args.days_off
        if n_workdays <= 0:
            print(f"❌ {s['console_zero_workdays']}", file=sys.stderr)
            sys.exit(1)

        # Load throughput
        daily = load_throughput_auto(
            fpath,
            window_weeks=args.window,
            window_start=window_start,
            window_end=window_end,
        )
        if not daily:
            print(f"❌ {s['console_could_not_load']}", file=sys.stderr)
            sys.exit(1)

        samples = weekly_samples(daily)

        # Summary
        loader       = get_loader(fpath)
        format_label = loader.FORMAT_NAME if loader else "?"
        label_width  = 14
        print(f"\n📋 {s['console_config_header']}")
        print(f"   {s['param_file']:<{label_width}}: {source_label}  [{format_label}]")
        print(f"   {s['console_sim_start']:<{label_width}}: {start_date} {s['console_monday_suffix']}")
        duration_str = f"{weeks} {s['console_weeks_word']}"
        if target_date is not None:
            duration_str += f" ({s['console_until'].format(date=target_date)})"
        print(f"   {s['param_duration']:<{label_width}}: {duration_str}")
        print(f"   {s['param_holidays']:<{label_width}}: {args.days_off} {s['console_days_word']}")
        print(f"   {s['param_workdays']:<{label_width}}: {n_workdays}")
        unplanned_str = f"{args.unplanned_ratio:.0%}" if args.unplanned_ratio else s["none_val"]
        print(f"   {s['param_unplanned']:<{label_width}}: {unplanned_str}")
        if window_start is not None and window_end is not None:
            history_window = s["window_range"].format(start=window_start, end=window_end)
        elif args.window is None:
            history_window = s["window_full"]
        else:
            history_window = f"{args.window} {s['console_weeks_word']}"
        print(f"   {s['param_window']:<{label_width}}: {history_window}")
        print(f"   {s['param_certainties']:<{label_width}}: {', '.join(str(c)+'%' for c in sorted(args.certainties))}")
        mix = " + ".join(
            f"{n}×{label}" for n, label in (
                (args.tiny, s["size_tiny"]), (args.small, s["size_small"]),
                (args.medium, s["size_medium"]), (args.large, s["size_large"]),
                (args.xlarge, s["size_xlarge"]),
            )
        )
        if args.points:
            mix += " + " + s["console_direct_pts"].format(n=args.points)
        print(f"   {s['param_target']:<{label_width}}: {target_score:g} pts  ({mix})")
        print(f"   {s['console_source_weeks_label']:<{label_width}}: "
              f"{s['console_source_weeks'].format(n=len(daily), avg=np.mean(samples))}\n")

        # Run simulation
        print(s["console_running"].format(n=args.simulations))
        rng = np.random.default_rng()
        weeks_arr, items_arr = simulate(
            samples, target_score, n_workdays, args.simulations, rng, n_weeks=weeks,
            unplanned_ratio=args.unplanned_ratio,
        )

        # Statistics
        pct_ok = 100 * np.sum(weeks_arr <= weeks) / args.simulations
        for p in sorted(args.certainties):
            val = np.nanpercentile(weeks_arr, p)
            print(f"   {s['console_certainty_line'].format(p=p, val=val)}")
        print(f"\n   🎯 {s['console_probability'].format(n=weeks, pct=pct_ok)}\n")

        # Annotations
        annots = load_annotations(args.annotations)
        if annots:
            print(f"   📌 {s['console_annotations_loaded'].format(n=len(annots))}")

        # Charts
        display_window = None if args.chart_weeks == 0 else args.chart_weeks
        make_charts(
            weeks_arr, items_arr, target_score, weeks,
            args.window, window_start, window_end, n_workdays, fpath, sorted(args.certainties), annots,
            display_window,
            days_off=args.days_off,
            target_date=target_date,
            unplanned_ratio=args.unplanned_ratio,
            source_label=source_label,
            tiny=args.tiny, small=args.small, medium=args.medium, large=args.large,
            xlarge=args.xlarge, points=args.points,
            annot_file=args.annotations,
            n_simulations=args.simulations,
            lang=args.lang,
            output_dir=args.output_dir,
            title=args.title,
            description=args.description,
        )
    finally:
        if args.board is not None:
            Path(fpath).unlink(missing_ok=True)
