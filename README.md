# Evolution LLM Tools

An experimental Ollama client that proposes small Python tools and keeps a
local registry. The installed import namespace is `alita`, matching the
original module layout. This is not a production autonomous-agent platform.

## Install And Test

Python 3.12+ in a dedicated virtual environment:

```sh
python -m pip install ".[dev]"
python -m pytest tests -q
python -m alita --help
```

Tests use temporary directories, fake model responses and mostly mocked process
execution. One explicitly approved, hand-written fixture runs in a temporary
venv and doubles a synthetic number; it does not use generated model output.
The tests require no Ollama server, downloaded model or credentials.

## Default Behaviour

```sh
evolution-tools run "Explain what this tool registry does"
evolution-tools tools
evolution-tools tool-run reviewed_tool
```

`run` needs a local Ollama service/model configured in `config.py`. It can
return a direct model answer. If a tool would be generated or executed, the
default is to stop with an explicit permission error. The `tool-run` example
above also refuses execution without consent. Model output, saved metadata
and requirement files cannot grant that consent.

## Explicit Unsafe Mode

`--unsafe-exec` on a single CLI command, or the exact boolean keyword
`allow_unsafe_execution=True` at an API entry point, authorizes host execution.
There is no persistent allow-execution switch. Use this only in an environment
where every executed script and its dependencies are trusted. In particular,
`run --unsafe-exec` may execute newly generated, unreviewed code; it is not an
approval workflow for reviewing individual scripts. Prefer reviewing saved
scripts before any manual unsafe run. Do not enable it in a shared service.

**This is not a sandbox.** A Python venv isolates packages, not user files,
credentials, network access or child processes. The subprocess timeout is not
process-tree containment or an OS resource quota. Approved code inherits the
host user's privileges and environment; output capture is not a memory quota.
The safeguards here prevent implicit execution and basic path traversal,
not malicious code or races caused by a hostile local user.

Dependency installation needs separate `settings.allow_pip = True` approval;
it remains disabled by default. Installation can itself execute third-party
code. An OS-isolated executor is future work, not a feature of this patch.

## Registry Boundaries

- Only safe single-component tool names are accepted.
- Only `tool.py` and `requirements.txt` may be written from generated output.
- Symlink/junction paths are rejected and existing tools are not overwritten.
- Nonzero execution results are not registered as working tools.
- Newly created tools execute once; registration does not execute them again.
- `.runs/` and `.mcp/` are local artifacts and must not be committed.

The public audit corrections do not change the original MIT license. The web
search module is still a stub. Full model quality, hostile-code isolation,
multi-user operation, process-tree cleanup and production deployment are not
qualified by the offline tests.
