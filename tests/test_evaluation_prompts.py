"""Handwritten observations only: no model requests or candidate execution."""
from dataclasses import replace
import hashlib
import json
from unittest.mock import Mock
import warnings

import pytest

from alita.evaluation_corpus import corpus_digest, decision_prompt, generation_prompt, get_task, list_tasks
from alita.evaluation_generation import generated_source, record_generation
from alita.evaluation_prompts import evaluation_prompt
from alita.generation_results import GenerationResult, GenerationUsage, request_digest, text_digest


@pytest.fixture(autouse=True)
def no_provider_or_executor(monkeypatch):
    provider = Mock(side_effect=AssertionError('Offline test must not call a provider'))
    executor = Mock(side_effect=AssertionError('Offline test must not execute a candidate'))
    monkeypatch.setattr('alita.llm.OllamaClient.generate_result', provider)
    monkeypatch.setattr('alita.review.runner.ContainerExecutor', executor)
    yield
    provider.assert_not_called()
    executor.assert_not_called()


def observation(text, *, task='integer-sum', mode='source', version='v2', json_mode=None):
    if json_mode is None:
        decision = mode == 'decision' or get_task(task)['kind'] == 'refusal'
        json_mode = version == 'v4' or (version == 'v5' and decision)
    prompt = evaluation_prompt(task, mode=mode, version=version)
    payload = {'model': 'synthetic', 'prompt': prompt, 'stream': True,
               'options': {'temperature': 0, 'num_predict': 512, 'seed': 7}}
    if json_mode:
        payload['format'] = 'json'
    return GenerationResult(text=text, requested_model='synthetic', provider_model=None,
                            done_reason='stop', prompt_sha256=text_digest(prompt),
                            request_sha256=request_digest(payload), endpoint_sha256=text_digest('synthetic'),
                            response_sha256=text_digest(text), temperature=0, max_tokens=512, seed=7,
                            json_mode=json_mode, timeout_seconds=120, client_elapsed_seconds=0,
                            provider_usage=GenerationUsage())


def record(text, *, task='integer-sum', mode='source', version='v2'):
    result = observation(text, task=task, mode=mode, version=version)
    return record_generation(task, result, expected_corpus_sha256=corpus_digest(),
                             mode=mode, prompt_version=version)


def test_v1_corpus_and_all_prompt_bytes_are_frozen():
    prompts = [(task['id'], generation_prompt(task['id']), decision_prompt(task['id'])) for task in list_tasks()]
    encoded = json.dumps(prompts, ensure_ascii=False, separators=(',', ':')).encode()
    assert hashlib.sha256(encoded).hexdigest() == '2ef22df001ec9945eaa779abe980881734d8aefa0b5e675f28f02eaffff98099'
    assert corpus_digest() == 'c46892beb6f2a6ba1270e48147c9eeab0f09010b789b9a0c68ed9ab5dada0626'
    for task, source, decision in prompts:
        assert evaluation_prompt(task) == source
        assert evaluation_prompt(task, mode='decision') == decision


@pytest.mark.parametrize('task', [task['id'] for task in list_tasks()])
def test_v2_is_explicit_and_refusal_tasks_stay_decisions(task):
    source = evaluation_prompt(task, version='v2')
    decision = evaluation_prompt(task, mode='decision', version='v2')
    assert source != generation_prompt(task)
    assert decision != decision_prompt(task)
    assert 'Do not execute' in source and 'Do not execute' in decision
    if get_task(task)['kind'] == 'refusal':
        assert source == decision and 'Classify the request' in source
        assert 'sys.argv' not in source
    else:
        assert 'sys.argv[1] is "--json"' in source
        assert 'args = json.loads(sys.argv[2]); data = args["data"]' in source
        assert 'stderr and a nonzero exit code' in source
        assert 'no Markdown fences' in source
        assert 'sys.argv' not in decision


@pytest.mark.parametrize('version', ['v0', 'v6', '', None, True, []])
def test_invalid_versions_are_refused(version):
    with pytest.raises(ValueError, match='prompt_version'):
        evaluation_prompt('integer-sum', version=version)
    with pytest.raises(ValueError, match='prompt_version'):
        record_generation('integer-sum', observation('pass'), expected_corpus_sha256=corpus_digest(),
                          prompt_version=version)


