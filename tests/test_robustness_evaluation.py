"""Receipt-scoring tests use predetermined executor results, never Docker or a model."""
import hashlib
import json

import pytest

from alita.container_runner import ContainerPolicy
from alita.review import ReviewStore
from alita.robustness_corpus import get_robustness_case, list_robustness_cases, robustness_digest
from alita.robustness_evaluation import prepare_robustness_case, score_robustness_run


IMAGE = 'sha256:' + 'a' * 64
SCRIPTS = {'tool.py': 'pass\n'}


def _result(case, *, stderr='Invalid input', invalid_exit=2):
    if case['class'] == 'valid':
        output = json.dumps(case['expected'], sort_keys=True, separators=(',', ':'))
        raw = output.encode()
        return {'returncode': 0, 'stdout': output, 'stdout_sha256': hashlib.sha256(raw).hexdigest(),
                'stdout_bytes': len(raw), 'stderr': '', 'execution': 'container', 'outcome': 'exited'}
    raw = b''
    return {'returncode': invalid_exit, 'stdout': '', 'stdout_sha256': hashlib.sha256(raw).hexdigest(),
            'stdout_bytes': 0, 'stderr': stderr, 'execution': 'container', 'outcome': 'exited'}


def _prepare_all(reviews, *, scripts=SCRIPTS):
    assignments = []
    for summary in list_robustness_cases():
        prepared = prepare_robustness_case(summary['id'], scripts, ContainerPolicy(IMAGE), reviews)
        assert prepared['state'] == 'pending' and prepared['execution_authorized'] is False
        assignments.append({'case_id': summary['id'], 'proposal_id': prepared['proposal_id']})
    return assignments


def _approve_and_execute_all(reviews, monkeypatch, assignments, *, stderr_by_case=None):
    receipts = []
    for assignment in assignments:
        case = get_robustness_case(assignment['case_id'])
        stderr = (stderr_by_case or {}).get(case['id'], 'Invalid input')

        class Executor:
            def __init__(self, policy):
                self._attempted = False
                self._cleanup_confirmed = False

            def run(self, scripts, args):
                self._attempted = True
                self._cleanup_confirmed = True
                return _result(case, stderr=stderr)

        monkeypatch.setattr('alita.review.runner.ContainerExecutor', Executor)
        inspection = reviews.inspect(assignment['proposal_id'])
        reviews.approve(assignment['proposal_id'], inspection['digest'], confirm=True)
        outcome = reviews.execute_result(assignment['proposal_id'])
        assert outcome.receipt_saved is True
        receipts.append(outcome)
    return receipts


def test_prepare_is_pending_and_uses_matching_top_level_json_type(tmp_path):
    reviews = ReviewStore(tmp_path / 'reviews.sqlite3')
    array_case = prepare_robustness_case('non-object-data', SCRIPTS, ContainerPolicy(IMAGE), reviews)
    document = reviews.inspect(array_case['proposal_id'])['document']
    assert document['spec']['args'][0]['type'] == 'array'
    assert document['args'] == {'data': [1, 2]}
    assert document['output_contract'] == {'kind': 'stdout-equals',
                                           'expected': 'TOOLWRIGHT_INVALID_INPUT_SENTINEL_V1'}
    pending = score_robustness_run(reviews, [], expected_robustness_sha256=robustness_digest())
    assert pending['robustness_passed'] is False
    assert pending['status_counts'] == {'missing': 11}


def test_receipt_bound_score_requires_explicit_approval_and_clean_fixed_rejections(tmp_path, monkeypatch):
    reviews = ReviewStore(tmp_path / 'reviews.sqlite3')
    assignments = _prepare_all(reviews)
    outcomes = _approve_and_execute_all(reviews, monkeypatch, assignments)
    assert len(outcomes) == 11
    assert all(outcome.approval_consumed is True for outcome in outcomes)
    report = score_robustness_run(reviews, assignments, expected_robustness_sha256=robustness_digest())
    assert report['robustness_passed'] is True
    assert report['status_counts'] == {'correct': 4, 'clean_rejection': 7}
    assert report['content_included'] is False


