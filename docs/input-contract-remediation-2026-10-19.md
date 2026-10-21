# Input-Contract Remediation

Date: October 19, 2026.
Commit: `bf6617b16a36bc6843e3bdbaed3bc8e12232bfbd`.
Branch: `feat/measured-generation-results`.

## Changes

- Added a bounded nested schema subset for strict JSON tool arguments: typed
  objects, required properties, closed objects and typed array items. Schemas are
  normalized into the proposal document/digest and checked before proposal
  creation and again when loading a proposal for execution.
- New `review propose` requests with explicit structured arguments now require
  nested schemas for object/array parameters; arrays must declare item types.
  Existing shallow specs and stored proposals remain readable for compatibility.
- Structured review drafting now asks for typed JSON arguments and validation
  details. The legacy manager prompt stays on its existing text-only path.
- Updated the generator prompt to require exact types, no coercion, and a
  controlled nonzero/stderr response for invalid input. This remains model
  guidance, not enforcement inside arbitrary generated source.
- Added opt-in evaluation prompt v3 with the integer-sum input contract, exact
  integer semantics and no-traceback instructions. V1/v2 prompt bytes were not
  changed. Source-fence derivation now accepts v3 observations.

## Verification

| Check | Result |
| --- | --- |
| Focused contract/review/prompt/transformation tests | 304 passed |
| Full source-tree suite | 716 passed, 39 skipped |
| Disposable Linux-container suite | 38 passed, 0 skipped/failures; 89.33s |
| Installed-wheel qualification, Windows Python 3.13.14 | 716 passed, 39 skipped |
| Dependency check | Passed |
| Wheel entries / Python modules | 36 / 30; all source, wheel and installed module bytes matched |

Wheel SHA256:
`8e34ef1d11af128f6aa8018fb84006d03a85f583c79ca0862c95a170c5df9702`.

The local Windows installed-wheel run does not require symlink privileges, so the
symlink test remains an environment skip. The Docker suite ran against
`python:3.12-slim` on a Linux/amd64 Docker engine; this is not native Linux-host
GitHub Actions qualification for this commit.

## Remaining Limits

No model call was made. Prompt v3 has not been evaluated against a live model, and
the existing candidate was not regenerated. The official model corpus score
therefore remains **3/48 cases and 1/16 tasks**. Prompt instructions do not make
model code semantically correct or guarantee clean errors when invoked outside
the reviewed proposal boundary. Existing direct/manual proposals without nested
schemas retain their previous shallow-type behavior. New hosted Linux/Windows CI,
real-model v3 evaluation and broader task coverage remain open; no push or release
was performed.
