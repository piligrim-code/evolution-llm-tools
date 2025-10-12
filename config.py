from pydantic import BaseModel
from typing import Optional

class Settings(BaseModel):
    ollama_url: str = "http://localhost:11434"
    model: str = "qwen2.5:14b"
    temperature: float = 0.2
    max_tokens: int = 1024
    request_timeout: int = 90  # seconds
    allow_pip: bool = False    # if True, generated tools may install deps
    tools_dir: str = ".mcp/tools"  # persisted MCP-like tools
    runs_dir: str = ".runs"        # per-run scratch
    verbose: bool = True

settings = Settings()
