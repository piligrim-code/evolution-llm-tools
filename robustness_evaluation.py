"""Approval-bound preparation and receipt scoring for robustness probes."""
from collections import Counter
import hashlib

from .contracts import json_object, tool_spec
from .output_contracts import validate_output
from .review import DOCUMENT_LIMIT, ReviewError, _digest, _json, _proposal_id
from .robustness_corpus import (ROBUSTNESS_VERSION, get_robustness_case,
                                list_robustness_cases, robustness_digest)

_INVALID_SENTINEL = 'TOOLWRIGHT_INVALID_INPUT_SENTINEL_V1'
_ARGUMENT_TYPES = {str: 'string', int: 'integer', float: 'number', bool: 'boolean',
                   dict: 'object', list: 'array'}


def _case_spec(case):
    kind = _ARGUMENT_TYPES.get(type(case['data']))
    if kind is None:
        raise ValueError('unsupported_robustness_argument_type')
    return tool_spec({'name': 'robustness_integer_sum',
                      'description': 'Validate integer-sum input and return its result.',
                      'args': [{'name': 'data', 'type': kind,
                                'description': 'JSON data value supplied to the task.'}]})


def _expected_contract(case):
    if case['class'] == 'valid':
        return {'kind': 'json-object-equals', 'expected': case['expected']}
    return {'kind': 'stdout-equals', 'expected': _INVALID_SENTINEL}


def prepare_robustness_case(case_id, scripts, policy, reviews):
    """Create one pending proposal; inspection and approval remain separate."""
    case = get_robustness_case(case_id)
    spec = _case_spec(case)
    args = {'data': case['data']}
    identifier = reviews.create(spec, scripts, args, policy,
                                output_contract=_expected_contract(case))
    return {'case_id': case_id, 'case_class': case['class'], 'proposal_id': identifier,
            'robustness_version': ROBUSTNESS_VERSION, 'robustness_sha256': robustness_digest(),
            'state': 'pending', 'execution_authorized': False}


def _score_case(db, reviews, case, identifier):
    base = {'case_id': case['id'], 'case_class': case['class'], 'proposal_id': identifier,
            'candidate_sha256': None}
    if identifier is None:
        return {**base, 'status': 'missing'}, None
    try:
        row, doc, _ = reviews._load(db, identifier)
    except (ValueError, PermissionError):
        return {**base, 'status': 'unavailable'}, None
    expected_spec = _case_spec(case)
    expected_args = {'data': case['data']}
    contract = _expected_contract(case)
    if (doc.get('version') != 2 or _json(doc['spec']) != _json(expected_spec)
            or _json(doc['args']) != _json(expected_args)
            or _json(doc['output_contract']) != _json(contract)):
        return {**base, 'status': 'binding_mismatch'}, None
    candidate_sha = _digest(_json({'scripts': doc['scripts'], 'policy': doc['policy']}))
    base['candidate_sha256'] = candidate_sha
    if row['state'] == 'claimed':
        return {**base, 'status': 'indeterminate'}, None
    if row['state'] in ('pending', 'approved', 'cancelled'):
        return {**base, 'status': 'not_run'}, None
    if row['state'] != 'finished' or row['approval'] != row['digest'] or row['result'] is None:
        return {**base, 'status': 'invalid_receipt'}, None
    try:
        result = json_object(row['result'], limit=DOCUMENT_LIMIT)
    except ValueError:
        return {**base, 'status': 'invalid_receipt'}, None
    if 'error' in result:
        status = 'cleanup_unknown' if result['error'] == 'cleanup_unconfirmed' else 'execution_failed'
        return {**base, 'status': status}, None
    if result.get('execution') != 'container' or type(result.get('returncode')) is not int:
        return {**base, 'status': 'invalid_receipt'}, None
    validation = validate_output(contract, result)
    if result.get('output_validation') != validation:
        return {**base, 'status': 'invalid_receipt'}, None
    if result.get('outcome') == 'timeout':
        return {**base, 'status': 'timeout'}, None
    if result.get('outcome') != 'exited':
        return {**base, 'status': 'execution_failed'}, None
    if case['class'] == 'valid':
        if validation['status'] == 'passed':
            return {**base, 'status': 'correct'}, None
        if validation['reason'] == 'output_mismatch':
            return {**base, 'status': 'incorrect'}, None
        return {**base, 'status': 'execution_failed'}, None
    if result['returncode'] == 0:
        return {**base, 'status': 'invalid_input_accepted'}, None
    stdout = result.get('stdout')
    stdout_bytes = result.get('stdout_bytes')
    stdout_digest = result.get('stdout_sha256')
    stderr = result.get('stderr')
    if (type(stdout) is not str or stdout != '' or type(stdout_bytes) is not int or stdout_bytes != 0
            or stdout_digest != hashlib.sha256(b'').hexdigest()):
        return {**base, 'status': 'unclean_rejection'}, None
    # print(..., file=sys.stderr) ends with one line terminator; allow exactly that.
    line = stderr
    if type(line) is str:
        line = line[:-2] if line.endswith('\r\n') else line[:-1] if line.endswith('\n') else line
    try:
        stderr_size = len(line.encode('utf-8')) if type(line) is str else 0
    except UnicodeError:
        stderr_size = 257
    if (type(line) is not str or not line.strip() or stderr_size > 256
            or '\n' in line or '\r' in line
            or 'traceback' in line.casefold() or 'file "' in line.casefold()):
        return {**base, 'status': 'unclean_rejection'}, None
    return {**base, 'status': 'clean_rejection'}, line


