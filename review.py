"""Local, single-use review receipts. The operator and database directory are trusted."""
from contextlib import closing, contextmanager
import hashlib
import json
import re
import sqlite3
import uuid

from . import container_runner as runner
from .contracts import bounded_text, json_object, tool_spec
from .execution_policy import normalized_tool_name, reject_linked_path

DOCUMENT_LIMIT = 2_000_000


class ReviewError(ValueError):
    pass


def _json(value):
    def check(item):
        if type(item) is dict:
            if not all(type(key) is str for key in item):
                raise ReviewError("non_json_key")
            for child in item.values():
                check(child)
        elif type(item) is list:
            for child in item:
                check(child)
        elif type(item) not in (str, int, float, bool, type(None)):
            raise ReviewError("non_json_value")
    try:
        check(value)
        text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
        bounded_text(text, DOCUMENT_LIMIT)
        return text
    except (TypeError, ValueError, RecursionError):
        raise ReviewError("invalid_review_document") from None


def _digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _policy(policy):
    runner.require_execution_mode(False, policy)
    return {
        "profile": "linux-stdlib-v1", "image": policy.image, "timeout": policy.timeout,
        "network": "none", "host_mounts": False, "read_only_root": True,
        "user": "65534:65534", "dependencies": "forbidden", "capabilities": "none",
        "memory_bytes": runner.MEMORY, "pids": runner.PIDS, "nano_cpus": runner.NANO_CPUS,
        "input_bytes": runner.INPUT_LIMIT, "output_bytes": runner.OUTPUT_LIMIT,
        "tmpfs": runner.TMPFS, "bootstrap_sha256": _digest(runner.BOOTSTRAP),
        "command_sha256": _digest(_json(runner.COMMAND)),
    }


def _document(spec, scripts, args, policy):
    spec = tool_spec(spec)
    # All declared arguments are required; no coercion, defaults or extra keys.
    if not isinstance(args, dict) or set(args) != {arg["name"] for arg in spec["args"]}:
        raise ReviewError("arguments_do_not_match_spec")
    kinds = {"string": (str,), "integer": (int,), "number": (int, float),
             "boolean": (bool,), "object": (dict,), "array": (list,)}
    for arg in spec["args"]:
        if type(args[arg["name"]]) not in kinds[arg["type"]]:
            raise ReviewError("argument_type_mismatch")
    runner.validate_payload(scripts, args)
    try:
        compile(scripts["tool.py"], "<reviewed tool>", "exec")
    except (SyntaxError, ValueError, RecursionError):
        raise ReviewError("invalid_python_syntax") from None
    return {"version": 1, "spec": spec, "scripts": scripts, "args": args,
            "policy": _policy(policy),
            "source_sha256": {name: _digest(source) for name, source in scripts.items()}}


