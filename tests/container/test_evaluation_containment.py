"""Handwritten reference candidates against all literal corpus cases in real Docker."""
import os

import pytest

from alita import review
from alita.container_runner import ContainerExecutor, ContainerPolicy
from alita.evaluation import prepare_case, score_run
from alita.evaluation_corpus import corpus_digest, get_task
from alita.outcomes import ExecutionStatus
from alita.review import ReviewStore
from tests.evaluation_reference import BODIES, scripts_for

pytestmark = pytest.mark.skipif(os.environ.get('ALITA_CONTAINER_TESTS') != '1',
                               reason='requires explicit disposable Docker run')


@pytest.fixture
def owned(monkeypatch):
    instances = []

    def executor(policy):
        instance = ContainerExecutor(policy)
        instances.append(instance)
        return instance

    monkeypatch.setattr(review.runner, 'ContainerExecutor', executor)
    yield instances
    for instance in instances:
        assert instance._cleanup_confirmed is True
        assert not instance._docker('container', 'ls', '--all', '--quiet', '--filter',
                                     'label=io.alita.executor.owner=' + instance.owner).stdout.strip()


@pytest.mark.parametrize('task_id', list(BODIES))
def test_handwritten_reference_all_examples_and_heldout_cases(tmp_path, owned, task_id):
    store = ReviewStore(tmp_path / 'reviews.sqlite3')
    policy = ContainerPolicy(os.environ['ALITA_TEST_IMAGE'])
    entries = []
    for case in get_task(task_id)['cases']:
        prepared = prepare_case(task_id, case['id'], scripts_for(task_id), policy, store)
        identifier = prepared['proposal_id']
        assert store.execute_result(identifier).status is ExecutionStatus.REFUSED
        store.approve(identifier, store.inspect(identifier)['digest'], confirm=True)
        assert store.execute_result(identifier).status is ExecutionStatus.SUCCEEDED
        assert store.execute_result(identifier).status is ExecutionStatus.REFUSED
        entries.append({key: prepared[key] for key in ('task_id', 'case_id', 'proposal_id')})
    report = score_run(ReviewStore(store.path, read_only=True), entries, expected_corpus_sha256=corpus_digest())
    assert report['cases_correct'] == 3 and report['tasks_passed'] == 1
    assert report['splits']['held-out']['correct'] == 2
    assert report['status_counts'] == {'correct': 3, 'missing': 45}
    assert len(owned) == 3