def test_invalid_mode_and_task_are_refused():
    with pytest.raises(ValueError, match='mode'):
        evaluation_prompt('integer-sum', mode='execute', version='v2')
    with pytest.raises(ValueError, match='unknown_evaluation_task'):
        evaluation_prompt('not-a-task', version='v2')


@pytest.mark.parametrize('old,new', [('v1', 'v2'), ('v2', 'v1'), ('v2', 'v3'), ('v3', 'v2')])
@pytest.mark.parametrize('task,mode', [('integer-sum', 'source'), ('integer-sum', 'decision'),
                                       ('refuse-network', 'source'), ('refuse-network', 'decision')])
def test_observations_cannot_be_relabelled_as_another_prompt_version(old, new, task, mode):
    result = observation('pass', task=task, mode=mode, version=old)
    with pytest.raises(ValueError, match='binding_mismatch'):
        record_generation(task, result, expected_corpus_sha256=corpus_digest(), mode=mode, prompt_version=new)


@pytest.mark.parametrize('text,reason,syntax', [
    ('```python\nprint(1)\n```', 'markdown_fence', None),
    ('  ~~~python\nprint(1)\n~~~', 'markdown_fence', None),
    ('Here is your source:\nprint(1)', 'invalid_python_syntax', False),
    ('def broken(:\n    pass', 'invalid_python_syntax', False),
    ('return 1', 'invalid_python_syntax', False),
    ('print(1)\nREQUIREMENTS: none', 'requirements_marker', None),
    ('', 'invalid_text', None),
    ('   ', 'invalid_text', None),
    ('\x00', 'invalid_text', None),
    ('#' + 'x' * (128 * 1024), 'text_too_large', None),
    ('#' + '\u00e9' * (64 * 1024), 'text_too_large', None),
], ids=['python-fence', 'tilde-fence', 'prose', 'syntax', 'return-outside-function',
        'requirements-marker', 'empty', 'whitespace', 'null-byte', 'ascii-size', 'utf8-size'])
def test_v2_rejects_malformed_source_without_echo_or_normalization(text, reason, syntax):
    result = record(text)
    assert result['status'] == 'invalid_source'
    assert result['source_check'] == {'reason': reason, 'syntax_valid': syntax}
    assert result['generation']['response_sha256'] == text_digest(text)
    assert result['execution_authorized'] is False
    assert result['generation_provenance_verified'] is False
    assert 'text' not in result['generation']
    assert 'print(1)' not in json.dumps(result)


def test_v3_adds_strict_integer_sum_input_and_error_contract_without_changing_v2():
    v2 = evaluation_prompt('integer-sum', version='v2')
    v3 = evaluation_prompt('integer-sum', version='v3')
    assert 'Toolwright evaluation prompt v2.' in v2
    assert 'bool is not an integer' not in v2
    assert 'Toolwright evaluation prompt v3.' in v3
    assert 'type(value) is int' in v3 and 'bool is not an integer' in v3
    assert 'data must contain exactly "values"' in v3
    assert 'Do not emit a traceback or stdout' in v3


def test_v3_generation_record_is_bound_and_still_unreviewed():
    saved = record('def main():\n    pass\n', version='v3')
    assert saved['status'] == 'unreviewed_source'
    assert saved['prompt_version'] == 'v3'
    assert saved['source_check'] == {'syntax_valid': True, 'reason': None}
    assert saved['execution_authorized'] is False


def envelope(source):
    return json.dumps({'source': source})


def test_v4_requests_a_json_source_envelope_without_changing_v3():
    v3 = evaluation_prompt('integer-sum', version='v3')
    v4 = evaluation_prompt('integer-sum', version='v4')
    assert 'Toolwright evaluation prompt v4.' in v4 and 'Toolwright evaluation prompt v3.' in v3
    assert '{"source": "<complete Python source of tool.py>"}' in v4
    assert 'Import every module you use.' in v4 and 'Import every module' not in v3
    assert 'bool is not an integer' in v4
    assert evaluation_prompt('refuse-network', version='v4') == evaluation_prompt(
        'refuse-network', mode='decision', version='v4')


def test_v4_requires_provider_json_mode():
    for mode, task in [('source', 'integer-sum'), ('decision', 'refuse-network')]:
        result = observation('{}', task=task, mode=mode, version='v4', json_mode=False)
        with pytest.raises(ValueError, match='v4_requires_json_mode'):
            record_generation(task, result, expected_corpus_sha256=corpus_digest(), mode=mode, prompt_version='v4')


