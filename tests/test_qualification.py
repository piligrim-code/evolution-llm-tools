"""The qualification gate must reject incomplete or mismatched evidence."""
import importlib.util
import json
from pathlib import Path
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('qualification', ROOT / 'tools/qualify_wheel.py')
qualification = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qualification)


def report(tmp_path, contents):
    path = tmp_path / 'report.xml'
    path.write_text('<testsuites><testsuite>' + contents + '</testsuite></testsuites>', encoding='utf-8')
    return path


def case(classname='tests.test_demo', name='test_one', outcome=''):
    return f'<testcase classname="{classname}" name="{name}">{outcome}</testcase>'


def test_passing_report_counts_executed_cases(tmp_path):
    result = qualification.summarize_junit(report(tmp_path, case() + case(name='test_two')))
    assert result == {'passed': 2, 'skipped': 0, 'failures': 0, 'errors': 0,
                      'unexpected_skips': [], 'accepted': True}


@pytest.mark.parametrize('outcome', ['<failure/>', '<error/>', '<skipped/>'])
def test_failed_or_unexpectedly_skipped_cases_cannot_pass(tmp_path, outcome):
    result = qualification.summarize_junit(report(tmp_path, case() + case(name='bad', outcome=outcome)))
    assert not result['accepted']


def test_opt_in_container_skips_only_accepted_in_default_suite(tmp_path):
    path = report(tmp_path, case() + case('tests.container.test_demo', outcome='<skipped/>'))
    assert qualification.summarize_junit(path)['accepted']
    assert not qualification.summarize_junit(path, containers=True)['accepted']


def test_optional_local_symlink_skip_not_accepted_in_required_gate(tmp_path):
    path = report(tmp_path, case() + case('tests.test_execution_policy',
                                         'test_linked_tool_directory_is_rejected', '<skipped/>'))
    assert qualification.summarize_junit(path)['accepted']
    assert not qualification.summarize_junit(path, require_symlinks=True)['accepted']


def test_empty_or_all_skipped_report_is_not_a_pass(tmp_path):
    with pytest.raises(ValueError, match='empty_test_report'):
        qualification.summarize_junit(report(tmp_path, ''))
    result = qualification.summarize_junit(report(tmp_path, case('tests.container.test_demo', outcome='<skipped/>')))
    assert not result['accepted']


def test_environment_cannot_enable_docker_or_override_pytest():
    original = {'PATH': 'preserve', 'PYTHONPATH': 'other-source', 'PYTHONHOME': 'other-python',
                'PYTEST_ADDOPTS': '-k no_tests', 'PYTEST_PLUGINS': 'untrusted',
                'ALITA_CONTAINER_TESTS': '1', 'ALITA_TEST_IMAGE': 'unexpected',
                'ALITA_REQUIRE_SYMLINKS': '1', 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '0'}
    env = qualification.clean_environment(original)
    assert env == {'PATH': 'preserve', 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1'}
    assert qualification.clean_environment(original, require_symlinks=True)['ALITA_REQUIRE_SYMLINKS'] == '1'
    assert original['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] == '0'


@pytest.fixture
def artifact(tmp_path):
    source, installed = tmp_path / 'source', tmp_path / 'installed'
    source.mkdir()
    installed.mkdir()
    (source / 'mcp').mkdir()
    (source / 'pyproject.toml').write_text('[project]\nname="evolution-llm-tools"\nversion="0.1.0"\n')
    (source / '__init__.py').write_bytes(b'# synthetic\n')
    (installed / '__init__.py').write_bytes(b'# synthetic\n')
    prefix = 'evolution_llm_tools-0.1.0.dist-info/'
    entries = {prefix + name: b'' for name in ('WHEEL', 'RECORD', 'entry_points.txt', 'top_level.txt', 'licenses/LICENSE')}
    entries[prefix + 'METADATA'] = b'Name: evolution-llm-tools\nVersion: 0.1.0\n'
    entries['alita/__init__.py'] = b'# synthetic\n'
    return source, installed, tmp_path / 'synthetic.whl', entries


def write_wheel(path, entries):
    with zipfile.ZipFile(path, 'w') as archive:
        for name, value in entries.items():
            archive.writestr(name, value)


def test_artifact_matches_source_and_installed_bytes(artifact):
    source, installed, wheel, entries = artifact
    write_wheel(wheel, entries)
    result = qualification.verify_wheel(wheel, source, installed, '0.1.0')
    assert result['python_modules'] == 1 and result['entries'] == 7
    assert result['source_and_installed_bytes_match'] and len(result['sha256']) == 64
    assert str(source) not in json.dumps(result)


@pytest.mark.parametrize('change,error', [
    ('extra', 'unexpected_or_missing'), ('missing', 'unexpected_or_missing'),
    ('source', 'source_mismatch'), ('installed', 'installed_mismatch'),
    ('version', 'installed_version_mismatch'), ('metadata', 'metadata_mismatch'),
])
def test_artifact_drift_is_refused(artifact, change, error):
    source, installed, wheel, entries = artifact
    version = '0.1.0'
    if change == 'extra':
        entries['alita/private.sqlite3'] = b'synthetic'
    elif change == 'missing':
        del entries['alita/__init__.py']
    elif change == 'source':
        (source / '__init__.py').write_bytes(b'# changed\n')
    elif change == 'installed':
        (installed / '__init__.py').write_bytes(b'# changed\n')
    elif change == 'version':
        version = '9.0.0'
    elif change == 'metadata':
        entries['evolution_llm_tools-0.1.0.dist-info/METADATA'] = b'Name: other\nVersion: 0.1.0\n'
    write_wheel(wheel, entries)
    with pytest.raises(ValueError, match=error):
        qualification.verify_wheel(wheel, source, installed, version)


def test_duplicate_archive_names_are_refused(artifact):
    source, installed, wheel, entries = artifact
    write_wheel(wheel, entries)
    with pytest.warns(UserWarning, match='Duplicate name'):
        with zipfile.ZipFile(wheel, 'a') as archive:
            archive.writestr('alita/__init__.py', b'# different\n')
    with pytest.raises(ValueError, match='duplicate_wheel_entries'):
        qualification.verify_wheel(wheel, source, installed, '0.1.0')


def test_report_directory_must_not_overwrite_existing_evidence(tmp_path):
    existing = tmp_path / 'evidence'
    existing.mkdir()
    with pytest.raises(FileExistsError):
        qualification.main(['--wheel', str(tmp_path / 'unused.whl'), '--report-dir', str(existing)])


def test_report_directory_cannot_dirty_source_tree():
    with pytest.raises(SystemExit):
        qualification.main(['--wheel', 'unused.whl', '--report-dir', str(ROOT / 'not-created-evidence')])
    assert not (ROOT / 'not-created-evidence').exists()
