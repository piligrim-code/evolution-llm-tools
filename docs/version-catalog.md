# Validated Version Catalog

The catalog preserves explicitly selected, output-validated proposals as immutable
versions. It is separate from the single-use review journal and legacy
`tools`/`tool-run` registry. Entries never grant execution permission. There is
no catalog `run` command, automatic promotion or latest-version execution alias.

## Version And Provenance

A version is a validated configuration: code/dependency hashes, input spec,
exact tested arguments, expected output and immutable image/resource policy.
Its identity is the full SHA-256 of that reviewed document, not a semantic-version
label. Changing any field creates a different version. The saved record also
contains the first successful proposal ID and result receipt. A match on one
input does not prove general algorithm correctness. Provenance is a trusted local
receipt, not an external signature or independently certified report.

Promotion requires explicit confirmation, an unchanged approved v2 proposal in
`finished` state and a currently reproducible passing output check. A stored
`passed` flag or exit code zero alone is insufficient. Pending, claimed, cancelled,
failed, v1 and incomplete proposals are refused. Cleanup errors take precedence.
Promotion never executes a tool or alters its approval. Re-promoting identical
content returns `promoted=false` and retains the first provenance, including
under concurrent callers.

## CLI

First complete the [reviewed output workflow](output-contracts.md), then:

```sh
evolution-tools catalog promote <completed-proposal-id>
evolution-tools catalog list --name length --limit 20
evolution-tools catalog inspect length <full-version-digest>
evolution-tools catalog prepare length <full-version-digest>
```

Promotion's prompt defaults to no. `--yes` is explicit confirmation, not a
substitute for inspecting the completed proposal. Lists contain only name,
version, insertion sequence and paging metadata, not source/result bodies. Use
`--before <next_cursor>` with the same name filter for older entries. Limits are
1 through 100; unknown cursors are refused. Listing does not verify record contents.

`inspect` shows the private snapshot/provenance and verifies stored digests;
`execution_authorized` is always false. Historical versions remain inspectable
after a policy change. `prepare` separately checks the current policy and original
proof; incompatible versions are refused rather than silently upgraded.

Preparation creates a new **pending** proposal and returns its ID/source version.
That new proposal needs its own inspection, approval and execution:

```sh
evolution-tools review inspect <new-proposal-id> --json
evolution-tools review approve <new-proposal-id> --digest <inspected-digest>
evolution-tools review execute <new-proposal-id>
```

An exact copy can have the original document digest but has a new ID with no
approval/result. A consumed approval is never reused. Repeated preparation
creates drafts, not execution retries. If the response was lost, inspect
`review list` before making another draft.

Changing inputs requires both new arguments and a new independent expectation.
For a text-length tool, using POSIX-shell JSON quoting:

```sh
evolution-tools catalog prepare length <full-version-digest> --args '{"text":"changed"}' --output-contract '{"kind":"stdout-equals","expected":"7\n"}'
```

Supplying only one is refused. The new draft is still pending and untested; the
old version's success does not validate these inputs. Successful execution does
not automatically save another version.

## Storage And API

Defaults are private `.mcp/versions.sqlite3` and `.mcp/reviews.sqlite3`, relative
to the current directory. Override paths before the subcommand:

```sh
evolution-tools catalog --store /private/versions.sqlite3 --review-store /private/reviews.sqlite3 promote <proposal-id>
```

The catalog has a distinct SQLite application ID/schema version and refuses an
unrelated database. ReviewStore also refuses non-review application IDs so it
cannot accidentally initialize inside a catalog. Existing review journals and
legacy registry entries are not migrated or imported automatically.

```python
from alita.catalog import VersionCatalog
from alita.review import ReviewStore

reviews = ReviewStore("private/reviews.sqlite3")
catalog = VersionCatalog("private/versions.sqlite3")
# Supply an independently inspected, completed output-validated proposal ID.
saved = catalog.promote(reviews, completed_id, confirm=True)
version = catalog.inspect(saved["name"], saved["version"])
new = catalog.prepare(saved["name"], saved["version"], reviews)
assert reviews.inspect(new["id"])["state"] == "pending"
```

`VersionCatalog(path, read_only=True)` does not create missing stores/directories
or change catalog records. Preparing with a read-only catalog still writes a new
draft into the explicitly supplied writable review journal. Promotion needs a
writable catalog but can read a read-only review journal. The CLI uses these modes.

The preparation response's `source_version` is metadata, not a foreign key added
to the v2 review document. Retain that returned mapping for a separate usage audit.
The new document binds its own code/arguments/expectation. The catalog records
version history and original provenance, not the full history of every reuse.

## Durability And Trust

SQLite transactions with full synchronous writes and a unique name/version key
serialize insertion. Normal SQL updates/deletes are refused by immutable-row
triggers. Initialization is transactional; future/foreign schemas are refused.
Failed promotion can be retried explicitly without replaying execution. If a
commit response was lost, repeating promotion returns the preserved version.

The finished review row is read as one snapshot and copied. The original journal
is not modified. These are separate stores, not a distributed transaction; catalog
versions can prepare fresh reviews even after the original journal is unavailable.
Preparation uses the normal atomic pending-proposal insertion, never approval.

The operator, directories and local storage are trusted. A privileged writer can
drop triggers, rewrite hashes or restore older files. This is not protection
against that attacker or hostile filesystem races. Linked paths are refused;
network filesystems and untrusted multi-user operation are not qualified. SQLite
may use locking sidecars on reads; readonly does not mean immutable OS metadata.

Records contain private plaintext source, arguments, expectations and outputs.
Even names/hashes can be sensitive. Protect directories/backups and keep `.mcp/`
out of Git. Each canonical record is bounded by the existing 2,000,000-byte review
limit. No automatic pruning, retirement, quota policy or remote sync is provided.
Do not bypass immutable triggers as routine maintenance; retention needs a later
explicit design.

## Verification And Remaining Work

```sh
python -m pytest tests/test_catalog.py -q
python -m pytest tests -q --tb=short -ra
python tools/run_container_tests.py
```

Tests cover fake-success rejection, first provenance, threads/processes,
commit/initialization failures, wrong-store/readonly guards, paging, changed
policies and fresh pending reuse. Actual Docker fixtures cover execution through
promotion and independently approved reuse with changed inputs, and refusal of
incorrect output. All fixtures use synthetic data.

The general typed execution-result API, retention/pruning policy and three
packaged deterministic demos remain further EVO-2 work, along with native
Linux-host CI and separate external/model evaluation.
