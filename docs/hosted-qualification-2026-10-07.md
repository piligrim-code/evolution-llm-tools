# Hosted Qualification

Date: October 7, 2026, Asia/Yekaterinburg.
Repository: `piligrim-code/evolution-llm-tools`.
Branch: `feat/measured-generation-results`.
Tested head: `e163644a47f7fa2dad2afbc29be6998fa392b6a4`.
GitHub Actions run: `37666186672`, triggered by push; all four jobs succeeded.

## Results

| Host | Python | Default Suite | Actual Docker Suite |
| --- | --- | --- | --- |
| Ubuntu 24.04 | 3.12.15 | 680 passed, 37 skipped | 37 passed |
| Ubuntu 24.04 | 3.13.15 | 680 passed, 37 skipped | 37 passed |
| Windows 2022 | 3.12.10 | 680 passed, 37 skipped | Not requested on Windows |
| Windows 2022 | 3.13.16 | 680 passed, 37 skipped | Not requested on Windows |

All jobs required symlink coverage. The 37 default-suite skips are the explicit
opt-in Docker tests; both Ubuntu jobs ran those tests successfully. There were
no failures, errors or unexpected skips. Counts repeat across environments and
are not summed as unique coverage.

## Artifact Evidence

Each job built and installed its own wheel, verified the installed import, checked
dependencies, and compared source, wheel and installed Python module bytes. Each
wheel contained 36 entries and 30 Python modules.

| Host / Python | Wheel SHA256 |
| --- | --- |
| Ubuntu 24.04 / 3.12 | `61607fc3a2d30203a28d4c46371d1864007cfb61b85dcc6025169406f90c510f` |
| Ubuntu 24.04 / 3.13 | `3ee279b1441b18bb98646b65683d540d7d2446b4e47d9feebffff717cbf2c173` |
| Windows 2022 / 3.12 | `e11d981ebb5d057188840ea2c7b7dbdc0c6919bbcf6e56ee29a6151343e2313a` |
| Windows 2022 / 3.13 | `ff90e58f2e703413fe5901ab5b912fdaa729bd88b7492cf4e873c1fea57fd2b7` |

The Ubuntu container checks used the workflow's verified dependency image and
passed containment, resource, review, output-contract, demo, catalog and frozen
evaluation coverage. The uploaded reports recorded a clean repository at the
exact tested commit. No live model inference, private data or runtime journals
were used.

## Limits

This qualifies the installed wheel and documented contained fixtures on the
listed GitHub-hosted environments. It is not a production-release certification,
model-quality evaluation, arbitrary-code escape proof, multi-tenant guarantee or
deployment approval. Dependency versions remain range-constrained rather than a
complete lockfile. Live-model evaluation and external integration trials remain
separate gates.
