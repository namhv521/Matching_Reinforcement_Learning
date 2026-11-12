"""Relocatable serving bundle: original weights and reviewed sources stay private."""
import hashlib
import io
import json
import os
import tarfile
import uuid
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
MAX_ARCHIVE = 64 * 1024 * 1024
MAX_CONTENT = 160 * 1024 * 1024


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def export_release(bundle_path, selection_path, destination):
    """Only export after the existing full source/checkpoint loaders verify inputs."""
    from src.serving.github_service import load_github_service
    service = load_github_service(bundle_path, selection_path, ROOT/'data_rebuild/runtime/release-export')
    bundle = json.loads(Path(bundle_path).read_bytes())
    selection = json.loads(Path(selection_path).read_bytes())
    source = bundle['serving']
    files = {}
    def add(name, value):
        files[name] = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
    add('catalog.json', service.advisors)
    add('versions.json', service.versions)
    add('taxonomy.json', service.taxonomy)
    add('identities.json', list(service.pipeline.identities))
    add('scorable.json', service.scorable.tolist())
    add('contract.json', bundle['model_contract'])
    add('training_problem.json', bundle['training_problems'][0])
    files['profiles.json'] = Path(source['source_profiles_path']).read_bytes()
    files['review.json'] = Path(source['github_quality_review_path']).read_bytes()
    files['training_report.json'] = (ROOT/'docs/validation/github_retraining_numeric_20261023.json').read_bytes()
    for name in ('transformer.json', 'idf.npz'):
        files['transformer/'+name] = (Path(source['transformer_dir'])/name).read_bytes()
    for algorithm in ('ppo', 'dqn'):
        for path in sorted(Path(selection['candidates'][algorithm]['path']).iterdir()):
            if path.is_file():
                files[f'models/{algorithm}/{path.name}'] = path.read_bytes()
    github = Path(source['github_source_run'])
    for path in sorted(github.rglob('*')):
        if path.is_file():
            files['github/'+path.relative_to(github).as_posix()] = path.read_bytes()
    manifest = {'origin_bundle_sha256': digest(Path(bundle_path).read_bytes()),
                'origin_selection_sha256': digest(Path(selection_path).read_bytes()),
                'native_weights_modified': False, 'github_manifest_sha256': source['github_manifest_sha256'],
                'review_sha256': source['github_quality_review_sha256']}
    return write_release(files, manifest, destination)


def write_release(files, metadata, destination):
    manifest = {**metadata, 'schema': 'unimatch-serving/1',
                'files': {name: digest(data) for name, data in files.items()}}
    entries = {**files, 'release.json': json.dumps(manifest, allow_nan=False).encode()}
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w:gz') as archive:
        for name, content in sorted(entries.items()):
            item = tarfile.TarInfo(name); item.size = len(content); item.mode = 0o600
            archive.addfile(item, io.BytesIO(content))
    payload = output.getvalue()
    if len(payload) > MAX_ARCHIVE:
        raise ValueError('serving_release_size_limit')
    destination = Path(destination)
    if not destination.resolve().is_relative_to(ROOT/'data_rebuild'):
        raise ValueError('private_release_destination_required')
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    return {'sha256': digest(payload), 'bytes': len(payload), 'files': len(entries)}


def unpack_release(payload, expected_sha256, runtime):
    if len(payload) > MAX_ARCHIVE or digest(payload) != expected_sha256:
        raise ValueError('release_hash_mismatch')
    contents = {}
    with tarfile.open(fileobj=io.BytesIO(payload), mode='r:gz') as archive:
        total = 0
        for member in archive:
            name = PurePosixPath(member.name)
            total += member.size
            if (not member.isfile() or name.is_absolute() or '..' in name.parts
                    or '\\' in member.name or ':' in member.name or member.name in contents
                    or str(name) != member.name or total > MAX_CONTENT or len(contents) >= 1000
                    or member.size > MAX_ARCHIVE):
                raise ValueError('release_archive_invalid')
            contents[member.name] = archive.extractfile(member).read()
    manifest = json.loads(contents.get('release.json', b'{}'))
    if (manifest.get('schema') != 'unimatch-serving/1' or set(contents) != set(manifest['files']) | {'release.json'}
            or any(digest(contents[name]) != sha for name, sha in manifest['files'].items())):
        raise ValueError('release_inventory_mismatch')
    runtime = Path(runtime).resolve(); runtime.mkdir(parents=True, exist_ok=True)
    folder = runtime/expected_sha256
    if folder.exists():
        if (folder.is_symlink() or {p.relative_to(folder).as_posix() for p in folder.rglob('*') if p.is_file()} != set(contents)
                or any((folder/name).is_symlink() or (folder/name).read_bytes() != content for name, content in contents.items())):
            raise ValueError('restored_release_changed')
        return folder
    temporary = runtime/('release-'+uuid.uuid4().hex)
    temporary.mkdir()
    for name, content in contents.items():
        path = temporary/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(content)
    temporary.rename(folder)
    return folder


