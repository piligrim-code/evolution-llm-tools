"""Admission tests use predetermined executor results, never Docker or a model."""
import hashlib
import json
import sqlite3
from unittest.mock import Mock

import pytest

from alita.admission import AdmissionError, AdmissionLedger, prepare_admission_case
from alita.catalog import VersionCatalog
from alita.container_runner import ContainerPolicy
from alita.evaluation_corpus_v2 import corpus_digest, get_task
from alita.review import ReviewStore

IMAGE = 'sha256:' + 'a' * 64
SCRIPTS = {'tool.py': 'pass\n'}
TASK = 'integer-sum'


@pytest.fixture(autouse=True)
def no_provider(monkeypatch):
    provider = Mock(side_effect=AssertionError('Admission tests must not call a provider'))
    monkeypatch.setattr('alita.llm.OllamaClient.generate_result', provider)
    yield
    provider.assert_not_called()


def _result(value):
    output = json.dumps(value, sort_keys=True, separators=(',', ':'))
    raw = output.encode()
    return {'returncode': 0, 'stdout': output, 'stdout_sha256': hashlib.sha256(raw).hexdigest(),
            'stdout_bytes': len(raw), 'stderr': '', 'execution': 'container', 'outcome': 'exited'}


def run_task(reviews, monkeypatch, *, scripts=SCRIPTS, answer=None, skip=()):
    """Prepare, inspect, approve and execute every case once; return the assignments."""
    assignments = []
    for case in get_task(TASK)['cases']:
        prepared = prepare_admission_case(TASK, case['id'], scripts, ContainerPolicy(IMAGE), reviews)
        assert prepared['state'] == 'pending' and prepared['execution_authorized'] is False
        assignments.append({'case_id': case['id'], 'proposal_id': prepared['proposal_id']})
        if case['id'] in skip:
            continue
        value = case['expected'] if answer is None else answer(case)

        class Executor:
            def __init__(self, policy):
                self._attempted = self._cleanup_confirmed = False

            def run(self, scripts, args):
                self._attempted = self._cleanup_confirmed = True
                return _result(value)

        monkeypatch.setattr('alita.review.runner.ContainerExecutor', Executor)
        inspection = reviews.inspect(prepared['proposal_id'])
        reviews.approve(prepared['proposal_id'], inspection['digest'], confirm=True)
        assert reviews.execute_result(prepared['proposal_id']).receipt_saved is True
    return assignments


def held_out_ids():
    return [case['id'] for case in get_task(TASK)['cases'] if case['split'] == 'held-out']


def wrong_on(case_id):
    return lambda case: {'result': -999} if case['id'] == case_id else case['expected']


def test_correct_candidate_is_admitted_and_promoted_through_an_example_receipt(tmp_path, monkeypatch):
    reviews = ReviewStore(tmp_path / 'reviews.sqlite3')
    ledger = AdmissionLedger(tmp_path / 'admissions.sqlite3')
    summary = ledger.evaluate(reviews, TASK, run_task(reviews, monkeypatch), expected_corpus_sha256=corpus_digest())
    assert summary['admitted'] is True and summary['newly_recorded'] is True
    assert summary['held_out_passed'] == summary['held_out_total'] == 5
    assert set(summary['examples'].values()) == {'correct'}
    assert not any(case_id in json.dumps(summary) for case_id in held_out_ids())
    catalog = VersionCatalog(tmp_path / 'versions.sqlite3')
    promoted = ledger.promote(catalog, reviews, summary['attempt'], confirm=True)
    assert promoted['promoted'] is True and promoted['admission_attempt'] == summary['attempt']
    record = catalog.inspect(promoted['name'], promoted['version'])['record']
    assert record['document']['args'] == get_task(TASK)['cases'][0]['args']


def test_one_held_out_failure_refuses_admission_without_naming_the_case(tmp_path, monkeypatch):
    reviews = ReviewStore(tmp_path / 'reviews.sqlite3')
    ledger = AdmissionLedger(tmp_path / 'admissions.sqlite3')
    failing = held_out_ids()[2]
    summary = ledger.evaluate(reviews, TASK, run_task(reviews, monkeypatch, answer=wrong_on(failing)),
                              expected_corpus_sha256=corpus_digest())
    assert summary['admitted'] is False and summary['held_out_passed'] == 4
    assert failing not in json.dumps(summary)
    with pytest.raises(PermissionError, match='candidate_not_admitted'):
        ledger.promote(VersionCatalog(tmp_path / 'versions.sqlite3'), reviews, summary['attempt'], confirm=True)
    audit = ledger.inspect(summary['attempt'], include_held_out=True)
    assert audit['held_out'][failing] == 'incorrect' and audit['held_out_details_included'] is True


def test_example_failure_also_refuses_admission(tmp_path, monkeypatch):
    reviews = ReviewStore(tmp_path / 'reviews.sqlite3')
    ledger = AdmissionLedger(tmp_path / 'admissions.sqlite3')
    summary = ledger.evaluate(reviews, TASK, run_task(reviews, monkeypatch, answer=wrong_on('example')),
                              expected_corpus_sha256=corpus_digest())
    assert summary['admitted'] is False and summary['examples']['example'] == 'incorrect'
    assert summary['held_out_passed'] == 5


