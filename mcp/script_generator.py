from __future__ import annotations
import json, re
from typing import Dict, Any
from ..llm import OllamaClient

GEN_PROMPT = """
Write a SINGLE Python file named tool.py that implements the tool below.

Rules:
- Must accept a single CLI flag: --json '<JSON string>'
- Parse JSON into dict args, do the computation, and print ONLY the final textual answer to stdout.
- No network calls unless strictly necessary. Prefer stdlib only.
- Keep it small, robust, and deterministic.
- If dependencies are required, list them on a separate line starting exactly with: REQUIREMENTS: pkg1==x.y, pkg2
- If no deps: write 'REQUIREMENTS: none' as the very last line.
- Do NOT wrap code in ```python or any markdown fences.
- Return only the code of tool.py and the REQUIREMENTS line.

Tool Spec (JSON):
{tool_spec}
"""

def strip_code_fences(text: str) -> str:
    """Удаляем markdown-блоки ```python ... ``` если они есть"""
    text = text.strip()
    text = re.sub(r"^```[a-zA-Z0-9]*\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()

def propose_tool_scripts(tool_spec: Dict[str, Any], llm: OllamaClient, *, stdlib_only=False) -> Dict[str, str]:
    prompt = GEN_PROMPT.format(tool_spec=json.dumps(tool_spec, ensure_ascii=False, indent=2))
    if stdlib_only:
        prompt += "\nExecution profile: Python standard library only, no network, no host files, no pip. REQUIREMENTS must be none."
    raw_code = llm.generate(prompt, max_tokens=1800)
    clean_code = strip_code_fences(raw_code)

    # REQUIREMENTS line
    req = "none"
    for line in clean_code.splitlines()[::-1]:
        if line.strip().startswith("REQUIREMENTS:"):
            req = line.strip().split("REQUIREMENTS:", 1)[1].strip() or "none"
            break

    # удаляем REQUIREMENTS из tool.py
    cleaned_lines = [ln for ln in clean_code.splitlines() if not ln.strip().startswith("REQUIREMENTS:")]
    tool_py = "\n".join(cleaned_lines).strip() + "\n"

    scripts = {"tool.py": tool_py, "requirements.txt": ""}
    if req and req.lower() != "none":
        # каждая зависимость в новой строке
        scripts["requirements.txt"] = "\n".join(x.strip() for x in req.split(",") if x.strip()) + "\n"

    return scripts
