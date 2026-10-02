"""Actual OS controls on test-owned containers. No generated model output is run."""
import os
import socket

import pytest

from alita.container_runner import ContainerExecutor, ContainerPolicy, OUTPUT_LIMIT

pytestmark = pytest.mark.skipif(os.environ.get("ALITA_CONTAINER_TESTS") != "1", reason="requires explicit disposable Docker run")


def execute(code, args=None, timeout=10):
    executor = ContainerExecutor(ContainerPolicy(os.environ["ALITA_TEST_IMAGE"], timeout))
    result = executor.run({"tool.py": code, "requirements.txt": ""}, args or {})
    remaining = executor._docker("container", "ls", "--all", "--quiet", "--filter",
                                 "label=io.alita.executor.owner=" + executor.owner)
    assert not remaining.stdout.strip(), "Owned container was not removed"
    return result


def test_actual_identity_kernel_limits_and_read_only_root():
    result = execute('''import json, os, pathlib, resource
status = dict(line.split(':', 1) for line in pathlib.Path('/proc/self/status').read_text().splitlines() if ':' in line)
assert os.getuid() == 65534 and os.getgid() == 65534
assert int(status['CapEff'].strip(), 16) == 0
assert status['NoNewPrivs'].strip() == '1' and status['Seccomp'].strip() == '2'
assert pathlib.Path('/sys/fs/cgroup/memory.max').read_text().strip() == '134217728'
assert pathlib.Path('/sys/fs/cgroup/memory.swap.max').read_text().strip() == '0'
assert pathlib.Path('/sys/fs/cgroup/pids.max').read_text().strip() == '32'
quota, period = map(int, pathlib.Path('/sys/fs/cgroup/cpu.max').read_text().split())
assert quota / period == 0.5
assert resource.getrlimit(resource.RLIMIT_NOFILE) == (64, 64)
assert resource.getrlimit(resource.RLIMIT_FSIZE) == (8388608, 8388608)
try:
    pathlib.Path('/forbidden-write').write_text('synthetic')
except OSError:
    pass
else:
    raise AssertionError('root filesystem writable')
try:
    os.setuid(0)
except PermissionError:
    pass
else:
    raise AssertionError('privilege elevation succeeded')
pathlib.Path('/work/synthetic').write_text('temporary')
print('controls verified')
''')
    assert result["returncode"] == 0, result
    assert result["stdout"].strip() == "controls verified"


def test_host_files_environment_and_network_are_not_available(tmp_path, monkeypatch):
    sentinel = tmp_path / "host-only.txt"
    sentinel.write_text("synthetic host sentinel")
    monkeypatch.setenv("ALITA_SYNTHETIC_SECRET", "not-for-container")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        result = execute('''import argparse, json, os, pathlib, socket
p = argparse.ArgumentParser(); p.add_argument('--json'); args = json.loads(p.parse_args().json)
assert 'ALITA_SYNTHETIC_SECRET' not in os.environ
assert not pathlib.Path(args['path']).exists()
assert not pathlib.Path('/var/run/docker.sock').exists()
assert {name for _, name in socket.if_nameindex()} == {'lo'}
try:
    socket.create_connection(('127.0.0.1', args['port']), timeout=0.2)
except OSError:
    pass
else:
    raise AssertionError('host network reachable')
print('host boundaries verified')
''', {"path": str(sentinel), "port": listener.getsockname()[1]})
    assert result["returncode"] == 0, result
    assert sentinel.read_text() == "synthetic host sentinel"


def test_fork_pressure_is_bounded_inside_private_pid_namespace():
    result = execute('''import errno, os, signal, time
children = []
limited = False
try:
    for _ in range(64):
        try:
            pid = os.fork()
        except OSError as error:
            assert error.errno == errno.EAGAIN
            limited = True
            break
        if pid == 0:
            time.sleep(5)
            os._exit(0)
        children.append(pid)
    assert limited and len(children) < 32
finally:
    for pid in children:
        os.kill(pid, signal.SIGTERM)
    for pid in children:
        os.waitpid(pid, 0)
print('pid bound verified')
''')
    assert result["returncode"] == 0, result


def test_memory_exhaustion_is_not_host_memory_exhaustion():
    result = execute("payload = bytearray(256 * 1024 * 1024)\nprint(len(payload))\n")
    assert result["returncode"] != 0 and result["outcome"] == "memory_limit", result


def test_timeout_kills_owned_container_and_does_not_retry():
    result = execute("import time\nprint('one attempt', flush=True)\ntime.sleep(30)\n", timeout=1)
    assert result["outcome"] == "timeout" and result["returncode"] == 124
    assert result["stdout"].count("one attempt") <= 1


def test_output_is_bounded_and_overflow_is_failure():
    result = execute("while True:\n    print('x' * 4096, flush=True)\n")
    assert result["outcome"] == "output_limit" and result["returncode"] == 124
    assert len(result["stdout"].encode()) + len(result["stderr"].encode()) <= OUTPUT_LIMIT
