from __future__ import annotations
import json, re
from typing import Dict, Any
from ..llm import OllamaClient

BRAINSTORM_PROMPT = """
You are designing a small, safe Python CLI tool that runs locally.
Given the user's question, propose a SPEC for a single-file Python tool that helps answer it.
- Prefer pure Python, avoid heavy deps. If absolutely needed, list a few PyPI deps.
- Provide a JSON with:
  name: short_snake_case name
  description: one sentence
  args: list of {name, type, description}
  output: description string
  entrypoint: 'python tool.py --json "<JSON string here>"'
  example_args: example JSON object for quick test
"""

def brainstorm_tools(question: str, tool_name_hint: str, llm: OllamaClient, *, stdlib_only=False) -> Dict[str, Any]:
    prompt = BRAINSTORM_PROMPT + f"\nUser question:\n{question}\nName hint: {tool_name_hint}\nReturn JSON only."
    if stdlib_only:
        prompt += "\nExecution profile: Python standard library only, no network, no host files. All inputs must be JSON arguments."
    text = llm.generate(prompt)
    # Try extracting JSON
    import json as _json, re as _re
    m = _re.search(r"\{.*\}", text, _re.S)
    spec = _json.loads(m.group(0)) if m else _json.loads(text)
    # Light postprocess
    spec.setdefault("name", tool_name_hint)
    if not spec.get("entrypoint"):
        spec["entrypoint"] = 'python tool.py --json "<JSON here>"'
    if not spec.get("example_args"):
        spec["example_args"] = {"question": question}
    return spec
