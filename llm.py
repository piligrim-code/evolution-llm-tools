"""Bounded Ollama generation with strict NDJSON completion and owned HTTP cleanup."""
import asyncio
import math
from urllib.parse import urlsplit

import aiohttp

from .config import settings
from .contracts import ModelContractError, json_object, bounded_text

MAX_BODY = 1024 * 1024
MAX_LINE = 256 * 1024
MAX_TEXT = 128 * 1024
MAX_EVENTS = 8192


class OllamaError(RuntimeError):
    def __init__(self, code, status=None):
        self.code, self.status = code, status
        suffix = "" if status is None else f" (HTTP {status})"
        super().__init__(f"Ollama: {code}{suffix}; not retried")


def _endpoint(value):
    try:
        if not isinstance(value, str) or len(value) > 2048 or any(char.isspace() or ord(char) < 32 for char in value):
            raise ValueError()
        parsed = urlsplit(value)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment):
            raise ValueError()
        parsed.port
    except (ValueError, TypeError):
        raise OllamaError("invalid_endpoint") from None
    return value.rstrip("/") + "/api/generate"


class _Stream:
    def __init__(self):
        self.buffer = bytearray()
        self.total = self.text_size = self.events = 0
        self.done = False
        self.parts = []

    def _line(self, line):
        if len(line) > MAX_LINE:
            raise OllamaError("line_too_large")
        if not line.strip():
            return
        if self.done:
            raise OllamaError("trailing_event")
        self.events += 1
        if self.events > MAX_EVENTS:
            raise OllamaError("too_many_events")
        try:
            event = json_object(line, limit=MAX_LINE)
            if "error" in event:
                raise OllamaError("provider_error")
            if type(event.get("done")) is not bool:
                raise ModelContractError("invalid_done")
            if "thinking" in event and not isinstance(event["thinking"], str):
                raise ModelContractError("invalid_thinking")
            if not event["done"] and "response" not in event and "thinking" not in event:
                raise ModelContractError("missing_response")
            part = bounded_text(event.get("response", ""), MAX_TEXT, allow_empty=True)
        except ModelContractError:
            raise OllamaError("invalid_event") from None
        self.text_size += len(part.encode("utf-8"))
        if self.text_size > MAX_TEXT:
            raise OllamaError("text_too_large")
        self.parts.append(part)
        self.done = event["done"]

    def feed(self, data):
        self.total += len(data)
        if self.total > MAX_BODY:
            raise OllamaError("response_too_large")
        self.buffer.extend(data)
        while (end := self.buffer.find(b"\n")) >= 0:
            line = bytes(self.buffer[:end])
            del self.buffer[:end + 1]
            self._line(line)
        if len(self.buffer) > MAX_LINE:
            raise OllamaError("line_too_large")

    def finish(self):
        if self.buffer:
            self._line(bytes(self.buffer))
        if not self.done:
            raise OllamaError("incomplete_response")
        answer = "".join(self.parts).strip()
        if not answer:
            raise OllamaError("empty_response")
        return answer


class OllamaClient:
    def __init__(self, base_url=None, model=None, *, timeout=None):
        self.url = _endpoint(settings.ollama_url if base_url is None else base_url)
        self.model = bounded_text(settings.model if model is None else model, 256)
        self.timeout = settings.request_timeout if timeout is None else timeout
        if (type(self.timeout) not in (int, float) or not math.isfinite(self.timeout)
                or not 0 < self.timeout <= 300):
            raise ValueError("Ollama timeout must be a finite number in (0, 300]")

    def generate(self, prompt, temperature=None, max_tokens=None, *, json_mode=False):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.generate_async(prompt, temperature, max_tokens, json_mode=json_mode))
        raise RuntimeError("Use await generate_async() inside an event loop")

    async def generate_async(self, prompt, temperature=None, max_tokens=None, *, json_mode=False):
        bounded_text(prompt, 65536)
        temperature = settings.temperature if temperature is None else temperature
        max_tokens = settings.max_tokens if max_tokens is None else max_tokens
        if type(temperature) not in (int, float) or not math.isfinite(temperature) or not 0 <= temperature <= 2:
            raise ValueError("Temperature must be a finite number in [0, 2]")
        if type(max_tokens) is not int or not 1 <= max_tokens <= 4096:
            raise ValueError("max_tokens must be an integer in [1, 4096]")
        if type(json_mode) is not bool:
            raise ValueError("json_mode must be a boolean")
        payload = {"model": self.model, "prompt": prompt, "stream": True,
                   "options": {"temperature": temperature, "num_predict": max_tokens}}
        if json_mode:
            payload["format"] = "json"
        limits = aiohttp.ClientTimeout(total=self.timeout, connect=min(5, self.timeout), sock_read=min(15, self.timeout))
        parser = _Stream()
        try:
            async with asyncio.timeout(self.timeout):
                async with aiohttp.ClientSession(timeout=limits, trust_env=False, auto_decompress=False) as session:
                    async with session.post(self.url, json=payload, allow_redirects=False,
                                            headers={"Accept-Encoding": "identity"}) as response:
                        if response.status != 200:
                            raise OllamaError("http_error", response.status)
                        if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                            raise OllamaError("unsupported_encoding")
                        if response.content_length is not None and response.content_length > MAX_BODY:
                            raise OllamaError("response_too_large")
                        async for chunk in response.content.iter_chunked(4096):
                            parser.feed(chunk)
            return parser.finish()
        except OllamaError:
            raise
        except TimeoutError:
            raise OllamaError("timeout") from None
        except aiohttp.ClientError:
            raise OllamaError("transport_error") from None
