"""Explicit source derivation, never normalization in place or execution approval."""
from dataclasses import dataclass, field

from .evaluation_generation import _python_fence_body as _unwrap_python_fence, record_generation
from .generation_results import GenerationResult, text_digest

TRANSFORMATION_VERSION = 'unwrap-python-fence-v1'


@dataclass(frozen=True)
class SourceTransformation:
    task_id: str
    prompt_version: str
    corpus_version: str
    corpus_sha256: str
    original_status: str
    generation: GenerationResult = field(repr=False)
    source: str = field(repr=False)

    @property
    def source_sha256(self):
        return text_digest(self.source)

    def to_dict(self, *, include_text=False):
        if type(include_text) is not bool:
            raise ValueError('include_text_must_be_boolean')
        result = {
            'schema_version': 1, 'transformation_version': TRANSFORMATION_VERSION,
            'task_id': self.task_id, 'prompt_version': self.prompt_version,
            'corpus_version': self.corpus_version, 'corpus_sha256': self.corpus_sha256,
            'original_status': self.original_status,
            'original_response_sha256': self.generation.response_sha256,
            'source_sha256': self.source_sha256,
            'generation': self.generation.to_dict(include_text=include_text),
            'status': 'unreviewed_source', 'syntax_valid': None,
            'generation_provenance_verified': False, 'execution_authorized': False,
            'automatic_retry_allowed': False,
        }
        if include_text:
            result['source'] = self.source
        return result


def unwrap_generation_source(task_id, result, *, expected_corpus_sha256, prompt_version):
    """Derive one block's exact body; no compile, I/O, provider call or proposal."""
    if not isinstance(result, GenerationResult):
        raise ValueError('generation_result_required')
    if prompt_version in ('v4', 'v5', 'v6'):
        # v4 replies are JSON envelopes and v5/v6 already declare the fence as their format.
        raise ValueError(f'fence_transformation_not_applicable_to_{prompt_version}')
    # Validate the envelope first so raw-source checks never compile fenced text.
    source = _unwrap_python_fence(result.text)
    original = record_generation(task_id, result, expected_corpus_sha256=expected_corpus_sha256,
                                 mode='source', prompt_version=prompt_version)
    if original['response_kind'] != 'source':
        raise ValueError('source_transformation_requires_source')
    return SourceTransformation(task_id=task_id, prompt_version=prompt_version,
                                corpus_version=original['corpus_version'],
                                corpus_sha256=original['corpus_sha256'], original_status=original['status'],
                                generation=result, source=source)
