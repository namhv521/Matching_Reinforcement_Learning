"""Source-bound offline Phase 5 training and shared, replayable comparisons."""
import importlib.metadata
import json
import time
import uuid
from dataclasses import replace
from datetime import datetime,timezone
from pathlib import Path

import numpy as np
import torch
from scipy.stats import t

from src.baselines.rebuild_baselines import solve
from src.data_pipeline.rebuild_cohorts import build_research_suite
from src.data_pipeline.reconcile import ROOT,_digest
from src.data_pipeline.review_decisions import record_hash
from src.domain.rebuild_matching import AllocationProblem,equal_quotas,feasible,validate_assignments
from src.environment.rebuild_env import MatchingEnv
from src.features.rebuild_acceptance import load_approved_features
from src.rl.rebuild_dqn import MaskedDQN
from src.rl.rebuild_ppo import MaskedPPOAgent


ALGORITHMS=('hungarian','greedy','random','ppo','dqn')
RELEASE_SEEDS=(42,43,44,45,46)
DECLARED_TIMESTEPS=16384


def _write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def problem_payload(problem):
    return {**{key:getattr(problem,key).tolist() for key in ('scores','available','capacities','eligible','present',
            'student_features','student_feature_known','preferences','preference_known')},
            'student_ids':list(problem.student_ids),'advisor_ids':list(problem.advisor_ids),
            'fixed_assignments':dict(problem.fixed_assignments),'preference_weight':problem.preference_weight,
            'metadata':problem.metadata}


def _metrics(problem,assignments):
    validation=validate_assignments(problem,assignments)
    pairs=[(problem.student_ids.index(r['student_id']),problem.advisor_ids.index(r['advisor_id'])) for r in assignments]
    scores=np.array([problem.scores[i,j] for i,j in pairs])
    loads=np.bincount([j for _,j in pairs],minlength=len(problem.advisor_ids))
    active=problem.present&(problem.capacities>0)
    utilization=loads[active]/problem.capacities[active]
    return {'objective':float(sum(problem.utility[i,j] for i,j in pairs)),
        'mean_compatibility':float(scores.mean()) if scores.size else None,
        'min_compatibility':float(scores.min()) if scores.size else None,
        'p10_compatibility':float(np.quantile(scores,.1)) if scores.size else None,
        'normalized_load_imbalance':float(np.ptp(utilization)) if utilization.size else 0.,
        'coverage':validation['coverage'],'constraint_violations':len(validation['violations'])}


def verify_trace(problem,trace):
    env=MatchingEnv([problem])
    order=trace[0]['student_order'] if trace else list(problem.student_ids)
    env.reset(seed=0,options={'student_order':order})
    for row in trace:
        _,_,_,_,info=env.step(row['action_index'])
        original={k:v for k,v in row.items() if k!='policy_output'}
        if row.get('policy_output', {}).get('kind') == 'quota_only_random':
            original.update(score=0.0, score_known=True)
        if original!=info['decision']:
            raise ValueError('trace_replay_mismatch')
    if len(env.assignments)!=len(problem.student_ids):
        raise ValueError('trace_replay_incomplete')
    return True


