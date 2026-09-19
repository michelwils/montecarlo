"""
Fetch cards directly from the Kanban Zone Public API, as an
alternative to a manually exported CSV.

Cards are converted into rows shaped like a Kanban Zone CSV export and
written to a temporary CSV file, which KanbanZoneCSVLoader then reads
completely unchanged — this reuses all the existing parsing,
zero-week-filling, ALL_SCORES, and unplanned-work-exclusion logic
instead of duplicating it for a second data source.

API shape verified against a live board (2026-09-19); Kanban Zone's
own developer docs (docs.kanbanzone.io) are a JS-rendered site this
tool can't introspect automatically, so this is grounded in observed
responses rather than official reference documentation:

  GET {BASE_URL}/cards?board=...&page=...&count=...&includeArchived=...
  Auth: "Authorization: Basic base64(api_key)"
  Response: {"count", "totalAvailable", "cards": [...], "hasMore"}
  Each entry in "cards" is {"_id", "CardItem": {...}, "meta": {}} —
  the real fields live under "CardItem".
  CardItem fields used here: "doneAt" (ISO 8601 or null), "archivedAt"
  (ISO 8601 or null), "customFields" ([{"label", "value"}, ...] —
  labels have no "CF " prefix; that prefix is added by the CSV export
  itself, so it's reconstructed here for column-name compatibility).
  A checkbox-style custom field's "value" is a native JSON boolean,
  not the string "true" a CSV export would contain.

  Each card also carries "columnState", a normalized value assigned by
  Kanban Zone independent of that column's actual (freeform, per-board,
  possibly translated) title — confirmed via GET
  {BASE_URL}/boards/{{board}}/columns on two real boards (2026-09-19):
  "Backlog", "Start", "In Progress", "Buffer", "Done", "Archive".
  compute_board_target() uses this to derive a simulation target
  straight from cards currently on the board (see --include-todo/
  --include-wip), instead of requiring it to be entered by hand.
  "Backlog" is deliberately excluded from --include-todo: it's an
  undated, not-yet-committed pool (e.g. ideas slated for some future
  session), unlike "Start" (committed, queued to begin soon) — see
  _TODO_STATES.
"""
import base64
import csv
import json
import tempfile
import urllib.error
import urllib.request

from .constants import ALL_SCORES
from .loaders import _SIZE_COLUMNS, _get_field

BASE_URL = "https://integrations.kanbanzone.io/v1"
PAGE_SIZE = 100
REQUEST_TIMEOUT = 20

# Kanban Zone's own normalized column states (see module docstring).
# "To Do" = committed and queued to start soon ("Start" only — "Backlog"
# is an uncommitted pool, not yet scheduled work, so it's excluded);
# "WIP" = work already underway.
_TODO_STATES = {"Start"}
_WIP_STATES = {"In Progress", "Buffer"}


class KanbanZoneAPIError(Exception):
    """Raised when the Kanban Zone API call fails or returns an unexpected shape."""


def _auth_header(api_key: str) -> str:
    encoded = base64.b64encode(api_key.encode("utf-8")).decode("ascii")
    return f"Basic {encoded}"


