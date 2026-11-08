"""Collect directly observed paper PDFs without modifying source datasets."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.data_pipeline.advisor_paper_fulltext import collect_papers

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--captures', type=Path, required=True)
    parser.add_argument('--publication-index', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--max-downloads', type=int, default=60)
    parser.add_argument('--capture-quality', type=Path)
    args = parser.parse_args()
    report = collect_papers(args.captures, args.publication_index, args.output,
                            max_downloads=args.max_downloads, capture_quality=args.capture_quality)
    print(json.dumps({key: value for key, value in report.items() if key != 'artifact_hashes'}))
