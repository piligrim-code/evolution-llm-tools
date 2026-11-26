from pydantic import BaseModel
from typing import Optional

class Settings(BaseModel):
    ollama_url: str = "http://localhost:11434"
    # Strongest model measured on the evaluation corpus (14/16 tasks, see
    # docs/qualification/model-comparison-2026-11-01.md). It needs about 30-60 s
    # per request on an 8 GB GPU, partly on CPU, hence the longer deadline.
    model: str = "gemma3:12b"
    temperature: float = 0.2
    max_tokens: int = 1024
    request_timeout: int = 300  # aggregate HTTP deadline in seconds (client maximum)
    allow_pip: bool = False    # if True, generated tools may install deps
    tools_dir: str = ".mcp/tools"  # persisted MCP-like tools
    runs_dir: str = ".runs"        # per-run scratch
    verbose: bool = True

settings = Settings()