def fetch_cards(board: str, api_key: str, include_archived: bool = False) -> list[dict]:
    """
    Fetch every card on `board`, following pagination via the
    response's "hasMore" flag. Returns the list of CardItem dicts,
    already unwrapped from the API's {_id, CardItem, meta} envelope.
    """
    headers = {"Authorization": _auth_header(api_key), "Accept": "application/json"}
    cards: list[dict] = []
    page = 1
    while True:
        params = (
            f"board={board}&page={page}&count={PAGE_SIZE}"
            f"&includeArchived={'true' if include_archived else 'false'}"
        )
        req = urllib.request.Request(f"{BASE_URL}/cards?{params}", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise KanbanZoneAPIError(
                    "Kanban Zone API authentication failed — check the API key."
                ) from e
            raise KanbanZoneAPIError(
                f"Kanban Zone API returned HTTP {e.code}: {e.reason}"
            ) from e
        except urllib.error.URLError as e:
            raise KanbanZoneAPIError(f"Could not reach the Kanban Zone API: {e.reason}") from e

        try:
            data = json.loads(body)
        except json.JSONDecodeError as e:
            raise KanbanZoneAPIError(
                "Kanban Zone API returned an unexpected (non-JSON) response."
            ) from e

        for wrapper in data.get("cards", []):
            item = wrapper.get("CardItem")
            if item is None:
                raise KanbanZoneAPIError(
                    "Unexpected card shape from the Kanban Zone API "
                    "(missing 'CardItem') — the API may have changed."
                )
            cards.append(item)

        if not data.get("hasMore"):
            break
        page += 1

    return cards


def cards_to_csv_rows(cards: list[dict]) -> list[dict[str, str]]:
    """
    Adapt raw CardItem dicts into rows shaped like a Kanban Zone CSV
    export: {"Done At": ..., "CF <Label>": ...}. Only completion date
    and custom fields are carried over — title, description, owner,
    etc. are not needed for throughput and are dropped here.
    """
    rows = []
    for card in cards:
        done_at = card.get("doneAt")
        row: dict[str, str] = {"Done At": done_at[:10] if done_at else ""}
        for cf in card.get("customFields") or []:
            label = (cf.get("label") or "").strip()
            if label:
                row[f"CF {label}"] = str(cf.get("value", ""))
        rows.append(row)
    return rows


def write_cards_as_csv(cards: list[dict]) -> str:
    """
    Write cards_to_csv_rows(cards) to a new temporary CSV file and
    return its path. The caller is responsible for deleting it once
    done (it isn't cleaned up automatically).
    """
    rows = cards_to_csv_rows(cards)

    fieldnames: list[str] = ["Done At"]
    seen = set(fieldnames)
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)

    fd, path = tempfile.mkstemp(suffix=".csv", prefix="kanbanzone_api_")
    with open(fd, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


def _card_size_points(card: dict, uniform_size: float | None) -> float | None:
    """
    Points for one card, or None if it can't be sized: no CF Size/CF
    Envergure value and no uniform_size override — same rule
    KanbanZoneCSVLoader applies to throughput.
    """
    if uniform_size is not None:
        return uniform_size
    row = {
        f"CF {(cf.get('label') or '').strip()}": str(cf.get("value", ""))
        for cf in card.get("customFields") or []
    }
    size = _get_field(row, _SIZE_COLUMNS)
    return ALL_SCORES.get(size)


def compute_board_target(
    cards: list[dict],
    include_todo: bool,
    include_wip: bool,
    uniform_size: float | None = None,
) -> dict[str, tuple[float, int, int]]:
    """
    Sum the point value of cards currently sitting in matching column
    states, as an alternative to entering -t/-s/-m/-l/-x/-p by hand.

    include_todo matches "Start" (committed, queued to begin soon —
    "Backlog" is deliberately excluded, see module docstring);
    include_wip matches "In Progress"/"Buffer" (work already underway)
    — see _TODO_STATES/_WIP_STATES.

    Returns {"todo"|"wip": (points, matched_cards, skipped_cards)},
    with only the requested categories present. skipped_cards counts
    cards in a matching state that couldn't be sized (see
    _card_size_points) — they're excluded from points.

    A card with "archivedAt" set is always excluded here, even if its
    columnState happens to be a to-do/WIP one — --include-archived (used
    to fetch it in the first place) is meant to widen the historical
    throughput to completed-but-archived cards, not to count cards that
    were archived (e.g. cancelled) while still queued or in progress.
    """
    result: dict[str, tuple[float, int, int]] = {}
    for key, states, wanted in (
        ("todo", _TODO_STATES, include_todo),
        ("wip", _WIP_STATES, include_wip),
    ):
        if not wanted:
            continue
        points = 0.0
        matched = 0
        skipped = 0
        for card in cards:
            if card.get("archivedAt"):
                continue
            if card.get("columnState") not in states:
                continue
            card_points = _card_size_points(card, uniform_size)
            if card_points is None:
                skipped += 1
                continue
            points += card_points
            matched += 1
        result[key] = (points, matched, skipped)
    return result
