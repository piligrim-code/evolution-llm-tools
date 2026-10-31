# Hosted Qualification

Date: October 3, 2026.
Repository: `piligrim-code/evolution-llm-tools`.
Branch: `ci/installed-wheel-qualification`.
Tested head: `5df6c93e48dcf3c4356f6ccb2dafd8f78c11e290`.
GitHub Actions run: `37130896192`, triggered by push, all four jobs successful.

## Results

| Host | Python | Default Suite | Actual Docker Suite |
| --- | --- | --- | --- |
| Ubuntu 24.04 | 3.12.14 | 455 passed, 21 skipped; 8.12 s | 21 passed; 14.60 s |
| Ubuntu 24.04 | 3.13.15 | 455 passed, 21 skipped; 7.18 s | 21 passed; 13.73 s |
| Windows 2022 | 3.12.10 | 455 passed, 21 skipped; 36.36 s | Not requested on Windows |
| Windows 2022 | 3.13.15 | 455 passed, 21 skipped; 37.59 s | Not requested on Windows |

The default skips are exactly the opt-in Docker cases, separately exercised on
both Ubuntu jobs. All four default JUnit reports include the linked-directory
symlink test with no skip, failure or error. All summaries report
`symlinks_required=true`, `repository.clean=true`, the exact head above and no
unexpected skips. Counts repeat across environments and are not summed as unique
coverage. Timings are observations, not benchmark claims.

## Evidence

Every job built and installed its own wheel, verified all 23 Python modules
against source and installed bytes, checked its 29-entry archive inventory,
checked dependencies and ran tests outside the source tree in isolated Python.
Installed module CLI smoke and evidence upload succeeded on all jobs. Downloaded
summary JSON, JUnit XML and logs were inspected, not only the workflow status.

| Job | Wheel SHA-256 |
| --- | --- |
| Ubuntu / 3.12 | `b26879b9e8c8f9d50e1b8ba3a8edf28098eb36a602a88d67d82217a7a11fc725` |
| Ubuntu / 3.13 | `efc6c90e02c51d4012d15b9ad0200e5165cd852a1158352d9c6db00687ba402b` |
| Windows / 3.12 | `e0ab764b16532484d27d56c415db9227a626575507b472bedc2ff68123f3adcd` |
| Windows / 3.13 | `a7fe240977790f26fdced9d9cbf8548d2f0d4804df11796080dc4e9e0afdf635` |

Independent wheel builds are not claimed bit-reproducible. Each job checks its
own bytes against the tested source. Build/runtime dependencies are constrained
by ranges rather than locked as a complete reproducible environment.

Both Ubuntu jobs used Linux/amd64 image:

```text
sha256:414a398990af718f018ff9c23cea0e7489b7986eb54f2b1d7cc874c99ebc7364
```

Container ownership/cleanup assertions passed. Fixtures are hand-written and
synthetic, not generated model code or private user data. No workstation logs,
runtime databases, environment files or private credentials were published.

## Scope And Follow-Up

This closes the previously pending native hosted Linux and supported Windows
symlink qualification for this candidate. It does not change the lack of symlink
privilege on the local developer Windows machine, and does not qualify every
Windows token or configuration. Existing local reports remain historical evidence.

The run warned that the old upload-artifact pin used a deprecated Node 20 action
runtime and was forced onto Node 24. The follow-up pins official
`actions/upload-artifact` v7.0.1 at
`043fb46d1a93c77aae656e7c1c64a875d1fc6a0a`, whose action metadata uses Node 24.
It also adds this report and updates README; package/runtime and test logic are
unchanged. That follow-up must obtain its own successful hosted run; this report
does not extend the first run's exact-head evidence to an untested commit.

Branch publication and CI were authorized. No merge, release, deployment,
live-model evaluation, production database migration or MCP Memory testing
occurred. Model evaluation, external integration trials and release decisions
remain separate gates. These tests do not establish arbitrary generated-code
safety, multi-tenant isolation or production readiness.
