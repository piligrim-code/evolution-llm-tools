# Explicit Source Transformations

`unwrap_generation_source()` is an opt-in operation on an existing measured
generation observation. It does not call a model, write files, compile/import
source, prepare a proposal, approve or execute code. It is not invoked by the
generation client, recorder, legacy generator or CLI.

The frozen v1/v2 prompts and raw observation semantics remain unchanged. V3 is
an opt-in prompt revision. A fenced v2/v3 response remains `invalid_source` in
its original record.
The transformation produces a separate `unreviewed_source`, not a successful
evaluation result. The body may still contain invalid syntax or dangerous code.

## API

```python
from alita.evaluation_corpus import corpus_digest
from alita.source_transform import unwrap_generation_source

# result is an existing GenerationResult from a separately authorized request.
derived = unwrap_generation_source(
    "integer-sum", result,
    expected_corpus_sha256=corpus_digest(), prompt_version="v2",
)
summary = derived.to_dict()  # No source or original text by default.
source = derived.source     # Still unreviewed; do not execute it.
```

`prompt_version` is mandatory; v1, v2 and v3 observations are supported. The
operation rechecks task/corpus, exact prompt/response hashes and request settings
through `record_generation`. Decision/refusal observations cannot become source.
Caller-supplied record dictionaries are not accepted in place of GenerationResult.

## Exact Envelope

Transformation version `unwrap-python-fence-v1` accepts exactly one block:

- Opening line is exactly three backticks followed by `python`, then LF or CRLF.
- Closing line is exactly three backticks, optionally ending in LF or CRLF.
- No leading/trailing prose, extra blank lines outside the block, indenting of
  delimiters, other language labels, unlabeled fences or tilde fences.
- Body must be nonempty/non-whitespace. Lines whose first non-whitespace text
  starts with three backticks or three tildes are rejected as ambiguous. This is
  deliberately conservative even inside Python multiline string literals.
- Entire returned text must fit in 128 KiB of UTF-8, without null bytes or invalid
  encoding. Only LF/CRLF can delimit the fence lines; Unicode line separators
  are not fence boundaries. The body is sliced unchanged from the returned text: indentation,
  trailing spaces, mixed line endings and the final body newline are preserved.

This is a narrow transport envelope, not a general Markdown parser. Other formats
are refused, never guessed or repaired. Inline backticks inside ordinary code
are unchanged. No syntax or behavioral validation is performed on the body.

## Identity And Privacy

The frozen result retains the original immutable GenerationResult, task, corpus,
prompt version and original status. Its summary includes the transformation
version, original response hash and independently computed source hash. Original
settings, metrics and hashes are included under `generation` without text by
default. Extracting source never changes the original response hash or observation.
The hashes identify the returned text, not wire bytes before the client's existing
whitespace trimming. They are not signatures or independent provider attestation.

`derived.to_dict(include_text=True)` explicitly includes both the original
generation text and derived source. Repr omits both; summary dictionaries are
detached. Hashes/model aliases can themselves be sensitive. Do not publish raw
observations or machine-specific evidence in issue attachments by default.

Dataclasses and hashes can be constructed by a trusted local caller; this API
detects mixed observations, not malicious forgery. `syntax_valid` remains null,
`execution_authorized` and `generation_provenance_verified` remain false. There
is no automatic retry, approval, filesystem persistence or execution authority.

Review the derived source separately before any explicitly authorized contained
execution. A later proposal must bind the derived source, not reuse the original
response hash as its program identity. Further edits are further transformations
and must not silently reuse this transformation's source hash.
