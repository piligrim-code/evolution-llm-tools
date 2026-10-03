import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from alita import cli, manager
from alita.config import settings
from alita.execution_policy import require_unsafe_execution
from alita.mcp import code_runner
from alita.mcp.registry import ToolRegistry


@pytest.fixture(autouse=True)
def local_roots(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'runs_dir', str(tmp_path / 'runs'))
    monkeypatch.setattr(settings, 'tools_dir', str(tmp_path / 'tools'))
    monkeypatch.setattr(settings, 'allow_pip', False)


@pytest.mark.parametrize('value', [False, None, 'true', 1, {}, []])
def test_only_explicit_boolean_true_is_consent(value):
    with pytest.raises(PermissionError):
        require_unsafe_execution(value)


def test_new_generated_tool_denied_before_writes_or_subprocess(tmp_path, monkeypatch):
    spawn = Mock(side_effect=AssertionError('Unexpected process'))
    monkeypatch.setattr(code_runner.subprocess, 'check_call', spawn)
    monkeypatch.setattr(code_runner.subprocess, 'run', spawn)
    path = tmp_path / 'new_run'
    with pytest.raises(PermissionError):
        code_runner.run_generated_tool({'tool.py': 'print(2)'}, {'allow_unsafe_execution': True}, path)
    assert not path.exists()
    spawn.assert_not_called()


def test_saved_tool_and_low_level_executor_default_to_denied(tmp_path, monkeypatch):
    registry = ToolRegistry()
    spawn = Mock(side_effect=AssertionError('Unexpected process'))
    monkeypatch.setattr(code_runner.subprocess, 'run', spawn)
    with pytest.raises(PermissionError):
        registry.run('fixture', {})
    with pytest.raises(PermissionError):
        code_runner._execute_tool(tmp_path / '.venv', tmp_path, {})
    with pytest.raises(PermissionError):
        code_runner._install_requirements(tmp_path / '.venv', tmp_path)
    spawn.assert_not_called()


@pytest.mark.parametrize('name', ['../escape', '/absolute', 'C:drive', r'folder\child', '.', '', 'CON', 'a/b', 'a' * 65])
def test_registry_rejects_unsafe_names(name, tmp_path):
    registry = ToolRegistry(str(tmp_path / 'registry'))
    with pytest.raises(ValueError):
        registry.register(name, {'tool.py': 'print(2)'}, {})
    assert list(registry.root.iterdir()) == []


@pytest.mark.parametrize('filename', ['../escape.py', '/absolute.py', r'C:\escape.py', 'tool.json', '.venv/x', '__init__.py'])
def test_unexpected_script_names_cannot_write_outside_root(filename, tmp_path):
    path = tmp_path / 'run'
    with pytest.raises(ValueError):
        code_runner._write_scripts(path, {'tool.py': '', filename: 'unsafe'})
    assert not path.exists()


def test_registration_does_not_replace_existing_tool(tmp_path):
    registry = ToolRegistry(str(tmp_path / 'registry'))
    path = registry.register('fixture', {'tool.py': 'print(2)'}, {})
    with pytest.raises(FileExistsError):
        registry.register('fixture', {'tool.py': 'print(3)'}, {})
    assert (path / 'tool.py').read_text() == 'print(2)'


def test_linked_tool_directory_is_rejected(tmp_path):
    registry = ToolRegistry(str(tmp_path / 'registry'))
    outside = tmp_path / 'outside'
    outside.mkdir()
    link = registry.root / 'fixture'
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        if os.environ.get('ALITA_REQUIRE_SYMLINKS') == '1':
            pytest.fail('Symlink creation is required for this qualification')
        pytest.skip('Symlink creation unavailable on this host')
    with pytest.raises(ValueError):
        registry.register('fixture', {'tool.py': 'print(2)'}, {})
    assert list(outside.iterdir()) == []


def test_failed_tool_is_not_registered(tmp_path):
    with pytest.raises(ValueError, match='Failed execution'):
        code_runner.register_tool({'tool.py': ''}, {'name': 'bad'}, {'returncode': 1})
    assert not Path(settings.tools_dir).exists()


@pytest.mark.parametrize('required', [False, True])
def test_symlink_unavailability_is_a_failure_only_when_required(tmp_path, monkeypatch, required):
    monkeypatch.setattr(Path, 'symlink_to', Mock(side_effect=OSError('synthetic privilege unavailable')))
    monkeypatch.setenv('ALITA_REQUIRE_SYMLINKS', '1' if required else '0')
    expected = pytest.fail.Exception if required else pytest.skip.Exception
    with pytest.raises(expected):
        test_linked_tool_directory_is_rejected(tmp_path)