def evaluate_problem(problem,algorithm,*,model=None,seed=42,quota_only=()):
    if algorithm not in ALGORITHMS: raise ValueError('unknown_benchmark_algorithm')
    started=time.perf_counter()
    if quota_only:
        missing = [i for i, sid in enumerate(problem.student_ids) if sid in quota_only]
        if len(missing) != len(quota_only):
            raise ValueError('invalid_quota_only_students')
        available = problem.available.copy()
        scores = problem.scores.copy()
        available[missing] = True
        scores[missing] = 0
        problem = replace(problem, available=available, scores=scores,
                          fixed_assignments=dict(problem.fixed_assignments))
        order = [i for i in range(len(problem.student_ids)) if i not in missing] + missing
        random = np.random.default_rng(seed)
    else:
        order = None
    if not feasible(problem):
        return {'status':'infeasible','assignments':[],'trace':[],'invalid_action_count':0,
                'elapsed_seconds':time.perf_counter()-started,'metrics':{'coverage':0.,'constraint_violations':0},
                'diagnostic':'No complete allocation under exact supplied constraints; no fabricated assignment.'}
    baseline=solve(problem,algorithm,seed) if algorithm == 'hungarian' or (
        not quota_only and algorithm in ('greedy', 'random')) else None
    if baseline:
        choices={r['student_id']:r['advisor_id'] for r in baseline['assignments']}
    elif model is None and algorithm in ('ppo', 'dqn'):
        raise ValueError('trained_model_required')
    env=MatchingEnv([problem]); obs,_=env.reset(seed=seed,options={'student_order':order}); done=False
    while not done:
        mask=env.action_masks()
        i = env.remaining_students[0]
        sid = problem.student_ids[i]
        if sid in quota_only:
            action = int(random.choice(np.flatnonzero(mask)))
            output = {'kind':'quota_only_random', 'seed':seed}
        elif baseline:
            action=problem.advisor_ids.index(choices[sid])
            output={'kind':'solver_decision','algorithm':algorithm}
        elif algorithm in ('greedy', 'random'):
            candidates = np.flatnonzero(mask)
            action = int(random.choice(candidates)) if algorithm == 'random' else min(
                candidates, key=lambda j: (-problem.utility[i,j], problem.advisor_ids[j]))
            output={'kind':'solver_decision','algorithm':algorithm}
        else:
            action=model.predict(obs,mask,deterministic=True)
            values=model.probabilities(obs,mask) if algorithm=='ppo' else model.q_values(obs)
            output={'kind':'masked_policy_probability' if algorithm=='ppo' else 'q_value_not_probability',
                    'values':values.tolist()}
        obs,_,terminated,truncated,info=env.step(action); done=terminated or truncated
        info['decision']['policy_output']=output
    assignments=[{'student_id':sid,'advisor_id':aid} for sid,aid in env.assignments.items()]
    metrics=_metrics(problem,assignments)
    if metrics['coverage']!=1 or metrics['constraint_violations']:
        raise RuntimeError('benchmark_final_validation_failed')
    elapsed=time.perf_counter()-started
    verify_trace(problem,env.trace)
    if quota_only:
        scored = [row['score'] for row in env.trace if row['student_id'] not in quota_only and row['score_known']]
        metrics.update(scored_students=len(scored), quota_only_students=len(quota_only),
                       mean_compatibility=float(np.mean(scored)) if scored else None,
                       min_compatibility=float(min(scored)) if scored else None,
                       p10_compatibility=float(np.quantile(scored,.1)) if scored else None)
        for row in env.trace:
            if row['student_id'] in quota_only:
                row['score'] = None
                row['score_known'] = False
    return {'status':'feasible','assignments':assignments,'trace':env.trace,'metrics':metrics,
            'invalid_action_count':env.invalid_action_count,'trace_replay_verified':True,'elapsed_seconds':elapsed}


def summarize_seeds(rows):
    result={}
    for case in sorted({row['case'] for row in rows}):
        result[case]={}
        for algorithm in sorted({row['algorithm'] for row in rows if row['case']==case}):
            chosen=[row for row in rows if row['case']==case and row['algorithm']==algorithm]
            keys={key for row in chosen for key in row['metrics']}|{'elapsed_seconds'}
            statistics={}
            for key in sorted(keys):
                values=[row['elapsed_seconds'] if key=='elapsed_seconds' else row['metrics'].get(key) for row in chosen]
                values=np.array([value for value in values if value is not None],dtype=float)
                n=len(values); mean=float(values.mean()) if n else None
                std=float(values.std(ddof=1)) if n>1 else (0. if n else None)
                half=float(t.ppf(.975,n-1)*std/np.sqrt(n)) if n>1 else None
                statistics[key]={'n':n,'mean':mean,'std':std,'ci95':[mean-half,mean+half] if half is not None else None}
            statistics['status_counts']={status:sum(row['status']==status for row in chosen) for status in {row['status'] for row in chosen}}
            result[case][algorithm]=statistics
    return result


