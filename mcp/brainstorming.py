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

STRUCTURED_BRAINSTORM_PROMPT = """
You are designing a small, safe Python CLI tool that runs locally.
Given the user's question, propose a SPEC for a single-file Python tool.
- Use typed JSON arguments instead of asking the tool to parse an unstructured question string.
- Provide args as {name, type, description}; types are string, integer, number, boolean, object, or array.
- For every object/array argument, include a strict schema using type, properties, required, and items; every array schema must define items, and objects are closed and reject extra keys.
- Integer means an exact integer, never a boolean or float. Do not use coercion.
- Include exact example_args matching the declared arguments and nested schema.
- Handle invalid input with a short stderr message and nonzero exit, without traceback or partial stdout.
- Include name, description, args, output, entrypoint, and example_args as JSON. Do not treat the entrypoint as executable shell text.
- Prefer standard library only; no network or host-file access.
"""


def brainstorm_tools(question: str, tool_name_hint: str, llm: OllamaClient, *, stdlib_only=False,
                     structured_args=False) -> Dict[str, Any]:
    template = STRUCTURED_BRAINSTORM_PROMPT if structured_args else BRAINSTORM_PROMPT
    prompt = template + f"\nUser question:\n{question}\nName hint: {tool_name_hint}\nReturn JSON only."
    if stdlib_only:
        prompt += "\nExecution profile: Python standard library only, no network, no host files. All inputs must be JSON arguments."
    text = llm.generate(prompt, json_mode=True)
    return tool_spec(json_object(text), fallback_name=tool_name_hint)
