"""Export a verified private release; optionally publish immutably to PostgreSQL."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path)
    parser.add_argument('--selection', type=Path)
    parser.add_argument('--semester-outputs', type=Path, help='Verified Strict GitHub PPO/DQN V1–V3 runs')
    parser.add_argument('--release-name', help='Immutable release name for a semester catalog')
    parser.add_argument('--archive', type=Path, help='Publish a previously exported archive without rebuilding it')
    parser.add_argument('--expected-sha256', help='SHA-256 from the verified archive export')
    parser.add_argument('--output', type=Path, default=ROOT/'data_rebuild/deployment/serving.tar.gz')
    parser.add_argument('--publish-key', help='Publish under a new immutable key using DATABASE_URL')
    args = parser.parse_args()
    from backend.app.production_release import digest, export_release, publish_release
    output = args.output
    if args.archive:
        if args.semester_outputs or args.bundle or args.selection or args.release_name or not (args.publish_key and args.expected_sha256):
            parser.error('--archive requires --publish-key and --expected-sha256')
        output = args.archive
        sha = digest(output.read_bytes())
        if sha != args.expected_sha256:
            raise ValueError('release_hash_mismatch')
        result = {'sha256': sha, 'bytes': output.stat().st_size}
    elif args.expected_sha256:
        parser.error('--expected-sha256 requires --archive')
    elif args.semester_outputs:
        if args.bundle or args.selection or not args.release_name or args.publish_key not in (None, args.release_name):
            parser.error('--semester-outputs requires --release-name and its publish key must match')
        from backend.app.catalog_release import export_catalog_release
        result = export_catalog_release(args.semester_outputs, args.output, args.release_name)
    else:
        if not (args.bundle and args.selection) or args.release_name:
            parser.error('provide --bundle and --selection, or use --semester-outputs')
        result = export_release(args.bundle, args.selection, args.output)
    if args.publish_key:
        from backend.app.portal_database import Database, database_location
        location = database_location()
        if not location.startswith(('postgres://', 'postgresql://')):
            raise ValueError('postgresql_required_for_publish')
        result['published_sha256'] = publish_release(Database(location), args.publish_key, output,
                                                     expected_sha256=result['sha256'])
    print(json.dumps(result))


if __name__ == '__main__':
    main()