def _stress_problems(suite):
    registry=tuple(suite['metadata']['advisor_registry']); m=len(registry)
    k=suite['train'][0].student_features.shape[1]; selected=suite['metadata']['selected_advisor_ids'][:2]
    first,second=[registry.index(key) for key in selected]
    def make(name,scores,*,hall=False):
        n=len(scores); values=np.zeros((n,m),float); values[:,[first,second]]=scores
        mask=np.zeros((n,m),bool); mask[:,[first,second]]=True
        eligible=mask.copy()
        if hall: eligible[:]=False; eligible[:,first]=True
        return AllocationProblem(scores=values,available=mask,student_ids=tuple(f'synthetic-{i}' for i in range(n)),
            advisor_ids=registry,capacities=equal_quotas(n,registry,selected),eligible=eligible,
            present=np.array([key in selected for key in registry],bool),
            student_features=np.zeros((n,k),np.float32),student_feature_known=np.zeros((n,k),bool),
            metadata={'scope':'synthetic_stress_only','case':name})
    base=make('2x2',[[.9,.8],[.7,.1]])
    missing=base.available.copy(); missing[:,second]=False
    shortage=make('quota',[[.9,.8],[.7,.1],[.2,.9]])
    quotas=shortage.capacities.copy(); quotas[first]=quotas[second]=1
    return {'synthetic_2x2':base,
            'synthetic_3x2':make('3x2',[[.9,.8],[.7,.1],[.2,.9]]),
            'synthetic_fixed_future':replace(base,fixed_assignments={'synthetic-1':selected[0]}),
            'synthetic_missing_profile':replace(base,available=missing,fixed_assignments=dict(base.fixed_assignments)),
            'synthetic_quota_shortage':replace(shortage,capacities=quotas,fixed_assignments=dict(shortage.fixed_assignments)),
            'synthetic_hall_conflict':make('hall',[[.9,.8],[.7,.1]],hall=True)}


def _evaluation_problems(suite,smoke):
    cases={'validation':suite['validation'],**_stress_problems(suite)}
    if not smoke: cases['test']=suite['test']
    return cases