def load_release(folder, runtime_dir):
    folder = Path(folder)
    manifest = json.loads((folder/'release.json').read_bytes())
    if manifest.get('kind') == 'semester-catalog':
        from .catalog_release import load_catalog_release
        return load_catalog_release(folder, runtime_dir)
    import numpy as np
    import torch
    from src.domain.rebuild_matching import AllocationProblem
    from src.environment.rebuild_env import MatchingEnv
    from src.features.rebuild_features import FeaturePipeline
    from src.rl.rebuild_dqn import MaskedDQN
    from src.rl.rebuild_ppo import MaskedPPOAgent
    from src.serving.rebuild_service import RebuildService
    from src.serving.github_service import GithubAssistant
    from src.data_pipeline.review_decisions import record_hash
    read = lambda name: json.loads((folder/name).read_bytes())
    versions, contract = read('versions.json'), read('contract.json')
    pipeline = FeaturePipeline.load(folder/'transformer', known_identities=read('identities.json'))
    raw = read('training_problem.json')
    for key in ('scores', 'student_features', 'preferences'):
        raw[key] = np.asarray(raw[key], dtype=float)
    for key in ('available', 'eligible', 'present', 'student_feature_known', 'preference_known'):
        raw[key] = np.asarray(raw[key], dtype=bool)
    raw['capacities'] = np.asarray(raw['capacities'], dtype=int)
    problem = AllocationProblem(**raw)
    env = MatchingEnv([problem])
    taxonomy, advisors = read('taxonomy.json'), read('catalog.json')
    if (tuple(row['advisor_id'] for row in advisors) != tuple(problem.advisor_ids)
            or record_hash(sorted((group, tag) for group, tags in taxonomy['groups'].items() for tag in tags)) != contract['taxonomy_feature_order_sha256']
            or env.reward_weights != contract['reward_weights']
            or digest((folder/'transformer/transformer.json').read_bytes()) != versions['frozen_encoder']['transformer_json_sha256']
            or digest((folder/'transformer/idf.npz').read_bytes()) != versions['frozen_encoder']['transformer_idf_sha256']):
        raise ValueError('release_feature_contract_mismatch')
    torch.set_num_threads(1)
    for algorithm in ('ppo', 'dqn'):
        hashes = {path.name: digest(path.read_bytes()) for path in (folder/'models'/algorithm).iterdir() if path.is_file()}
        if record_hash(hashes) != versions['models'][algorithm]['checkpoint_sha256']:
            raise ValueError('release_selected_checkpoint_mismatch')
    models = {'ppo': MaskedPPOAgent.load(folder/'models/ppo', env, expected_contract=contract),
              'dqn': MaskedDQN.load(folder/'models/dqn', expected_contract=contract)}
    service = RebuildService(pipeline=pipeline, advisors=advisors, taxonomy=taxonomy,
        versions=versions, runtime_dir=runtime_dir, scorable=read('scorable.json'), models=models,
        model_contracts={key: contract for key in models})
    assistant = GithubAssistant(read('profiles.json'), service, github_run=folder/'github',
        github_manifest_sha256=manifest['github_manifest_sha256'], quality_review_path=folder/'review.json',
        quality_review_sha256=manifest['review_sha256'])
    return service, assistant


def publish_release(database, key, path, *, expected_sha256=None):
    payload = Path(path).read_bytes(); sha = digest(payload)
    if expected_sha256 is not None and sha != expected_sha256:
        raise ValueError('release_hash_mismatch')
    if len(payload) > MAX_ARCHIVE:
        raise ValueError('serving_release_size_limit')
    with database.connect() as db:
        db.execute('INSERT INTO model_bundles(bundle_key,sha256,payload) VALUES (?,?,?) ON CONFLICT(bundle_key) DO NOTHING',
                   (key, sha, payload))
        row = db.execute('SELECT sha256 FROM model_bundles WHERE bundle_key=?', (key,)).fetchone()
        if row['sha256'] != sha:
            raise ValueError('immutable_model_bundle_conflict')
    return sha
