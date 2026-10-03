# Reviewed Output Contracts

See [the exact-commit source/wheel/Docker qualification](output-contract-qualification-2026-10-03.md)
for test results and remaining gaps.

An exit code of zero proves only that the process exited without reporting an
error. A reviewed proposal can now carry an independently supplied assertion
about stdout for its exact arguments. This is the first output-validation part
of EVO-2, not the versioned working-tool registry or a completed stable library
contract.

The caller supplies the expected result before approval. The assertion is stored
inside the proposal, displayed by `review inspect` and included in its digest.
Changing or removing it invalidates approval. Proposal generation does not include
the expected value in the model prompts. That separation is not a secrecy
guarantee: the question itself may contain the answer, and the operator must
independently decide whether the expectation is correct.

## Supported Assertions

Only objects with exactly `kind` and `expected` are accepted. There are no
executable validators, regexes, callbacks, shell snippets, schema references,
network requests or new dependencies.

### Exact Text

```json
{"kind":"stdout-equals","expected":"9\n"}
```

`expected` is valid UTF-8 text, at most 65,536 bytes, with no NUL character, matching
the existing text contract. Empty text is allowed. Comparison is byte-exact: no
trimming, newline conversion, case folding or Unicode normalization. Remember
that Python `print` normally appends a newline. The executor fingerprints the
captured stdout bytes before terminal sanitization; a hidden control byte or
invalid UTF-8 cannot disappear and make a different raw output match.

The expected text may include other controls accepted by the text contract;
inspect its escaped JSON form to review them. Returned `stdout` remains sanitized
for display and may differ from raw bytes, even for a passing text assertion.
The raw byte count and digest identify what was compared; raw output is not added
as a separate plaintext field.

### Exact JSON Object

```json
{"kind":"json-object-equals","expected":{"count":3,"total":12}}
```

Output must be one finite JSON object, not an array, prose, markdown or multiple
documents. Duplicate keys, NaN/Infinity and overflowing exponents are refused.
Object key order and ordinary spaces/tabs/LF outside values are insignificant.
List order and all object keys/values must match. There is no type coercion:
`true`, `1` and `1.0` compare differently. This is an equality assertion, not a
general JSON Schema validator or approximate numeric tolerance.

JSON comparison uses the existing sanitized stdout only when its UTF-8 bytes
exactly reproduce the executor's original byte count and SHA-256. If sanitization
changed it, the check fails with `stdout_not_lossless_utf8` instead of validating
altered data. Consequently raw CR/CRLF and unescaped formatting controls rejected
by the terminal sanitizer are not supported in this mode. Escaped JSON controls
inside string values remain supported; the original output bytes then contain
the ASCII escape sequence. Use LF for JSON formatting.

Both expected and actual JSON are bounded. Validation does not install or execute
code from the assertion. Structural equality on one input does not establish that
the tool works correctly on other inputs or that either value is factually true.

## CLI

Pass the assertion as a JSON option when drafting. This example is POSIX-shell
syntax; use your shell's normal JSON quoting rules:

```sh
evolution-tools review propose "Count the supplied text characters" --name text_length --args '{"text":"synthetic"}' --container-image <local-sha256-image-id> --output-contract '{"kind":"stdout-equals","expected":"9\n"}'
evolution-tools review inspect <proposal-id> --json
evolution-tools review approve <proposal-id> --digest <inspected-digest>
evolution-tools review execute <proposal-id>
```

The proposal and approval steps do not execute generated code. Inspect the entire
code, exact arguments, image/policy and output expectation before approving.
Execution still uses only the existing stdlib-only container boundary and consumes
one approval before entering the executor. A failed assertion cannot re-enable it.

The CLI prints the persisted result and exits 1 on a failed or unperformed output
check even if the process `returncode` is 0. Permission/contract/container errors
retain the existing error path. No tool is promoted into a working registry merely
because it exited or matched the assertion.

## Local API

Creating this hand-written proposal does not run it:

```python
from alita.container_runner import ContainerPolicy
from alita.review import ReviewStore

store = ReviewStore()
proposal_id = store.create(
    {"name": "length", "args": [{"name": "text", "type": "string"}],
     "output": "Character count as a JSON object"},
    {"tool.py": "import json, sys\nprint(json.dumps({'count': len(json.loads(sys.argv[2])['text'])}))\n"},
    {"text": "synthetic"},
    ContainerPolicy("sha256:" + "a" * 64),  # Supply your trusted local image ID.
    output_contract={"kind": "json-object-equals", "expected": {"count": 9}},
)
record = store.inspect(proposal_id)
```

After a separate review and explicit approval, inspect
`result["output_validation"]["status"]` from `store.execute(proposal_id)`, not
just `returncode`. The library preserves the actual process code rather than
rewriting it to pretend a validation failure was a process failure. A completed
receipt's state is `finished` for both correct and incorrect answers.

`output_validation` follows the importable `OutputValidation` TypedDict:

| Status | Meaning |
| --- | --- |
| `passed` | A completed, cleaned-up execution matched the supplied expectation. |
| `failed` | Output mismatched, JSON was invalid/altered or executor evidence was missing/invalid. |
| `not_checked` | Execution failed or hit a resource/time/output limit. |

`reason` is a fixed code, not a dump of expected/actual values. The full expectation
is still stored in the private proposal and output in the receipt; do not put
secrets in either. `stdout_sha256` and `stdout_bytes` are additive executor-result
fields for captured original bytes, not a remote attestation. For limit failures
they describe the captured prefix, which is never accepted as a passed assertion.
Stderr is not part of these stdout assertions; normal execution/cleanup checks
still take precedence.

Cleanup failures raise the existing container error and never produce a passed
check. Unexpected validation or receipt-persistence failure leaves the attempt
claimed, without automatic replay. A normal mismatch is persisted as finished
with a failed check. Deliberate new work requires a new proposal/approval.

## Compatibility

Proposals without an assertion retain document version 1 and their existing
digests and behavior. They do not gain an `output_validation` field or become
validated tools retroactively. Proposals with an assertion use document version 2
inside the same existing journal schema. Earlier readers refuse version-2 content
instead of silently dropping the assertion. There is no database migration,
automatic approval renewal or mutation of old proposals.

Legacy manager/registry/unsafe-execution commands are unchanged and do not acquire
these assertions. Runtime result metadata is additive; the executor boundary and
immutable-image requirements are unchanged. A general typed execution-outcome
API, versioned registration/promotion and reusable input-specific validations
remain further EVO-2 work.

## Verification

```sh
python -m pytest tests/test_output_contracts.py tests/test_review.py -q
python -m pytest tests -q --tb=short -ra
python tools/run_container_tests.py
```

Synthetic tests cover contract changes/downgrades, exact byte fingerprints,
type-sensitive JSON matching, invalid JSON, sanitized bytes, resource failures,
cleanup precedence, persistence failures, old proposals, provider isolation and
CLI failure on incorrect output. Actual Docker fixtures exercise both passing
and failing assertions through the reviewed CLI and check owned cleanup/replay
refusal. No live model or private data is needed for these tests.
