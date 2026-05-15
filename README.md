# Monte Carlo — Delivery Forecasting

Command-line tool for estimating the probability of delivering a set of work items within a given timeframe, using Monte Carlo simulation driven by the team's historical throughput.

> This script and its documentation were generated with the assistance of a generative artificial intelligence and reviewed by a human.

---

## Requirements

- Python 3.10 or later
- pip

## Installation

```bash
pip install -r requirements.txt
```

---

## Quick start

```bash
# From a Kanban Zone export: deliver 2 Large + 3 Medium in 10 weeks
python monte_carlo.py -l 2 -m 3 -w 10

# Same, history window limited to the last 12 weeks
python monte_carlo.py -l 2 -m 3 -w 10 -W 12

# 42 direct points, 15 weeks, 5 days off, certainties at 80% and 90%, French chart
python monte_carlo.py -p 42 -w 15 -d 5 -c 80 90 --lang fr

# List supported formats
python monte_carlo.py --formats
```

The chart is saved in the `output/` directory as `monte_carlo_YYYYMMDD_HHMMSS.png` (override with `-o/--output-dir`).

---

## Option reference

| Short | Long              | Default      | Description |
|:---:|---|:---:|---|
| `-f` | `--file`          | auto-detect  | Data file (CSV or TXT) |
| `-s` | `--weeks`         | *(required)* | Simulation duration in weeks |
| `-w` | `--window`        | all          | Most recent N history weeks to use |
| `-G` | `--chart-weeks`   | `26`         | Weeks shown in the sensitivity chart (0 = all) |
| `-p` | `--small`         | `0`          | Number of *Small* items (1 pt) |
| `-m` | `--medium`        | `0`          | Number of *Medium* items (3 pts) |
| `-g` | `--large`         | `0`          | Number of *Large* items (5 pts) |
| `-t` | `--xlarge`        | `0`          | Number of *X-Large* items (8 pts) |
| `-n` | `--points`        | `0`          | Extra points added directly to the target |
| `-c` | `--holidays`      | `0`          | Non-working days to subtract (holidays, vacation…) |
| `-i` | `--simulations`   | `10000`      | Number of Monte Carlo simulations |
| `-d` | `--certainties`   | `80`         | Certainty levels to display (e.g. `-d 80 90 95`) |
| `-a` | `--annotations`   | auto-detect  | CSV annotations file (see below) |
| `-o` | `--output-dir`    | `output`     | Directory for generated charts |
|      | `--lang`          | `en`         | Chart language: `en` or `fr` |
|      | `--formats`       |              | List supported formats and exit |

### Item sizes and point values

| Size    | Points |
|:---:|:---:|
| Small   | 1      |
| Medium  | 3      |
| Large   | 5      |
| X-Large | 8      |

---

## Supported data formats

### Kanban Zone CSV

Native export from [Kanban Zone](https://kanbanzone.com/). Required columns:

| Column        | Description |
|---|---|
| `Done At`     | Completion date, format `MM-DD-YYYY HH:MM` |
| `CF Envergure`| Item size: `Petit`, `Moyen`, `Grand`, or `Très grand` |

All other export columns are ignored. Detection is automatic: if both required columns are present in the header row, the file is recognized as a Kanban Zone export.

**Example file:** `exemples/kanban_zone.csv`

```bash
python monte_carlo.py -f exemples/kanban_zone.csv -w 12 -l 3 -m 4
```

---

### Plain-text throughput file

Simple format: comma-separated numeric values on a single line, ordered from oldest to most recent week. Each value represents the total points delivered in that week.

```
3, 8, 5, 6, 11, 4, 9, 13, 7, 5, 14, 8
```

Synthetic dates are assigned automatically, anchoring the last value to the Monday of the previous week.

**Example file:** `exemples/throughput.txt`

```bash
python monte_carlo.py -f exemples/throughput.txt -w 10 -p 30
```

---

## Annotations file

Annotations let you mark events visually on the sensitivity chart (collective holidays, deployment freezes, team member changes, etc.).

**Format:** CSV with two columns, `Date` and `Note`.

```csv
Date,Note
2025-12-22,Holiday break begins
2026-01-05,Holiday break ends
2026-03-20,Deployment freeze — end of quarter
```

Accepted date formats: `YYYY-MM-DD`, `YYYY/MM/DD`, or `MM-DD-YYYY HH:MM`.

**Example file:** `exemples/annotations.csv`

By default, the script automatically loads `data/annotations.csv` if present. To specify a different file:

```bash
python monte_carlo.py -f my_export.csv -w 12 -l 2 -a my_annotations.csv
```

---

## Adding a new data format

The architecture uses a loader registry. To add support for a new format (e.g. Jira, Azure DevOps, Linear…):

**1. Create a subclass of `ThroughputLoader`**

```python
class JiraCSVLoader(ThroughputLoader):
    FORMAT_NAME = "jira"
    DESCRIPTION = "Jira CSV export (columns 'Resolved' and 'Story Points')"
    EXTENSIONS = [".csv"]
    _REQUIRED_COLS = {"Resolved", "Story Points"}

    def match(self, filepath: str) -> bool:
        # Header inspection avoids confusion with Kanban Zone exports
        if Path(filepath).suffix.lower() not in self.EXTENSIONS:
            return False
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
                resolved   = row.get("Resolved", "").strip()
                points_raw = row.get("Story Points", "").strip()
                if not resolved or not points_raw:
                    continue
                d = parse_date(resolved)
                try:
                    pts = float(points_raw)
                except ValueError:
                    continue
                if d is not None:
                    daily[d] += pts
        # ... weekly aggregation identical to KanbanZoneCSVLoader
```

**2. Register the loader in `LOADERS`**

```python
LOADERS: list[ThroughputLoader] = [
    KanbanZoneCSVLoader(),
    TxtLoader(),
    JiraCSVLoader(),   # ← add here
]
```

The position in `LOADERS` determines priority in case of ambiguity. Header-based `match()` ensures that two distinct CSV dialects never conflict.

---

## Example files

| File                        | Format       | Usage |
|---|---|---|
| `exemples/kanban_zone.csv`  | Kanban Zone  | `-f exemples/kanban_zone.csv` |
| `exemples/throughput.txt`   | Plain text   | `-f exemples/throughput.txt` |
| `exemples/annotations.csv`  | Annotations  | `-a exemples/annotations.csv` |

---

## Project structure

```
monte_carlo.py          Main script
requirements.txt        Python dependencies
README.md               This documentation
.gitignore
data/                   Input data (gitignored — place your files here)
    kanban_zone.csv
    annotations.csv
    Throughput.txt
output/                 Generated charts (gitignored)
exemples/               Committed sample files
    kanban_zone.csv
    throughput.txt
    annotations.csv
```
