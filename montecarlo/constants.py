"""Shared constants: item scoring, default paths, and accepted date formats."""

# SCORES keys must remain in French: they are this project's own canonical
# tier names (also used to key the -t/-s/-m/-l/-x CLI target calculation).
# They match Kanban Zone's 'CF Envergure' values.
SCORES = {"Très petit": 0.5, "Petit": 1, "Moyen": 3, "Grand": 5, "Très grand": 8}

# English equivalents of the same tiers, for boards whose 'CF Size' custom
# field was filled in English instead of French 'CF Envergure' values.
SCORES_EN = {"X-Small": 0.5, "Small": 1, "Medium": 3, "Large": 5, "X-Large": 8}

# Combined lookup used when reading item-size values out of throughput
# files — accepts either language, regardless of which column name matched.
ALL_SCORES: dict[str, float] = {**SCORES, **SCORES_EN}

N_SIMULATIONS = 10_000
DEFAULT_FILE             = "data/kanban_zone.csv"
DEFAULT_THROUGHPUT_TXT   = "data/Throughput.txt"
DEFAULT_ANNOTATIONS_FILE = "data/annotations.csv"
DEFAULT_OUTPUT_DIR       = "output"
DATE_FORMATS = ["%m-%d-%Y %H:%M", "%m/%d/%Y %I:%M %p", "%Y/%m/%d", "%Y-%m-%d"]