def score_robustness_run(reviews, assignments, *, expected_robustness_sha256):
    """Score existing receipts only; never prepares, approves, or executes proposals."""
    if expected_robustness_sha256 != robustness_digest():
        raise ValueError('robustness_corpus_mismatch')
    cases = [get_robustness_case(summary['id']) for summary in list_robustness_cases()]
    if type(assignments) is not list or len(assignments) > len(cases):
        raise ValueError('robustness_assignment_limit')
    selected, seen = {}, set()
    for entry in assignments:
        if type(entry) is not dict or set(entry) != {'case_id', 'proposal_id'}:
            raise ValueError('invalid_robustness_assignment')
        case = get_robustness_case(entry['case_id'])
        identifier = _proposal_id(entry['proposal_id'])
        if case['id'] in selected or identifier in seen:
            raise ValueError('duplicate_robustness_assignment')
        selected[case['id']] = identifier
        seen.add(identifier)
    rows, messages = [], {}
    with reviews._connection() as db:
        db.execute('BEGIN')
        for case in cases:
            row, message = _score_case(db, reviews, case, selected.get(case['id']))
            rows.append(row)
            if message is not None:
                messages[case['id']] = message
    identities = {row['candidate_sha256'] for row in rows if row['candidate_sha256'] is not None}
    if len(identities) > 1:
        for row in rows:
            row['individual_status'] = row['status']
            row['status'] = 'inconsistent_candidate'
    elif len(identities) == 1:
        invalid_rows = [row for row in rows if row['case_class'] == 'invalid']
        if (all(row['status'] == 'clean_rejection' for row in invalid_rows)
                and len({messages[row['case_id']] for row in invalid_rows}) > 1):
            for row in invalid_rows:
                row['status'] = 'inconsistent_rejection_message'
    counts = dict(Counter(row['status'] for row in rows))
    valid_total = sum(row['case_class'] == 'valid' for row in rows)
    invalid_total = len(rows) - valid_total
    passed = (valid_total == 4 and invalid_total == 7
              and all(row['status'] == 'correct' for row in rows if row['case_class'] == 'valid')
              and all(row['status'] == 'clean_rejection' for row in rows if row['case_class'] == 'invalid'))
    for row in rows:
        row.pop('candidate_sha256', None)
    return {'robustness_version': ROBUSTNESS_VERSION, 'robustness_sha256': robustness_digest(),
            'cases_total': len(rows), 'valid_cases_total': valid_total, 'invalid_cases_total': invalid_total,
            'status_counts': counts, 'robustness_passed': passed,
            'observed_candidate_count': len(identities),
            'candidate_consistency': 'unobserved' if not identities else
            'consistent' if len(identities) == 1 else 'inconsistent',
            'content_included': False, 'cases': rows}
