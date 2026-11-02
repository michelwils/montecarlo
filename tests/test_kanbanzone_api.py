import csv
import json
import os
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from montecarlo.kanbanzone_api import (
    KanbanZoneAPIError,
    cards_to_csv_rows,
    compute_board_target,
    count_board_sizes,
    fetch_cards,
    fetch_cards_cached,
    write_cards_as_csv,
)


def _response(payload: dict):
    """A fake object matching what urllib.request.urlopen(...) returns
    when used as a context manager."""
    body = json.dumps(payload).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.read.return_value = body
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = False
    return mock_resp


class TestFetchCards:
    def test_single_page(self):
        page = {
            "count": 2, "totalAvailable": 2, "hasMore": False,
            "cards": [
                {"_id": "1", "CardItem": {"doneAt": "2026-01-05T10:00:00.000Z"}, "meta": {}},
                {"_id": "2", "CardItem": {"doneAt": None}, "meta": {}},
            ],
        }
        with patch("urllib.request.urlopen", return_value=_response(page)) as mock_open:
            cards = fetch_cards("board123", "fake-key")
        assert len(cards) == 2
        assert cards[0]["doneAt"] == "2026-01-05T10:00:00.000Z"
        # Auth header uses Basic + base64, and default is active-only.
        req = mock_open.call_args[0][0]
        assert req.get_header("Authorization").startswith("Basic ")
        assert "includeArchived=false" in req.full_url
        assert "board=board123" in req.full_url

    def test_include_archived_flag_is_passed_through(self):
        page = {"cards": [], "hasMore": False}
        with patch("urllib.request.urlopen", return_value=_response(page)) as mock_open:
            fetch_cards("board123", "fake-key", include_archived=True)
        req = mock_open.call_args[0][0]
        assert "includeArchived=true" in req.full_url

    def test_paginates_until_has_more_is_false(self):
        page1 = {"cards": [{"_id": "1", "CardItem": {"doneAt": None}, "meta": {}}], "hasMore": True}
        page2 = {"cards": [{"_id": "2", "CardItem": {"doneAt": None}, "meta": {}}], "hasMore": False}
        with patch("urllib.request.urlopen", side_effect=[_response(page1), _response(page2)]) as mock_open:
            cards = fetch_cards("board123", "fake-key")
        assert len(cards) == 2
        assert mock_open.call_count == 2
        # second call requested page 2
        second_req = mock_open.call_args_list[1][0][0]
        assert "page=2" in second_req.full_url

    def test_401_raises_auth_error(self):
        err = urllib.error.HTTPError(
            url="x", code=401, msg="Unauthorized", hdrs=None, fp=None
        )
        with patch("urllib.request.urlopen", side_effect=err):
            with pytest.raises(KanbanZoneAPIError, match="[Aa]uthentication"):
                fetch_cards("board123", "bad-key")

    def test_other_http_error_raises(self):
        err = urllib.error.HTTPError(
            url="x", code=500, msg="Server Error", hdrs=None, fp=None
        )
        with patch("urllib.request.urlopen", side_effect=err):
            with pytest.raises(KanbanZoneAPIError, match="500"):
                fetch_cards("board123", "fake-key")

    def test_connection_error_raises(self):
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("no route")):
            with pytest.raises(KanbanZoneAPIError, match="reach"):
                fetch_cards("board123", "fake-key")

    def test_malformed_json_raises(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"not json"
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = False
        with patch("urllib.request.urlopen", return_value=mock_resp):
            with pytest.raises(KanbanZoneAPIError, match="unexpected"):
                fetch_cards("board123", "fake-key")

    def test_missing_carditem_envelope_raises(self):
        page = {"cards": [{"_id": "1", "meta": {}}], "hasMore": False}  # no "CardItem"
        with patch("urllib.request.urlopen", return_value=_response(page)):
            with pytest.raises(KanbanZoneAPIError, match="CardItem"):
                fetch_cards("board123", "fake-key")


class TestCardsToCsvRows:
    def test_maps_done_at_to_date_only(self):
        rows = cards_to_csv_rows([{"doneAt": "2026-03-16T14:30:00.000Z", "customFields": []}])
        assert rows[0]["Done At"] == "2026-03-16"

    def test_missing_done_at_becomes_empty_string(self):
        rows = cards_to_csv_rows([{"doneAt": None, "customFields": []}])
        assert rows[0]["Done At"] == ""

    def test_reconstructs_cf_prefix_from_label(self):
        rows = cards_to_csv_rows([{
            "doneAt": "2026-03-16T14:30:00.000Z",
            "customFields": [{"label": "Envergure", "value": "Grand"}],
        }])
        assert rows[0]["CF Envergure"] == "Grand"

    def test_boolean_custom_field_value_becomes_string(self):
        # Regression guard: a checkbox-style field's value is a native
        # JSON bool (True), not the string "true" a CSV export has —
        # _is_unplanned()'s .strip().lower() would crash on a raw bool.
        rows = cards_to_csv_rows([{
            "doneAt": "2026-03-16T14:30:00.000Z",
            "customFields": [{"label": "Prioritaire", "value": True}],
        }])
        assert rows[0]["CF Prioritaire"] == "True"
        assert rows[0]["CF Prioritaire"].lower() == "true"

    def test_no_custom_fields_key(self):
        rows = cards_to_csv_rows([{"doneAt": "2026-03-16T14:30:00.000Z"}])
        assert rows[0] == {"Done At": "2026-03-16", "Owners": ""}

    def test_owners_are_carried_over(self):
        rows = cards_to_csv_rows([
            {"doneAt": None, "owner": "alice@example.com"},
            {"doneAt": None, "owners": [{"name": "Bob"}, 42]},
        ])
        assert [row["Owners"] for row in rows] == ["alice@example.com", "Bob, 42"]

    def test_multiple_cards(self):
        rows = cards_to_csv_rows([
            {"doneAt": "2026-01-01T00:00:00.000Z", "customFields": []},
            {"doneAt": "2026-01-02T00:00:00.000Z", "customFields": []},
        ])
        assert len(rows) == 2


class TestWriteCardsAsCsv:
    def test_writes_a_readable_csv(self, tmp_path):
        cards = [
            {
                "doneAt": "2026-03-16T14:30:00.000Z",
                "customFields": [
                    {"label": "Envergure", "value": "Petit"},
                    {"label": "Prioritaire", "value": False},
                ],
            },
        ]
        path = write_cards_as_csv(cards)
        try:
            assert path.endswith(".csv")
            with open(path, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            assert rows == [{
                "Done At": "2026-03-16",
                "Owners": "",
                "CF Envergure": "Petit",
                "CF Prioritaire": "False",
            }]
        finally:
            os.unlink(path)

    def test_handles_no_cards(self):
        path = write_cards_as_csv([])
        try:
            with open(path, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            assert rows == []
        finally:
            os.unlink(path)


def _card(column_state, size=None, done_at=None, archived_at=None):
    custom_fields = [{"label": "Envergure", "value": size}] if size is not None else []
    return {
        "columnState": column_state,
        "doneAt": done_at,
        "archivedAt": archived_at,
        "customFields": custom_fields,
    }


class TestFetchCardsCached:
    @staticmethod
    def _fetcher(calls, cards=None):
        def fetch(board, api_key, include_archived=False):
            calls.append((board, include_archived))
            return cards if cards is not None else [{"n": len(calls)}]
        return fetch

    def test_second_call_within_ttl_is_served_from_cache(self, tmp_path):
        calls = []
        kw = dict(cache_dir=str(tmp_path), ttl_minutes=15, fetch=self._fetcher(calls))
        cards1, age1 = fetch_cards_cached("b", "k", **kw)
        cards2, age2 = fetch_cards_cached("b", "k", **kw)
        assert len(calls) == 1
        assert age1 is None and age2 is not None
        assert cards2 == cards1

    def test_expired_cache_triggers_a_new_fetch(self, tmp_path):
        calls = []
        kw = dict(cache_dir=str(tmp_path), fetch=self._fetcher(calls))
        fetch_cards_cached("b", "k", ttl_minutes=15, **kw)
        with patch("montecarlo.kanbanzone_api.time.time", return_value=__import__("time").time() + 16 * 60):
            _cards, age = fetch_cards_cached("b", "k", ttl_minutes=15, **kw)
        assert len(calls) == 2 and age is None

    def test_ttl_zero_disables_cache_entirely(self, tmp_path):
        calls = []
        kw = dict(cache_dir=str(tmp_path / "c"), ttl_minutes=0, fetch=self._fetcher(calls))
        fetch_cards_cached("b", "k", **kw)
        fetch_cards_cached("b", "k", **kw)
        assert len(calls) == 2
        assert not (tmp_path / "c").exists()

    def test_refresh_skips_read_but_updates_cache(self, tmp_path):
        calls = []
        kw = dict(cache_dir=str(tmp_path), ttl_minutes=15, fetch=self._fetcher(calls))
        fetch_cards_cached("b", "k", **kw)
        fresh, age = fetch_cards_cached("b", "k", refresh=True, **kw)
        assert len(calls) == 2 and age is None
        cached, cached_age = fetch_cards_cached("b", "k", **kw)
        assert len(calls) == 2 and cached == fresh and cached_age is not None

    def test_board_and_include_archived_are_separate_cache_entries(self, tmp_path):
        calls = []
        kw = dict(cache_dir=str(tmp_path), ttl_minutes=15, fetch=self._fetcher(calls))
        fetch_cards_cached("b1", "k", **kw)
        fetch_cards_cached("b2", "k", **kw)
        fetch_cards_cached("b1", "k", include_archived=True, **kw)
        assert len(calls) == 3

    def test_corrupt_cache_file_is_ignored(self, tmp_path):
        calls = []
        kw = dict(cache_dir=str(tmp_path), ttl_minutes=15, fetch=self._fetcher(calls))
        fetch_cards_cached("b", "k", **kw)
        for f in tmp_path.iterdir():
            f.write_text("{not json", encoding="utf-8")
        _cards, age = fetch_cards_cached("b", "k", **kw)
        assert len(calls) == 2 and age is None

    def test_api_key_is_never_written_to_the_cache(self, tmp_path):
        fetch_cards_cached("b", "SECRET-KEY", cache_dir=str(tmp_path), ttl_minutes=15,
                           fetch=self._fetcher([]))
        for f in tmp_path.iterdir():
            assert "SECRET-KEY" not in f.name
            assert "SECRET-KEY" not in f.read_text(encoding="utf-8")


class TestComputeBoardTarget:
    def test_sums_todo_state_start_only(self):
        cards = [
            _card("Start", "Grand"),      # 5 pts
            _card("Backlog", "Petit"),    # uncommitted pool: deliberately excluded
            _card("Done", "Très grand"),  # not todo/wip: ignored
            _card("Archive", "Petit"),    # not todo/wip: ignored
        ]
        result = compute_board_target(cards, include_todo=True, include_wip=False)
        assert result == {"todo": (5.0, 1, 0)}

    def test_sums_wip_states_in_progress_and_buffer(self):
        cards = [
            _card("In Progress", "Moyen"),  # 3 pts
            _card("Buffer", "Petit"),       # 1 pt
            _card("Backlog", "Grand"),      # not wip: ignored
        ]
        result = compute_board_target(cards, include_todo=False, include_wip=True)
        assert result == {"wip": (4.0, 2, 0)}

    def test_both_categories_returned_together(self):
        cards = [_card("Start", "Petit"), _card("In Progress", "Petit")]
        result = compute_board_target(cards, include_todo=True, include_wip=True)
        assert result == {"todo": (1.0, 1, 0), "wip": (1.0, 1, 0)}

    def test_neither_flag_returns_empty_dict(self):
        cards = [_card("Start", "Petit")]
        assert compute_board_target(cards, include_todo=False, include_wip=False) == {}

    def test_cards_with_no_readable_size_are_skipped_and_counted(self):
        cards = [_card("Start", "Petit"), _card("Start", None), _card("Start", "not-a-size")]
        result = compute_board_target(cards, include_todo=True, include_wip=False)
        assert result == {"todo": (1.0, 1, 2)}

    def test_uniform_size_overrides_size_field(self):
        cards = [_card("Start"), _card("Start", "Grand")]
        result = compute_board_target(cards, include_todo=True, include_wip=False, uniform_size=2.0)
        assert result == {"todo": (4.0, 2, 0)}

    def test_english_size_values_also_recognized(self):
        cards = [
            {"columnState": "Start", "customFields": [{"label": "Size", "value": "Small"}]},
        ]
        result = compute_board_target(cards, include_todo=True, include_wip=False)
        assert result == {"todo": (1.0, 1, 0)}

    def test_archived_cards_are_excluded_even_with_a_todo_or_wip_column_state(self):
        # --include-archived widens fetch_cards() to also return archived
        # cards, so throughput can include completed-but-archived work —
        # but a card archived (e.g. cancelled) while still queued or in
        # progress must not count toward the to-do/WIP target.
        cards = [
            _card("Start", "Grand", archived_at="2026-01-01T00:00:00.000Z"),
            _card("In Progress", "Grand", archived_at="2026-01-01T00:00:00.000Z"),
            _card("Start", "Petit"),  # active, still counts
        ]
        result = compute_board_target(cards, include_todo=True, include_wip=True)
        assert result == {"todo": (1.0, 1, 0), "wip": (0.0, 0, 0)}

    def test_backlog_is_never_counted_as_todo(self):
        # Backlog is an uncommitted, not-yet-scheduled pool — unlike
        # "Start" (committed, queued to begin soon), it never counts.
        cards = [_card("Backlog", "Très grand")]
        result = compute_board_target(cards, include_todo=True, include_wip=False)
        assert result == {"todo": (0.0, 0, 0)}

    def test_include_backlog_sums_backlog_cards_only(self):
        cards = [
            _card("Backlog", "Grand"),   # 5 pts
            _card("Backlog", "Petit"),   # 1 pt
            _card("Backlog", None),      # unsized: skipped
            _card("Backlog", "Grand", archived_at="2026-01-01T00:00:00.000Z"),  # archived
            _card("Start", "Petit"),     # not requested
        ]
        result = compute_board_target(
            cards, include_todo=False, include_wip=False, include_backlog=True
        )
        assert result == {"backlog": (6.0, 2, 1)}

    def test_backlog_combines_with_todo_and_wip(self):
        cards = [_card("Start", "Petit"), _card("In Progress", "Petit"), _card("Backlog", "Petit")]
        result = compute_board_target(
            cards, include_todo=True, include_wip=True, include_backlog=True
        )
        assert result == {"todo": (1.0, 1, 0), "wip": (1.0, 1, 0), "backlog": (1.0, 1, 0)}


class TestCountBoardSizes:
    def test_counts_todo_and_wip_by_canonical_tier(self):
        cards = [
            _card("Start", "Petit"),
            _card("In Progress", "Petit"),
            _card("Buffer", "Grand"),
            {"columnState": "Start", "customFields": [{"label": "Size", "value": "Small"}]},
        ]
        assert count_board_sizes(cards, include_todo=True, include_wip=True) == {
            "Small": 3, "Large": 1,
        }

    def test_only_requested_categories_are_counted(self):
        cards = [_card("Start", "Petit"), _card("In Progress", "Grand")]
        assert count_board_sizes(cards, include_todo=False, include_wip=True) == {"Large": 1}

    def test_backlog_counted_only_when_requested(self):
        cards = [_card("Backlog", "Moyen"), _card("Start", "Petit")]
        assert count_board_sizes(cards, include_todo=True, include_wip=False) == {"Small": 1}
        assert count_board_sizes(
            cards, include_todo=True, include_wip=False, include_backlog=True
        ) == {"Small": 1, "Medium": 1}

    def test_unsized_archived_and_other_states_are_left_out(self):
        cards = [
            _card("Start", None),
            _card("Start", "not-a-size"),
            _card("Start", "Moyen", archived_at="2026-01-01T00:00:00.000Z"),
            _card("Backlog", "Moyen"),
            _card("Done", "Moyen"),
        ]
        assert count_board_sizes(cards, include_todo=True, include_wip=True) == {}
