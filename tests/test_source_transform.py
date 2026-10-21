"""Synthetic source derivations only, never a model call or source execution."""
from dataclasses import FrozenInstanceError, replace
import hashlib
import json
from unittest.mock import Mock

import pytest

from alita.evaluation_corpus import corpus_digest
from alita.evaluation_generation import record_generation
from alita.evaluation_prompts import evaluation_prompt
from alita.generation_results import GenerationResult, GenerationUsage, request_digest, text_digest
from alita.source_transform import TRANSFORMATION_VERSION, unwrap_generation_source


@pytest.fixture(autouse=True)
def no_side_effects(monkeypatch):
    guards = []
    for target in ('alita.llm.OllamaClient.generate_result', 'alita.llm.OllamaClient.generate',
                   'alita.review.runner.ContainerExecutor', 'alita.mcp.script_generator.propose_tool_scripts'):
        guard = Mock(side_effect=AssertionError('Source transformation must not call ' + target))
        monkeypatch.setattr(target, guard)
        guards.append(guard)
    compiler = Mock(side_effect=AssertionError('Source transformation must not compile'))
    monkeypatch.setattr('alita.evaluation_generation.compile', compiler, raising=False)
    monkeypatch.setattr('alita.source_transform.compile', compiler, raising=False)
    guards.append(compiler)
    yield
    for guard in guards:
        guard.assert_not_called()


def observation(text, *, task='integer-sum', version='v2', mode='source'):
    prompt = evaluation_prompt(task, mode=mode, version=version)
    payload = {'model': 'synthetic', 'prompt': prompt, 'stream': True,
               'options': {'temperature': 0, 'num_predict': 512, 'seed': 7}}
    return GenerationResult(text=text, requested_model='synthetic', provider_model=None,
                            done_reason='stop', prompt_sha256=text_digest(prompt),
                            request_sha256=request_digest(payload), endpoint_sha256=text_digest('synthetic'),
                            response_sha256=text_digest(text), temperature=0, max_tokens=512, seed=7,
                            json_mode=False, timeout_seconds=120, client_elapsed_seconds=0,
                            provider_usage=GenerationUsage())


def transform(text, *, version='v2'):
    return unwrap_generation_source('integer-sum', observation(text, version=version),
                                    expected_corpus_sha256=corpus_digest(), prompt_version=version)


@pytest.mark.parametrize('version', ['v1', 'v2', 'v3'])
@pytest.mark.parametrize('opening', ['```python\n', '```python\r\n'])
@pytest.mark.parametrize('closing', ['```', '```\n', '```\r\n'])
def test_exact_body_and_original_are_preserved(version, opening, closing):
    body = '\n# synthetic\r\nvalue = 1  \n\r\n'
    raw = opening + body + closing
    derived = transform(raw, version=version)
    assert derived.source == body and derived.generation.text == raw
    assert derived.source_sha256 == hashlib.sha256(body.encode()).hexdigest()
    summary = derived.to_dict()
    assert summary['original_response_sha256'] == text_digest(raw)
    assert summary['original_response_sha256'] != summary['source_sha256']
    assert summary['transformation_version'] == TRANSFORMATION_VERSION == 'unwrap-python-fence-v1'
    assert summary['original_status'] == ('invalid_source' if version in ('v2', 'v3') else 'unreviewed_source')
    assert summary['status'] == 'unreviewed_source' and summary['syntax_valid'] is None
    assert summary['execution_authorized'] is False and summary['generation_provenance_verified'] is False
    assert summary['automatic_retry_allowed'] is False


@pytest.mark.parametrize('raw', [
    'print(1)\n', '```\nprint(1)\n```', '```py\nprint(1)\n```',
    '```Python\nprint(1)\n```', '~~~python\nprint(1)\n~~~',
    ' ```python\nprint(1)\n```', '```python \nprint(1)\n```',
    '```python\nprint(1)\n ```', '```python\nprint(1)\n``` ',
    'Here is code:\n```python\nprint(1)\n```',
    '```python\nprint(1)\n```\nExplanation', '```python\nprint(1)',
    '```python\nprint(1)\n````', '```python\rprint(1)\r```',
    '\n```python\nprint(1)\n```', '```python\nprint(1)\n```\n\n',
])
def test_noncanonical_or_incomplete_envelope_is_refused(raw):
    with pytest.raises(ValueError, match='expected_single_python_fence'):
        transform(raw)


@pytest.mark.parametrize('body', [
    'pass\n```\n```python\npass\n', 'pass\n~~~\n~~~python\npass\n',
    '```python\npass\n', '    ```\n', 'value = """\n```\n"""\n',
])
def test_multiple_nested_or_ambiguous_fences_are_refused(body):
    with pytest.raises(ValueError, match='ambiguous_python_fence'):
        transform('```python\n' + body + '```')


@pytest.mark.parametrize('raw', ['', '\x00', '```python\n\n```', '```python\n  \t\n```'])
def test_empty_or_invalid_text_is_refused(raw):
    with pytest.raises(ValueError, match='invalid_text'):
        transform(raw)


def test_empty_block_is_refused():
    with pytest.raises(ValueError, match='expected_single_python_fence'):
        transform('```python\n```')


@pytest.mark.parametrize('separator', ['\r', '\v', '\f', '\x85', '\u2028', '\u2029'],
                         ids=['bare-cr', 'vertical-tab', 'form-feed', 'nel', 'line-separator', 'paragraph-separator'])
def test_non_lf_line_separators_cannot_delimit_the_closing_fence(separator):
    with pytest.raises(ValueError, match='expected_single_python_fence'):
        transform('```python\npass' + separator + '```')


