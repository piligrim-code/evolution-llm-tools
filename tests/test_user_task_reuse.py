"""Reuse for user tasks: handwritten receipts and predetermined executor results; no model or Docker."""
import json

import pytest
from typer.testing import CliRunner

from alita import cli
from alita.catalog import CatalogError
from alita.review import ReviewStore
from alita.skill_index import decide_for_task, reuse_candidate
from alita.user_tasks import UserTaskSource
from tests.test_skill_index import stocked  # noqa: F401
from tests.test_user_tasks import IMAGE, no_provider, run_cases  # noqa: F401


def sum_task(**changes):
    document = {
        'format': 'toolwright-user-task-v1', 'id': 'basket-total',
        'instruction': 'Add up the integer prices in values and return the total.',
        'examples': [{'id': 'two', 'data': {'values': [3, 4]}, 'result': 7}],
        'held_out': [{'id': 'empty', 'data': {'values': []}, 'result': 0},
                     {'id': 'negative', 'data': {'values': [-2, 5]}, 'result': 3},
                     {'id': 'many', 'data': {'values': [1, 1, 1, 1]}, 'result': 4}],
    }
    document.update(changes)
    return document


def test_matching_contract_selects_a_version_without_consulting_held_out_cases(stocked):  # noqa: F811
    catalog, promoted = stocked
    decision = decide_for_task(catalog, UserTaskSource(sum_task()))
    assert decision['action'] == 'verify_reuse' and decision['held_out_consulted'] is False
    assert decision['selected']['name'] == promoted['integer-sum']['name']
    assert decision['estimated_cost'] == {'model_requests': 0, 'executions': 4}
    assert decision['signature'] == 'data{values:array}->integer'
    other_held_out = sum_task(held_out=[{'id': 'x', 'data': {'values': [9]}, 'result': 9},
                                        {'id': 'y', 'data': {'values': [8]}, 'result': 8},
                                        {'id': 'z', 'data': {'values': [7]}, 'result': 7}])
    again = decide_for_task(catalog, UserTaskSource(other_held_out))
    assert again['selected'] == decision['selected'] and again['candidates'] == decision['candidates']


def test_no_match_generates_and_mixed_example_contracts_are_refused(stocked):  # noqa: F811
    catalog, _ = stocked
    text = sum_task(examples=[{'id': 'word', 'data': {'text': 'a b'}, 'result': 2}],
                    held_out=[{'id': 'one', 'data': {'text': 'a'}, 'result': 1},
                              {'id': 'none', 'data': {'text': ''}, 'result': 0},
                              {'id': 'three', 'data': {'text': 'a b c'}, 'result': 3}])
    decision = decide_for_task(catalog, UserTaskSource(text))
    assert decision['action'] == 'generate' and decision['selected'] is None
    assert decision['estimated_cost'] == {'model_requests': 1, 'executions': 4}
    mixed = sum_task(examples=[{'id': 'two', 'data': {'values': [3, 4]}, 'result': 7},
                               {'id': 'float', 'data': {'values': [0.5]}, 'result': 0.5}])
    with pytest.raises(CatalogError, match='different_contracts'):
        decide_for_task(catalog, UserTaskSource(mixed))


def test_reuse_candidate_returns_checked_scripts_and_refuses_retired_versions(stocked):  # noqa: F811
    catalog, promoted = stocked
    name, version = promoted['median']['name'], promoted['median']['version']
    record, scripts = reuse_candidate(catalog, name, version)
    assert scripts == {'tool.py': '# median\n'} and record['execution_authorized'] is False
    plan = catalog.retire(name, version)
    catalog.retire(name, version, plan_digest=plan['plan_digest'], confirm=True)
    with pytest.raises(PermissionError, match='version_retired'):
        reuse_candidate(catalog, name, version)


def test_cli_reused_candidate_goes_through_admission_under_the_task_name(stocked, tmp_path, monkeypatch):  # noqa: F811
    catalog, promoted = stocked
    runner = CliRunner()
    task_file, candidate = tmp_path / 'task.json', tmp_path / 'reused.json'
    task_file.write_text(json.dumps(sum_task()))
    catalog_option = ['--catalog', str(catalog.path)]
    decided = runner.invoke(cli.app, ['task', 'reuse', str(task_file), *catalog_option])
    assert decided.exit_code == 0, decided.output
    selected = json.loads(decided.output)['selected']
    written = runner.invoke(cli.app, ['task', 'reuse-candidate', str(task_file), selected['name'],
                                      selected['version'], '--out', str(candidate), *catalog_option])
    assert written.exit_code == 0, written.output
    assert json.loads(candidate.read_text()) == {'tool.py': '# integer-sum\n'}
    store = ['--store', str(tmp_path / 'r2.sqlite3')]
    prepared = runner.invoke(cli.app, ['task', 'prepare', str(task_file), '--scripts', str(candidate),
                                       '--container-image', IMAGE, *store])
    assert prepared.exit_code == 0, prepared.output
    manifest = json.loads(prepared.output)
    answers = {case['id']: case['result'] for case in sum_task()['examples'] + sum_task()['held_out']}
    run_cases(ReviewStore(tmp_path / 'r2.sqlite3'), monkeypatch, manifest, answers)
    manifest_file = tmp_path / 'manifest.json'
    manifest_file.write_text(json.dumps(manifest))
    ledger = ['--ledger', str(tmp_path / 'a.sqlite3')]
    admitted = runner.invoke(cli.app, ['task', 'admit', str(task_file), str(manifest_file), *store, *ledger])
    assert admitted.exit_code == 0, admitted.output
    assert json.loads(admitted.output)['admitted'] is True
    promoted_task = runner.invoke(cli.app, ['task', 'promote', str(task_file), str(json.loads(admitted.output)['attempt']),
                                            *store, *ledger, '--catalog', str(tmp_path / 'v2.sqlite3'), '--yes'])
    assert promoted_task.exit_code == 0 and json.loads(promoted_task.output)['name'] == 'task_basket_total'