class ReviewStore:
    """A local SQLite journal, separate from the legacy working-tool registry."""

    def __init__(self, path=".mcp/reviews.sqlite3"):
        self.path = reject_linked_path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise ReviewError("unsupported_review_store_version")
            db.execute("""CREATE TABLE IF NOT EXISTS proposals (
                id TEXT PRIMARY KEY, document TEXT NOT NULL, digest TEXT NOT NULL,
                state TEXT NOT NULL, approval TEXT, result TEXT)""")
            db.execute("PRAGMA user_version=1")

    @contextmanager
    def _connection(self):
        # SQLite sidecars are also inside the trusted operator-owned directory.
        for suffix in ("", "-journal", "-wal", "-shm"):
            reject_linked_path(str(self.path) + suffix)
        with closing(sqlite3.connect(self.path, timeout=5, isolation_level=None)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA trusted_schema=OFF")
            db.execute("PRAGMA synchronous=FULL")
            yield db

    @contextmanager
    def _transaction(self):
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def _load(self, db, proposal_id):
        if not isinstance(proposal_id, str) or not re.fullmatch(r"[a-f0-9]{32}", proposal_id):
            raise ReviewError("invalid_proposal_id")
        row = db.execute("SELECT * FROM proposals WHERE id=?", (proposal_id,)).fetchone()
        if row is None:
            raise ReviewError("proposal_not_found")
        doc = json_object(row["document"], limit=DOCUMENT_LIMIT)
        if _digest(_json(doc)) != row["digest"]:
            raise ReviewError("proposal_content_changed")
        try:
            policy = runner.ContainerPolicy(doc["policy"]["image"], doc["policy"]["timeout"])
            expected = _document(doc["spec"], doc["scripts"], doc["args"], policy)
        except (KeyError, TypeError):
            raise ReviewError("invalid_review_document") from None
        if _json(expected) != _json(doc):
            raise ReviewError("proposal_policy_or_contract_changed")
        return row, doc, policy

    def create(self, spec, scripts, args, policy):
        document = _json(_document(spec, scripts, args, policy))
        identifier = uuid.uuid4().hex
        with self._transaction() as db:
            db.execute("INSERT INTO proposals(id,document,digest,state) VALUES(?,?,?,'pending')",
                       (identifier, document, _digest(document)))
        return identifier

    def inspect(self, proposal_id):
        with self._connection() as db:
            row, doc, _ = self._load(db, proposal_id)
            return {"id": proposal_id, "digest": row["digest"], "state": row["state"],
                    "document": doc, "result": json_object(row["result"], limit=DOCUMENT_LIMIT)
                    if row["result"] is not None else None}

    def approve(self, proposal_id, digest, *, confirm=False):
        if confirm is not True:
            raise PermissionError("explicit_review_approval_required")
        with self._transaction() as db:
            row, _, _ = self._load(db, proposal_id)
            if row["state"] != "pending":
                raise ReviewError("proposal_not_pending")
            if digest != row["digest"]:
                raise ReviewError("review_digest_mismatch")
            db.execute("UPDATE proposals SET state='approved', approval=? WHERE id=?", (digest, proposal_id))

    def cancel(self, proposal_id):
        with self._transaction() as db:
            row, _, _ = self._load(db, proposal_id)
            if row["state"] not in ("pending", "approved"):
                raise ReviewError("proposal_not_cancellable")
            db.execute("UPDATE proposals SET state='cancelled', approval=NULL WHERE id=?", (proposal_id,))

    def _finish(self, proposal_id, result):
        with self._transaction() as db:
            changed = db.execute("UPDATE proposals SET state='finished', result=? WHERE id=? AND state='claimed'",
                                 (_json(result), proposal_id)).rowcount
            if changed != 1:
                raise ReviewError("execution_receipt_not_saved")

    def execute(self, proposal_id):
        with self._transaction() as db:
            row, doc, policy = self._load(db, proposal_id)
            if row["state"] != "approved" or row["approval"] != row["digest"]:
                raise PermissionError("proposal_not_approved_or_already_attempted")
            # Commit consumption BEFORE calling any executor. Even ambiguous failures
            # remain consumed; another process cannot claim this approval again.
            db.execute("UPDATE proposals SET state='claimed' WHERE id=?", (proposal_id,))
        try:
            result = runner.ContainerExecutor(policy).run(doc["scripts"], doc["args"])
        except runner.ContainerError as error:
            try:
                self._finish(proposal_id, {"error": error.code, "resource": error.resource})
            except Exception as receipt_error:
                # Preserve the owned-resource identity even when the disk fails.
                raise error from receipt_error
            raise
        # Unexpected errors/interrupts or failed persistence leave state=claimed.
        self._finish(proposal_id, result)
        return result


def propose(question, name, policy, store, *, args=None, model=None):
    """Generate a stdlib-only draft, never execute it or register it as working."""
    from .llm import OllamaClient
    from .mcp.brainstorming import brainstorm_tools
    from .mcp.script_generator import propose_tool_scripts

    bounded_text(question, 16000)
    name = normalized_tool_name(name)
    _policy(policy)
    provider = OllamaClient(model=model)
    spec = brainstorm_tools(question, name, provider, stdlib_only=True)
    if args is None:
        if any(arg["name"] not in ("text", "question", "input") or arg["type"] != "string"
               for arg in spec["args"]):
            raise ReviewError("explicit_arguments_required")
        args = {arg["name"]: question for arg in spec["args"]}
    scripts = propose_tool_scripts(spec, provider, stdlib_only=True)
    return store.create(spec, scripts, args, policy)
