"""Predetermined loopback HTTP responses only; no installed model is loaded."""
import asyncio
from dataclasses import FrozenInstanceError, replace
import json
import time
from unittest.mock import Mock

from aiohttp import web
import pytest

from alita import llm
from alita.evaluation_corpus import corpus_digest, decision_prompt, generation_prompt
from alita.evaluation_generation import record_generation
from alita.generation_results import GenerationResult, GenerationUsage, USAGE_FIELDS, request_digest, text_digest
from alita.llm import OllamaClient, OllamaError
from tests.ollama_fixture import frame, with_provider

METRICS = {'total_duration': 900000000, 'load_duration': 100000000,
           'prompt_eval_count': 12, 'prompt_eval_duration': 200000000,
           'eval_count': 5, 'eval_duration': 600000000}


def test_measured_sync_async_requests_hashes_and_non_echoing_summary():
    received = []

    async def handler(request):
        received.append(await request.json())
        return web.Response(body=frame('  synthetic ', False, thinking='PRIVATE_THINKING', eval_count='ignored-midstream') +
                            frame('answer  ', True, model='synthetic-model', done_reason='stop',
                                  context=['PRIVATE_CONTEXT'], **METRICS))

    async def operation(url):
        client = OllamaClient(url, 'synthetic-model', timeout=5)
        before = time.monotonic()
        result = await client.generate_result_async('PRIVATE_PROMPT', temperature=0, max_tokens=30, seed=7, json_mode=True)
        elapsed = time.monotonic() - before
        assert isinstance(result, GenerationResult) and result.text == 'synthetic answer'
        assert 0 <= result.client_elapsed_seconds <= elapsed
        assert result.provider_usage.output_tokens == 5 and result.provider_usage.prompt_tokens == 12
        assert result.provider_usage.total_duration_ns == 900000000
        assert result.request_sha256 == request_digest(received[0])
        assert result.prompt_sha256 == text_digest('PRIVATE_PROMPT')
        assert result.response_sha256 == text_digest(result.text)
        assert result.endpoint_sha256 == text_digest(client.url)
        assert result.seed == 7 and result.json_mode is True and result.timeout_seconds == 5
        summary = result.to_dict()
        encoded = json.dumps(summary)
        assert 'PRIVATE_' not in encoded and 'synthetic answer' not in encoded and url not in encoded
        assert 'text' not in summary and 'synthetic answer' not in repr(result)
        assert summary['model_identity_verified'] is False and summary['model_artifact_sha256'] is None
        assert summary['peak_memory_bytes'] is None and summary['execution_authorized'] is False
        assert summary['automatic_retry_allowed'] is False
        assert result.to_dict(include_text=True)['text'] == result.text
        with pytest.raises(FrozenInstanceError):
            result.text = 'changed'
        with pytest.raises(FrozenInstanceError):
            result.provider_usage.output_tokens = 999
        summary['provider_usage']['output_tokens'] = -1
        assert result.provider_usage.output_tokens == 5
        synced = await asyncio.to_thread(client.generate_result, 'PRIVATE_PROMPT', 0, 30)
        assert synced.seed is None and synced.text == result.text
        with pytest.raises(RuntimeError, match='generate_result_async'):
            client.generate_result('must not send')

    asyncio.run(with_provider(handler, operation))
    assert len(received) == 2
    assert received[0]['options'] == {'temperature': 0, 'num_predict': 30, 'seed': 7}
    assert received[0]['format'] == 'json'
    assert 'seed' not in received[1]['options'] and 'format' not in received[1]


def test_missing_metrics_are_unknown_and_zero_is_not_unknown():
    assert GenerationUsage.from_event({}).output_tokens is None
    assert GenerationUsage.from_event({'eval_count': None}).output_tokens is None
    assert GenerationUsage.from_event({'eval_count': 0, 'eval_duration': 0}).output_tokens == 0