def run_benchmark(output,*,total_timesteps=DECLARED_TIMESTEPS,seeds=RELEASE_SEEDS,smoke=False):
    if (type(total_timesteps) is not int or total_timesteps<1 or not seeds
            or len(set(seeds))!=len(seeds) or any(type(seed) is not int or seed<0 for seed in seeds)):
        raise ValueError('invalid_training_budget_or_seeds')
    output=Path(output).resolve(); suite=build_research_suite(output)
    groups=[set(p.student_ids) for p in suite['train']]
    train_ids=set().union(*groups); val_ids=set(suite['validation'].student_ids); test_ids=set(suite['test'].student_ids)
    if (any(a&b for i,a in enumerate(groups) for b in groups[i+1:]) or train_ids&val_ids or train_ids&test_ids or val_ids&test_ids):
        raise ValueError('training_holdout_overlap')
    torch.set_num_threads(1); torch.use_deterministic_algorithms(True)
    code_paths=[ROOT/path for path in ('src/domain/rebuild_matching.py','src/baselines/rebuild_baselines.py',
        'src/environment/rebuild_env.py','src/rl/rebuild_dqn.py','src/rl/rebuild_ppo.py',
        'src/data_pipeline/rebuild_cohorts.py','src/evaluation/rebuild_benchmark.py','requirements-rebuild-rl.txt')]
    code_hashes={str(path.relative_to(ROOT)): _digest(path) for path in code_paths}
    run_id=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
    run=output/'phase5_runs'/run_id; run.mkdir(parents=True,exist_ok=False)
    train_env=MatchingEnv(suite['train'],shuffle_students=True)
    contract={'scope':'research_only','feature_contract_sha256':suite['metadata']['feature_contract_sha256'],
        'phase4_run_id':suite['metadata']['phase4_run_id'],'state_contract':train_env.state_contract,
        'taxonomy_feature_order_sha256':suite['metadata']['taxonomy_feature_order_sha256'],
        'quota_policy_version':suite['metadata']['policy_version'],'reward_weights':train_env.reward_weights,
        'training_student_ids':sorted(train_ids),'training_problem_sha256':[record_hash(problem_payload(p)) for p in suite['train']]}
    cases=_evaluation_problems(suite,smoke)
    _write(run/'input_manifest.json',{'suite_metadata':suite['metadata'],'model_contract':contract,
        'training_problems':[problem_payload(p) for p in suite['train']],
        'evaluation_problems':{name:problem_payload(p) for name,p in cases.items()},
        'budget':{'timesteps_per_algorithm_seed':total_timesteps,'seeds':list(seeds),'smoke':smoke},
        'versions':{name:importlib.metadata.version(name) for name in ('torch','gymnasium','stable-baselines3','sb3-contrib','numpy','scipy')},
        'code_sha256':code_hashes})
    rows=[]; training=[]; reproducibility=[]
    for seed in seeds:
        print(f'Phase5 seed={seed} start steps={total_timesteps}',flush=True)
        env=MatchingEnv(suite['train'],shuffle_students=True)
        ppo=MaskedPPOAgent(env,seed=seed,contract=contract)
        started=time.perf_counter(); ppo_report=ppo.learn(total_timesteps)
        ppo_report['train_seconds']=time.perf_counter()-started
        ppo.save(run/f'checkpoints/ppo/seed-{seed}')
        ppo_loaded=MaskedPPOAgent.load(run/f'checkpoints/ppo/seed-{seed}',env,expected_contract=contract)
        print(f'Phase5 seed={seed} PPO trained actual={ppo_report["actual_timesteps"]}',flush=True)
        env2=MatchingEnv(suite['train'],shuffle_students=True)
        dqn=MaskedDQN(env2.observation_space.shape[0],env2.action_space.n,seed=seed,contract=contract)
        started=time.perf_counter(); dqn_report=dqn.learn(env2,total_timesteps)
        dqn_report['train_seconds']=time.perf_counter()-started
        dqn.save(run/f'checkpoints/dqn/seed-{seed}')
        dqn_loaded=MaskedDQN.load(run/f'checkpoints/dqn/seed-{seed}',expected_contract=contract)
        print(f'Phase5 seed={seed} DQN trained actual={dqn_report["actual_timesteps"]}',flush=True)
        for name,report in [('ppo',ppo_report),('dqn',dqn_report)]:
            report.update(algorithm=name,seed=seed)
            training.append(report); _write(run/f'training/{name}-seed-{seed}.json',report)
        for case,problem in cases.items():
            exact=solve(problem,'hungarian',seed)
            denominator=exact['metrics'].get('objective')
            for algorithm in ALGORITHMS:
                model={'ppo':ppo_loaded,'dqn':dqn_loaded}.get(algorithm)
                result=evaluate_problem(problem,algorithm,model=model,seed=seed)
                if result['status']=='feasible':
                    result['metrics']['optimality_ratio']=result['metrics']['objective']/denominator if denominator else None
                trace=result.pop('trace'); _write(run/f'traces/{case}/{algorithm}-seed-{seed}.json',trace)
                result.update(case=case,algorithm=algorithm,seed=seed)
                rows.append(result)
                if algorithm in ('ppo','dqn') and result['status']=='feasible':
                    original={'ppo':ppo,'dqn':dqn}[algorithm]
                    replay=evaluate_problem(problem,algorithm,model=original,seed=seed)
                    reproducibility.append({'case':case,'algorithm':algorithm,'seed':seed,
                        'assignments_match':result['assignments']==replay['assignments'],
                        'trace_match':trace==replay['trace']})
        _write(run/'progress.json',{'completed_seeds':[s for s in seeds if s<=seed],'last_seed':seed})
        print(f'Phase5 seed={seed} evaluations complete',flush=True)
    summary=summarize_seeds(rows)
    _write(run/'reports/per_seed_results.json',rows); _write(run/'reports/summary.json',summary)
    _write(run/'reports/reproducibility.json',reproducibility)
    infeasible_cases={'synthetic_hall_conflict','synthetic_missing_profile','synthetic_quota_shortage'}
    checks={'all_feasible_cases_complete':all(row['status']=='feasible' and row['metrics']['coverage']==1
                for row in rows if row['case'] not in infeasible_cases),
        'infeasible_cases_rejected':all(row['status']=='infeasible' and not row['assignments'] for row in rows if row['case'] in infeasible_cases),
        'zero_constraint_violations':all(row['metrics']['constraint_violations']==0 for row in rows),
        'zero_invalid_actions':all(row['invalid_action_count']==0 for row in rows),
        'all_traces_replay':all(row.get('trace_replay_verified',True) for row in rows),
        'checkpoint_inference_reproducible':all(row['assignments_match'] and row['trace_match'] for row in reproducibility),
        'no_train_holdout_overlap':not(train_ids&val_ids or train_ids&test_ids or val_ids&test_ids),
        'training_budget_completed':all(report['actual_timesteps']>=total_timesteps for report in training),
        'training_has_real_optimization':all(bool(report['losses']) for report in training),
        'training_all_135_rows_encountered':all(report['training_unique_student_count']==len(train_ids) for report in training),
        'five_predeclared_seeds':tuple(seeds)==RELEASE_SEEDS,
        'declared_budget_reached':total_timesteps>=DECLARED_TIMESTEPS,
        'code_unchanged_during_run':all(_digest(path)==code_hashes[str(path.relative_to(ROOT))] for path in code_paths)}
    try:
        final_binding=load_approved_features(output)['gate']
        checks['phase4_binding_unchanged']=final_binding['feature_contract_sha256']==contract['feature_contract_sha256'] and final_binding['run_id']==contract['phase4_run_id']
    except (ValueError,OSError): checks['phase4_binding_unchanged']=False
    blockers=[key for key,value in checks.items() if not value]
    if smoke: blockers.append('SMOKE_NOT_RELEASE_BENCHMARK')
    gate={'phase':5,'status':'verified' if not blockers else 'partial','can_start_phase6':not blockers,
        'run_id':run_id,'run_dir':str(run),'scope':'research_only_offline_technical_gate',
        'blocking_reasons':blockers,'phase4_run_id':contract['phase4_run_id'],
        'feature_contract_sha256':contract['feature_contract_sha256'],'model_contract_sha256':record_hash(contract),
        'seeds':list(seeds),'timesteps_per_algorithm_seed':total_timesteps,'algorithms':list(ALGORITHMS),
        'checks':checks,'operational_allocation_authorized':False,'models_promoted':False,
        'recommended_default':'hungarian','production_deployed':False,
        'limitations':['One source snapshot; three disjoint student groups, not three verified semesters.',
            'Non-temporal heldout student comparison; no measured future-semester/outcome benefit.',
            'No confirmed semester roster/eligibility supplied; catalog eligibility is a research assumption.',
            'No claim of convergence or RL superiority from this fixed CPU budget.'],
        'created_at':datetime.now(timezone.utc).isoformat()}
    _write(run/'reports/phase5_gate.json',gate)
    _write(run/'manifest.json',{'gate':gate,'artifacts':[{'path':path.relative_to(run).as_posix(),'sha256':_digest(path)}
        for path in sorted(run.rglob('*')) if path.is_file()]})
    _write(output/'reports/phase5_gate.json',gate)
    return gate
