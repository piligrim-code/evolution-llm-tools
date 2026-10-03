"""Offline evaluation against reviewed receipts. No generation, approval or execution."""
from collections import Counter

from .contracts import json_object, tool_spec
from .evaluation_corpus import CORPUS_VERSION, corpus_digest, get_case, get_task, list_tasks, task_spec
from .output_contracts import _canonical_object, validate_output
from .review import DOCUMENT_LIMIT, _digest, _json, _proposal_id


def prepare_case(task_id, case_id, scripts, policy, reviews):
    task, case = get_case(task_id, case_id)
    identifier = reviews.create(task_spec(task), scripts, case['args'], policy,
                                output_contract={'kind': 'json-object-equals', 'expected': case['expected']})
    return {'task_id': task_id, 'case_id': case_id, 'proposal_id': identifier,
            'corpus_sha256': corpus_digest(), 'state': 'pending', 'execution_authorized': False}


def score_answer(task_id, case_id, answer):
    """Direct-answer semantic baseline only, never an execution receipt."""
    _, case = get_case(task_id, case_id)
    equal = _canonical_object(answer) == _canonical_object(case['expected'])
    return {'task_id': task_id, 'case_id': case_id, 'corpus_sha256': corpus_digest(),
            'baseline': 'supplied-direct-answer', 'status': 'correct' if equal else 'incorrect',
            'generation_provenance_verified': False, 'execution_verified': False}


def score_decision(task_id, decision):
    """Grade an explicit supplied policy label, not arbitrary refusal prose."""
    task = get_task(task_id)
    expected = ({'action': 'refuse', 'reason': task['reason']} if task['kind'] == 'refusal'
                else {'action': 'prepare'})
    equal = _canonical_object(decision) == _canonical_object(expected)
    return {'task_id': task_id, 'corpus_sha256': corpus_digest(),
            'status': 'correct' if equal else 'incorrect', 'kind': task['kind'],
            'generation_provenance_verified': False, 'execution_authorized': False}


def _case_score(db, reviews, task, case, identifier):
    base = {'task_id': task['id'], 'case_id': case['id'], 'split': case['split'],
            'proposal_id': identifier, 'candidate_sha256': None, 'limits': None,
            'measurements': {'generation_seconds': None, 'execution_seconds': None,
                             'peak_memory_bytes': None, 'tokens': None, 'stdout_bytes': None},
            'cleanup': 'not_recorded'}
    if identifier is None:
        return {**base, 'status': 'missing'}
    try:
        row, doc, _ = reviews._load(db, identifier)
    except (ValueError, PermissionError):
        return {**base, 'status': 'unavailable'}
    expected = {'kind': 'json-object-equals', 'expected': case['expected']}
    if (doc.get('version') != 2 or _json(doc['spec']) != _json(tool_spec(task_spec(task)))
            or _json(doc['args']) != _json(case['args']) or _json(doc['output_contract']) != _json(expected)):
        return {**base, 'status': 'binding_mismatch'}
    base['candidate_sha256'] = _digest(_json({'spec': doc['spec'], 'scripts': doc['scripts'], 'policy': doc['policy']}))
    base['limits'] = {key: doc['policy'][key] for key in ('image', 'timeout', 'memory_bytes', 'pids')}
    if row['state'] == 'claimed':
        return {**base, 'status': 'indeterminate'}
    if row['state'] in ('pending', 'approved', 'cancelled'):
        return {**base, 'status': 'not_run'}
    if row['state'] != 'finished' or row['approval'] != row['digest'] or row['result'] is None:
        return {**base, 'status': 'invalid_receipt'}
    try:
        result = json_object(row['result'], limit=DOCUMENT_LIMIT)
    except ValueError:
        return {**base, 'status': 'invalid_receipt'}
    if 'error' in result:
        if result['error'] == 'cleanup_unconfirmed':
            return {**base, 'status': 'cleanup_unknown', 'cleanup': 'unconfirmed'}
        return {**base, 'status': 'execution_failed'}
    if result.get('execution') != 'container' or type(result.get('returncode')) is not int:
        return {**base, 'status': 'invalid_receipt'}
    validation = validate_output(expected, result)
    if result.get('output_validation') != validation:
        return {**base, 'status': 'invalid_receipt'}
    if result.get('outcome') == 'timeout':
        return {**base, 'status': 'timeout'}
    if validation['status'] == 'not_checked':
        return {**base, 'status': 'execution_failed'}
    if validation['reason'] not in ('expected_output_matched', 'output_mismatch'):
        return {**base, 'status': 'invalid_receipt'}
    base['measurements']['stdout_bytes'] = result['stdout_bytes']
    return {**base, 'status': 'correct' if validation['status'] == 'passed' else 'incorrect'}


def score_run(reviews, assignments, *, expected_corpus_sha256):
    """Read one snapshot and score every runnable case, including missing cases."""
    if expected_corpus_sha256 != corpus_digest():
        raise ValueError('evaluation_corpus_mismatch')
    if type(assignments) is not list or len(assignments) > 48:
        raise ValueError('evaluation_assignment_limit')
    selected, seen = {}, set()
    for entry in assignments:
        if type(entry) is not dict or set(entry) != {'task_id', 'case_id', 'proposal_id'}:
            raise ValueError('invalid_evaluation_assignment')
        get_case(entry['task_id'], entry['case_id'])
        identifier = _proposal_id(entry['proposal_id'])
        key = entry['task_id'], entry['case_id']
        if key in selected or identifier in seen:
            raise ValueError('duplicate_evaluation_assignment')
        selected[key] = identifier
        seen.add(identifier)
    rows = []
    # Single snapshot prevents concurrent pruning from mixing receipt generations.
    with reviews._connection() as db:
        db.execute('BEGIN')
        for summary in list_tasks():
            if summary['kind'] != 'tool':
                continue
            task = get_task(summary['id'])
            current = [_case_score(db, reviews, task, case, selected.get((task['id'], case['id'])))
                       for case in task['cases']]
            identities = {row['candidate_sha256'] for row in current if row['candidate_sha256'] is not None}
            if len(identities) > 1:
                for row in current:
                    row['individual_status'] = row['status']
                    row['status'] = 'inconsistent_candidate'
            rows.extend(current)
    counts = dict(Counter(row['status'] for row in rows))
    splits = {split: {'correct': sum(row['status'] == 'correct' for row in rows if row['split'] == split),
                      'total': sum(row['split'] == split for row in rows)} for split in ('example', 'held-out')}
    tasks_passed = sum(all(row['status'] == 'correct' for row in rows if row['task_id'] == task['id'])
                       for task in list_tasks() if task['kind'] == 'tool')
    return {'corpus_version': CORPUS_VERSION, 'corpus_sha256': corpus_digest(),
            'cases_total': len(rows), 'cases_correct': counts.get('correct', 0), 'status_counts': counts,
            'splits': splits, 'tasks_total': 16, 'tasks_passed': tasks_passed,
            'refusal_tasks_total': 4, 'refusal_tasks_scored': 0,
            'generation_provenance_verified': False, 'content_included': False, 'cases': rows}
