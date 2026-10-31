"""Qualify an already installed wheel, outside the source tree, without providers."""
import argparse
from email.parser import BytesParser
import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import sysconfig
import tempfile
import tomllib
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def clean_environment(environ, *, require_symlinks=False):
    env = dict(environ)
    for key in ('PYTHONPATH', 'PYTHONHOME', 'PYTEST_ADDOPTS', 'PYTEST_PLUGINS',
                'ALITA_CONTAINER_TESTS', 'ALITA_TEST_IMAGE', 'ALITA_REQUIRE_SYMLINKS'):
        env.pop(key, None)
    env['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
    if require_symlinks:
        env['ALITA_REQUIRE_SYMLINKS'] = '1'
    return env


def verify_wheel(wheel, source, installed, version):
    """Compare an allowlisted archive against source and installed module bytes."""
    project = tomllib.loads((source / 'pyproject.toml').read_text(encoding='utf-8'))['project']
    distribution = project['name'].replace('-', '_')
    if version != project['version']:
        raise ValueError('installed_version_mismatch')
    metadata_dir = f'{distribution}-{version}.dist-info/'
    metadata_files = {metadata_dir + name for name in
                      ('METADATA', 'WHEEL', 'RECORD', 'entry_points.txt', 'top_level.txt', 'licenses/LICENSE')}
    modules = {'alita/' + path.relative_to(source).as_posix(): path
               for path in (*source.glob('*.py'), *(source / 'mcp').glob('*.py'))}
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError('duplicate_wheel_entries')
        if set(names) != set(modules) | metadata_files:
            raise ValueError('unexpected_or_missing_wheel_entries')
        if sum(item.file_size for item in archive.infolist()) > 20_000_000:
            raise ValueError('wheel_inventory_size_limit')
        metadata = BytesParser().parsebytes(archive.read(metadata_dir + 'METADATA'))
        if metadata['Name'] != project['name'] or metadata['Version'] != version:
            raise ValueError('wheel_metadata_mismatch')
        for name, path in modules.items():
            data = archive.read(name)
            if data != path.read_bytes():
                raise ValueError('wheel_source_mismatch')
            if data != (installed / name.removeprefix('alita/')).read_bytes():
                raise ValueError('wheel_installed_mismatch')
    return {'sha256': hashlib.sha256(wheel.read_bytes()).hexdigest(),
            'entries': len(names), 'python_modules': len(modules),
            'source_and_installed_bytes_match': True}


def summarize_junit(path, *, containers=False, require_symlinks=False):
    cases = ET.parse(path).getroot().findall('.//testcase')
    if not cases:
        raise ValueError('empty_test_report')
    counts = {'passed': 0, 'skipped': 0, 'failures': 0, 'errors': 0}
    unexpected = []
    for case in cases:
        if case.find('failure') is not None:
            counts['failures'] += 1
        elif case.find('error') is not None:
            counts['errors'] += 1
        elif case.find('skipped') is not None:
            counts['skipped'] += 1
            classname, name = case.get('classname', ''), case.get('name', '')
            container_skip = classname.startswith('tests.container.')
            symlink_skip = (classname == 'tests.test_execution_policy'
                            and name == 'test_linked_tool_directory_is_rejected'
                            and not require_symlinks)
            if containers or not (container_skip or symlink_skip):
                unexpected.append(classname + '.' + name)
        else:
            counts['passed'] += 1
    return {**counts, 'unexpected_skips': unexpected,
            'accepted': not (counts['failures'] or counts['errors'] or unexpected) and counts['passed'] > 0}


def repository_state(source):
    head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=source, capture_output=True,
                          text=True, check=True, timeout=15).stdout.strip()
    dirty = subprocess.run(['git', 'status', '--porcelain'], cwd=source, capture_output=True,
                           text=True, check=True, timeout=15).stdout.strip()
    return {'commit': head, 'clean': not bool(dirty)}


