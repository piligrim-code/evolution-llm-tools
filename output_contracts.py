"""Bounded, non-executable assertions for the exact reviewed input, not model judging."""
import hashlib
import json
import re
from typing import Literal, TypedDict

from .container_runner import OUTPUT_LIMIT
from .contracts import bounded_text, json_object


class OutputValidation(TypedDict):
    status: Literal["passed", "failed", "not_checked"]
    reason: str


def _canonical_object(value):
    def check(item):
        if type(item) is dict:
            if not all(type(key) is str for key in item):
                raise ValueError("invalid_expected_json")
            for child in item.values():
                check(child)
        elif type(item) is list:
            for child in item:
                check(child)
        elif type(item) not in (str, int, float, bool, type(None)):
            raise ValueError("invalid_expected_json")
    if type(value) is not dict:
        raise ValueError("expected_json_object_required")
    try:
        check(value)
        text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        return bounded_text(text, OUTPUT_LIMIT)
    except (ValueError, TypeError, RecursionError):
        raise ValueError("invalid_expected_json") from None


def normalize_output_contract(value):
    """Return an independent JSON copy; unknown fields/kinds cannot add privileges."""
    if type(value) is not dict or set(value) != {"kind", "expected"}:
        raise ValueError("invalid_output_contract")
    kind = value["kind"]
    if kind == "stdout-equals":
        expected = bounded_text(value["expected"], OUTPUT_LIMIT, allow_empty=True)
    elif kind == "json-object-equals":
        expected = json_object(_canonical_object(value["expected"]), limit=OUTPUT_LIMIT)
    else:
        raise ValueError("unsupported_output_contract")
    return {"kind": kind, "expected": expected}


def validate_output(contract, result) -> OutputValidation:
    """Check trusted executor evidence, never infer success from sanitized display text."""
    contract = normalize_output_contract(contract)
    if (not isinstance(result, dict) or result.get("execution") != "container"
            or type(result.get("returncode")) is not int):
        return {"status": "failed", "reason": "invalid_execution_result"}
    if result["returncode"] != 0 or result.get("outcome") != "exited":
        return {"status": "not_checked", "reason": "execution_not_successful"}
    digest, size = result.get("stdout_sha256"), result.get("stdout_bytes")
    if (not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest)
            or type(size) is not int or not 0 <= size <= OUTPUT_LIMIT):
        return {"status": "failed", "reason": "stdout_evidence_missing"}
    if contract["kind"] == "stdout-equals":
        expected = contract["expected"].encode("utf-8")
        matches = len(expected) == size and hashlib.sha256(expected).hexdigest() == digest
    else:
        try:
            displayed = bounded_text(result.get("stdout"), OUTPUT_LIMIT, allow_empty=True)
            raw = displayed.encode("utf-8")
            # The existing executor strips terminal controls and replaces invalid
            # UTF-8 for display. Altered text must not pass a JSON assertion.
            if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
                return {"status": "failed", "reason": "stdout_not_lossless_utf8"}
            actual = json_object(displayed, limit=OUTPUT_LIMIT)
            matches = _canonical_object(actual) == _canonical_object(contract["expected"])
        except (ValueError, TypeError, RecursionError, UnicodeError):
            return {"status": "failed", "reason": "invalid_json_output"}
    return {"status": "passed" if matches else "failed",
            "reason": "expected_output_matched" if matches else "output_mismatch"}
