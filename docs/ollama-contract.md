# Ollama Transport And Model Contracts

The client uses the Ollama `/api/generate` streaming protocol. It sends `stream`
explicitly and applies the configured `max_tokens` as `options.num_predict` even
when the caller does not override it. Manager decisions and tool specifications
request `format: json`; code generation remains text. Responses are still validated
locally: asking a model for JSON does not make its output trustworthy.

## Transport Bounds

| Boundary | Limit |
| --- | --- |
| Prompt | 65,536 UTF-8 bytes |
| Model identifier | 256 UTF-8 bytes |
| Aggregate generation deadline | settings.request_timeout, default90s; explicit range(0,300] |
| Connection / read inactivity | At most5s /15s, capped by the aggregate deadline |
| Entire response body | 1MiB |
| One NDJSON line | 256KiB |
| Returned response text | 128KiB |
| Nonblank stream events | 8,192 |
| Requested output tokens | Configured default1,024; accepted range1..4,096 |

The aggregate deadline covers connection and reading/cleanup in an asyncio timeout
scope; continuously arriving chunks cannot reset it. These are asynchronous and
application-buffer bounds, not a hard OS CPU/RAM/process guarantee. A manager flow
can make multiple bounded requests; there is no single whole-question deadline.

The base URL comes only from caller/configuration, not model output. It must be
HTTP(S), with no credentials/query/fragment. Environment proxies, redirects,
compressed responses and automatic request retries are not used. Local Ollama is
the existing default; configuring a remote service sends prompts/code there and
requires separate transport/authentication/data-policy review. No models are pulled.

`generate()` is the synchronous CLI-facing API. It refuses calls inside an active
event loop; async callers use `await generate_async()`. A new owned HTTP session
and response context are closed on success, provider errors, truncation, timeout
or cancellation. Cancellation propagates; errors expose fixed codes/statuses,
not raw provider bodies, prompts, URLs or credentials.

## Complete Responses Only

NDJSON is decoded incrementally across arbitrary network/UTF-8 boundaries. JSON
must be an object with unique keys and finite numbers. Each event has a boolean
`done`; response/thinking text, when present, must be strings. A final event can
omit its empty response fragment. Provider error events are failures, not answers.
Unused provider metrics are tolerated rather than used as application settings.

Success requires a `done: true` event and clean HTTP body completion. Missing
completion, trailing nonblank events, invalid fields, malformed JSON, transport
truncation and empty final text fail; previously received fragments are not returned
as a successful partial answer. A terminal event followed by a hanging HTTP body
still meets the aggregate timeout, not an indefinite wait.

## Manager And Generation Contracts

The manager accepts an exact JSON object, not a guessed object extracted from
prose. `need_tool` must be a real boolean; required text fields are bounded and a
direct-answer decision must contain an answer. Additional decision metadata is
ignored and cannot grant execution consent. Malformed output no longer falls back
to displaying the raw draft as a direct answer. The existing calculation heuristic
can still request a tool, but cannot bypass the explicit execution mode check.

Tool names, argument schema, example arguments and descriptive fields are checked.
The command entrypoint is normalized to the supported Python/JSON contract rather
than trusting a model-supplied shell command. The manager maps the question only
to string aliases `text`, `question` and `input` (or a default `text` argument when
none are declared). An unsupported argument mapping is refused instead of sending
the wrong arguments silently. Direct `tool-run --args` remains available for
owner-reviewed tools with other JSON inputs.

Generated code must contain exactly one final `REQUIREMENTS:` line. An optional
complete Python fence is accepted; arbitrary prose or partial fences are not.
Empty/ambiguous dependency declarations and invalid Python syntax are refused.
The contained stdlib profile rejects nonempty requirements before execution.
Compilation checks syntax only and does not run the source; it is not a safety
approval, a semantic test or proof that a model solved the requested problem.

Default execution denial and container/unsafe-host mode separation are unchanged.
The default-deny gate remains outside all model-controlled data. Registry manifests,
prompts, JSON mode and syntax checking are not alternate permission sources.
CLI final output disables rich markup and strips terminal-control characters.

## Verification And Remaining Gates

Default tests use actual ephemeral loopback HTTP servers with predetermined NDJSON.
They cover request options, proxy/redirect refusal, malformed/duplicate/oversized
events, completion, slow drip, transport failure, cancellation and session closure.
Structured-output tests ensure invalid decisions/specifications never lead to an
execution attempt. The Windows drip fixture uses intervals above its coarse clock
resolution so it actually exercises elapsed time rather than a burst of writes.

The Docker integration fixture now traverses actual HTTP -> Ollama client ->
manager -> specification -> code parsing -> contained execution -> registry ->
reuse. The provider and source are synthetic, not a downloaded or evaluated model.
Real Ollama/model-version compatibility, generation quality, prompt-injection
resistance, throughput, remote authentication and multi-user deployment still
require separate qualification. Container containment has its own documented
kernel/daemon/image assumptions; this transport change does not remove them.