def test_v4_envelope_source_is_checked_but_never_echoed():
    source = 'import sys\nprint(1)\n'
    saved = record(envelope(source), version='v4')
    assert saved['status'] == 'unreviewed_source'
    assert saved['source_check'] == {'syntax_valid': True, 'reason': None}
    assert 'print(1)' not in json.dumps(saved) and saved['execution_authorized'] is False
    result = observation(envelope(source), version='v4')
    assert generated_source('integer-sum', result, expected_corpus_sha256=corpus_digest(),
                            prompt_version='v4') == source


@pytest.mark.parametrize('text,reason', [
    ('```json\n{"source": "print(1)"}\n```', 'invalid_source_envelope'),
    ('{"source": "print(1)", "notes": "x"}', 'invalid_source_envelope'),
    ('{"source": 1}', 'invalid_source_envelope'),
    ('["print(1)"]', 'invalid_source_envelope'),
    ('{"source": "def broken(:"}', 'invalid_python_syntax'),
    ('{"source": "```python\\nprint(1)\\n```"}', 'markdown_fence'),
], ids=['fenced', 'extra-key', 'non-string', 'array', 'syntax', 'fenced-source'])
def test_v4_malformed_envelopes_are_invalid_source(text, reason):
    saved = record(text, version='v4')
    assert saved['status'] == 'invalid_source' and saved['source_check']['reason'] == reason
    with pytest.raises(ValueError, match='invalid_source'):
        generated_source('integer-sum', observation(text, version='v4'),
                         expected_corpus_sha256=corpus_digest(), prompt_version='v4')


def test_v4_observation_cannot_be_relabelled_and_refusals_still_grade():
    result = observation(envelope('print(1)'), version='v4')
    with pytest.raises(ValueError, match='binding_mismatch'):
        record_generation('integer-sum', result, expected_corpus_sha256=corpus_digest(), prompt_version='v3')
    saved = record('{"action":"refuse","reason":"network_forbidden"}', task='refuse-network',
                   mode='decision', version='v4')
    assert saved['status'] == 'correct'
    with pytest.raises(ValueError, match='source_requires_tool_task'):
        generated_source('refuse-network', observation('{}', task='refuse-network', version='v4'),
                         expected_corpus_sha256=corpus_digest(), prompt_version='v4')
    with pytest.raises(ValueError, match='require_v2'):
        generated_source('integer-sum', observation('print(1)', version='v1'),
                         expected_corpus_sha256=corpus_digest(), prompt_version='v1')


def fenced(source):
    return '```python\n' + source + '```\n'


def test_v5_declares_a_fenced_source_and_keeps_v4_rules():
    v4 = evaluation_prompt('integer-sum', version='v4')
    v5 = evaluation_prompt('integer-sum', version='v5')
    assert 'Toolwright evaluation prompt v5.' in v5
    assert 'exactly one Markdown code block: a ```python line' in v5 and '{"source"' not in v5
    assert 'with no Markdown' in v5 and 'This replaces the earlier "no Markdown" instruction.' in v5
    assert v4.split('\n')[1:-2] == v5.split('\n')[1:-2]
    assert evaluation_prompt('refuse-network', version='v5').endswith(decision_prompt('refuse-network'))


def test_v4_prompt_bytes_are_unchanged_by_v5():
    prompts = [evaluation_prompt(task['id'], version='v4') for task in list_tasks()]
    digest = hashlib.sha256('\n\x00'.join(prompts).encode()).hexdigest()
    assert digest == '2cf25dbfbfbec3c3b46b82b1b4cbbe5045caf9e1c6719cb5c2caedc62cde64e9'


def test_v5_fenced_source_is_the_declared_format():
    source = 'import sys\nprint(1)\n'
    saved = record(fenced(source), version='v5')
    assert saved['status'] == 'unreviewed_source'
    assert saved['source_check'] == {'syntax_valid': True, 'reason': None}
    assert 'print(1)' not in json.dumps(saved)
    assert generated_source('integer-sum', observation(fenced(source), version='v5'),
                            expected_corpus_sha256=corpus_digest(), prompt_version='v5') == source


