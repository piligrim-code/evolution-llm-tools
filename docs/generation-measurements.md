# Measured Generation Results

`OllamaClient.generate_result()` and `generate_result_async()` add a structured
observation for one explicit model request. Existing `generate()` and
`generate_async()` still return text. No batch runner, default provider call,
approval shortcut or execution permission is added.

## Measurements

The frozen `GenerationResult` records requested settings, hashes and local
`client_elapsed_seconds`. The monotonic timer covers HTTP, parsing and connection
cleanup, excluding earlier input validation. It is not GPU time, time to first
token, peak memory or an isolated performance benchmark.

Optional `provider_usage` values come only from the final `done=true` event:

| Result Field | Provider Field | Unit |
| --- | --- | --- |
| total_duration_ns | total_duration | Nanoseconds |
| load_duration_ns | load_duration | Nanoseconds |
| prompt_tokens | prompt_eval_count | Provider-reported tokens |
| prompt_duration_ns | prompt_eval_duration | Nanoseconds |
| output_tokens | eval_count | Provider-reported tokens |
| output_duration_ns | eval_duration | Nanoseconds |

Fields were checked against upstream Ollama `api/types.go` at v0.32.9. Missing/null
values stay null; zero stays zero. Values must be integers in [0, 2^63-1], not
booleans, strings or floats. Malformed optional metadata refuses measured results;
legacy text calls still ignore optional metrics. Unknown event fields are omitted.

Provider metrics are unverified self-reports, separate from local elapsed time.
Do not infer cache hits, billing, peak memory or additive timing identities from
them. `peak_memory_bytes` and `model_artifact_sha256` remain null;
`model_identity_verified` is false. Requested/reported model aliases are not
verified weight hashes. Requested `seed` may be an integer in [0, 2147483647];
None omits it. A recorded seed is not a cross-backend determinism guarantee.
Other parameter and deadline bounds remain unchanged.

## Privacy And Identity

`result.text` is the same trimmed answer as the legacy client. It is omitted from
the dataclass representation and `to_dict()` unless `include_text=True` is explicit.
The summary never includes the prompt, endpoint URL, thinking, raw context or
arbitrary provider metadata. Aliases, completion reasons and hashes may still be
private; summaries are not automatically suitable for public issue attachments.

`prompt_sha256` hashes the exact UTF-8 prompt; `response_sha256` hashes the returned
trimmed text. `request_sha256` hashes canonical JSON for the model/prompt/options
payload, not wire serialization. `endpoint_sha256` fingerprints the generate URL.
Hashes do not anonymize low-entropy secrets. Request fields are snapshotted before
waiting, not reread from a modified client after response. Frozen values and
detached summaries are not signatures or proof against a hostile local caller.

## Evaluation Binding

Only after reviewing/provisioning the actual model, artifact/license and budget:

```python
from alita.evaluation_corpus import corpus_digest, generation_prompt
from alita.evaluation_generation import record_generation
from alita.llm import OllamaClient

task_id = "integer-sum"
expected_corpus = corpus_digest()
prompt = generation_prompt(task_id)
client = OllamaClient(model="reviewed-local-model", timeout=60)
# This explicitly contacts the configured provider; do not run without approval.
result = client.generate_result(prompt, temperature=0, max_tokens=512, seed=7)
record = record_generation(task_id, result, expected_corpus_sha256=expected_corpus)
```

Use `await client.generate_result_async(...)` inside an event loop.
`record_generation` itself calls no provider, writes nothing and does not create,
approve or execute a proposal. It checks corpus identity, the exact prompt,
returned-text hash and requested settings/payload hash. Source stays
`unreviewed_source`, not a valid or approved program. Source postprocessing and
ordinary inspected proposal creation still need their own provenance.

For classification use `decision_prompt(task_id)` and `mode="decision"` when
recording. Refusal tasks use decision prompts even in source mode. Structured
labels are graded; malformed/prose output is `invalid_response`. Records explicitly
do not prove who generated the content: callers can construct dataclasses and
servers can misreport metadata. Binding detects mixed observations, not forgery.

## Opt-In Prompt V2

The original corpus, `generation_prompt()` and `decision_prompt()` remain frozen.
`evaluation_prompt(task_id, mode="source", version="v2")` adds an explicit argv
contract: `sys.argv[1]` is `--json`, `sys.argv[2]` is the JSON object string,
and `args["data"]` is the required data object. Valid inputs produce one JSON
result on stdout; invalid inputs use stderr and a nonzero exit. No shell command
construction is needed. Version `v1` remains the default.

```python
from alita.evaluation_prompts import evaluation_prompt

prompt = evaluation_prompt("integer-sum", version="v2")
# After a separately authorized provider request using this exact prompt:
# record = record_generation("integer-sum", result,
#     expected_corpus_sha256=corpus_digest(), prompt_version="v2")
```

Supply the same `prompt_version` to `record_generation`. Versions are bound by
the exact prompt/request hashes, including decision/refusal prompts; a v1 result
cannot be relabelled v2. Task expectations and corpus identity do not change.
Records add `prompt_version` and `source_check`. V1 keeps its previous statuses
and has `source_check=None`; decision records also have no source check.

For v2 source only, recording checks the 128 KiB UTF-8 bound, nonempty text,
opening Markdown fences, a trailing `REQUIREMENTS:` marker and Python syntax.
Malformed source is `invalid_source` with a fixed reason, never repaired or
retried. `source_check.syntax_valid` is null when compilation was not attempted,
false for a compilation failure, and true after compilation succeeds. Syntax
checking compiles to a temporary code object but never executes/imports it or
creates a proposal. Compiler warnings/exceptions are not echoed, since they can
include source. The exact returned-text hash is retained, with no fence removal.

This is not a sandbox or semantic validator. Compilation happens in the operator
process, with a text-size bound but no separate CPU/memory isolation. Valid syntax
can still read host files, perform network I/O, reverse argv positions, hardcode
answers or produce invalid output if executed. Even an empty-behavior program
such as comments alone can pass syntax. Such results stay `unreviewed_source`,
never approved or correct. Review and separately authorized contained tests remain
necessary. Current offline fixtures do not establish improved real-model quality.

## Explicit Source Derivation

A separately invoked [source transformation](source-transformations.md) can
extract exactly one complete Python fence while retaining the original result,
response hash, derived-source hash and transformation version. It never edits
the raw record or upgrades it to success. No compilation, model request,
proposal preparation, approval or execution is implied by this text operation.

## Failures And Remaining Work

Results require a bounded complete stream and valid final metadata. A final
`done_reason=length` may still indicate truncation: transport completion is not
semantic correctness. Existing body/line/text/event bounds, redirects/proxy
refusal, deadlines and owned HTTP cleanup remain in force. Cancellation propagates.

No retries are added. A metadata/binding error can occur after generation already
consumed resources. An exception does not imply zero tokens or permission to replay.
Usage for failed requests remains unknown without a valid returned result.

Tests use ephemeral loopback HTTP with predetermined responses, not installed
models. Real-model identity/license/budget review, actual quality comparison,
execution timing/peak-memory measurement, reuse analysis, external trials and
release decisions remain separate. Old execution receipts and the offline scorer
do not gain invented measurements from this additive generation API.
