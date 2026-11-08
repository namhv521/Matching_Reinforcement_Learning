"""Use real survey preferences; never turn registration status into a rejection."""
from __future__ import annotations

import copy
import json
import re
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.data_pipeline.review_decisions import record_hash
from src.features.fresh_suite import digest, write_json
from src.features.semester_suite import VERSIONS, read_csv


def timestamp(value):
    result = datetime.fromisoformat(value)
    return result.replace(tzinfo=ZoneInfo('Asia/Ho_Chi_Minh')) if result.tzinfo is None else result


def declared_term(value):
    text = unicodedata.normalize('NFC', str(value or '')).casefold()
    years = re.search(r'(20\d{2})\s*[-–]\s*20\d{2}', text)
    if not years:
        return None
    year = years[1]
    if re.search(r'(?:kỳ|kì)\s*(?:3|iii)\b|kỳ\s*hè', text):
        return year + '.3'
    if re.search(r'(?:kỳ|kì)\s*(?:2|ii)\b|mùa\s*xuân', text):
        return year + '.2'
    if re.search(r'(?:kỳ|kì)\s*(?:1|i)\b|(?:mùa|kỳ|kì)\s*thu', text):
        return year + '.1'
    return None


def select_rows(rows, train_ids, cutoff, term):
    latest, audit = {}, Counter()
    limit = timestamp(cutoff)
    for row in rows:
        sid = row['student_id']
        if sid not in train_ids:
            audit['not_in_train'] += 1
            continue
        try:
            observed = timestamp(row['timestamp'])
        except (TypeError, ValueError):
            audit['missing_timestamp'] += 1
            continue
        if observed > limit:
            audit['future_rows'] += 1
            continue
        declared = declared_term(row.get('declared_term'))
        if declared and declared != term:
            audit['declared_term_mismatch'] += 1
        if sid in latest:
            audit['superseded_or_repeated_rows'] += 1
            if (observed, row['source_row']) <= (timestamp(latest[sid]['timestamp']), latest[sid]['source_row']):
                continue
        latest[sid] = row
    return [latest[sid] for sid in sorted(latest)], dict(audit)


def name_key(value):
    value = re.sub(r'^(?:(?:PGS|GS|TS|ThS|CN|Cô|Thầy)[.\s]*)+', '', str(value), flags=re.I)
    value = unicodedata.normalize('NFD', value.casefold().replace('đ', 'd'))
    return re.sub(r'[^a-z]+', ' ', ''.join(c for c in value if not unicodedata.combining(c))).strip()


def bind(data, output, version, index, rows, changes, *, receipt_only=False, no_new_feedback=False,
         signal_type='student_preference', provenance='real_survey_ranked_preference', available_at=None):
    spec = data['round']
    source = output / version / f'R{index}-source.json'
    signal_id = f'SURVEY-{version}-R{index}-' + record_hash({'rows': rows, 'changes': changes})[:12]
    write_json(source, {'signal_id': signal_id, 'scope': 'real_survey_source_with_retrospective_document_features',
                        'records': rows, 'changes': changes, 'receipt_only': receipt_only,
                        'no_new_feedback': no_new_feedback,
                        'registration_semantics': 'self_reported_status_not_verified_advisor_acceptance_or_rejection',
                        'provenance': provenance})
    if rows:
        spec['signals'].append({'signal_id': signal_id,
            'type': 'initial_source' if receipt_only else signal_type,
            'source_path': str(source), 'source_sha256': digest(source),
            'available_at': available_at or max(timestamp(r['timestamp']) for r in rows).isoformat(),
            'available_at_basis': ('cohort_event_upper_bound_proxy' if available_at
                                  else 'recorded_form_timestamp_edit_history_not_available'),
            'review_status': 'source_verified' if receipt_only else 'verified',
            'provenance': 'real_survey_registration_receipt_no_eligibility_effect' if receipt_only else provenance})
    snapshot = json.loads(Path(spec['snapshot_path']).read_text(encoding='utf-8'))
    snapshot.update(training_problem_sha256=[record_hash(p) for p in data['train']],
                    validation_problem_sha256=record_hash(data['validation']),
                    signal_ids=[s['signal_id'] for s in spec['signals']],
                    applied_signal_source_sha256={} if receipt_only or no_new_feedback else {signal_id: digest(source)})
    path = output / version / f'R{index}-snapshot.json'
    write_json(path, snapshot)
    spec.update(snapshot_path=str(path), snapshot_sha256=digest(path), round_index=index,
                signal_state_sha256=record_hash([s['signal_id'] for s in spec['signals']]))
    if receipt_only or no_new_feedback:
        spec['control'] = 'extra_steps_no_new_signal'
    else:
        spec.pop('control', None)
    data['experiment_scope'] = 'real_survey_registration_status_not_invented_advisor_response'
    data['feedback_note'] = ('no_new_feedback_optimization_only' if no_new_feedback else
                             'registration_status_receipt_only_no_constraint_change' if receipt_only else 'real_ranked_preferences')
    write_json(output / version / f'R{index}.json', data)


