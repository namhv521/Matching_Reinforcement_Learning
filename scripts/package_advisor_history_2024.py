"""Stage calendar-year advisor candidates without changing the legacy V1 pool."""

import argparse
import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "outputs/advisor_history_through_2024"


def rows(path):
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def stage(base=BASE):
    source = base / "papers/eligible_works.jsonl"
    audit = base / "audit_v2/eligible_source_records.jsonl"
    destination = base / "dataset"
    destination.mkdir(parents=True, exist_ok=True)
    profile_source = ROOT / "data/2024/advisors/faculty_profiles/advisors_profile.csv"
    with profile_source.open(encoding="utf-8-sig", newline="") as handle:
        profiles = list(csv.DictReader(handle))
    advisor_ids = {row["advisor_id"] for row in profiles}
    if len(advisor_ids) != 17 or len(profiles) != 17:
        raise ValueError("Unexpected advisor roster")
    result_path = base / "papers_corrected/work_results.jsonl"
    paper_results = {row["work_id"]: row for row in rows(result_path)} if result_path.exists() else {}

    # Paper crawler contains the dated official records and additional dated
    # browser candidates. The old software rows describe current content; retain
    # their historical dates only, pending a matching historical Git commit.
    items = []
    for record in rows(source):
        year = record.get("event_year")
        if not isinstance(year, int) or not 1 <= year <= 2024:
            raise ValueError(f"Out-of-scope paper row: {record.get('record_id')}")
        if record["advisor_id"] not in advisor_ids:
            raise ValueError("Unknown advisor")
        result = paper_results.get(record["work_id"])
        if paper_results and (not result or result["advisor_id"] != record["advisor_id"]):
            raise ValueError("Missing or mismatched paper result")
        fulltext = bool(result and result["status"] == "full_document_extracted" and result.get("title_match_first_two_pages"))
        items.append({
            "record_id": record["record_id"],
            "advisor_id": record["advisor_id"],
            "event_year": year,
            "date_precision": record.get("date_precision"),
            "date_witness": record.get("timing", {}).get("date_witness"),
            "content_type": record["content_type"],
            "title": record["title"],
            "content": record.get("content", ""),
            "source_url": record.get("source_url"),
            "raw_path": record.get("raw_path"),
            "source_sha256": record.get("source_sha256"),
            "source_record_id": record.get("source_record_id"),
            "available_at": None,
            "review_status": "needs_review",
            "historical_training_eligible": False,
            "source_kind": "dated_paper_candidate",
            "collection_status": result["status"] if result else "not_processed",
            "fulltext_extracted_path": result.get("extracted_path") if fulltext else None,
            "fulltext_pdf_sha256": result.get("pdf_sha256") if fulltext else None,
            "article_person_link_status": result.get("article_person_link_status") if result else "pending",
        })
    for record in rows(audit):
        if record["content_type"] != "software_project":
            continue
        year = record["_audit"]["event_year"]
        if not isinstance(year, int) or not 1 <= year <= 2024:
            raise ValueError("Out-of-scope software row")
        items.append({
            "record_id": record["record_id"],
            "advisor_id": record["advisor_id"],
            "event_year": year,
            "date_precision": record["_audit"]["date_classification"].get("event_date", {}).get("precision"),
            "content_type": "software_project",
            "title": record["title"],
            "content": None,
            "source_url": record.get("source_url"),
            "raw_path": record.get("raw_path"),
            "source_sha256": record.get("sha256"),
            "available_at": None,
            "review_status": "needs_historical_commit_and_identity_review",
            "historical_training_eligible": False,
            "source_kind": "software_metadata_only",
        })
    items.sort(key=lambda x: (x["event_year"], x["advisor_id"], x["record_id"]))
    years = Counter(row["event_year"] for row in items)
    output = destination / "by_event_year"
    output.mkdir(exist_ok=True)
    for stale in output.glob("*.jsonl"):
        stale.unlink()
    for year in sorted(years):
        with (output / f"{year}.jsonl").open("w", encoding="utf-8") as handle:
            for row in items:
                if row["event_year"] == year:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (destination / "faculty_candidates.jsonl").open("w", encoding="utf-8") as handle:
        for row in items:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (destination / "advisor_registry.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=profiles[0].keys())
        writer.writeheader()
        writer.writerows(profiles)
    git_index = base / "github_history_index/records.jsonl"
    git_rows = []
    if git_index.exists():
        cutoff = datetime.fromisoformat("2025-01-01T00:00:00+07:00")
        for record in rows(git_index):
            if record["advisor_id"] not in advisor_ids:
                raise ValueError("Unknown Git advisor")
            author = datetime.fromisoformat(record["author_date"].replace("Z", "+00:00"))
            committer = datetime.fromisoformat(record["committer_date"].replace("Z", "+00:00"))
            if not author < cutoff or not committer < cutoff or record["event_year"] != committer.astimezone(cutoff.tzinfo).year:
                raise ValueError("Git snapshot crosses calendar boundary")
            git_rows.append(record)
        git_rows.sort(key=lambda row: (row["event_year"], row["repository"]))
        with (destination / "github_snapshots.jsonl").open("w", encoding="utf-8") as handle:
            for record in git_rows:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        git_dir = destination / "by_event_year_github"
        git_dir.mkdir(exist_ok=True)
        for stale in git_dir.glob("*.jsonl"):
            stale.unlink()
        for year in sorted({row["event_year"] for row in git_rows}):
            with (git_dir / f"{year}.jsonl").open("w", encoding="utf-8") as handle:
                for record in git_rows:
                    if record["event_year"] == year:
                        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    report = {
        "schema_version": "advisor-calendar-history-staging/1",
        "boundary_exclusive_local": "2025-01-01T00:00:00+07:00",
        "advisor_count": len(profiles),
        "candidate_rows": len(items),
        "paper_candidate_rows": sum(row["source_kind"] == "dated_paper_candidate" for row in items),
        "software_metadata_only_rows": sum(row["source_kind"] == "software_metadata_only" for row in items),
        "historical_github_snapshots": len(git_rows),
        "fulltext_pending_identity_review": sum(bool(row.get("fulltext_extracted_path")) for row in items),
        "quarantined_identity_rows": sum(row.get("collection_status") == "quarantined_identity" for row in items),
        "by_event_year": dict(sorted(years.items())),
        "unique_work_count_claimed": False,
        "identity_approvals_granted": 0,
        "historical_training_ready_rows": 0,
        "note": "Candidate dates are not evidence of historical availability. Paper title variants may duplicate works. Software source text is excluded until historical commit verification.",
    }
    (destination / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, default=BASE)
    args = parser.parse_args()
    print(json.dumps(stage(args.base), ensure_ascii=False, indent=2))