def test_rescoring_the_same_candidate_returns_the_first_decision_without_budget(tmp_path, monkeypatch):
    reviews = ReviewStore(tmp_path / 'reviews.sqlite3')
    ledger = AdmissionLedger(tmp_path / 'admissions.sqlite3', candidate_limit=1)
    first = ledger.evaluate(reviews, TASK, run_task(reviews, monkeypatch, answer=wrong_on(held_out_ids()[0])),
                            expected_corpus_sha256=corpus_digest())
    # A fresh run of the identical candidate cannot buy a second held-out look.
    again = ledger.evaluate(reviews, TASK, run_task(reviews, monkeypatch), expected_corpus_sha256=corpus_digest())
    assert again['newly_recorded'] is False and again['attempt'] == first['attempt']
    assert again['admitted'] is False
    assert ledger.budget(TASK)['candidates_used'] == 1


def test_distinct_candidates_are_budgeted_per_task(tmp_path, monkeypatch):
    reviews = ReviewStore(tmp_path / 'reviews.sqlite3')
    ledger = AdmissionLedger(tmp_path / 'admissions.sqlite3', candidate_limit=2)
    for index in range(2):
        assignments = run_task(reviews, monkeypatch, scripts={'tool.py': f'# candidate {index}\n'})
        assert ledger.evaluate(reviews, TASK, assignments, expected_corpus_sha256=corpus_digest())['newly_recorded']
    third = run_task(reviews, monkeypatch, scripts={'tool.py': '# candidate 2\n'})
    with pytest.raises(PermissionError, match='budget_exhausted'):
        ledger.evaluate(reviews, TASK, third, expected_corpus_sha256=corpus_digest())
    assert ledger.budget(TASK) == {'task_id': TASK, 'corpus_version': 'toolwright-eval-v2',
                                   'candidates_used': 2, 'candidate_limit': 2}


def test_incomplete_mixed_or_partial_evidence_is_refused_before_recording(tmp_path, monkeypatch):
    reviews = ReviewStore(tmp_path / 'reviews.sqlite3')
    ledger = AdmissionLedger(tmp_path / 'admissions.sqlite3')
    pending = run_task(reviews, monkeypatch, skip={held_out_ids()[0]})
    with pytest.raises(AdmissionError, match='finished_receipts'):
        ledger.evaluate(reviews, TASK, pending, expected_corpus_sha256=corpus_digest())
    complete = run_task(reviews, monkeypatch)
    other = run_task(reviews, monkeypatch, scripts={'tool.py': '# other\n'})
    mixed = complete[:-1] + other[-1:]
    with pytest.raises(AdmissionError, match='one_bound_candidate'):
        ledger.evaluate(reviews, TASK, mixed, expected_corpus_sha256=corpus_digest())
    with pytest.raises(AdmissionError, match='every_case'):
        ledger.evaluate(reviews, TASK, complete[:3], expected_corpus_sha256=corpus_digest())
    with pytest.raises(AdmissionError, match='duplicate'):
        ledger.evaluate(reviews, TASK, complete[:-1] + complete[:1], expected_corpus_sha256=corpus_digest())
    with pytest.raises(AdmissionError, match='corpus_mismatch'):
        ledger.evaluate(reviews, TASK, complete, expected_corpus_sha256='0' * 64)
    assert ledger.budget(TASK)['candidates_used'] == 0


def test_cli_runs_the_admission_flow_without_exposing_held_out_content(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from alita import cli

    reviews = ReviewStore(tmp_path / 'reviews.sqlite3')
    runner = CliRunner()
    listed = runner.invoke(cli.app, ['eval', 'admission-cases', TASK])
    assert listed.exit_code == 0 and '"values"' not in listed.output
    assert json.loads(listed.output)['cases'][3] == {'id': held_out_ids()[0], 'split': 'held-out'}
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'corpus_sha256': corpus_digest(), 'task_id': TASK,
                                    'assignments': run_task(reviews, monkeypatch)}))
    paths = ['--store', str(reviews.path), '--ledger', str(tmp_path / 'admissions.sqlite3')]
    evaluated = runner.invoke(cli.app, ['eval', 'admission-evaluate', str(manifest), *paths])
    assert evaluated.exit_code == 0, evaluated.output
    summary = json.loads(evaluated.output)
    assert summary['admitted'] is True and summary['held_out_details_included'] is False
    refused = runner.invoke(cli.app, ['eval', 'admission-promote', str(summary['attempt']), *paths,
                                      '--catalog', str(tmp_path / 'versions.sqlite3')])
    assert refused.exit_code != 0
    promoted = runner.invoke(cli.app, ['eval', 'admission-promote', str(summary['attempt']), *paths,
                                       '--catalog', str(tmp_path / 'versions.sqlite3'), '--yes'])
    assert promoted.exit_code == 0 and json.loads(promoted.output)['promoted'] is True
    budget = runner.invoke(cli.app, ['eval', 'admission-budget', TASK, '--ledger', str(tmp_path / 'admissions.sqlite3')])
    assert json.loads(budget.output)['candidates_used'] == 1


def test_ledger_is_append_only_and_promotion_needs_confirmation(tmp_path, monkeypatch):
    reviews = ReviewStore(tmp_path / 'reviews.sqlite3')
    path = tmp_path / 'admissions.sqlite3'
    ledger = AdmissionLedger(path)
    summary = ledger.evaluate(reviews, TASK, run_task(reviews, monkeypatch), expected_corpus_sha256=corpus_digest())
    with sqlite3.connect(path) as db:
        for statement in ('UPDATE attempts SET admitted=0', 'DELETE FROM attempts'):
            with pytest.raises(sqlite3.IntegrityError, match='immutable'):
                db.execute(statement)
    with pytest.raises(PermissionError, match='confirmation'):
        ledger.promote(VersionCatalog(tmp_path / 'versions.sqlite3'), reviews, summary['attempt'])
    assert 'held_out' not in ledger.inspect(summary['attempt'])
