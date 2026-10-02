from __future__ import annotations
import json, os, time, uuid, pathlib, subprocess, sys, re, shutil
from typing import Optional, Dict, Any
from rich.console import Console
from rich.panel import Panel
from .config import settings
from .llm import OllamaClient
from .mcp.brainstorming import brainstorm_tools
from .mcp.script_generator import propose_tool_scripts
from .mcp.code_runner import run_generated_tool, register_tool
from .mcp.registry import ToolRegistry
from .container_runner import require_execution_mode
from .contracts import bounded_text, decision, tool_spec as validate_tool_spec, ModelContractError

console = Console()


def normalize_args(question: str, spec: dict) -> dict:
    """
    Унифицируем входные аргументы для запуска тулзы.
    - Всегда прокидываем и 'text', и 'question'
    - Подстраиваемся под args тулзы
    """
    spec = validate_tool_spec(spec)
    base_args = {"text": question, "question": question, "input": question}
    if any(arg["name"] not in base_args or arg["type"] != "string" for arg in spec["args"]):
        raise ModelContractError("unsupported_manager_arguments")
    expected = [a["name"] for a in spec["args"]]

    normalized = {}
    for k in expected:
        if k in base_args:
            normalized[k] = base_args[k]

    # если тулза не описала args — даём text по умолчанию
    if not normalized:
        normalized = {"text": question}

    return normalized


def code_react_loop(question: str, *, allow_unsafe_execution=False, model=None, container=None) -> Dict[str, Any]:
    bounded_text(question, 16000)
    llm = OllamaClient(model=model)
    run_id = str(uuid.uuid4())[:8]
    run_dir = pathlib.Path(settings.runs_dir) / run_id

    console.rule("[bold]Manager: Analyze & Decide")
    prompt = f"""
You are an agent that solves tasks with minimal predefined tools.
Task: {question}

Decide if you need to create a small Python tool or can answer directly.
If a tool helps, briefly name it and describe inputs/outputs.

Respond as JSON with keys:
- need_tool: bool
- tool_idea: short name (or "")
- reason: why or why not
- direct_answer: attempt a direct answer (string; can be empty)
- input_schema: optional JSON schema for tool input
- output_schema: optional JSON schema for tool output
"""
    meta = decision(llm.generate(prompt, json_mode=True))

    # эвристики: форсим need_tool на даты/среднее/CSV
    text_q = question.lower()
    date_pat = r"\b(\d{1,2}[./-]\d{1,2}[./-]\d{2,4})\b"
    has_two_dates = len(re.findall(date_pat, text_q)) >= 2
    has_avg_words = any(w in text_q for w in ["средн", "average", "mean", "медиан"])
    has_2plus_numbers = len(re.findall(r"[-+]?\d+(?:[.,]\d+)?", text_q)) >= 2
    mentions_csv = any(w in text_q for w in ["csv", "таблиц", "table", "comma-separated"])

    if has_two_dates or (has_2plus_numbers and has_avg_words) or mentions_csv:
        meta["need_tool"] = True
        if not meta.get("tool_idea"):
            meta["tool_idea"] = "auto_calc"
        meta["reason"] = "Heuristic: structured calc (dates/numbers/CSV) requires a tool."

    console.print(Panel.fit(json.dumps(meta, ensure_ascii=False, indent=2), title="Decision"))

    final_answer = meta.get("direct_answer", "").strip()

    if meta.get("need_tool"):
        require_execution_mode(allow_unsafe_execution, container)
        registry = ToolRegistry()
        tool_name_hint = meta.get("tool_idea","").strip().lower().replace(" ", "_")[:40] or "auto_tool"
        existing = registry.find_similar(tool_name_hint)
        if existing:
            console.print(f"[bold green]Reusing existing tool:[/bold green] {existing['name']}")
            args = normalize_args(question, existing["spec"])
            result = registry.run(existing["name"], args, allow_unsafe_execution=allow_unsafe_execution, container=container)
            final_answer = f"{final_answer}\n[Used tool {existing['name']}] Output:\n{result}"
            return {"answer": final_answer, "used_tool": existing["name"]}

        # создать новый tool
        tool_spec = validate_tool_spec(brainstorm_tools(question=question, tool_name_hint=tool_name_hint, llm=llm,
                                     stdlib_only=container is not None))
        args = normalize_args(question, tool_spec)
        console.print(Panel.fit(json.dumps(tool_spec, ensure_ascii=False, indent=2), title="Brainstorm Spec"))

        scripts = propose_tool_scripts(tool_spec=tool_spec, llm=llm, stdlib_only=container is not None)
        run_out = run_generated_tool(scripts=scripts, tool_spec=tool_spec, run_dir=run_dir,
                                     question=question, tool_args=args,
                                     allow_unsafe_execution=allow_unsafe_execution, container=container)
        if run_out['returncode'] != 0:
            raise RuntimeError('Generated tool failed; it was not registered')
        console.print(Panel.fit(run_out["stdout"][-2000:], title="Tool Execution (tail)"))

        tool_meta = register_tool(scripts=scripts, tool_spec=tool_spec, run_result=run_out)
        console.print(Panel.fit(json.dumps(tool_meta, ensure_ascii=False, indent=2), title="Registered Tool"))

        # финальный ответ — уже по реальному запросу
        real_out = run_out['stdout'].strip()
        final_answer = f"{final_answer}\n[Created tool {tool_meta['name']}] Output:\n{real_out}"

        return {"answer": final_answer, "used_tool": tool_meta["name"]}

    return {"answer": final_answer, "used_tool": None}
