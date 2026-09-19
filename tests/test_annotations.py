from datetime import date

from montecarlo.annotations import load_annotations


def _write_csv(tmp_path, rows, name="annotations.csv"):
    path = tmp_path / name
    lines = ["Date,Note"] + [f"{d},{n}" for d, n in rows]
    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


class TestLoadAnnotations:
    def test_none_path_and_no_default_file_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)  # no data/annotations.csv here
        assert load_annotations(None) == {}

    def test_missing_explicit_file_warns_and_returns_empty(self, capsys):
        result = load_annotations("does/not/exist.csv")
        assert result == {}
        assert "not found" in capsys.readouterr().err

    def test_groups_multiple_notes_per_date(self, tmp_path):
        path = _write_csv(tmp_path, [
            ("2026-03-20", "Deployment freeze"),
            ("2026-03-20", "Team offsite"),
            ("2026-04-01", "New hire onboarded"),
        ])
        result = load_annotations(path)
        assert result[date(2026, 3, 20)] == ["Deployment freeze", "Team offsite"]
        assert result[date(2026, 4, 1)] == ["New hire onboarded"]

    def test_skips_rows_with_blank_date_or_note(self, tmp_path):
        path = _write_csv(tmp_path, [
            ("", "Missing date"),
            ("2026-03-20", ""),
            ("2026-03-21", "Valid"),
        ])
        result = load_annotations(path)
        assert result == {date(2026, 3, 21): ["Valid"]}

    def test_unparseable_date_is_skipped(self, tmp_path):
        path = _write_csv(tmp_path, [("not-a-date", "Ignored")])
        assert load_annotations(path) == {}