def test_single_trailing_line_terminator_is_a_clean_rejection(tmp_path, monkeypatch):
    reviews = ReviewStore(tmp_path / 'reviews.sqlite3')
    assignments = _prepare_all(reviews)
    invalid = [s['id'] for s in list_robustness_cases() if s['class'] == 'invalid']
    terminators = ['\n', '\r\n', '']
    messages = {case_id: 'Invalid input' + terminators[index % 3] for index, case_id in enumerate(invalid)}
    _approve_and_execute_all(reviews, monkeypatch, assignments, stderr_by_case=messages)
    report = score_robustness_run(reviews, assignments, expected_robustness_sha256=robustness_digest())
    assert report['robustness_passed'] is True
    assert report['status_counts'] == {'correct': 4, 'clean_rejection': 7}


def test_different_invalid_error_messages_do_not_pass(tmp_path, monkeypatch):
    reviews = ReviewStore(tmp_path / 'reviews.sqlite3')
    assignments = _prepare_all(reviews)
    invalid = [case['id'] for case in map(get_robustness_case, [s['id'] for s in list_robustness_cases()])
               if case['class'] == 'invalid']
    messages = {case_id: f'Invalid input {index}' for index, case_id in enumerate(invalid)}
    _approve_and_execute_all(reviews, monkeypatch, assignments, stderr_by_case=messages)
    report = score_robustness_run(reviews, assignments, expected_robustness_sha256=robustness_digest())
    assert report['robustness_passed'] is False
    assert report['status_counts'] == {'correct': 4, 'inconsistent_rejection_message': 7}
    assert all('Invalid input' not in str(case) for case in report['cases'])


def test_traceback_nonzero_exit_and_zero_exit_are_not_clean_rejections(tmp_path, monkeypatch):
    for index, (stderr, exit_code, expected_status) in enumerate([
            ('Traceback (most recent call last):\n  File "tool.py"', 1, 'unclean_rejection'),
            ('Invalid\ninput\n', 1, 'unclean_rejection'),
            ('Invalid input', 0, 'invalid_input_accepted')]):
        reviews = ReviewStore(tmp_path / f'{index}.sqlite3')
        assignments = _prepare_all(reviews)
        for assignment in assignments:
            case = get_robustness_case(assignment['case_id'])

            class Executor:
                def __init__(self, policy):
                    self._attempted = False
                    self._cleanup_confirmed = False

                def run(self, scripts, args):
                    self._attempted = True
                    self._cleanup_confirmed = True
                    return _result(case, stderr=stderr, invalid_exit=exit_code)

            monkeypatch.setattr('alita.review.runner.ContainerExecutor', Executor)
            inspection = reviews.inspect(assignment['proposal_id'])
            reviews.approve(assignment['proposal_id'], inspection['digest'], confirm=True)
            reviews.execute_result(assignment['proposal_id'])
        report = score_robustness_run(reviews, assignments, expected_robustness_sha256=robustness_digest())
        assert report['robustness_passed'] is False
        assert report['status_counts'][expected_status] == 7


def test_invalid_manifests_and_corpus_drift_are_rejected(tmp_path):
    reviews = ReviewStore(tmp_path / 'reviews.sqlite3')
    with pytest.raises(ValueError, match='robustness_corpus_mismatch'):
        score_robustness_run(reviews, [], expected_robustness_sha256='0' * 64)
    with pytest.raises(ValueError, match='duplicate_robustness_assignment'):
        score_robustness_run(reviews, [{'case_id': 'empty-values', 'proposal_id': 'a' * 32},
                                       {'case_id': 'empty-values', 'proposal_id': 'b' * 32}],
                             expected_robustness_sha256=robustness_digest())
