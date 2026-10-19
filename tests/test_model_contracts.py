import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from alita import cli, manager
from alita.config import settings
from alita.container_runner import ContainerPolicy
from alita.contracts import ModelContractError, decision, json_object, tool_spec
from alita.mcp.brainstorming import brainstorm_tools
from alita.mcp.script_generator import propose_tool_scripts
from alita.llm import OllamaError
from typer.testing import CliRunner


@pytest.mark.parametrize("value", ['[]', 'prefix {"need_tool":false}', '{"x":1,"x":2}',
                                 '{"x":NaN}', '{"x":1e999}', '```json\n{}\n```'])
def test_structured_output_is_exact_finite_unambiguous_json(value):
    with pytest.raises(ModelContractError):
        json_object(value)


@pytest.mark.parametrize("value", [{}, {"need_tool": "false", "direct_answer": "x"},
    {"need_tool": 0, "direct_answer": "x"}, {"need_tool": False, "direct_answer": ""},
    {"need_tool": True, "tool_idea": []}, {"need_tool": False, "direct_answer": {"x": 1}}])
def test_invalid_decision_types_are_not_guessed(value):
    with pytest.raises(ModelContractError):
        decision(json.dumps(value))


@pytest.mark.parametrize("draft", ["synthetic-private malformed answer", '{"need_tool":"true"}', '[]'])
def test_invalid_decision_never_reaches_registry_or_execution(tmp_path, monkeypatch, draft):
    monkeypatch.setattr(settings, "runs_dir", str(tmp_path / "runs"))
    monkeypatch.setattr(settings, "tools_dir", str(tmp_path / "tools"))
    monkeypatch.setattr(manager, "OllamaClient", lambda **kwargs: SimpleNamespace(generate=lambda *args, **opts: draft))
    registry = Mock(side_effect=AssertionError("Must not open registry"))
    monkeypatch.setattr(manager, "ToolRegistry", registry)
    with pytest.raises(ModelContractError) as caught:
        manager.code_react_loop("hello", container=ContainerPolicy("sha256:" + "a" * 64))
    assert "synthetic-private" not in str(caught.value)
    registry.assert_not_called()
    assert not (tmp_path / "runs").exists()


@pytest.mark.parametrize("spec", [[], {"name": "../bad"}, {"name": "x", "args": {}},
    {"name": "x", "args": [{"name": "text"}, {"name": "text"}]},
    {"name": "x", "args": [{"name": "x", "type": "unknown"}]},
    {"name": "x", "example_args": []}, {"name": "x", "example_args": {"x": "\ud800"}},
    {"name": "x", "example_args": {"x": float("inf")}}])
def test_bad_tool_schema_refused(spec):
    with pytest.raises(ModelContractError):
        tool_spec(spec)


@pytest.mark.parametrize("schema", [
    {"type": "object", "required": ["missing"], "properties": {}},
    {"type": "object", "properties": {"x": {"type": "integer"}}, "additionalProperties": True},
    {"type": "array", "items": {"type": "unknown"}},
    {"type": "array"},
    {"type": "string", "items": {"type": "integer"}},
    {"type": "object", "items": {"type": "integer"}},
    {"type": "object", "properties": {"x": {"type": "object", "properties": {}}}, "surprise": 1},
])
def test_nested_argument_schema_is_a_bounded_closed_subset(schema):
    with pytest.raises(ModelContractError, match="invalid_argument_schema"):
        tool_spec({"name": "fixture", "args": [{"name": "data", "type": schema["type"], "schema": schema}]})


def test_nested_argument_schema_is_preserved_in_normalized_spec():
    schema = {"type": "object", "required": ["values"],
              "properties": {"values": {"type": "array", "items": {"type": "integer"}}}}
    result = tool_spec({"name": "fixture", "args": [{"name": "data", "type": "object", "schema": schema}]})
    assert result["args"][0]["schema"] == {
        "type": "object", "required": ["values"], "additionalProperties": False,
        "properties": {"values": {"type": "array", "items": {"type": "integer"}}}}


def test_nested_argument_schema_depth_limit_is_inclusive():
    schema = {"type": "integer"}
    for _ in range(8):
        schema = {"type": "array", "items": schema}
    tool_spec({"name": "fixture", "args": [{"name": "data", "type": "array", "schema": schema}]})
    schema = {"type": "array", "items": schema}
    with pytest.raises(ModelContractError, match="invalid_argument_schema"):
        tool_spec({"name": "fixture", "args": [{"name": "data", "type": "array", "schema": schema}]})


