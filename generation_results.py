"""Immutable generation observations, not verified model identity or execution authority."""
from dataclasses import asdict, dataclass, field
import hashlib
import json

from .contracts import bounded_text

USAGE_FIELDS = {
    'total_duration_ns': 'total_duration',
    'load_duration_ns': 'load_duration',
    'prompt_tokens': 'prompt_eval_count',
    'prompt_duration_ns': 'prompt_eval_duration',
    'output_tokens': 'eval_count',
    'output_duration_ns': 'eval_duration',
}


def text_digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def request_digest(payload):
    return text_digest(json.dumps(payload, sort_keys=True, separators=(',', ':'),
                                  ensure_ascii=False, allow_nan=False))


@dataclass(frozen=True)
class GenerationUsage:
    total_duration_ns: int | None = None
    load_duration_ns: int | None = None
    prompt_tokens: int | None = None
    prompt_duration_ns: int | None = None
    output_tokens: int | None = None
    output_duration_ns: int | None = None

    @classmethod
    def from_event(cls, event):
        values = {}
        for field, key in USAGE_FIELDS.items():
            value = event.get(key)
            if value is not None and (type(value) is not int or not 0 <= value <= 2**63 - 1):
                raise ValueError('invalid_generation_usage')
            values[field] = value
        return cls(**values)


def final_metadata(event):
    values = []
    for key, limit in (('model', 256), ('done_reason', 128)):
        value = event.get(key)
        values.append(bounded_text(value, limit) if value is not None else None)
    return GenerationUsage.from_event(event), *values


@dataclass(frozen=True)
class GenerationResult:
    text: str = field(repr=False)
    requested_model: str
    provider_model: str | None
    done_reason: str | None
    prompt_sha256: str
    request_sha256: str
    endpoint_sha256: str
    response_sha256: str
    temperature: float
    max_tokens: int
    seed: int | None
    json_mode: bool
    timeout_seconds: float
    client_elapsed_seconds: float
    provider_usage: GenerationUsage

    def to_dict(self, *, include_text=False):
        if type(include_text) is not bool:
            raise ValueError('include_text_must_be_boolean')
        result = {key: value for key, value in asdict(self).items() if key != 'text'}
        result.update(schema_version=1, provider_usage_source='unverified_final_provider_event',
                      model_identity_verified=False, model_artifact_sha256=None,
                      peak_memory_bytes=None, execution_authorized=False, automatic_retry_allowed=False)
        if include_text:
            result['text'] = self.text
        return result
