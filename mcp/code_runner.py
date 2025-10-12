from __future__ import annotations
import os, pathlib, json, subprocess, sys, shutil, uuid
from typing import Dict, Any
from ..config import settings
from .registry import ToolRegistry

def _write_scripts(run_dir: pathlib.Path, scripts: Dict[str, str]):
    run_dir.mkdir(parents=True, exist_ok=True)
    for name, content in scripts.items():
        (run_dir / name).write_text(content, encoding="utf-8")

def _create_venv(venv_dir: pathlib.Path):
    subprocess.check_call([sys.executable, "-m", "venv", str(venv_dir)])

def _install_requirements(venv_dir: pathlib.Path, run_dir: pathlib.Path):
    req = run_dir / "requirements.txt"
    if not req.exists() or req.read_text().strip() == "":
        return
    if not settings.allow_pip:
        return
    pip = venv_dir / ("Scripts/pip.exe" if os.name == "nt" else "bin/pip")
    subprocess.check_call([str(pip), "install", "-r", str(req)], stdout=subprocess.DEVNULL)

def _execute_tool(venv_dir: pathlib.Path, run_dir: pathlib.Path, tool_args: Dict[str, Any]) -> Dict[str, Any]:
    py = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    tool = run_dir / "tool.py"
    payload = json.dumps(tool_args, ensure_ascii=False)
    cmd = [str(py), str(tool), "--json", payload]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(run_dir), timeout=120)
    return {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}

def run_generated_tool(scripts: Dict[str, str], tool_spec: Dict[str, Any], run_dir: pathlib.Path, question: str | None = None) -> Dict[str, Any]:
    _write_scripts(run_dir, scripts)
    venv_dir = run_dir / ".venv"
    _create_venv(venv_dir)
    _install_requirements(venv_dir, run_dir)
    tool_args = {"question": question} if question else tool_spec.get("example_args", {})
    return _execute_tool(venv_dir, run_dir, tool_args)

def register_tool(scripts: Dict[str, str], tool_spec: Dict[str, Any], run_result: Dict[str, Any]) -> Dict[str, Any]:
    registry = ToolRegistry()
    name = tool_spec.get("name","auto_tool")
    tool_dir = registry.register(name=name, scripts=scripts, tool_spec=tool_spec)
    meta = registry.get(name)
    meta["last_run"] = run_result
    registry._write_manifest(meta["name"], meta)  # update
    return meta
