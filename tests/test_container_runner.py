import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from alita import cli, container_runner as runner
from alita.container_runner import ContainerError, ContainerExecutor, ContainerPolicy
from alita.mcp import code_runner
from alita.mcp.registry import ToolRegistry

IMAGE = "sha256:" + "a" * 64


def item(executor):
    return {"Id": "b" * 64, "Name": "/" + executor.name, "Image": IMAGE, "State": {"Status": "created"},
        "Mounts": [], "Config": {"Labels": {runner.OWNER_LABEL: executor.owner}, "User": "65534:65534",
            "WorkingDir": "/work", "Entrypoint": ["/usr/bin/env"], "Cmd": runner.COMMAND, "Tty": False, "OpenStdin": True},
        "HostConfig": {"ReadonlyRootfs": True, "Privileged": False, "NetworkMode": "none", "Memory": runner.MEMORY,
            "MemorySwap": runner.MEMORY, "NanoCpus": runner.NANO_CPUS, "PidsLimit": runner.PIDS, "PidMode": "",
            "IpcMode": "none", "CgroupnsMode": "private", "UTSMode": "", "Init": True, "PublishAllPorts": False,
            "CapDrop": ["ALL"], "SecurityOpt": ["no-new-privileges=true"], "Tmpfs": {"/work": runner.TMPFS},
            "LogConfig": {"Type": "none"}, "RestartPolicy": {"Name": "no"}, "Ulimits": [
                {"Name": name, "Soft": value, "Hard": value} for name, value in [("nofile", 64), ("fsize", 8388608), ("core", 0)]]}}


@pytest.mark.parametrize("image", ["python:latest", "python@sha256:" + "a" * 64, "", None, "sha256:" + "z" * 64])
def test_mutable_or_invalid_image_refused(image):
    with pytest.raises(ValueError):
        ContainerPolicy(image)


@pytest.mark.parametrize("value", [True, 0, 61, float("nan"), float("inf")])
def test_invalid_deadline_refused(value):
    with pytest.raises(ValueError):
        ContainerPolicy(IMAGE, value)


@pytest.mark.parametrize("endpoint", ["tcp://127.0.0.1:2375", "ssh://host", "unix://other/run/docker.sock",
    "unix:///var/run/docker.sock?x=1", "npipe:////remote/pipe/docker", "unix:///bad path", ""])
def test_remote_or_ambiguous_endpoints_refused(endpoint):
    with pytest.raises(ContainerError):
        runner.validate_local_endpoint(endpoint)


@pytest.mark.parametrize("endpoint", ["unix:///var/run/docker.sock", "npipe:////./pipe/docker_engine"])
def test_local_endpoints_supported(endpoint):
    runner.validate_local_endpoint(endpoint)


def test_docker_host_override_refused_before_control(monkeypatch):
    monkeypatch.setenv("DOCKER_HOST", "tcp://synthetic.invalid:2375")
    executor = ContainerExecutor(ContainerPolicy(IMAGE))
    control = Mock()
    monkeypatch.setattr(executor, "_json", control)
    with pytest.raises(ContainerError, match="override_refused"):
        executor.check_engine()
    control.assert_not_called()


def test_endpoint_is_pinned_and_context_environment_removed(monkeypatch):
    monkeypatch.setattr(runner.os, "environ", {"PATH": "synthetic-path", "DOCKER_CONTEXT": "synthetic-context"})
    executor = ContainerExecutor(ContainerPolicy(IMAGE))
    info = {"OSType": "linux", "CgroupVersion": "2", "SecurityOptions": ["name=seccomp,profile=builtin"],
            **{key: True for key in ("MemoryLimit", "SwapLimit", "CpuCfsQuota", "PidsLimit")}}
    answers = [[{"Endpoints": {"docker": {"Host": "unix:///var/run/docker.sock"}}}], info,
               [{"Id": IMAGE, "Os": "linux", "Config": {}}]]
    run = Mock(side_effect=[SimpleNamespace(returncode=0, stdout=json.dumps(answer).encode()) for answer in answers])
    monkeypatch.setattr(runner.subprocess, "run", run)
    executor.preflight()
    assert run.call_args_list[0].args[0] == ["docker", "context", "inspect"]
    for call in run.call_args_list[1:]:
        assert call.args[0][:3] == ["docker", "--host", executor.endpoint]
        assert "DOCKER_CONTEXT" not in call.kwargs["env"]


