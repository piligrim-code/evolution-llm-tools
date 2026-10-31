# Reviewed Lifecycle And Discovery Qualification

Date: October 3, 2026, Asia/Yekaterinburg.

Tested implementation commit: `125ec0db92fa159ffc579589f182951af3a46614`.
This covers the reviewed lifecycle from `cd1255a` and discovery from `125ec0d`.
The follow-up commit adding this report changes documentation only; no runtime
code or tests were changed during qualification. Nothing was pushed, merged or
released by this local verification.

## Results

| Installation / Host Interpreter | Default Suite | Actual Linux Container Suite |
| --- | --- | --- |
| Editable source, Windows Python 3.13.14 | 252 passed, 10 skipped; 12.91 s | 9 passed; 13.35 s |
| Installed wheel, Windows Python 3.12.10 | 252 passed, 10 skipped; 15.30 s | 9 passed; 14.46 s |

The ten default-suite skips consist of nine explicit opt-in Docker tests, all
subsequently run successfully in the container suite, and one symlink test that
could not create a link with this Windows account's privileges. That final skip
is still an unverified case on this machine. Counts from the two installations
are repeat verification, not additional independent test scenarios. Timings are
observations, not performance benchmarks.

The engine was Docker 29.5.2 (client and server), Linux/amd64 through the local
Docker Desktop engine. The execution preflight required a local endpoint,
cgroup v2 and the existing resource/seccomp controls. No controls were weakened
to get the suite to pass. The test setup pulled the public `python:3.12-slim`
image and resolved this immutable execution image ID for both runs:

```text
sha256:dddfd7e07f9d15aeeca61529320492139d21cac7f0070c00609243e51e4e0016
```

The executor itself never pulls an image or installs tool dependencies. Tests use
hand-written synthetic fixtures, not live model-generated output or private data.
The manager's simulated provider runs on loopback; no live Ollama/model call was
made. No service outside test-owned resources was stopped or removed.

## Package Evidence

Built from the exact implementation commit above:

```text
evolution_llm_tools-0.1.0-py3-none-any.whl
SHA256: 2f4e0b07cd17b6da87bb831d3ca6012415e1f8e87899184637aaec15fd0a5d6b
```

A fresh Python 3.12 environment installed this wheel, not an editable copy. Its
`alita.review` import resolved under that environment's `site-packages`; default
tests were launched from outside the source directory. The Docker harness also
used this environment's interpreter and installed modules.

The archive contained 23 entries including 17 Python modules; all 17 module byte
sequences matched the working source at the tested commit. Inventory checks found
no `.mcp`, `.runs`, SQLite databases, environment files, bytecode/cache directories
or `direct_url` installation metadata. This is an artifact inventory check, not
a comprehensive independent security audit. No sdist was qualified in this run.

`pip check` passed, and the installed `evolution-tools review list --help` entry
point returned successfully. Principal installed versions:

| Package | Version |
| --- | --- |
| pytest | 9.1.1 |
| typer | 0.27.2 |
| pydantic | 2.13.5 |
| aiohttp | 3.14.3 |
| rich | 14.3.4 |

This is an observed environment, not a dependency lock. The wheel hash above
identifies the artifact built before this documentation-only report; rebuilding
after README changes can change package metadata and therefore the wheel hash.

## Boundaries Exercised

Default tests cover exact-content approval, changed/stale approvals, cancellation,
thread/process contention, interrupted writes and non-replay after an ambiguous
attempt. Discovery tests cover filters, cursor paging, missing stores, read-only
handles, omitted private content and discoverable-but-uninspectable corrupt
documents. They do not turn a list row into an integrity or success attestation.

Actual container fixtures exercise non-root identity, resource/kernel limits,
read-only root, host file/environment/network separation, PID pressure, file/tmpfs
limits, memory pressure, timeout, output overflow, manager execution/reuse and
the reviewed create/inspect/approve/execute flow. Unapproved and repeated reviewed
execution are refused. The reviewed fixture confirms removal of its owned
container; the executor also verifies owned-resource removal on normal paths.
Read-only post-run listings found no containers with the executor ownership label.
No broad cleanup or prune command was used.

## Reproduce

Use a disposable environment and a trusted local Linux Docker engine, not a
production memory/tool store. From the repository:

```sh
python -m pip install ".[dev]"
python -m pytest tests -q --tb=short -ra
python tools/run_container_tests.py
```

For installed-artifact verification, build the wheel, install it in a new virtual
environment, confirm imports come from `site-packages`, and run the same tests
using that interpreter. The Docker harness explicitly enables the opt-in suite;
the default suite alone does not qualify containment.

## Remaining Work

- A native Linux host default-suite run and remote CI for this exact implementation
  were not performed here. Linux containers on a Windows host are not that check.
- The Windows symlink case needs an environment with suitable privileges.
- Live model quality, adversarial/kernel-escape resistance, macOS, mutually
  untrusted tenants and production operations were not qualified.
- EVO-2 versioned working-tool registration, typed outcomes and validated output
  contracts remain future work. Passing EVO-1/discovery tests does not implement
  those features or qualify a production release.
- MCP Memory is independent and its deferred tests were not run in this task.
