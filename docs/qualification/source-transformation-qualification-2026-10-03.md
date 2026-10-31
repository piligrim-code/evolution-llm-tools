# Source Transformation Qualification

Date: October 3, 2026, Asia/Yekaterinburg.
Tested implementation: `3f7d516a7f0386f5d620ebd5fa4b401bc6c452e6`.
Branch: `feat/measured-generation-results`, local only.

## Results

| Environment | Result |
| --- | --- |
| Source, Windows Python 3.13.14 | 678 passed, 38 skipped; 18.21 s |
| Fresh installed wheel, Windows Python 3.12.10 | 678 passed, 38 skipped; 19.40 s |

The 72 new handwritten cases cover the exact fence envelope, preservation of
source bytes and line endings, UTF-8 limits, invalid encoding, refusal of prose/
multiple/incomplete/ambiguous blocks, version/corpus/request/response binding,
immutable observations, detached summaries, privacy and non-execution. Unicode
line separators cannot act as closing-fence boundaries. They remain untouched
inside the body. Fixtures with invalid syntax or side effects are extracted only,
never compiled, imported or executed by the transformation.

All test runs in this checkpoint passed. An initial focused run passed 171 cases;
an intermediate full run passed 671 with 38 skips before final delimiter tests
and parser tightening. These are intermediate observations, not extra scenarios.

The 38 final skips are 37 opt-in Docker tests and one local Windows symlink test.
Docker was not rerun: this additive operation does not change execution policy,
the container runner or approval handling. Earlier Docker results remain tied to
earlier commits. No model requests were made for this checkpoint.

## Artifact Verification

Wheel: `evolution_llm_tools-0.1.0-py3-none-any.whl`.
SHA256: `cb1c2a6b6e24e53d828e10fab25f5b3a39f5c859cb07d08254f4e02db1396094`.

The isolated installed-wheel qualifier verified installed imports, dependencies,
30 Python modules and 36 allowlisted archive entries. Source/installed bytes
matched. The repository stayed clean at the tested commit throughout the run.
Runtime dependency versions were pinned to the preceding qualified environment.
This artifact predates the documentation-only qualification commit.

## Behavior And Limits

The operation is explicit, with mandatory prompt-version selection; it does not
change the frozen v1/v2 prompts, existing records or the legacy generator/CLI.
The raw response and its hash are retained alongside the derived source/hash and
transformation version. A fenced v2 record remains invalid_source. Its separately
derived body is unreviewed_source, with no syntax/correctness or execution claim.

See [the API and exact envelope](../source-transformations.md). Hash binding detects
mixed observations, not malicious fabrication or independent model identity.
No model-quality improvement, safety approval, hosted CI result, publication,
merge, release or production readiness is established by these tests.

Separately scoped source review and contained correctness tests remain the next
gate before treating any transformed output as a working tool.
