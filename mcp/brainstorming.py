from __future__ import annotations
import json, re
from typing import Dict, Any
from ..llm import OllamaClient
from ..contracts import json_object, tool_spec

BRAINSTORM_PROMPT = """
You are designing a small, safe Python CLI tool that runs locally.
Given the user's question, propose a SPEC for a single-file Python tool that helps answer it.
- Prefer pure Python, avoid heavy deps. If absolutely needed, list a few PyPI deps.
- Provide a JSON with:
  name: short_snake_case name
  description: one sentence
  args: list of {name, type, description}. Names must be text, question or input;
        type must be "string". Parse needed values inside the tool from this text.
  output: description string
  entrypoint: 'python tool.py --json "<JSON string here>"'
  example_args: example JSON object for quick test
"""

def brainstorm_tools(question: str, tool_name_hint: str, llm: OllamaClient, *, stdlib_only=False) -> Dict[str, Any]:
    prompt = BRAINSTORM_PROMPT + f"\nUser question:\n{question}\nName hint: {tool_name_hint}\nReturn JSON only."
    if stdlib_only:
        prompt += "\nExecution profile: Python standard library only, no network, no host files. All inputs must be JSON arguments."
    text = llm.generate(prompt, json_mode=True)
    return tool_spec(json_object(text), fallback_name=tool_name_hint)
