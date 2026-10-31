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


_VALUE_TYPES = ("string", "integer", "number", "boolean", "object", "array")
_SCHEMA_KEYS = {"type", "properties", "required", "items", "additionalProperties"}


def _normalize_value_schema(schema, *, depth=0, budget=None):
    if budget is None:
        budget = [128]
    budget[0] -= 1
    if (depth > 8 or budget[0] < 0 or type(schema) is not dict
            or set(schema) - _SCHEMA_KEYS or schema.get("type") not in _VALUE_TYPES):
        raise ModelContractError("invalid_argument_schema")
    kind = schema["type"]
    result = {"type": kind}
    if kind == "object":
        if set(schema) - {"type", "properties", "required", "additionalProperties"}:
            raise ModelContractError("invalid_argument_schema")
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if (type(properties) is not dict or len(properties) > 64
                or not all(type(name) is str and 0 < len(name) <= 128 for name in properties)
                or type(required) is not list or len(required) > len(properties)
                or any(type(name) is not str for name in required)
                or len(set(required)) != len(required) or not set(required) <= set(properties)
                or schema.get("additionalProperties", False) is not False):
            raise ModelContractError("invalid_argument_schema")
        result.update(properties={name: _normalize_value_schema(child, depth=depth + 1, budget=budget)
                                  for name, child in properties.items()},
                      required=sorted(required), additionalProperties=False)
    elif kind == "array":
        if "items" not in schema or set(schema) - {"type", "items"}:
            raise ModelContractError("invalid_argument_schema")
        result["items"] = _normalize_value_schema(schema["items"], depth=depth + 1, budget=budget)
    elif set(schema) != {"type"}:
        raise ModelContractError("invalid_argument_schema")
    return result


def normalize_value_schema(schema, *, expected_type=None):
    normalized = _normalize_value_schema(schema)
    if expected_type is not None and normalized["type"] != expected_type:
        raise ModelContractError("invalid_argument_schema")
    return normalized


def validate_value_schema(value, schema):
    """Validate the deliberately small strict JSON-schema subset used by tools."""
    kind = schema["type"]
    matches = {
        "string": type(value) is str,
        "integer": type(value) is int,
        "number": type(value) in (int, float),
        "boolean": type(value) is bool,
        "object": type(value) is dict,
        "array": type(value) is list,
    }[kind]
    if not matches:
        return False
    if kind == "object":
        properties = schema["properties"]
        if not set(schema["required"]) <= set(value) or not set(value) <= set(properties):
            return False
        return all(validate_value_schema(value[key], properties[key]) for key in value)
    if kind == "array" and "items" in schema:
        return all(validate_value_schema(item, schema["items"]) for item in value)
    return True


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
        if kind not in _VALUE_TYPES:
            raise ModelContractError("invalid_argument_type")
        seen.add(arg["name"])
        normalized = {"name": arg["name"], "type": kind,
                      "description": bounded_text(arg.get("description", ""), 2048, allow_empty=True)}
        if "schema" in arg:
            normalized["schema"] = normalize_value_schema(arg["schema"], expected_type=kind)
        result.append(normalized)
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