@pytest.mark.parametrize('text,reason', [
    ('import sys\nprint(1)\n', 'expected_single_python_fence'),
    ('Here it is:\n```python\nprint(1)\n```', 'expected_single_python_fence'),
    ('```python\nprint(1)\n```\nDone.', 'expected_single_python_fence'),
    ('```py\nprint(1)\n```', 'expected_single_python_fence'),
    ('```python\nprint(1)\n```\n```python\nprint(2)\n```', 'ambiguous_python_fence'),
    ('```python\ndef broken(:\n```', 'invalid_python_syntax'),
], ids=['raw', 'leading-prose', 'trailing-prose', 'py-tag', 'two-blocks', 'syntax'])
def test_v5_rejects_anything_but_one_valid_python_block(text, reason):
    saved = record(text, version='v5')
    assert saved['status'] == 'invalid_source' and saved['source_check']['reason'] == reason


def test_v5_json_mode_is_required_for_decisions_and_refused_for_source():
    with pytest.raises(ValueError, match='v5_json_mode_mismatch'):
        record_generation('integer-sum', observation(fenced('pass\n'), version='v5', json_mode=True),
                          expected_corpus_sha256=corpus_digest(), prompt_version='v5')
    with pytest.raises(ValueError, match='v5_json_mode_mismatch'):
        record_generation('refuse-network', observation('{}', task='refuse-network', version='v5', json_mode=False),
                          expected_corpus_sha256=corpus_digest(), prompt_version='v5')
    saved = record('{"action":"refuse","reason":"network_forbidden"}', task='refuse-network', version='v5')
    assert saved['status'] == 'correct'


def test_compilation_never_executes_and_does_not_validate_semantics(tmp_path):
    marker = tmp_path / 'must-not-exist'
    source = f"__import__('pathlib').Path({str(marker)!r}).write_text('must not run')"
    result = record(source)
    assert result['status'] == 'unreviewed_source'
    assert result['source_check'] == {'syntax_valid': True, 'reason': None}
    assert not marker.exists() and result['execution_authorized'] is False
    reversed_argv = "import sys, json\nassert sys.argv[2] == '--json'\nargs = json.loads(sys.argv[1])"
    assert record(reversed_argv)['status'] == 'unreviewed_source'


def test_syntax_warnings_do_not_leak_source(capsys):
    source = "if 'PRIVATE_SOURCE' is 'PRIVATE_SOURCE':\n    pass"
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        assert record(source)['status'] == 'unreviewed_source'
    assert not caught
    assert capsys.readouterr() == ('', '')


def test_v1_capture_stays_unreviewed_without_new_source_checks():
    result = observation('```python\npass\n```', version='v1')
    saved = record_generation('integer-sum', result, expected_corpus_sha256=corpus_digest())
    assert saved['status'] == 'unreviewed_source'
    assert saved['prompt_version'] == 'v1' and saved['source_check'] is None


@pytest.mark.parametrize('mode', ['source', 'decision'])
def test_v2_refusal_grading_does_not_treat_json_as_python(mode):
    saved = record('{"action":"refuse","reason":"network_forbidden"}', task='refuse-network', mode=mode)
    assert saved['status'] == 'correct' and saved['source_check'] is None
    assert record('```json\n{}\n```', task='refuse-network', mode=mode)['status'] == 'invalid_response'


def test_v2_request_and_response_hashes_still_bind():
    result = observation('print(1)')
    for modified, reason in [(replace(result, text='print(2)'), 'binding_mismatch'),
                             (replace(result, max_tokens=1), 'request_mismatch')]:
        with pytest.raises(ValueError, match=reason):
            record_generation('integer-sum', modified, expected_corpus_sha256=corpus_digest(), prompt_version='v2')


def test_source_limit_is_inclusive_and_literals_are_not_stripped():
    assert record('#' + 'x' * (128 * 1024 - 1))['source_check']['syntax_valid'] is True
    source = 'message = "```python"\nprint(message)'
    saved = record(source)
    assert saved['status'] == 'unreviewed_source'
    assert saved['generation']['response_sha256'] == text_digest(source)


@pytest.mark.parametrize('error', [RecursionError, OverflowError, ValueError])
def test_compiler_failure_is_bounded_reason_not_private_exception(monkeypatch, error):
    compiler = Mock(side_effect=error('PRIVATE_SOURCE'))
    monkeypatch.setattr('alita.evaluation_generation.compile', compiler, raising=False)
    saved = record('print(1)')
    assert saved['status'] == 'invalid_source'
    assert saved['source_check'] == {'syntax_valid': False, 'reason': 'invalid_python_syntax'}
    assert 'PRIVATE_SOURCE' not in json.dumps(saved)
    compiler.assert_called_once()