@pytest.mark.parametrize("key,value", [("Privileged", True), ("Memory", 0), ("MemorySwap", -1),
    ("PidsLimit", 0), ("NanoCpus", 0), ("NetworkMode", "host"), ("PidMode", "host"),
    ("ReadonlyRootfs", False), ("Binds", ["/:/host"]), ("CapAdd", ["SYS_ADMIN"]),
    ("SecurityOpt", ["no-new-privileges=false"]), ("Tmpfs", {}), ("Devices", [{"PathOnHost": "/dev/sda"}]),
    ("LogConfig", {"Type": "json-file"}), ("RestartPolicy", {"Name": "always"})])
def test_weakened_boundary_refused(key, value):
    executor = ContainerExecutor(ContainerPolicy(IMAGE))
    data = item(executor)
    executor._verify_policy(data)
    data["HostConfig"][key] = value
    with pytest.raises(ContainerError):
        executor._verify_policy(data)


def test_ownership_mismatch_prevents_removal(monkeypatch):
    executor = ContainerExecutor(ContainerPolicy(IMAGE))
    data = item(executor)
    data["Config"]["Labels"][runner.OWNER_LABEL] = "other-owner"
    monkeypatch.setattr(executor, "_json", Mock(return_value=[data]))
    control = Mock()
    monkeypatch.setattr(executor, "_docker", control)
    with pytest.raises(ContainerError, match="ownership_mismatch"):
        executor._remove()
    control.assert_not_called()


def test_policy_mismatch_never_starts_and_still_cleans_owned_container(monkeypatch):
    executor = ContainerExecutor(ContainerPolicy(IMAGE))
    monkeypatch.setattr(executor, "preflight", Mock())
    monkeypatch.setattr(executor, "_docker", Mock(return_value=SimpleNamespace(stdout=b"b" * 64)))
    data = item(executor)
    data["HostConfig"]["ReadonlyRootfs"] = False
    monkeypatch.setattr(executor, "_owned", Mock(return_value=data))
    execute, remove = Mock(), Mock()
    monkeypatch.setattr(executor, "_execute", execute)
    monkeypatch.setattr(executor, "_remove", remove)
    with pytest.raises(ContainerError, match="limits_mismatch"):
        executor.run({"tool.py": "print(2)"}, {})
    execute.assert_not_called()
    remove.assert_called_once()


@pytest.mark.parametrize("args", [[], {"x": float("nan")}, {"x": "x" * runner.INPUT_LIMIT}])
def test_invalid_or_oversize_arguments_refused(args):
    with pytest.raises(ValueError):
        runner.validate_payload({"tool.py": "print(2)"}, args)


def test_dependencies_never_install_in_contained_mode(tmp_path, monkeypatch):
    spawn = Mock(side_effect=AssertionError("Must not execute host Python or pip"))
    monkeypatch.setattr(code_runner.subprocess, "check_call", spawn)
    with pytest.raises(PermissionError, match="standard-library"):
        code_runner.run_generated_tool({"tool.py": "print(2)", "requirements.txt": "dependency"}, {},
            tmp_path / "run", container=ContainerPolicy(IMAGE))
    assert not (tmp_path / "run").exists()
    spawn.assert_not_called()


def test_generation_and_registry_pass_container_policy_without_host_execution(tmp_path, monkeypatch):
    execute = Mock(return_value={"returncode": 0, "stdout": "4\n", "stderr": "", "outcome": "exited"})
    monkeypatch.setattr(ContainerExecutor, "run", execute)
    monkeypatch.setattr(code_runner, "_create_venv", Mock(side_effect=AssertionError("Host venv must not run")))
    policy = ContainerPolicy(IMAGE)
    scripts = {"tool.py": "print(4)", "requirements.txt": ""}
    result = code_runner.run_generated_tool(scripts, {}, tmp_path / "run", tool_args={"value": 2}, container=policy)
    assert result["stdout"] == "4\n" and not (tmp_path / "run" / ".venv").exists()
    registry = ToolRegistry(str(tmp_path / "registry"))
    registry.register("fixture", scripts, {"container": "not consent"})
    assert registry.run("fixture", {"value": 2}, container=policy) == "4"
    assert execute.call_count == 2
    with pytest.raises(PermissionError):
        registry.run("fixture", {})


def test_cli_does_not_mix_modes_or_carry_policy_between_commands(monkeypatch):
    run = Mock(return_value={"answer": "Synthetic", "used_tool": None})
    monkeypatch.setattr(cli, "code_react_loop", run)
    command = CliRunner()
    assert command.invoke(cli.app, ["run", "hello", "--container-image", IMAGE, "--unsafe-exec"]).exit_code == 2
    run.assert_not_called()
    assert command.invoke(cli.app, ["run", "hello", "--container-image", IMAGE]).exit_code == 0
    assert run.call_args.kwargs["container"] == ContainerPolicy(IMAGE)
    assert command.invoke(cli.app, ["run", "hello"]).exit_code == 0
    assert run.call_args.kwargs["container"] is None
