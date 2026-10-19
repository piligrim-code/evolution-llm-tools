from __future__ import annotations
import json, re
from typing import Dict, Any
from ..llm import OllamaClient
from ..contracts import ModelContractError, bounded_text, tool_spec as validate_tool_spec
from ..execution_policy import validate_scripts

GEN_PROMPT = """
Write a SINGLE Python file named tool.py that implements the tool below.

Rules:
- Accept argv as: python tool.py --json '<JSON object>'. The flag is sys.argv[1]; the JSON text is sys.argv[2].
- Parse one JSON object and validate every required argument, nested field, and array item against the Tool Spec before computing.
- Use exact JSON types: in particular, type(value) is int for integers because bool is a subclass of int in Python. Do not coerce strings, booleans, or floats.
- Reject missing, extra, or malformed fields with a short fixed message on stderr and a nonzero exit. Do not emit a traceback or partial stdout for invalid input.
- On valid input, print only the result to stdout; follow the output format in the Tool Spec.
- No network calls or host-file access. Prefer standard library only.
- Keep it small, deterministic, and explicit about input validation.
- If dependencies are required, list them on a separate line starting exactly with: REQUIREMENTS: pkg1==x.y, pkg2
- If no deps: write 'REQUIREMENTS: none' as the very last line.
- Do NOT wrap code in ```python or any markdown fences.
- Return only source code and the REQUIREMENTS line.

Tool Spec (JSON):
{tool_spec}
"""

def strip_code_fences(text: str) -> str:
    """Accept only an optional complete Python fence, never arbitrary prose."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) < 3 or lines[0] not in ("```", "```python") or lines[-1] != "```":
            raise ModelContractError("invalid_code_fence")
        text = "\n".join(lines[1:-1])
    return text.strip()

def propose_tool_scripts(tool_spec: Dict[str, Any], llm: OllamaClient, *, stdlib_only=False) -> Dict[str, str]:
    tool_spec = validate_tool_spec(tool_spec)
    prompt = GEN_PROMPT.format(tool_spec=json.dumps(tool_spec, ensure_ascii=False, indent=2))
    if stdlib_only:
        prompt += "\nExecution profile: Python standard library only, no network, no host files, no pip. REQUIREMENTS must be none."
    raw_code = llm.generate(prompt, max_tokens=1800)
    bounded_text(raw_code, 256000)
    clean_code = strip_code_fences(raw_code)
    lines = clean_code.splitlines()
    markers = [index for index, line in enumerate(lines) if line.strip().startswith("REQUIREMENTS:")]
    if markers != [len(lines) - 1]:
        raise ModelContractError("missing_or_ambiguous_requirements")
    req = lines[-1].strip().split(":", 1)[1].strip()
    if not req:
        raise ModelContractError("empty_requirements_marker")
    tool_py = "\n".join(lines[:-1]).strip() + "\n"
    bounded_text(tool_py, 256000)
    try:
        compile(tool_py, "<generated tool>", "exec")
    except (SyntaxError, ValueError, RecursionError):
        raise ModelContractError("invalid_python_syntax") from None
    scripts = {"tool.py": tool_py, "requirements.txt": ""}
    if req.lower() != "none":
        if stdlib_only:
            raise ModelContractError("dependencies_forbidden")
        entries = [entry.strip() for entry in req.split(",")]
        if not all(entries) or any(entry.startswith("-") for entry in entries):
            raise ModelContractError("invalid_requirements")
        scripts["requirements.txt"] = "\n".join(entries) + "\n"
    validate_scripts(scripts)
    return scripts
