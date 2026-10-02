"""Actual OS controls on test-owned containers. No generated model output is run."""
import os
import json
import asyncio
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


def test_file_and_tmpfs_capacity_limits_are_enforced():
    result = execute('''import errno, pathlib, signal
signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
chunk = b'x' * (1024 * 1024)
try:
    with open('/work/large', 'wb') as stream:
        for _ in range(9):
            stream.write(chunk)
except OSError as error:
    assert error.errno == errno.EFBIG
else:
    raise AssertionError('file size was not limited')
assert pathlib.Path('/work/large').stat().st_size <= 8388608
pathlib.Path('/work/large').unlink()
try:
    for index in range(8):
        with open('/work/part' + str(index), 'wb') as stream:
            for _ in range(4):
                stream.write(chunk)
except OSError as error:
    assert error.errno == errno.ENOSPC
else:
    raise AssertionError('tmpfs was not bounded')
print('disk bounds verified')
''')
    assert result["returncode"] == 0, result


def test_manager_create_register_and_reuse_stay_in_container(tmp_path, monkeypatch):
    from aiohttp import web
    from alita import manager
    from alita.config import settings
    from alita.mcp.registry import ToolRegistry
    from tests.ollama_fixture import frame, with_provider
    monkeypatch.setattr(settings, "runs_dir", str(tmp_path / "runs"))
    monkeypatch.setattr(settings, "tools_dir", str(tmp_path / "tools"))
    monkeypatch.setattr(settings, "allow_pip", True)
    decision = {"need_tool": True, "tool_idea": "synthetic_length", "direct_answer": ""}
    spec = {"name": "synthetic_length", "args": [{"name": "text", "type": "string"}]}
    code = 'import argparse, json\np=argparse.ArgumentParser();p.add_argument("--json")\nprint(len(json.loads(p.parse_args().json)["text"]))\n'
    answers = [json.dumps(decision), json.dumps(spec), code + "REQUIREMENTS: none", json.dumps(decision), json.dumps(decision)]
    received = []
    async def provider(request):
        received.append(await request.json())
        return web.Response(body=frame(answers[len(received) - 1], True))
    calls = []
    original = ContainerExecutor.run
    def record(self, scripts, args):
        calls.append(self.owner)
        return original(self, scripts, args)
    monkeypatch.setattr(ContainerExecutor, "run", record)
    policy = ContainerPolicy(os.environ["ALITA_TEST_IMAGE"])
    def scenario():
        first = manager.code_react_loop("abcd", container=policy)
        second = manager.code_react_loop("abcd", container=policy)
        assert first["used_tool"] == second["used_tool"] == "synthetic_length"
        assert len(calls) == len(set(calls)) == 2 and "Output:\n4" in second["answer"]
        saved = ToolRegistry().get("synthetic_length")
        assert saved["last_run"]["execution"] == "container" and saved["last_run"]["returncode"] == 0
        assert not list(tmp_path.rglob(".venv"))
        with pytest.raises(PermissionError):
            manager.code_react_loop("abcd")
        assert len(calls) == 2
    async def operation(url):
        monkeypatch.setattr(settings, "ollama_url", url)
        await asyncio.to_thread(scenario)
    asyncio.run(with_provider(provider, operation))
    assert len(received) == 5
    assert received[0]["format"] == received[1]["format"] == "json"
    assert "format" not in received[2] and received[2]["options"]["num_predict"] == 1800