def test_unicode_inside_body_is_preserved_without_becoming_a_delimiter():
    body = 'value = "\u00e9\u2028literal"\n'
    assert transform('```python\n' + body + '```').source == body


@pytest.mark.parametrize('character', ['x', '\u00e9'], ids=['ascii', 'utf8'])
def test_raw_utf8_byte_limit(character):
    raw = '```python\n#' + character * (128 * 1024) + '\n```'
    with pytest.raises(ValueError, match='text_too_large'):
        transform(raw)


def test_byte_limit_is_inclusive():
    envelope = '```python\n\n```'
    raw = '```python\n' + 'x' * (128 * 1024 - len(envelope)) + '\n```'
    assert len(raw.encode()) == 128 * 1024
    assert transform(raw).source.endswith('\n')


def test_private_source_and_original_are_opt_in_and_snapshots_detached():
    raw = '```python\nprint("PRIVATE_CONTENT")\n```'
    derived = transform(raw)
    summary = derived.to_dict()
    assert 'PRIVATE_CONTENT' not in json.dumps(summary) and 'PRIVATE_CONTENT' not in repr(derived)
    assert 'source' not in summary and 'text' not in summary['generation']
    exported = derived.to_dict(include_text=True)
    assert exported['source'] == derived.source and exported['generation']['text'] == raw
    exported['generation']['provider_usage']['output_tokens'] = 99
    assert derived.generation.provider_usage.output_tokens is None
    with pytest.raises(FrozenInstanceError):
        derived.source = 'changed'
    with pytest.raises(FrozenInstanceError):
        derived.generation.text = 'changed'


@pytest.mark.parametrize('value', [None, 0, 1, 'yes', []])
def test_export_requires_boolean_opt_in(value):
    with pytest.raises(ValueError, match='include_text_must_be_boolean'):
        transform('```python\npass\n```').to_dict(include_text=value)


def test_original_record_is_not_upgraded_or_mutated():
    result = observation('```python\nprint(1)\n```')
    before = record_generation('integer-sum', result, expected_corpus_sha256=corpus_digest(), prompt_version='v2')
    derived = unwrap_generation_source('integer-sum', result, expected_corpus_sha256=corpus_digest(), prompt_version='v2')
    after = record_generation('integer-sum', result, expected_corpus_sha256=corpus_digest(), prompt_version='v2')
    assert before == after and after['status'] == 'invalid_source'
    assert derived.generation is result


@pytest.mark.parametrize('field,value,reason', [
    ('text', '```python\nprint(2)\n```', 'binding_mismatch'),
    ('response_sha256', '0' * 64, 'binding_mismatch'),
    ('prompt_sha256', '0' * 64, 'binding_mismatch'),
    ('request_sha256', '0' * 64, 'request_mismatch'),
    ('max_tokens', 1, 'request_mismatch'), ('seed', 8, 'request_mismatch'),
])
def test_mixed_observations_are_refused(field, value, reason):
    modified = replace(observation('```python\npass\n```'), **{field: value})
    with pytest.raises(ValueError, match=reason):
        unwrap_generation_source('integer-sum', modified, expected_corpus_sha256=corpus_digest(), prompt_version='v2')


@pytest.mark.parametrize('task,version,digest,reason', [
    ('integer-sum', 'v1', None, 'binding_mismatch'),
    ('integer-sum', 'v6', None, 'prompt_version'),
    ('integer-sum', 'v5', None, 'not_applicable'),
    ('integer-sum', 'v4', None, 'not_applicable'),
    ('integer-sum', 'v2', '0' * 64, 'corpus_mismatch'),
    ('dot-product', 'v2', None, 'binding_mismatch'),
])
def test_task_version_and_corpus_are_bound(task, version, digest, reason):
    with pytest.raises(ValueError, match=reason):
        unwrap_generation_source(task, observation('```python\npass\n```'),
                                 expected_corpus_sha256=digest or corpus_digest(), prompt_version=version)


def test_decision_observations_cannot_become_source():
    result = observation('```python\npass\n```', task='refuse-network')
    with pytest.raises(ValueError, match='requires_source'):
        unwrap_generation_source('refuse-network', result, expected_corpus_sha256=corpus_digest(), prompt_version='v2')
    result = observation('```python\npass\n```', mode='decision')
    with pytest.raises(ValueError, match='binding_mismatch'):
        unwrap_generation_source('integer-sum', result, expected_corpus_sha256=corpus_digest(), prompt_version='v2')


def test_requires_a_measured_result():
    with pytest.raises(ValueError, match='generation_result_required'):
        unwrap_generation_source('integer-sum', {}, expected_corpus_sha256=corpus_digest(), prompt_version='v2')


def test_invalid_or_dangerous_body_is_not_compiled_or_executed(tmp_path):
    marker = tmp_path / 'must-not-exist'
    for body in ['def invalid(:\n', f"__import__('pathlib').Path({str(marker)!r}).write_text('no')\n",
                 'raise RuntimeError("PRIVATE_RUNTIME")\n', 'x = "inline ``` remains"\n']:
        derived = transform('```python\n' + body + '```')
        assert derived.source == body and derived.to_dict()['syntax_valid'] is None
    assert not marker.exists()


@pytest.mark.parametrize('value,reason', [(None, 'invalid_text'), (1, 'invalid_text'),
                                         ([], 'invalid_text'), ('\ud800', 'invalid_text_encoding')],
                         ids=['none', 'integer', 'list', 'surrogate'])
def test_invalid_text_has_fixed_errors_without_provider_content(value, reason):
    result = replace(observation('```python\npass\n```'), text=value)
    with pytest.raises(ValueError, match=reason):
        unwrap_generation_source('integer-sum', result, expected_corpus_sha256=corpus_digest(), prompt_version='v2')
