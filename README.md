# Toolwright

Toolwright is an experimental Ollama client for generating small Python tools,
explicitly controlled execution, and reuse through a local registry. It was
previously named Evolution LLM Tools. This is not a production autonomous-agent
platform.

The product name is **Toolwright**. For compatibility, the repository and Python
distribution remain `evolution-llm-tools`, the CLI remains `evolution-tools`, and
the import namespace remains `alita`. No install command, import or stored tool
needs changing for this naming update. Toolwright remains independent of MCP
Memory, with its own code, dependencies and release lifecycle.

## Review Before Execution

The new `evolution-tools review` commands separate non-executing drafts,
inspection, explicit approval and one contained execution attempt. Approval is
bound to the source, contract, exact arguments and immutable container image.
Changed proposals and consumed approvals cannot execute through this path.
See the [reviewed lifecycle walkthrough](docs/reviewed-lifecycle.md) for commands,
failure handling and trust limits. Existing `run`/`tool-run` commands keep their
explicit legacy semantics; they are not silently routed through review.

Discovery adds `review list` with state filters/pagination and read-only
`list`/`inspect` handles. Hosted Ubuntu/Windows qualification with Python 3.12/3.13
passed 455 default tests on each combination, including required symlink coverage.
Both Ubuntu jobs also passed all 21 actual Linux container tests. See
[the exact-commit report and limits](docs/hosted-qualification-2026-10-03.md).
This is experimental software, not a production release certification.

Optional [reviewed output contracts](docs/output-contracts.md) provide
exact text or JSON-object expectations tied to the approved proposal. A process
exit code of zero no longer makes a contract-bearing CLI run successful when
its output fails the check. Old proposals retain their explicit legacy behavior.

The separate [validated version catalog](docs/version-catalog.md) preserves an
explicitly promoted successful proposal. `catalog prepare` copies a selected
version into a fresh pending review, never into an automatically runnable tool.
Versions and their first validation provenance are immutable through the API.

`review execute --structured` and `ReviewStore.execute_result()` provide
[typed per-attempt outcomes](docs/typed-outcomes.md), including ambiguous failures
without automatic retries. Three [packaged deterministic demos](docs/demos.md)
cover text summaries, grouped tabular totals and JSON projection. `demo prepare`
only creates a pending proposal; normal inspection and approval remain mandatory.

[Explicit retention](docs/retention.md) adds read-only `review prune` previews
and permanent `catalog retire` markers. Applying a plan requires its inspected
digest and confirmation. Pruned IDs remain terminal; retirement retains proof
and does not revoke existing proposals. No automatic deletion or secure erasure
is provided. Writable opens upgrade private stores to schema 2; stop old clients
before upgrading.

## Install And Test

Python 3.12+ in a dedicated virtual environment:

```sh
python -m pip install ".[dev]"
python -m pytest tests -q
python -m alita --help
```

Default tests use temporary directories, fake model responses and mostly mocked process
execution. One explicitly approved, hand-written fixture runs in a temporary
venv and doubles a synthetic number; it does not use generated model output.
The default tests require no Ollama server, downloaded model or credentials.
The [installed-wheel qualification gate](docs/ci-qualification.md) checks package
identity and source/installed bytes, retains structured test evidence, and refuses
unexpected skips. Hosted CI requires symlink coverage and adds actual Docker
tests on Ubuntu; unexecuted workflow changes are not a passed Linux-host gate.
An opt-in Docker suite separately verifies actual OS controls with hand-written
adversarial synthetic fixtures. It never executes generated model output on the host.

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

The Ollama client now bounds the complete HTTP exchange and NDJSON/text size,
requires a complete valid stream, and closes sessions on failure/cancellation.
Malformed model decisions no longer become raw fallback answers. Specifications
and generated Python syntax are checked before execution, independently of the
permission gate. See `docs/ollama-contract.md` for exact limits and compatibility.

## Explicit Container Mode

With a trusted local Linux Docker engine (cgroup v2 and seccomp required), first
review/pull an image that provides `/usr/bin/env` and `/usr/local/bin/python`.
Resolve its immutable local ID; the executor never pulls or builds images:

```powershell
docker pull python:3.12-slim
$image = docker image inspect python:3.12-slim --format '{{.Id}}'
evolution-tools run "Calculate the average of 3, 5 and 7" --container-image $image
evolution-tools tool-run reviewed_tool --container-image $image --args '{"value":2}'
```

The model service is still separately provisioned. Container mode accepts only
standard-library tools with empty requirements; pip/network/host-file workflows
are refused, not silently run outside the container. It is mutually exclusive
with `--unsafe-exec`. No setting or saved tool metadata permanently enables it.

The container has no user host mounts or network, a read-only root, an unprivileged
UID, dropped capabilities, no-new-privileges, cgroup/resource limits, bounded output
and an ephemeral work directory. Limits are inspected before start and cleanup
is restricted to the uniquely labeled owned container. This is Linux container
containment with a trusted daemon/image, not a VM or a multi-tenant security claim.
Use a dedicated disposable engine/VM for untrusted workloads. See
`docs/container-execution.md` for the exact controls and failure/cleanup boundaries.

Actual Docker regression command (pulls a public Python dependency image):

```sh
python tools/run_container_tests.py
```

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
code. Those permissions apply only to unsafe host mode; container mode never
installs requirements, even when `allow_pip` is enabled.

## Registry Boundaries

- Only safe single-component tool names are accepted.
- Only `tool.py` and `requirements.txt` may be written from generated output.
- Symlink/junction paths are rejected and existing tools are not overwritten.
- Nonzero execution results are not registered as working tools.
- Newly created tools execute once; registration does not execute them again.
- `.runs/` and `.mcp/` are local artifacts and must not be committed.

The public audit corrections do not change the original MIT license. The web
search module is still a stub. Full model quality, resistance to kernel/container
escapes, multi-user operation and production deployment are not qualified by
the offline tests or the synthetic container checks. The two execution modes
have deliberately different limits and trust assumptions.
