"""Explicit consent and file boundaries, NOT an OS sandbox."""
import os
from pathlib import Path
import re


def require_unsafe_execution(allowed):
    if allowed is not True:
        raise PermissionError(
            "Generated-code execution is disabled. Only explicitly trusted code may "
            "use --unsafe-exec / allow_unsafe_execution=True; this is NOT a sandbox."
        )


def normalized_tool_name(name):
    if not isinstance(name, str):
        raise ValueError("Tool name must be text")
    name = name.strip().lower().replace(" ", "_")
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", name):
        raise ValueError("Tool name must contain only ASCII letters, digits, underscores or hyphens")
    if name.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
        raise ValueError("Reserved tool name")
    return name


def validate_scripts(scripts):
    if not isinstance(scripts, dict) or 'tool.py' not in scripts:
        raise ValueError("A tool.py script is required")
    if set(scripts) - {'tool.py', 'requirements.txt'}:
        raise ValueError("Only tool.py and requirements.txt may be written")
    if not all(isinstance(value, str) for value in scripts.values()):
        raise ValueError("Script content must be text")
    if sum(len(value.encode('utf-8')) for value in scripts.values()) > 256_000:
        raise ValueError("Generated scripts exceed the size limit")


def reject_linked_path(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part.is_symlink() or getattr(os.path, 'isjunction', lambda p: False)(part):
            raise ValueError("Linked tool paths are not supported")
    return path
