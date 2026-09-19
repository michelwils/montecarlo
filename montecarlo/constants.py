"""Shared constants: item scoring, default paths, and accepted date formats."""

# SCORES keys must remain in French: they match Kanban Zone's 'CF Envergure' values.
SCORES = {"Très petit": 0.5, "Petit": 1, "Moyen": 3, "Grand": 5, "Très grand": 8}

N_SIMULATIONS = 10_000
DEFAULT_FILE             = "data/kanban_zone.csv"
DEFAULT_THROUGHPUT_TXT   = "data/Throughput.txt"
DEFAULT_ANNOTATIONS_FILE = "data/annotations.csv"
DEFAULT_OUTPUT_DIR       = "output"
DATE_FORMATS = ["%m-%d-%Y %H:%M", "%m/%d/%Y %I:%M %p", "%Y/%m/%d", "%Y-%m-%d"]
