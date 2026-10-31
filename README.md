# Toolwright

Toolwright generates small Python tools with a local language model (through
Ollama) and runs them only after explicit human review, one attempt at a time, in
a locked-down container. Tools that prove themselves on cases the model never saw
are kept in a versioned catalog and reused instead of being generated again.

It is experimental research software, not a production agent platform.

> Naming: the product is **Toolwright**. For compatibility the repository and
> Python distribution stay `evolution-llm-tools`, the CLI stays `evolution-tools`
> and the import package stays `alita`.

## How it works

```text
request ─▶ reuse? ──yes──▶ check a catalog version on the requester's example ─▶ reuse
              │no
              ▼
        generate (local model) ─▶ pending proposal ─▶ human inspects ─▶ explicit approval
                                                                          │
           catalog ◀── admission on held-out cases ◀── receipt ◀── one contained run
              ▲                                            │
              └──── repair from failed example cases ◀─────┘
```

- **Review before execution.** A proposal binds source, arguments, output contract
  and an immutable container image. Approval is for that exact content and is
  consumed by a single execution. Nothing is approved or run automatically.
- **Contained execution.** No network, no host mounts, read-only root,
  unprivileged user, CPU/memory/PID/output/time limits, verified cleanup.
- **Evidence-gated admission.** A candidate enters the catalog only after passing
  example and held-out cases. Held-out results are recorded in an append-only
  ledger, budgeted per task, and reported only as pass counts.
- **Repair** builds a prompt from failed *example* cases only, never held-out ones.
- **Reuse** retrieves catalog versions by contract signature and verifies the best
  one on the requester's own example before reusing it.

## Current results

Synthetic corpus of 16 tool tasks (3 cases each) plus 4 policy-refusal tasks;
one request per task, temperature 0, prompt v7, no transformations. Details:
[model comparison](docs/qualification/model-comparison-2026-11-01.md).

| Local model | Tasks solved | Cases | Held-out cases | Refusals |
| --- | --- | --- | --- | --- |
| qwen2.5:7b | 11/16 | 38/48 | 26/32 | 4/4 |
| qwen3:8b (thinking on) | 12/16 | 36/48 | 24/32 | 4/4 |
| gemma3:12b | 14/16 | 44/48 | 29/32 | 4/4 |

Admission on a stricter corpus with five fresh held-out cases per task has
admitted versions for 13 of the 16 tasks so far, and caught one tool that looked
solved on the original cases but failed a fresh one. These are small synthetic
measurements on one workstation, not general quality estimates. Every report,
including negative results, is in [docs/qualification](docs/qualification/).

## Install and test

Python 3.12+ in a dedicated virtual environment:

```sh
python -m pip install ".[dev]"
python -m pytest tests -q
python -m alita --help
```

The default suite needs no Ollama server, model or credentials and never
executes model-generated code. An opt-in suite checks the real container
controls with hand-written adversarial fixtures:

```sh
python tools/run_container_tests.py
```

## Using it

You need a local Ollama model and a trusted local Linux Docker engine (cgroup v2,
seccomp). Resolve an immutable image ID once; the executor never pulls or builds
images:

```powershell
docker pull python:3.12-slim
$image = docker image inspect python:3.12-slim --format '{{.Id}}'
```

Reviewed workflow:

```sh
evolution-tools review propose "Average the numbers in values" --container-image <image-id>
evolution-tools review inspect <proposal-id>
evolution-tools review approve <proposal-id> --digest <digest-from-inspect> --yes
evolution-tools review execute <proposal-id> --structured
evolution-tools catalog promote <proposal-id> --yes
```

See the [reviewed lifecycle walkthrough](docs/reviewed-lifecycle.md) and the
[documentation index](docs/README.md) for evaluation, admission, repair and reuse
commands.

## Safety boundaries

- **Default deny.** Without explicit consent, `run` returns a direct answer or
  stops with a permission error. Model output, saved metadata and requirement
  files cannot grant consent.
- **Container mode** accepts standard-library tools only; pip, network and
  host-file workflows are refused rather than run elsewhere. It is Linux container
  containment with a trusted daemon and image, not a VM and not a multi-tenant
  security boundary. Use a dedicated disposable engine or VM for untrusted
  workloads. See [container execution](docs/container-execution.md).
- **Unsafe host mode** (`--unsafe-exec`, or `allow_unsafe_execution=True` at an API
  entry point) runs code as your user with your files, credentials and network.
  It is **not a sandbox**; a venv isolates packages only. There is no persistent
  switch. Use it only where every executed script is trusted, never in a shared
  service. Dependency installation needs separate approval and can itself run
  third-party code.
- **Registry boundaries.** Only safe single-component tool names; only `tool.py`
  and `requirements.txt` are written from generated output; symlink/junction
  paths are rejected; existing tools are not overwritten; failed runs are not
  registered.
- `.runs/` and `.mcp/` hold local artifacts and must not be committed.

Not qualified: general model quality, resistance to kernel or container escapes,
multi-user operation, production deployment. The web-search module is a stub.

## License

MIT, see [LICENSE](LICENSE).