def supervision_outcome_changes(data, links):
    changes = []
    for problem in data['train']:
        for link in links:
            if link['student_id'] not in problem['student_ids'] or link['advisor_id'] not in problem['advisor_ids']:
                continue
            student = problem['student_ids'].index(link['student_id'])
            advisor = problem['advisor_ids'].index(link['advisor_id'])
            for field, value in (('preferences', 1.0), ('preference_known', True)):
                old = problem[field][student][advisor]
                if old != value:
                    changes.append({'student_id': link['student_id'], 'advisor_id': link['advisor_id'],
                                    'field': field, 'old': old, 'new': value})
                    problem[field][student][advisor] = value
    return changes


def prepare_feedback(suites, survey, output, *, inputs, allow_empty=False):
    suites, survey, output, inputs = map(lambda p: Path(p).resolve(), (suites, survey, output, inputs))
    if output.exists():
        raise FileExistsError('fresh_survey_feedback_output_required')
    exported = json.loads(survey.read_text(encoding='utf-8'))
    if digest(exported['source_path']) != exported['source_sha256']:
        raise ValueError('original_survey_hash_mismatch')
    roster = read_csv(inputs / '2024/advisors_profile.csv')
    names = {name_key(r['name']): r['advisor_id'] for r in roster}
    # One observed survey spelling omits Thi; this is an explicit reviewed alias.
    full = name_key('Tống Thị Hảo Tâm')
    if full in names:
        names[name_key('Tống Hảo Tâm')] = names[full]
    output.mkdir(parents=True)
    reports = []
    for version, term in VERSIONS.items():
        data = json.loads((suites / version / 'suite.json').read_text(encoding='utf-8'))
        original = copy.deepcopy(data)
        train_ids = {sid for p in data['train'] for sid in p['student_ids']}
        selected, audit = select_rows(exported['rows'], train_ids, data['round']['cutoff_timestamp'], term)
        link_rows = read_csv(inputs / term / 'student_advisor_links.csv')
        outcome_rows = [row for row in link_rows if row.get('student_id') in train_ids
                        and row.get('status') == 'matched_needs_review' and row.get('advisor_id')]
        changes, unknown_names = [], Counter()
        for p in data['train']:
            for row in selected:
                if row['student_id'] not in p['student_ids']:
                    continue
                i = p['student_ids'].index(row['student_id'])
                seen = set()
                for rank, field in enumerate(('priority_1','priority_2','priority_3'),1):
                    name = row.get(field, '')
                    if not name:
                        continue
                    aid = names.get(name_key(name))
                    if aid is None:
                        unknown_names[name] += 1
                        continue
                    if aid in seen:
                        continue
                    seen.add(aid)
                    j = p['advisor_ids'].index(aid)
                    value = (4-rank)/3
                    for target, new in (('preferences',value),('preference_known',True)):
                        old = p[target][i][j]
                        if old != new:
                            changes.append({'student_id': row['student_id'], 'advisor_id': aid,
                                            'field': target,'old':old,'new':new})
                            p[target][i][j] = new
        entry = {'version':version,'semester_id':term,'train_students':len(train_ids),'matched_survey_students':len(selected),
                 'applied_preference_changes':len(changes),'audit':audit,'unknown_advisor_names':dict(unknown_names),
                 'r2_signal_students':len({r['student_id'] for r in changes}),
                 'r3_outcome_students':len({r['student_id'] for r in outcome_rows}),
                 'registration_status_counts':dict(Counter(r['registration_status'] for r in selected if str(r.get('registration_status') or '').strip()))}
        if not changes and not allow_empty:
            entry.update(status='waiting_for_historical_feedback_or_permission_for_optimization_only')
            reports.append(entry)
            continue
        bind(data,output,version,2,selected if changes else [],changes,no_new_feedback=not bool(changes))
        assert data['validation'] == original['validation']
        r3_changes = supervision_outcome_changes(data, outcome_rows)
        bind(data, output, version, 3, outcome_rows, r3_changes,
             no_new_feedback=not bool(r3_changes), signal_type='verified_outcome',
             provenance='historical_thesis_supervision_outcome_proxy_not_independent_advisor_acceptance',
             available_at=data['round']['cutoff_timestamp'])
        entry.update(status='ready', registration_status_effect='not_used_as_advisor_acceptance',
                     r3_effect='historical_supervision_outcome_proxy_preference_only_no_eligibility_change')
        reports.append(entry)
    report = {'schema_version':'survey-feedback/1','source_path':str(survey),'source_sha256':digest(survey),
              'xlsx_source_sha256':exported['source_sha256'],'source_rows':len(exported['rows']),
              'allow_empty_optimization_only':allow_empty,'mock_feedback_created':False,
              'missing_signal_policy':'skip_missing_information_keep_entire_cohort',
              'holdout_feedback_created':False,'versions':reports,'ready':all(r['status']=='ready' for r in reports)}
    write_json(output/'readiness.json',report)
    write_json(output/'manifest.json',{'artifacts':{p.relative_to(output).as_posix():digest(p) for p in output.rglob('*') if p.is_file()}})
    return report
