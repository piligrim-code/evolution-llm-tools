"""Explicit source derivation, never normalization in place or execution approval."""
from dataclasses import dataclass, field

from .contracts import ModelContractError, bounded_text
from .evaluation_generation import record_generation
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


def _unwrap_python_fence(text):
    bounded_text(text, 128 * 1024)
    opening, newline, remaining = text.partition('\n')
    if not newline or opening not in ('```python', '```python\r'):
        raise ModelContractError('expected_single_python_fence')
    closing = next((suffix for suffix in ('```', '```\n', '```\r\n') if remaining.endswith(suffix)), None)
    if closing is None:
        raise ModelContractError('expected_single_python_fence')
    source = remaining[:-len(closing)]
    if not source.endswith('\n'):
        raise ModelContractError('expected_single_python_fence')
    # This is a deliberately narrow envelope, not a general Markdown parser.
    # Reject ambiguous fence-like lines even inside a Python multiline literal.
    if any(line.lstrip().startswith(('```', '~~~')) for line in source.split('\n')):
        raise ModelContractError('ambiguous_python_fence')
    bounded_text(source, 128 * 1024)
    return source


def unwrap_generation_source(task_id, result, *, expected_corpus_sha256, prompt_version):
    """Derive one block's exact body; no compile, I/O, provider call or proposal."""
    if not isinstance(result, GenerationResult):
        raise ValueError('generation_result_required')
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
