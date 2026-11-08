import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('collect_advisor_repositories',
    Path(__file__).resolve().parents[1] / 'scripts/collect_advisor_repositories.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CollectionTests(unittest.TestCase):
    def test_pinned_inventory_and_raw_hashes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / 'registry.csv'
            registry.write_text('advisor_id,github_url\na,https://github.com/person\n')
            def fetch(url):
                if '/users/' in url:
                    return 200, json.dumps([{'id': 1, 'owner': {'login': 'person'}, 'name': 'repo',
                        'full_name': 'person/repo', 'default_branch': 'main'}]).encode(), {}
                if '/git/trees/' in url:
                    return 200, json.dumps({'tree': [{'type': 'blob', 'path': 'README.md', 'size': 5},
                        {'type': 'blob', 'path': 'vendor/a.py', 'size': 3},
                        {'type': 'blob', 'path': 'src/a.py', 'size': 3}]}).encode(), {}
                return 200, b'hello', {}
            out = root / 'out'
            result = module.harvest(registry, out, fetch=fetch, pin=lambda *args: ('a' * 40, b'head'))
            repo = json.loads((out / 'repositories.json').read_bytes())[0]
            self.assertEqual(repo['commit_sha'], 'a' * 40)
            self.assertEqual(repo['code_files_read'], 0)
            self.assertEqual(len(repo['first_party_inventory']), 2)
            self.assertEqual(result['requests'], 3)
            for path, digest in result['artifacts'].items():
                self.assertEqual(module.sha((out / path).read_bytes()), digest)
            with self.assertRaises(FileExistsError):
                module.harvest(registry, out, fetch=fetch)

    def test_rate_limit_stops_later_calls_without_claiming_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / 'registry.csv'
            registry.write_text('advisor_id,github_url\na,https://github.com/one\nb,https://github.com/two\n')
            calls = []
            def fetch(url):
                calls.append(url)
                return 403, b'{"message":"API rate limit exceeded"}', {'X-RateLimit-Remaining': '0'}
            result = module.harvest(registry, root / 'out', fetch=fetch)
            self.assertEqual(len(calls), 1)
            self.assertEqual(result['stop_reason'], 'github_rate_limited')
            self.assertEqual(set(result['account_statuses'].values()), {'github_rate_limited'})

    def test_resume_verifies_and_reuses_completed_without_requests(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / 'registry.csv'
            registry.write_text('advisor_id,github_url\na,https://github.com/person\n')
            def fetch(url):
                if '/users/' in url:
                    return 200, json.dumps([{'id': 1, 'owner': {'login': 'person'}, 'name': 'repo',
                        'full_name': 'person/repo', 'default_branch': 'main'}]).encode(), {}
                return 200, b'{"tree":[]}', {}
            original = root / 'original'
            module.harvest(registry, original, fetch=fetch, pin=lambda *a: ('a' * 40, b'head'))
            before = module.sha((original / 'manifest.json').read_bytes())
            def forbidden(*args):
                raise AssertionError('Completed repo must not be fetched or pinned again')
            resumed = module.harvest(registry, root / 'continued', resume_from=original,
                                      fetch=forbidden, pin=forbidden)
            self.assertEqual(resumed['requests'], 0)
            self.assertEqual(resumed['reused_repositories'], 1)
            self.assertEqual(resumed['upstream']['manifest_sha256'], before)
            (original / 'repositories.json').write_bytes(b'[]')
            with self.assertRaisesRegex(ValueError, 'hash_mismatch'):
                module.harvest(registry, root / 'bad', resume_from=original)

    def test_partial_resume_keeps_sha_and_fetches_only_root_readme(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / 'registry.csv'
            registry.write_text('advisor_id,github_url\na,https://github.com/person\n')
            def fetch(url):
                if '/users/' in url:
                    return 200, json.dumps([{'id': 1, 'owner': {'login': 'person'}, 'name': 'repo',
                        'full_name': 'person/repo', 'default_branch': 'main', 'fork': True}]).encode(), {}
                return 200, json.dumps({'tree': [
                    {'type': 'blob', 'path': 'README.md', 'size': 5},
                    {'type': 'blob', 'path': 'docs/README.md', 'size': 5}]}).encode(), {}
            old = root / 'old'
            module.harvest(registry, old, fetch=fetch, pin=lambda *a: ('a'*40, b'head'), max_requests=2)
            calls = []
            def root_only(url):
                calls.append(url)
                self.assertEqual(url, 'https://raw.githubusercontent.com/person/repo/' + 'a'*40 + '/README.md')
                return 200, b'hello', {}
            def no_repin(*args):
                raise AssertionError('Must preserve previous immutable reference')
            new = root / 'new'
            result = module.harvest(registry, new, resume_from=old, fetch=root_only, pin=no_repin)
            repo = json.loads((new / 'repositories.json').read_bytes())[0]
            self.assertEqual(len(calls), 1)
            self.assertEqual(repo['status'], 'captured_inventory_and_root_readme')
            self.assertEqual(repo['evidence_eligibility'], 'excluded_fork_without_verified_contribution')


if __name__ == '__main__':
    unittest.main()