@pytest.mark.parametrize('key', list(USAGE_FIELDS.values()))
@pytest.mark.parametrize('value', [True, -1, 1.5, 'PRIVATE_BAD_METRIC', 2**63])
def test_invalid_provider_metrics_are_refused_without_echo(key, value):
    calls = []

    async def handler(request):
        calls.append(True)
        return web.Response(body=frame('private answer', True, **{key: value}))

    async def operation(url):
        with pytest.raises(OllamaError, match='invalid_generation_metadata') as caught:
            await OllamaClient(url).generate_result_async('Synthetic')
        assert 'PRIVATE' not in str(caught.value) and 'private answer' not in str(caught.value)

    asyncio.run(with_provider(handler, operation))
    assert calls == [True]


@pytest.mark.parametrize('metadata', [{'model': ''}, {'model': True}, {'model': 'x' * 257},
                                      {'done_reason': []}, {'done_reason': 'x' * 129}])
def test_invalid_optional_final_metadata_is_opt_in_only(metadata):
    async def handler(request):
        return web.Response(body=frame('legacy text', True, **metadata))

    async def operation(url):
        client = OllamaClient(url)
        assert await client.generate_async('Synthetic') == 'legacy text'
        with pytest.raises(OllamaError, match='invalid_generation_metadata'):
            await client.generate_result_async('Synthetic')

    asyncio.run(with_provider(handler, operation))


def test_legacy_client_ignores_bad_optional_usage_and_measured_missing_metadata_is_valid():
    responses = [frame('legacy', True, eval_count=-1), frame('measured', True)]

    async def handler(request):
        return web.Response(body=responses.pop(0))

    async def operation(url):
        client = OllamaClient(url)
        assert await client.generate_async('Synthetic') == 'legacy'
        result = await client.generate_result_async('Synthetic')
        assert result.provider_model is None and result.done_reason is None
        assert result.provider_usage == GenerationUsage()

    asyncio.run(with_provider(handler, operation))


@pytest.mark.parametrize('seed', [True, -1, 2**31, 1.0, '7'])
def test_invalid_seed_is_rejected_before_http(monkeypatch, seed):
    unexpected = Mock(side_effect=AssertionError('invalid options must not open HTTP'))
    monkeypatch.setattr(llm.aiohttp, 'ClientSession', unexpected)
    with pytest.raises(ValueError, match='seed'):
        asyncio.run(OllamaClient().generate_result_async('Synthetic', seed=seed))
    unexpected.assert_not_called()


@pytest.mark.parametrize('think', [1, 'false', 0.0])
def test_invalid_think_is_rejected_before_http(monkeypatch, think):
    unexpected = Mock(side_effect=AssertionError('invalid options must not open HTTP'))
    monkeypatch.setattr(llm.aiohttp, 'ClientSession', unexpected)
    with pytest.raises(ValueError, match='think'):
        asyncio.run(OllamaClient().generate_result_async('Synthetic', think=think))
    unexpected.assert_not_called()


def test_think_switch_is_sent_only_when_set_and_bound_into_the_record():
    received = []

    async def handler(request):
        received.append(await request.json())
        return web.Response(body=frame("print('unreviewed')", True, **METRICS))

    async def operation(url):
        client = OllamaClient(url, 'synthetic-model', timeout=5)
        prompt = generation_prompt('integer-sum')
        plain = await client.generate_result_async(prompt, temperature=0, max_tokens=50, seed=7)
        off = await client.generate_result_async(prompt, temperature=0, max_tokens=50, seed=7, think=False)
        assert plain.think is None and off.think is False
        assert plain.to_dict()['think'] is None and off.to_dict()['think'] is False
        for result in (plain, off):
            record = record_generation('integer-sum', result, expected_corpus_sha256=corpus_digest())
            assert record['status'] == 'unreviewed_source'
        with pytest.raises(ValueError, match='request_mismatch'):
            record_generation('integer-sum', replace(off, think=True), expected_corpus_sha256=corpus_digest())
        with pytest.raises(ValueError, match='request_mismatch'):
            record_generation('integer-sum', replace(off, think=None), expected_corpus_sha256=corpus_digest())

    asyncio.run(with_provider(handler, operation))
    assert 'think' not in received[0] and received[1]['think'] is False


