# Installed-Wheel Qualification

The workflow in `.github/workflows/tests.yml` builds and installs a wheel on
Ubuntu 24.04 and Windows 2022 with Python 3.12/3.13. Each job requires symlink
coverage; Ubuntu jobs additionally run the authorized real Docker suite. A local
workflow file or a successful Docker Desktop run is not evidence that those
hosted jobs have passed. Check results for the exact candidate commit.

## Local Command

In a dedicated Python 3.12+ environment, build and install one candidate wheel:

```sh
python -m pip wheel . --no-deps --wheel-dir /private/artifacts
python -m pip install /private/artifacts/evolution_llm_tools-0.1.0-py3-none-any.whl pytest
python -I tools/qualify_wheel.py --wheel /private/artifacts/evolution_llm_tools-0.1.0-py3-none-any.whl --report-dir /private/qualification-new --require-clean
```

Use appropriate absolute paths for the host OS. The report directory must be new
and outside the source tree. The script will not overwrite earlier evidence.
It qualifies an already installed package; it does not install dependencies,
upgrade databases, call a model, push code or release anything.

`--containers` additionally authorizes the existing Docker harness, including its
public Python dependency-image pull and hand-written synthetic fixture execution.
Use only a trusted local Linux engine with the documented containment controls.
No generated model code, private files or application data enter those fixtures.

`--require-symlinks` turns unavailable symlink creation into a failed test, not a
skip. It is mandatory in hosted CI and automatic on non-Windows hosts. A normal
local Windows run may retain the documented symlink skip, but that does not
qualify this capability. The script never elevates privileges, enables Developer
Mode or changes security policy. A supported privileged test environment must be
provided separately if this gate fails.

## Evidence And Gates

The script requires Python isolated mode (`-I`) and rejects editable/source-tree
imports. It checks installed package identity, an explicit wheel-entry allowlist,
the archive SHA-256, and equality of all Python module bytes across source, wheel
and installed package. This is package consistency checking, not a malware audit
or a hermetic dependency lock. Build/runtime dependencies remain range-constrained.

It checks dependencies, runs tests from a temporary directory outside the source
tree and collects JUnit XML plus per-stage logs. Inherited pytest overrides and
optional Docker-test flags are removed; third-party pytest plugin autoloading is
disabled. The Docker harness receives an explicit immutable image ID resolved
from its dependency image. Actual container tests may not silently skip.

The default suite permits only known opt-in Docker skips and, for optional local
Windows runs, the named symlink case. Failures, unexpected skips, empty reports
and suites with no passing cases cannot qualify. The summary records exit codes,
test counts, required capabilities, artifact hash and the source Git commit/clean
state. `--require-clean` refuses dirty sources; CI always uses it. The Git state
must also remain unchanged across the run.

Reports are `summary.json`, `default.xml`/`default.log`, `dependencies.log` and,
when requested, `container.xml`/`container.log`. An interrupted process can leave
partial evidence: missing summary or `status=failed` is never a pass. Do not
automatically retry execution because a report is missing.

Local logs/XML can include machine paths and failure details. Keep them private;
do not commit them. The workflow uploads only its synthetic hosted-runner test
evidence for 14 days, including failed-job output when available. It does not
upload workstation state, runtime journals, environment files or the repository.
Workflow permissions remain read-only and checkout does not persist credentials.

## Limits

The workflow is statically checked separately from executing it. Hosted Linux
qualification requires a successful run at the exact published candidate commit;
Windows-host Linux containers alone do not satisfy it. A strict local symlink
failure must be reported as an unqualified gate, not relabeled as success.
Live-model evaluation, external integration trials and release authorization
remain separate from package/containment qualification.
