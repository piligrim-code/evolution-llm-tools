from __future__ import annotations
import os, pathlib, json, subprocess, sys, shutil, uuid
from typing import Dict, Any
from ..config import settings
from .registry import ToolRegistry
from ..execution_policy import require_unsafe_execution, validate_scripts, reject_linked_path
from ..container_runner import ContainerExecutor, require_execution_mode, validate_payload

def _write_scripts(run_dir: pathlib.Path, scripts: Dict[str, str]):
    validate_scripts(scripts)
    run_dir = reject_linked_path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=False)
    for name, content in scripts.items():
        (run_dir / name).write_text(content, encoding="utf-8")

def _create_venv(venv_dir: pathlib.Path):
    subprocess.check_call([sys.executable, "-m", "venv", str(venv_dir)], timeout=60)

def _install_requirements(venv_dir: pathlib.Path, run_dir: pathlib.Path, *, allow_unsafe_execution=False):
    require_unsafe_execution(allow_unsafe_execution)
    req = run_dir / "requirements.txt"
    if not req.exists() or req.read_text().strip() == "":
        return
    if not settings.allow_pip:
        raise PermissionError("Tool dependencies require separate allow_pip approval")
    pip = venv_dir / ("Scripts/pip.exe" if os.name == "nt" else "bin/pip")
    subprocess.check_call([str(pip), "install", "-r", str(req)], stdout=subprocess.DEVNULL, timeout=120)

def _execute_tool(venv_dir: pathlib.Path, run_dir: pathlib.Path, tool_args: Dict[str, Any], *, allow_unsafe_execution=False) -> Dict[str, Any]:
    require_unsafe_execution(allow_unsafe_execution)
    reject_linked_path(run_dir)
    reject_linked_path(venv_dir)
    reject_linked_path(run_dir / 'tool.py')
    py = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    tool = run_dir / "tool.py"
    payload = json.dumps(tool_args, ensure_ascii=False)
    cmd = [str(py), str(tool), "--json", payload]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(run_dir), timeout=120)
    return {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}

def run_generated_tool(scripts: Dict[str, str], tool_spec: Dict[str, Any], run_dir: pathlib.Path, question: str | None = None, *, allow_unsafe_execution=False, tool_args=None, container=None) -> Dict[str, Any]:
    require_execution_mode(allow_unsafe_execution, container)
    if tool_args is None:
        tool_args = {"question": question} if question else tool_spec.get("example_args", {})
    if container is not None:
        validate_payload(scripts, tool_args)
        _write_scripts(run_dir, scripts)
        return ContainerExecutor(container).run(scripts, tool_args)
    _write_scripts(run_dir, scripts)
    venv_dir = run_dir / ".venv"
    _create_venv(venv_dir)
    _install_requirements(venv_dir, run_dir, allow_unsafe_execution=allow_unsafe_execution)
    return _execute_tool(venv_dir, run_dir, tool_args, allow_unsafe_execution=allow_unsafe_execution)

def register_tool(scripts: Dict[str, str], tool_spec: Dict[str, Any], run_result: Dict[str, Any]) -> Dict[str, Any]:
    if run_result.get('returncode') != 0:
        raise ValueError('Failed execution must not be registered as a working tool')
    registry = ToolRegistry()
    name = tool_spec.get("name","auto_tool")
    tool_dir = registry.register(name=name, scripts=scripts, tool_spec=tool_spec)
    meta = registry.get(name)
    meta["last_run"] = run_result
    registry._write_manifest(meta["name"], meta)  # update
    return meta
