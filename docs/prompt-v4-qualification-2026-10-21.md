# Prompt v4 Qualification: JSON-Mode Source Envelope

Date: October 21, 2026.
Model: local Ollama `qwen2.5:7b`, `temperature=0`, `seed=7`, `max_tokens=2048`,
provider JSON mode. One request per task, no retries, no transformations.
Corpus: `toolwright-eval-v1` (unchanged).

## Summary

v4 was meant to remove the Markdown fences that `qwen2.5:7b` put around every
v3 reply. It does that, and it fixes refusals (4/4 correct, against 0/4 for
fenced v3 JSON). For source, it does worse than v3 with the recorded fence
transformation: **4/16 tasks and 16/48 cases**, against 11/16 and 39/48.

v4 stays opt-in. It is not a replacement for v3.

## Results

| Measure | v3 + fence transform | v4 JSON envelope |
| --- | --- | --- |
| Usable tool sources | 16/16 | 7/16 |
| Tool tasks passed | 11/16 | 4/16 |
| Cases correct | 39/48 | 16/48 (27 missing) |
| Refusal decisions correct | 0/4 (fenced) | 4/4 |

Of the 16 v4 tool requests:

- **4 requests: provider stream incomplete.** After the JSON object the model
  emitted a run of newlines, and Ollama ended the stream without a `done`
  event. A separate diagnostic request reproduced this (130 events, the last
  with `done: false`). The client refused these responses as
  `incomplete_response`, which is correct.
- **5 requests: invalid Python after decoding the envelope.** The model wrote
  Python string escapes such as `'...\n'` without JSON-escaping the backslash.
  Decoding the JSON turned them into literal newlines inside the Python string
  literal, which then failed to compile. This is a general cost of carrying
  code inside JSON.
- **7 requests: usable source.** Of these, `integer-sum` failed every case
  because it imports `sys` only inside its `except` block, despite the new
  "import every module you use" rule. `chunk-list` and `json-project` each
  failed one case.

## Conclusion

Provider JSON mode suits short decisions but not code for this model:
escaping errors and runaway whitespace cost more than the fences did. A better
direction is to keep JSON mode for decisions and accept a single fenced
Python block as the declared source format, rather than treating it as an
error to be transformed.

Raw responses, receipts and the review journal remain private.
