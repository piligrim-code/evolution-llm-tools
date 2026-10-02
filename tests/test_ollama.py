import asyncio
import json
import time

from aiohttp import web
import pytest

from alita import llm
from alita.config import settings
from alita.llm import MAX_BODY, MAX_EVENTS, MAX_LINE, MAX_TEXT, OllamaClient, OllamaError
from tests.ollama_fixture import frame, with_provider


def test_actual_request_defaults_json_mode_utf8_and_sync_wrapper(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setattr(settings, "max_tokens", 321)
    received = []
    async def handler(request):
        received.append(await request.json())
        assert request.headers["Accept-Encoding"] == "identity"
        return web.Response(body=frame("\u041f\u0440\u0438", False) + frame("\u0432\u0435\u0442", True).rstrip(b"\n"))
    async def operation(url):
        client = OllamaClient(url, "synthetic-model")
        assert await client.generate_async("Synthetic prompt", json_mode=True) == "\u041f\u0440\u0438\u0432\u0435\u0442"
        assert await asyncio.to_thread(client.generate, "Synthetic prompt", max_tokens=42) == "\u041f\u0440\u0438\u0432\u0435\u0442"
        with pytest.raises(RuntimeError, match="generate_async"):
            client.generate("must not open HTTP")
    asyncio.run(with_provider(handler, operation))
    assert received[0] == {"model": "synthetic-model", "prompt": "Synthetic prompt", "stream": True,
                           "format": "json", "options": {"temperature": settings.temperature, "num_predict": 321}}
    assert "format" not in received[1] and received[1]["options"]["num_predict"] == 42


@pytest.mark.parametrize("url", ["", "file:///tmp/model", "http://user:synthetic-secret@localhost", "http://localhost?key=synthetic",
                                "http://localhost/#fragment", "http://localhost:bad", "http://local host"])
def test_bad_endpoint_refused_without_echo(url):
    with pytest.raises(OllamaError, match="invalid_endpoint") as caught:
        OllamaClient(url)
    assert "synthetic" not in str(caught.value)


@pytest.mark.parametrize("value", [0, True, float("inf"), float("nan"), 301])
def test_bad_deadline_refused(value):
    with pytest.raises(ValueError):
        OllamaClient(timeout=value)


@pytest.mark.parametrize("options", [{"max_tokens": 0}, {"max_tokens": True}, {"max_tokens": 4097},
    {"temperature": float("nan")}, {"temperature": True}, {"temperature": -1}, {"json_mode": "true"}])
def test_invalid_generation_options_fail_before_session(monkeypatch, options):
    def unexpected(**kwargs):
        pytest.fail("Invalid options opened a session")
    monkeypatch.setattr(llm.aiohttp, "ClientSession", unexpected)
    with pytest.raises(ValueError):
        asyncio.run(OllamaClient().generate_async("Synthetic", **options))


@pytest.mark.parametrize("status", [301, 307, 401, 404, 429, 500])
def test_http_errors_are_sanitized_not_followed_or_retried(status):
    calls = []
    async def handler(request):
        calls.append(True)
        return web.Response(status=status, text="synthetic-private-detail", headers={"Location": "/api/generate"})
    async def operation(url):
        with pytest.raises(OllamaError) as caught:
            await OllamaClient(url).generate_async("Synthetic")
        assert caught.value.code == "http_error" and caught.value.status == status
        assert "synthetic-private" not in str(caught.value)
    asyncio.run(with_provider(handler, operation))
    assert calls == [True]


@pytest.mark.parametrize("body,code", [
    (b'not JSON\n', "invalid_event"), (b'[]\n', "invalid_event"),
    (b'{"response":"private","done":1}\n', "invalid_event"),
    (b'{"response":3,"done":true}\n', "invalid_event"),
    (b'{"response":"x","done":false,"done":true}\n', "invalid_event"),
    (b'{"response":"x","done":true,"metric":1e999}\n', "invalid_event"),
    (b'{"response":"x","done":true,"thinking":[]}\n', "invalid_event"),
    (b'{"response":"\xff","done":true}\n', "invalid_event"),
    (b'{"error":"synthetic-private-detail"}\n', "provider_error"),
    (frame("partial", False), "incomplete_response"),
    (frame(" ", True), "empty_response"),
    (frame("first", True) + frame("extra", False), "trailing_event"),
])
def test_bad_stream_never_returns_partial_answer(body, code):
    async def handler(request):
        return web.Response(body=body)
    async def operation(url):
        with pytest.raises(OllamaError) as caught:
            await OllamaClient(url).generate_async("Synthetic")
        assert caught.value.code == code and "private" not in str(caught.value)
    asyncio.run(with_provider(handler, operation))


@pytest.mark.parametrize("kind", ["line", "text", "events", "length", "compression"])
def test_independent_response_bounds(kind):
    bodies = {"line": b" " * (MAX_LINE + 1),
              "text": frame("x" * (MAX_TEXT // 2 + 1)) * 2 + frame("", True),
              "events": frame() * (MAX_EVENTS + 1), "length": b"x" * (MAX_BODY + 1),
              "compression": b"synthetic"}
    expected = {"line": "line_too_large", "text": "text_too_large", "events": "too_many_events",
                "length": "response_too_large", "compression": "unsupported_encoding"}
    async def handler(request):
        return web.Response(body=bodies[kind], headers={"Content-Encoding": "gzip"} if kind == "compression" else {})
    async def operation(url):
        with pytest.raises(OllamaError) as caught:
            await OllamaClient(url).generate_async("Synthetic")
        assert caught.value.code == expected[kind]
    asyncio.run(with_provider(handler, operation))


def test_chunked_body_is_bounded_without_content_length():
    async def handler(request):
        response = web.StreamResponse()
        await response.prepare(request)
        try:
            chunk = frame("", False, padding="x" * 2048)
            for _ in range(MAX_BODY // len(chunk) + 2):
                await response.write(chunk)
            await response.write_eof()
        except ConnectionResetError:
            pass
        return response
    async def operation(url):
        with pytest.raises(OllamaError, match="response_too_large"):
            await OllamaClient(url).generate_async("Synthetic")
    asyncio.run(with_provider(handler, operation))


def test_slow_drip_has_total_deadline_and_closes_http(monkeypatch):
    sessions = []
    sent = []
    original = llm.aiohttp.ClientSession
    def tracked(**kwargs):
        session = original(**kwargs)
        sessions.append(session)
        return session
    monkeypatch.setattr(llm.aiohttp, "ClientSession", tracked)
    async def handler(request):
        response = web.StreamResponse()
        await response.prepare(request)
        try:
            for _ in range(100):
                await response.write(frame("x"))
                sent.append(True)
                # Keep the drip interval above the coarse Windows clock resolution.
                await asyncio.sleep(0.05)
        except ConnectionResetError:
            pass
        return response
    async def operation(url):
        started = time.monotonic()
        with pytest.raises(OllamaError) as caught:
            await OllamaClient(url, timeout=0.2).generate_async("Synthetic")
        assert caught.value.code == "timeout", (caught.value.code, time.monotonic() - started, len(sent))
        assert time.monotonic() - started < 2
        assert len(sessions) == 1 and sessions[0].closed
    asyncio.run(with_provider(handler, operation))


def test_cancellation_propagates_and_closes_session(monkeypatch):
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        sessions = []
        original = llm.aiohttp.ClientSession
        def tracked(**kwargs):
            session = original(**kwargs)
            sessions.append(session)
            return session
        monkeypatch.setattr(llm.aiohttp, "ClientSession", tracked)
        async def handler(request):
            entered.set()
            await release.wait()
            return web.Response(body=frame("Synthetic", True))
        async def operation(url):
            task = asyncio.create_task(OllamaClient(url).generate_async("Synthetic"))
            await asyncio.wait_for(entered.wait(), 2)
            task.cancel()
            try:
                with pytest.raises(asyncio.CancelledError):
                    await task
                assert len(sessions) == 1 and sessions[0].closed
            finally:
                release.set()
        await with_provider(handler, operation)
    asyncio.run(scenario())


def test_record_parser_handles_every_utf8_byte_boundary():
    parser = llm._Stream()
    for byte in frame("\u041f\u0440\u0438\u0432\u0435\u0442", True):
        parser.feed(bytes([byte]))
    assert parser.finish() == "\u041f\u0440\u0438\u0432\u0435\u0442"


def test_eof_transport_failure_closes_session_and_next_call_is_independent(monkeypatch):
    sessions, calls = [], []
    original = llm.aiohttp.ClientSession
    def tracked(**kwargs):
        session = original(**kwargs)
        sessions.append(session)
        return session
    monkeypatch.setattr(llm.aiohttp, "ClientSession", tracked)
    async def handler(request):
        calls.append(True)
        if len(calls) == 1:
            response = web.StreamResponse(headers={"Content-Length": "4096"})
            await response.prepare(request)
            await response.write(frame("partial", False))
            request.transport.close()
            return response
        return web.Response(body=frame("healthy next call", True))
    async def operation(url):
        client = OllamaClient(url)
        with pytest.raises(OllamaError, match="transport_error"):
            await client.generate_async("Synthetic")
        assert len(calls) == len(sessions) == 1 and sessions[0].closed
        assert await client.generate_async("Synthetic") == "healthy next call"
        assert len(calls) == len(sessions) == 2 and all(session.closed for session in sessions)
    asyncio.run(with_provider(handler, operation))