def run_stage(command, *, cwd, env, directory, name, timeout):
    with (directory / f'{name}.log').open('w', encoding='utf-8') as output:
        result = subprocess.run(command, cwd=cwd, env=env, stdout=output, stderr=subprocess.STDOUT,
                                timeout=timeout)
    return result.returncode


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheel', required=True, type=Path)
    parser.add_argument('--report-dir', required=True, type=Path)
    parser.add_argument('--containers', action='store_true', help='Run the authorized real Docker suite too.')
    parser.add_argument('--require-symlinks', action='store_true', help='Refuse unavailable symlink coverage.')
    parser.add_argument('--require-clean', action='store_true', help='Refuse a dirty source tree.')
    args = parser.parse_args(argv)
    directory = args.report_dir.resolve()
    # Never overwrite a previous qualification's evidence or write under source.
    if directory.is_relative_to(ROOT):
        parser.error('report_directory_must_be_outside_source')
    directory.mkdir(parents=True, exist_ok=False)
    require_symlinks = args.require_symlinks or sys.platform != 'win32'
    report = {'schema_version': 1, 'status': 'failed', 'python': platform.python_version(),
              'system': platform.system(), 'architecture': platform.machine(),
              'containers_requested': args.containers, 'symlinks_required': require_symlinks,
              'stages': {}}
    try:
        if not sys.flags.isolated:
            raise ValueError('launch_with_python_isolated_flag')
        report['repository'] = repository_state(ROOT)
        if args.require_clean and not report['repository']['clean']:
            raise ValueError('clean_source_tree_required')
        package = Path(importlib.import_module('alita').__file__).resolve().parent
        libraries = [Path(sysconfig.get_path(key)).resolve() for key in ('purelib', 'platlib')]
        if package.is_relative_to(ROOT) or not any(package.is_relative_to(path) for path in libraries):
            raise ValueError('installed_site_packages_required')
        report['artifact'] = verify_wheel(args.wheel.resolve(), ROOT, package,
                                          importlib.metadata.version('evolution-llm-tools'))
        report['installed_import_verified'] = True
        env = clean_environment(os.environ, require_symlinks=require_symlinks)
        with tempfile.TemporaryDirectory(prefix='toolwright-qualification-') as scratch:
            code = run_stage([sys.executable, '-I', '-m', 'pip', 'check'], cwd=scratch, env=env,
                             directory=directory, name='dependencies', timeout=60)
            report['stages']['dependencies'] = {'exit_code': code}
            if code:
                raise ValueError('dependency_check_failed')
            xml = directory / 'default.xml'
            code = run_stage([sys.executable, '-I', '-m', 'pytest', str(ROOT / 'tests'), '-q', '--tb=short',
                              '--import-mode=append', f'--junitxml={xml}'], cwd=scratch, env=env,
                             directory=directory, name='default', timeout=300)
            report['stages']['default'] = {'exit_code': code}
            result = summarize_junit(xml, require_symlinks=require_symlinks)
            report['stages']['default'].update(result)
            if code or not result['accepted']:
                raise ValueError('default_suite_not_qualified')
            if args.containers:
                xml = directory / 'container.xml'
                code = run_stage([sys.executable, '-I', str(ROOT / 'tools/run_container_tests.py'),
                                  '--junitxml', str(xml), '--workdir', scratch], cwd=scratch, env=env,
                                 directory=directory, name='container', timeout=480)
                report['stages']['container'] = {'exit_code': code}
                result = summarize_junit(xml, containers=True, require_symlinks=require_symlinks)
                report['stages']['container'].update(result)
                if code or not result['accepted']:
                    raise ValueError('container_suite_not_qualified')
        after = repository_state(ROOT)
        if after != report['repository']:
            raise ValueError('repository_changed_during_qualification')
        report['status'] = 'passed'
    except (OSError, ValueError, subprocess.SubprocessError, zipfile.BadZipFile,
            ET.ParseError, ImportError) as error:
        report['error_type'] = type(error).__name__
        # Fixed validation codes are useful; external exception text can expose paths.
        report['error'] = str(error) if type(error) is ValueError else 'qualification_incomplete'
    finally:
        encoded = json.dumps(report, indent=2, ensure_ascii=True)
        (directory / 'summary.json').write_text(encoded + '\n', encoding='utf-8')
        print(encoded, flush=True)
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
