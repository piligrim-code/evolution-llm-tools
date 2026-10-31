"""Actual ephemeral loopback HTTP, predetermined responses, no downloaded model."""
import json

from aiohttp import web
from aiohttp.test_utils import TestServer


def frame(response="", done=False, **metadata):
    return json.dumps({"response": response, "done": done, **metadata}, ensure_ascii=False).encode("utf-8") + b"\n"


async def with_provider(handler, operation):
    app = web.Application()
    app.router.add_post("/api/generate", handler)
    async with TestServer(app, host="127.0.0.1") as server:
        return await operation(str(server.make_url("/")))
