import requests
import time
from .config import settings

class OllamaClient:
    def __init__(self, base_url: str | None = None, model: str | None = None):
        self.base_url = base_url or settings.ollama_url
        self.model = model or settings.model

    def generate(self, prompt: str, temperature: float | None = None, max_tokens: int | None = None) -> str:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "options": {
                "temperature": temperature if temperature is not None else settings.temperature
            }
        }
        # For compatibility with different Ollama versions, we don't set "num_predict" if None.
        if max_tokens is not None:
            payload["options"]["num_predict"] = max_tokens
        url = f"{self.base_url}/api/generate"
        resp = requests.post(url, json=payload, timeout=settings.request_timeout, stream=True)
        resp.raise_for_status()
        text_chunks = []
        for line in resp.iter_lines():
            if not line:
                continue
            # Each line is a JSON object
            try:
                data = line.decode("utf-8")
                import json
                obj = json.loads(data)
                if "response" in obj:
                    text_chunks.append(obj["response"])
                if obj.get("done", False):
                    break
            except Exception:
                # Best effort
                pass
        return "".join(text_chunks).strip()
