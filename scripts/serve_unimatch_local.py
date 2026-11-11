"""Launch the additive local UniMatch API/page; never prints access tokens."""
import argparse
import json
import os
import secrets
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def load_local_token(path):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists():
        # Exclusive creation prevents a second launcher from replacing a token.
        try:
            with path.open('x',encoding='utf-8') as stream:
                stream.write(secrets.token_urlsafe(32))
            path.chmod(0o600)
        except FileExistsError:
            pass
    token=path.read_text(encoding='utf-8').strip()
    if len(token)<32 or any(c.isspace() for c in token):
        raise ValueError('local_access_token_invalid; inspect the token file before replacing it')
    return token


def local_selection_path(output):
    """Choose the local selection pointer; the serving loader verifies its bytes."""
    output=Path(output).resolve();pointer=output/'reports/convergence_gate.json'
    if not pointer.exists(): return None
    gate=json.loads(pointer.read_text(encoding='utf-8'))
    if gate.get('status')!='verified': return None
    directory=Path(gate['run_dir']).resolve()
    if directory.parent!=output/'convergence_runs' or directory.name!=gate['run_id']:
        raise ValueError('local_convergence_selection_path_invalid')
    return directory/'selection_manifest.json'


def local_app_entrypoint(output):
    gate_path=Path(output)/'reports/phase8_local_gate.json'
    if gate_path.exists():
        gate=json.loads(gate_path.read_text(encoding='utf-8'))
        if (gate.get('phase')==8 and gate.get('status')=='verified'
                and gate.get('scope')=='owner_authorized_local_release'):
            return 'backend.app.rebuild_assistant_api:app'
    return 'backend.app.rebuild_api:app'


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8767)
    parser.add_argument('--token-file',type=Path)
    parser.add_argument('--semester-run',type=Path,help='Completed semester run containing suites/ and training/.')
    parser.add_argument('--checkpoint-catalog', action='store_true', help='Serve all six Strict GitHub research checkpoints.')
    parser.add_argument('--semester-inputs',type=Path,default=ROOT/'data/training_prepared_20261101')
    parser.add_argument('--env-file',type=Path,default=ROOT/'.env',help='Local OAuth/settings file; existing process variables take precedence.')
    parser.add_argument('--selection',type=Path,help='Explicit verified model-selection manifest')
    args=parser.parse_args()
    if args.checkpoint_catalog and (args.semester_run or args.selection):
        parser.error('--checkpoint-catalog has its own checkpoint selection')
    if args.checkpoint_catalog:
        from dotenv import load_dotenv
        if args.env_file.is_file():
            load_dotenv(args.env_file)
        if os.environ.get('UNIMATCH_DEPLOYMENT') == 'production':
            parser.error('--checkpoint-catalog is a loopback research portal')
        runtime = ROOT/'data_rebuild/runtime/strict_catalog'
        os.environ['UNIMATCH_AUTH_DB'] = str(runtime/'portal.sqlite3')
        os.environ['UNIMATCH_DATABASE_URL'] = str(runtime/'portal.sqlite3')
        os.environ['UNIMATCH_PUBLIC_ORIGIN'] = f'http://127.0.0.1:{args.port}'
        from backend.app.rebuild_assistant_api import create_app
        from src.serving.semester_catalog import load_catalog
        import torch
        import uvicorn
        torch.set_num_threads(1)
        service, assistant = load_catalog(ROOT/'outputs', runtime/'proposals')
        app = create_app(service=service, assistant=assistant,
                         token=load_local_token(args.token_file or runtime/'access.token'))
        print(f'Local workspace: http://127.0.0.1:{args.port}/login.html', flush=True)
        uvicorn.run(app, host='127.0.0.1', port=args.port, access_log=False)
        raise SystemExit(0)
    current_semester_run=ROOT/'outputs/semester_rl_20261101'
    if not args.semester_run and not args.selection and (current_semester_run/'training/selection.json').is_file():
        args.semester_run=current_semester_run
    if args.semester_run:
        os.environ['UNIMATCH_SEMESTER_RUN']=str(args.semester_run.resolve())
        os.environ['UNIMATCH_SEMESTER_INPUTS']=str(args.semester_inputs.resolve())
        local_database=str(args.semester_run.resolve()/'runtime/portal.sqlite3')
        os.environ['UNIMATCH_AUTH_DB']=local_database
        os.environ['UNIMATCH_DATABASE_URL']=local_database
    args.token_file=args.token_file or (args.semester_run/'runtime/access.token' if args.semester_run else ROOT/'data_rebuild/runtime/access.token')
    os.environ['UNIMATCH_REBUILD_TOKEN']=load_local_token(args.token_file)
    selection=args.selection or (None if args.semester_run else local_selection_path(ROOT/'data_rebuild/v1'))
    if selection is not None:
        os.environ['UNIMATCH_REBUILD_SELECTION']=str(selection.resolve())
    os.environ.setdefault('OMP_NUM_THREADS','1')
    os.environ.setdefault('MKL_NUM_THREADS','1')
    os.environ.setdefault('UNIMATCH_PUBLIC_ORIGIN',f'http://127.0.0.1:{args.port}')
    print(f'Local workspace: http://127.0.0.1:{args.port}/login.html',flush=True)
    print(f'Access token file: {args.token_file.resolve()} (private; value not logged)',flush=True)
    import uvicorn
    entrypoint='backend.app.rebuild_api:app' if args.semester_run else local_app_entrypoint(ROOT/'data_rebuild/v1')
    uvicorn.run(entrypoint,host='127.0.0.1',port=args.port,access_log=False,
                env_file=str(args.env_file.resolve()) if args.env_file.is_file() else None)
