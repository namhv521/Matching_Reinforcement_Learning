import json
import unittest
from datetime import datetime
from pathlib import Path


BASE = Path(__file__).resolve().parents[1] / "outputs/advisor_history_through_2024/dataset"


@unittest.skipUnless(BASE.exists(), "Historical crawl artifact is local and optional")
class HistoricalPackageTest(unittest.TestCase):
    def test_calendar_boundary_and_source_safety(self):
        report = json.loads((BASE / "report.json").read_text(encoding="utf-8"))
        records = [json.loads(line) for line in (BASE / "faculty_candidates.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(records), report["candidate_rows"])
        self.assertEqual(len(records), len({record["record_id"] for record in records}))
        self.assertTrue(all(1 <= record["event_year"] <= 2024 for record in records))
        self.assertTrue(all(record["available_at"] is None and not record["historical_training_eligible"] for record in records))
        self.assertTrue(all(record["content"] is None for record in records if record["source_kind"] == "software_metadata_only"))
        for year, count in report["by_event_year"].items():
            year_rows = (BASE / "by_event_year" / f"{year}.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(year_rows), count)
            self.assertTrue(all(json.loads(line)["event_year"] == int(year) for line in year_rows))
        git_path = BASE / "github_snapshots.jsonl"
        if git_path.exists():
            git_rows = [json.loads(line) for line in git_path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(git_rows), report["historical_github_snapshots"])
            cutoff = datetime.fromisoformat("2025-01-01T00:00:00+07:00")
            for row in git_rows:
                self.assertLess(datetime.fromisoformat(row["author_date"].replace("Z", "+00:00")), cutoff)
                self.assertLess(datetime.fromisoformat(row["committer_date"].replace("Z", "+00:00")), cutoff)
                self.assertIsNone(row["available_at"])


if __name__ == "__main__":
    unittest.main()
