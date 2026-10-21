# CI Gate Local Qualification

Date: October 3, 2026, Asia/Yekaterinburg.
Tested implementation: `4e52dc47e386b70b4410deaa7f082505e29d0a1a`.
The follow-up adds this evidence, README updates and restores an explicit installed
module CLI help step in the workflow. Package/runtime and qualification-script
code are unchanged. No remote push, hosted run, merge or release was performed.

## Results

| Check | Result |
| --- | --- |
| Source, Windows Python 3.13.14 | 454 passed, 22 skipped; 18.36 s |
| Fresh installed wheel, Windows Python 3.12.10 | 454 passed, 22 skipped; 16.34 s |
| Fresh installed wheel, actual Linux containers | 21 passed, no skips; 43.97 s |
| Installed module CLI help | Exit 0 |
| actionlint 1.7.12, corrected workflow | Exit 0 |
| Required local symlink probe | Expected exit 1: one failed test, WinError 1314 |
| Hosted Ubuntu/Windows matrix | Not run; unqualified |

Twenty-one default skips are opt-in Docker tests exercised separately. The
remaining local Windows skip is unavailable symlink creation. A deliberate
required-capability probe failed rather than silently skipping; that demonstrates
the gate works, **not** that symlink behavior passed. No privileges or OS settings
were changed. Unit tests also cover the required and optional branches.

Initial actionlint validation found two invalid `runner.temp` expressions in
job-level environment declarations. They were replaced with step-local path use;
subsequent validation passed. A prior dirty-tree harness trial also passed 454
default and 21 Docker tests, but is not the exact-commit qualification above.
No unexpected pytest failures occurred. Timings are observations, not benchmarks.

## Verified Evidence

The new [qualification script](ci-qualification.md) completed with `status=passed`,
`repository.clean=true`, the exact commit above and `symlinks_required=false` on
this local Windows environment. It verified installed site-packages imports,
all 23 module bytes against source and the wheel, the 29-entry archive allowlist,
dependencies and JUnit acceptance rules. Default tests ran outside the source
tree in isolated Python mode with inherited test overrides removed.

```text
evolution_llm_tools-0.1.0-py3-none-any.whl
SHA256: 4f40327ac12c7d3da0582dea5a2bb6758e5c2af3937d374936b13bfbf2036e86
```

The wheel was built from the tested implementation before the follow-up README
update. The runtime package is unchanged from the retention checkpoint; this
stage adds test and CI tooling. Archive equality is not a comprehensive security
audit or dependency lock; no sdist was qualified.

Actual Docker tests used the local Linux/amd64 engine and image:

```text
sha256:dddfd7e07f9d15aeeca61529320492139d21cac7f0070c00609243e51e4e0016
```

Owned cleanup assertions passed, and the final owner-label listing was empty.
No broad cleanup, other project changes, live model calls, private database
migrations or MCP Memory tests occurred. Local full logs/XML stay private.

## Remaining Gates

The workflow now requests Ubuntu 24.04/Windows 2022 and Python 3.12/3.13, strict
symlink coverage on every job, and real Docker tests on Ubuntu. Actionlint can
check configuration, not actual hosted-runner behavior. The branch remains local;
publishing it and running CI require authorization. Evaluate the exact published
head, including the final workflow, rather than reusing these local results as
a hosted pass. Do not disable required checks to obtain a green run.

Native Linux-host qualification and privileged Windows symlink coverage therefore
remain open. Model evaluation, external adoption and a versioned release remain
separate subsequent gates; no production-readiness claim is made.
