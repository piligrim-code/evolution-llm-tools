"""Generalization CLI end to end: handwritten replies and predetermined executor results; no model or Docker."""
import json

from typer.testing import CliRunner

from alita import cli
from alita.generalization import record_generalization
from alita.review import ReviewStore
from tests.test_generalization import DOC, SOURCE, family, generalized_reply, max_task
from tests.test_user_tasks import IMAGE, no_provider, run_cases  # noqa: F401

runner = CliRunner()


def invoke(*args):
    result = runner.invoke(cli.app, list(args))
    return result.exit_code, result.output


def write_generalization(tmp_path, name, source):
    members = family()
    record, text = record_generalization(members, generalized_reply(members, source))
    assert text is not None
    (tmp_path / f'{name}.record.json').write_text(json.dumps(record))
    (tmp_path / f'{name}.scripts.json').write_text(json.dumps({'tool.py': text}))
    return str(tmp_path / f'{name}.record.json'), str(tmp_path / f'{name}.scripts.json')


def admit_all(tmp_path, monkeypatch, record, scripts, members, paths, *, wrong=None):
    attempts = []
    for key in ('max', 'sum'):
        code, output = invoke('general', 'prepare', record, key, *members, '--scripts', scripts,
                              '--container-image', IMAGE, *paths[:2])
        assert code == 0, output
        manifest = json.loads(output)
        manifest_file = tmp_path / f'{key}.{len(attempts)}.manifest.json'
        manifest_file.write_text(json.dumps(manifest))
        task = family()[0 if key == 'sum' else 1].task
        answers = {case['id']: case['expected']['result'] for case in task['cases']}
        if wrong == key:
            answers[task['cases'][-1]['id']] = -999
        run_cases(ReviewStore(paths[1]), monkeypatch, manifest, answers)
        code, output = invoke('general', 'admit', record, key, str(manifest_file), *members, *paths)
        assert code == 0, output
        attempts += ['--attempt', f"{key}={json.loads(output)['attempt']}"]
    return attempts


def test_cli_family_flow_promotes_a_documented_general_tool(tmp_path, monkeypatch):
    task_file = tmp_path / 'max.json'
    task_file.write_text(json.dumps(max_task()))
    members = ['--member', 'sum=corpus:integer-sum', '--member', f'max={task_file}']
    code, output = invoke('general', 'families', *members, '--member', 'med=corpus:median')
    assert code == 0 and json.loads(output)['families'][0]['members'] == ['max', 'sum']
    code, output = invoke('general', 'prompt', *members)
    assert code == 0 and 'Variant max:' in json.loads(output)['prompt']
    record, scripts = write_generalization(tmp_path, 'g', SOURCE)
    paths = ['--store', str(tmp_path / 'r.sqlite3'), '--ledger', str(tmp_path / 'a.sqlite3')]
    attempts = admit_all(tmp_path, monkeypatch, record, scripts, members, paths)
    code, output = invoke('general', 'decide', record, *members, *attempts, *paths)
    assert code == 0, output
    assert json.loads(output)['admitted'] is True and 'held_out_details_included' in output
    code, output = invoke('general', 'promote', record, *members, *attempts, *paths,
                          '--catalog', str(tmp_path / 'v.sqlite3'), '--yes')
    assert code == 0, output
    assert json.loads(output)['name'] == 'general_reduce_values'


def test_cli_refuses_foreign_attempts_changed_members_and_mismatched_candidates(tmp_path, monkeypatch):
    task_file = tmp_path / 'max.json'
    task_file.write_text(json.dumps(max_task()))
    members = ['--member', 'sum=corpus:integer-sum', '--member', f'max={task_file}']
    paths = ['--store', str(tmp_path / 'r.sqlite3'), '--ledger', str(tmp_path / 'a.sqlite3')]
    record, scripts = write_generalization(tmp_path, 'g', SOURCE)
    other_doc = {**DOC, 'name': 'other_reduce', 'description': 'A different documented tool.'}
    other_record, other_scripts = write_generalization(
        tmp_path, 'h', 'import json\nimport sys\nTOOLWRIGHT_DOC = ' + repr(other_doc) + '\nprint(2)\n')
    foreign = admit_all(tmp_path, monkeypatch, other_record, other_scripts, members, paths)
    # Attempts admitted for another generalization cannot be promoted under this record.
    code, output = invoke('general', 'promote', record, *members, *foreign, *paths,
                          '--catalog', str(tmp_path / 'v.sqlite3'), '--yes')
    assert code != 0 and 'not_this_generalization' in output
    # A candidate whose documentation differs from the record is refused before any proposal.
    code, output = invoke('general', 'prepare', record, 'sum', *members, '--scripts', other_scripts,
                          '--container-image', IMAGE, '--store', str(tmp_path / 'r.sqlite3'))
    assert code != 0 and 'differs_from_record' in output
    # Editing a member task file after generation changes its digest.
    task_file.write_text(json.dumps(max_task(instruction='Return the largest integer in values, please.')))
    code, output = invoke('general', 'prepare', record, 'max', *members, '--scripts', scripts,
                          '--container-image', IMAGE, '--store', str(tmp_path / 'r.sqlite3'))
    assert code != 0 and 'members_changed' in output


def test_cli_decision_is_not_admitted_when_one_member_fails(tmp_path, monkeypatch):
    task_file = tmp_path / 'max.json'
    task_file.write_text(json.dumps(max_task()))
    members = ['--member', 'sum=corpus:integer-sum', '--member', f'max={task_file}']
    paths = ['--store', str(tmp_path / 'r.sqlite3'), '--ledger', str(tmp_path / 'a.sqlite3')]
    record, scripts = write_generalization(tmp_path, 'g', SOURCE)
    attempts = admit_all(tmp_path, monkeypatch, record, scripts, members, paths, wrong='max')
    code, output = invoke('general', 'decide', record, *members, *attempts, *paths)
    assert code == 0 and json.loads(output)['admitted'] is False
    code, output = invoke('general', 'promote', record, *members, *attempts, *paths,
                          '--catalog', str(tmp_path / 'v.sqlite3'), '--yes')
    assert code != 0 and 'not_admitted_on_every_member' in output
