from __future__ import annotations
import os, json, pathlib, subprocess, sys, shutil
from typing import Dict, Any, Optional
from ..config import settings

class ToolRegistry:
    def __init__(self, tools_dir: str | None = None):
        self.root = pathlib.Path(tools_dir or settings.tools_dir)
        self.root.mkdir(parents=True, exist_ok=True)

    def _tool_path(self, name: str) -> pathlib.Path:
        return self.root / name

    def _manifest_path(self, name: str) -> pathlib.Path:
        return self._tool_path(name) / "tool.json"

    def _write_manifest(self, name: str, manifest: Dict[str, Any]):
        p = self._manifest_path(name)
        p.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    def register(self, name: str, scripts: Dict[str, str], tool_spec: Dict[str, Any]) -> pathlib.Path:
        name = name.strip().lower().replace(" ","_")
        td = self._tool_path(name)
        if td.exists():
            shutil.rmtree(td)
        td.mkdir(parents=True, exist_ok=True)
        # write files
        for fn, content in scripts.items():
            (td / fn).write_text(content, encoding="utf-8")
        manifest = {"name": name, "spec": tool_spec, "files": list(scripts.keys())}
        self._write_manifest(name, manifest)
        return td

    def list(self):
        out = []
        for p in self.root.iterdir():
            if not p.is_dir():
                continue
            mf = p / "tool.json"
            if mf.exists():
                try:
                    out.append(json.loads(mf.read_text(encoding="utf-8")))
                except Exception:
                    pass
        return out

    def get(self, name: str) -> Optional[Dict[str, Any]]:
        p = self._manifest_path(name)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
        return None

    def find_similar(self, hint: str) -> Optional[Dict[str, Any]]:
        hint = hint.strip().lower()
        for it in self.list():
            if hint in it["name"] or it["name"] in hint:
                return it
        return None

    def run(self, name: str, args: Dict[str, Any]) -> str:
        td = self._tool_path(name)
        if not td.exists():
            raise FileNotFoundError(name)
        venv = td / ".venv"
        # Create or reuse venv (no deps by default)
        if not venv.exists():
            subprocess.check_call([sys.executable, "-m", "venv", str(venv)])
        py = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        # install requirements if present and enabled
        req = td / "requirements.txt"
        if req.exists() and req.read_text().strip() and settings.allow_pip:
            pip = venv / ("Scripts/pip.exe" if os.name == "nt" else "bin/pip")
            subprocess.check_call([str(pip), "install", "-r", str(req)])
        payload = json.dumps(args, ensure_ascii=False)
        proc = subprocess.run(
            [str(py), "tool.py", "--json", payload],
            capture_output=True, text=True, cwd=str(td), timeout=120
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr)
        return proc.stdout.strip()