def test_nested_argument_schema_property_and_node_budgets_are_enforced():
    too_wide = {"type": "object", "properties": {
        f"field_{index}": {"type": "string"} for index in range(65)}}
    with pytest.raises(ModelContractError, match="invalid_argument_schema"):
        tool_spec({"name": "fixture", "args": [{"name": "data", "type": "object", "schema": too_wide}]})

    many_nodes = {"type": "object", "properties": {
        f"group_{index}": {"type": "object", "properties": {
            "left": {"type": "string"}, "right": {"type": "integer"}}}
        for index in range(64)}}
    with pytest.raises(ModelContractError, match="invalid_argument_schema"):
        tool_spec({"name": "fixture", "args": [{"name": "data", "type": "object", "schema": many_nodes}]})


def test_manager_does_not_silently_map_unsupported_arguments():
    with pytest.raises(ModelContractError, match="unsupported_manager_arguments"):
        manager.normalize_args("values", {"name": "fixture", "args": [{"name": "numbers", "type": "array"}]})
    assert manager.normalize_args("hello", {"name": "fixture", "args": [{"name": "input"}]}) == {"input": "hello"}


@pytest.mark.parametrize("source", ['print(2)', 'print(2)\nREQUIREMENTS:',
    'print(2)\nREQUIREMENTS: none\nREQUIREMENTS: none',
    'if :\nREQUIREMENTS: none', 'return 2\nREQUIREMENTS: none',
    '```python\nprint(2)\n```\nREQUIREMENTS: none'])
def test_incomplete_or_invalid_generated_script_is_not_executable_output(source):
    provider = SimpleNamespace(generate=Mock(return_value=source))
    with pytest.raises(ModelContractError):
        propose_tool_scripts({"name": "fixture"}, provider)


def test_generation_checks_syntax_without_running_source(tmp_path):
    sentinel = tmp_path / "must-not-exist"
    source = f'open({str(sentinel)!r}, "w").write("synthetic")\nREQUIREMENTS: none'
    provider = SimpleNamespace(generate=Mock(return_value=source))
    scripts = propose_tool_scripts({"name": "fixture"}, provider, stdlib_only=True)
    assert "tool.py" in scripts and not sentinel.exists()
    provider.generate.assert_called_once()


def test_generation_prompt_requires_exact_types_and_clean_invalid_input_failures():
    provider = SimpleNamespace(generate=Mock(return_value="print(2)\nREQUIREMENTS: none"))
    propose_tool_scripts({"name": "fixture"}, provider, stdlib_only=True)
    prompt = provider.generate.call_args.args[0]
    assert "type(value) is int" in prompt and "bool is a subclass of int" in prompt
    assert "nonzero exit" in prompt and "Do not emit a traceback" in prompt


def test_stdlib_profile_rejects_generated_dependencies():
    provider = SimpleNamespace(generate=Mock(return_value="print(2)\nREQUIREMENTS: synthetic-package"))
    with pytest.raises(ModelContractError, match="dependencies_forbidden"):
        propose_tool_scripts({"name": "fixture"}, provider, stdlib_only=True)


def test_brainstorm_requests_json_and_ignores_arbitrary_entrypoint():
    provider = SimpleNamespace(generate=Mock(return_value=json.dumps({"name": "fixture", "entrypoint": "arbitrary shell"})))
    result = brainstorm_tools("Synthetic", "fixture", provider)
    assert provider.generate.call_args.kwargs["json_mode"] is True
    assert result["entrypoint"] == 'python tool.py --json "<JSON>"'


def test_reviewed_brainstorm_prompt_declares_strict_nested_json_arguments():
    provider = SimpleNamespace(generate=Mock(return_value=json.dumps({"name": "fixture"})))
    brainstorm_tools("sum integer values", "fixture", provider, structured_args=True)
    prompt = provider.generate.call_args.args[0]
    assert "typed JSON arguments" in prompt
    assert "objects are closed and reject extra keys" in prompt
    assert "never a boolean or float" in prompt


def test_cli_reports_provider_failure_without_traceback_or_retry(monkeypatch):
    operation = Mock(side_effect=OllamaError("incomplete_response"))
    monkeypatch.setattr(cli, "code_react_loop", operation)
    result = CliRunner().invoke(cli.app, ["run", "Synthetic question"])
    assert result.exit_code == 2 and "incomplete_response" in result.stdout
    assert "Traceback" not in result.stdout
    operation.assert_called_once()