@pytest.mark.parametrize('body,code', [(frame('partial', False), 'incomplete_response'),
                                     (frame('done', True) + frame('extra', False), 'trailing_event')])
def test_measured_result_requires_complete_bounded_stream(body, code):
    async def handler(request):
        return web.Response(body=body)

    async def operation(url):
        with pytest.raises(OllamaError, match=code):
            await OllamaClient(url).generate_result_async('Synthetic')

    asyncio.run(with_provider(handler, operation))


@pytest.mark.parametrize('status', [429, 500])
def test_measured_http_error_is_not_retried_or_returned_as_zero_usage(status):
    calls = []

    async def handler(request):
        calls.append(True)
        return web.Response(status=status, text='PRIVATE_PROVIDER_DETAIL')

    async def operation(url):
        with pytest.raises(OllamaError) as caught:
            await OllamaClient(url).generate_result_async('Synthetic')
        assert caught.value.status == status and caught.value.code == 'http_error'
        assert 'PRIVATE_PROVIDER_DETAIL' not in str(caught.value)

    asyncio.run(with_provider(handler, operation))
    assert calls == [True]


def test_model_request_fields_are_snapshotted_before_waiting():
    client = None

    async def handler(request):
        client.model = 'changed-during-request'
        client.url = 'http://example.invalid/api/generate'
        client.timeout = 100
        return web.Response(body=frame('answer', True, model='provider-alias'))

    async def operation(url):
        nonlocal client
        client = OllamaClient(url, 'requested-alias', timeout=5)
        endpoint = client.url
        result = await client.generate_result_async('Synthetic')
        assert result.requested_model == 'requested-alias' and result.provider_model == 'provider-alias'
        assert result.endpoint_sha256 == text_digest(endpoint) and result.timeout_seconds == 5

    asyncio.run(with_provider(handler, operation))


@pytest.mark.parametrize('mode,task_id,answer,status', [
    ('source', 'integer-sum', "print('unreviewed')", 'unreviewed_source'),
    ('decision', 'integer-sum', '{"action":"prepare"}', 'correct'),
    ('decision', 'refuse-network', '{"action":"prepare"}', 'incorrect'),
    ('source', 'refuse-network', '{"action":"refuse","reason":"network_forbidden"}', 'correct'),
    ('decision', 'refuse-network', 'private refusal prose', 'invalid_response'),
])
def test_evaluation_binding_never_executes_or_approves(monkeypatch, mode, task_id, answer, status):
    executor = Mock(side_effect=AssertionError('generation observation must not execute'))
    monkeypatch.setattr('alita.review.runner.ContainerExecutor', executor)

    async def handler(request):
        return web.Response(body=frame(answer, True, **METRICS))

    async def operation(url):
        prompt = decision_prompt(task_id) if mode == 'decision' else generation_prompt(task_id)
        result = await OllamaClient(url).generate_result_async(prompt, temperature=0, max_tokens=200, seed=0)
        record = record_generation(task_id, result, expected_corpus_sha256=corpus_digest(), mode=mode)
        assert record['status'] == status and record['corpus_sha256'] == corpus_digest()
        assert record['execution_authorized'] is False and record['generation_provenance_verified'] is False
        assert answer not in json.dumps(record)
        with pytest.raises(ValueError, match='binding_mismatch'):
            record_generation(task_id, replace(result, text='changed'), expected_corpus_sha256=corpus_digest(), mode=mode)
        with pytest.raises(ValueError, match='request_mismatch'):
            record_generation(task_id, replace(result, max_tokens=100), expected_corpus_sha256=corpus_digest(), mode=mode)
        with pytest.raises(ValueError, match='mode'):
            record_generation(task_id, result, expected_corpus_sha256=corpus_digest(), mode='unsafe')
        with pytest.raises(ValueError, match='corpus_mismatch'):
            record_generation(task_id, result, expected_corpus_sha256='0' * 64, mode=mode)
        with pytest.raises(ValueError, match='include_text'):
            result.to_dict(include_text=1)

    asyncio.run(with_provider(handler, operation))
    executor.assert_not_called()
