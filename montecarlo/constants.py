"""Shared constants: item scoring, default paths, and accepted date formats."""

# SCORES keys are this project's own canonical tier names (also used to key
# the -t/-s/-m/-l/-x CLI target calculation).
SCORES = {"X-Small": 0.5, "Small": 1, "Medium": 3, "Large": 5, "X-Large": 8}

# French equivalents of the same tiers, for boards whose 'CF Envergure'
# custom field was filled in French instead of English 'CF Size' values —
# this project's own Kanban Zone board is one such case.
SCORES_FR = {"Très petit": 0.5, "Petit": 1, "Moyen": 3, "Grand": 5, "Très grand": 8}

# Combined lookup used when reading item-size values out of throughput
# files — accepts either language, regardless of which column name matched.
ALL_SCORES: dict[str, float] = {**SCORES, **SCORES_FR}

N_SIMULATIONS = 10_000
DEFAULT_FILE             = "data/kanban_zone.csv"
DEFAULT_THROUGHPUT_TXT   = "data/Throughput.txt"
DEFAULT_ANNOTATIONS_FILE = "data/annotations.csv"
DEFAULT_OUTPUT_DIR       = "output"
DATE_FORMATS = ["%m-%d-%Y %H:%M", "%m/%d/%Y %I:%M %p", "%Y/%m/%d", "%Y-%m-%d"]
