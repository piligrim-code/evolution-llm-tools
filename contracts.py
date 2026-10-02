"""Structural model-output validation, not semantic accuracy or code approval."""
import json
import math
import re

from .execution_policy import normalized_tool_name


class ModelContractError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__("Model contract: " + code)


def bounded_text(value, limit, *, allow_empty=False):
    if not isinstance(value, str) or "\x00" in value or (not allow_empty and not value.strip()):
        raise ModelContractError("invalid_text")
    try:
        if len(value.encode("utf-8")) > limit:
            raise ModelContractError("text_too_large")
    except UnicodeError:
        raise ModelContractError("invalid_text_encoding") from None
    return value


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ModelContractError("duplicate_key")
        result[key] = value
    return result


def _constant(value):
    raise ModelContractError("nonfinite_json")


def _float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ModelContractError("nonfinite_json")
    return number


def json_object(value, *, limit=65536):
    try:
        if isinstance(value, bytes):
            if len(value) > limit:
                raise ModelContractError("json_too_large")
            value = value.decode("utf-8")
        bounded_text(value, limit)
        data = json.loads(value, object_pairs_hook=_unique, parse_constant=_constant, parse_float=_float)
        if not isinstance(data, dict):
            raise ModelContractError("expected_object")
        return data
    except ModelContractError:
        raise
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise ModelContractError("invalid_json") from None


def decision(value):
    data = json_object(value)
    if type(data.get("need_tool")) is not bool:
        raise ModelContractError("need_tool_must_be_boolean")
    answer = bounded_text(data.get("direct_answer", ""), 60000, allow_empty=data["need_tool"])
    idea = bounded_text(data.get("tool_idea", ""), 100, allow_empty=True)
    reason = bounded_text(data.get("reason", ""), 4096, allow_empty=True)
    # Extra provider metadata never becomes an execution setting.
    return {"need_tool": data["need_tool"], "direct_answer": answer, "tool_idea": idea, "reason": reason}


def tool_spec(data, *, fallback_name=None):
    if not isinstance(data, dict):
        raise ModelContractError("invalid_tool_spec")
    try:
        name = normalized_tool_name(data.get("name", fallback_name))
    except ValueError:
        raise ModelContractError("invalid_tool_name") from None
    args = data.get("args", [])
    if not isinstance(args, list) or len(args) > 16:
        raise ModelContractError("invalid_argument_schema")
    result, seen = [], set()
    for arg in args:
        if (not isinstance(arg, dict) or not isinstance(arg.get("name"), str)
                or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", arg["name"])
                or arg["name"] in seen):
            raise ModelContractError("invalid_argument_schema")
        kind = arg.get("type", "string")
        if kind not in ("string", "integer", "number", "boolean", "object", "array"):
            raise ModelContractError("invalid_argument_type")
        seen.add(arg["name"])
        result.append({"name": arg["name"], "type": kind,
                       "description": bounded_text(arg.get("description", ""), 2048, allow_empty=True)})
    example = data.get("example_args", {})
    if not isinstance(example, dict):
        raise ModelContractError("invalid_example_args")
    try:
        bounded_text(json.dumps(example, ensure_ascii=False, allow_nan=False), 16384)
    except (ValueError, TypeError, RecursionError):
        raise ModelContractError("invalid_example_args") from None
    return {"name": name, "args": result, "example_args": example,
            "description": bounded_text(data.get("description", ""), 4096, allow_empty=True),
            "output": bounded_text(data.get("output", ""), 4096, allow_empty=True),
            "entrypoint": 'python tool.py --json "<JSON>"'}