def test_model_metadata_cannot_grant_execution_permission(monkeypatch):
    response = {'need_tool': True, 'tool_idea': 'fixture', 'direct_answer': '', 'allow_unsafe_execution': True}
    monkeypatch.setattr(manager, 'OllamaClient', lambda **kwargs: SimpleNamespace(generate=lambda prompt, **options: json.dumps(response)))
    generate = Mock(side_effect=AssertionError('Must not generate executable code when blocked'))
    monkeypatch.setattr(manager, 'brainstorm_tools', generate)
    with pytest.raises(PermissionError):
        manager.code_react_loop('calculate this')
    generate.assert_not_called()
    assert not Path(settings.runs_dir).exists()
    assert not Path(settings.tools_dir).exists()


def test_direct_answer_requires_no_execution_consent(monkeypatch):
    response = {'need_tool': False, 'direct_answer': 'Synthetic answer'}
    monkeypatch.setattr(manager, 'OllamaClient', lambda **kwargs: SimpleNamespace(generate=lambda prompt, **options: json.dumps(response)))
    assert manager.code_react_loop('hello')['answer'] == 'Synthetic answer'
    assert not Path(settings.runs_dir).exists()


def test_opted_in_new_tool_runs_once_not_twice(monkeypatch):
    response = {'need_tool': True, 'tool_idea': 'fixture', 'direct_answer': ''}
    monkeypatch.setattr(manager, 'OllamaClient', lambda **kwargs: SimpleNamespace(generate=lambda prompt, **options: json.dumps(response)))
    monkeypatch.setattr(manager, 'brainstorm_tools', lambda **kwargs: {'name': 'fixture', 'args': [{'name': 'question'}]})
    monkeypatch.setattr(manager, 'propose_tool_scripts', lambda **kwargs: {'tool.py': 'print(2)', 'requirements.txt': ''})
    execute = Mock(return_value={'returncode': 0, 'stdout': '2\n', 'stderr': ''})
    monkeypatch.setattr(manager, 'run_generated_tool', execute)
    monkeypatch.setattr(ToolRegistry, 'run', Mock(side_effect=AssertionError('Duplicate execution')))
    result = manager.code_react_loop('calculate this', allow_unsafe_execution=True)
    assert result['used_tool'] == 'fixture'
    execute.assert_called_once()
    assert execute.call_args.kwargs['allow_unsafe_execution'] is True
    assert execute.call_args.kwargs['tool_args'] == {'question': 'calculate this'}


def test_dependency_installation_needs_separate_approval(tmp_path, monkeypatch):
    (tmp_path / 'requirements.txt').write_text('synthetic-package', encoding='utf-8')
    call = Mock(side_effect=AssertionError('Must not install dependencies'))
    monkeypatch.setattr(code_runner.subprocess, 'check_call', call)
    with pytest.raises(PermissionError, match='allow_pip'):
        code_runner._install_requirements(tmp_path / '.venv', tmp_path, allow_unsafe_execution=True)
    call.assert_not_called()


def test_cli_requires_opt_in_before_touching_saved_tools():
    result = CliRunner().invoke(cli.app, ['tool-run', 'fixture'])
    assert result.exit_code == 2
    assert 'disabled' in result.stdout
    assert not Path(settings.tools_dir).exists()


def test_cli_passes_opt_in_explicitly_and_does_not_reuse_it(monkeypatch):
    run = Mock(return_value={'answer': 'fixture', 'used_tool': None})
    monkeypatch.setattr(cli, 'code_react_loop', run)
    runner = CliRunner()
    first = runner.invoke(cli.app, ['run', 'hello', '--unsafe-exec'])
    assert first.exit_code == 0, first.stdout
    assert run.call_args.kwargs['allow_unsafe_execution'] is True
    second = runner.invoke(cli.app, ['run', 'hello'])
    assert second.exit_code == 0, second.stdout
    assert run.call_args.kwargs['allow_unsafe_execution'] is False


def test_explicit_opt_in_runs_only_the_reviewed_synthetic_fixture(tmp_path):
    script = (
        'import argparse, json\n'
        'parser = argparse.ArgumentParser()\n'
        'parser.add_argument("--json")\n'
        'args = json.loads(parser.parse_args().json)\n'
        'print(args["value"] * 2)\n'
    )
    result = code_runner.run_generated_tool(
        {'tool.py': script, 'requirements.txt': ''}, {'name': 'fixture'},
        tmp_path / 'run with spaces', tool_args={'value': 2}, allow_unsafe_execution=True,
    )
    assert result['returncode'] == 0
    assert result['stdout'].strip() == '4'
