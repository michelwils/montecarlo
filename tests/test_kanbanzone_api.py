import csv
import json
import os
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from montecarlo.kanbanzone_api import (
    KanbanZoneAPIError,
    cards_to_csv_rows,
    fetch_cards,
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
        assert rows[0] == {"Done At": "2026-03-16"}

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
