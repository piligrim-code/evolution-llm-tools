from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import multiprocessing
import sqlite3
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from alita import cli, review
from alita.container_runner import ContainerError, ContainerPolicy

IMAGE = "sha256:" + "a" * 64
SPEC = {"name": "fixture", "args": [{"name": "text", "type": "string"}], "output": "Text length"}
SCRIPTS = {"tool.py": "print('fixture')\n", "requirements.txt": ""}
ARGS = {"text": "synthetic"}
SUCCESS = {"returncode": 0, "stdout": "9\n", "stderr": "", "execution": "container", "outcome": "exited"}


@pytest.fixture
def store(tmp_path):
    return review.ReviewStore(tmp_path / "reviews.sqlite3")


@pytest.fixture(autouse=True)
def executor(monkeypatch):
    mock = Mock(side_effect=AssertionError("Unexpected execution"))
    monkeypatch.setattr(review.runner, "ContainerExecutor", mock)
    return mock


def create(store):
    return store.create(SPEC, SCRIPTS, ARGS, ContainerPolicy(IMAGE))


def approve(store, identifier):
    store.approve(identifier, store.inspect(identifier)["digest"], confirm=True)


def modify(store, identifier, transform, *, rehash=False):
    with sqlite3.connect(store.path) as db:
        doc = json.loads(db.execute("SELECT document FROM proposals WHERE id=?", (identifier,)).fetchone()[0])
        transform(doc)
        text = review._json(doc)
        db.execute("UPDATE proposals SET document=? WHERE id=?", (text, identifier))
        if rehash:
            db.execute("UPDATE proposals SET digest=? WHERE id=?", (review._digest(text), identifier))


def test_create_inspect_approve_do_not_execute_or_mutate_returned_source(store, tmp_path, executor):
    sentinel = tmp_path / "must-not-exist"
    scripts = {"tool.py": f"open({str(sentinel)!r}, 'w').write('synthetic')"}
    identifier = store.create(SPEC, scripts, ARGS, ContainerPolicy(IMAGE))
    record = store.inspect(identifier)
    assert record["state"] == "pending" and record["result"] is None
    assert record["document"]["scripts"] == scripts
    record["document"]["scripts"]["tool.py"] = "raise Exception()"
    assert store.inspect(identifier)["document"]["scripts"] == scripts
    approve(store, identifier)
    assert store.inspect(identifier)["state"] == "approved"
    assert not sentinel.exists()
    executor.assert_not_called()


def test_default_refusal_and_digest_required(store, executor):
    identifier = create(store)
    with pytest.raises(PermissionError):
        store.execute(identifier)
    with pytest.raises(PermissionError):
        store.approve(identifier, store.inspect(identifier)["digest"])
    with pytest.raises(review.ReviewError, match="digest_mismatch"):
        store.approve(identifier, "0" * 64, confirm=True)
    assert store.inspect(identifier)["state"] == "pending"
    executor.assert_not_called()


@pytest.mark.parametrize("field,value", [
    ("scripts", {"tool.py": "print('changed')"}),
    ("scripts", {"tool.py": SCRIPTS["tool.py"], "requirements.txt": "dependency==1"}),
    ("args", {"text": "changed"}), ("spec", {"name": "other"}),
    ("source_sha256", {}), ("policy", {"image": "sha256:" + "b" * 64, "timeout": 20}),
])
def test_any_content_change_invalidates_approval(store, executor, field, value):
    identifier = create(store)
    approve(store, identifier)
    modify(store, identifier, lambda doc: doc.update({field: value}))
    with pytest.raises(review.ReviewError, match="content_changed"):
        store.execute(identifier)
    executor.assert_not_called()


@pytest.mark.parametrize("rehash", [False, True])
def test_changed_exact_arguments_never_reuse_old_approval(store, executor, rehash):
    identifier = create(store)
    approve(store, identifier)
    modify(store, identifier, lambda doc: doc["args"].update(text="different"), rehash=rehash)
    with pytest.raises((PermissionError, review.ReviewError)):
        store.execute(identifier)
    executor.assert_not_called()


def test_current_policy_change_requires_new_proposal(store, monkeypatch, executor):
    identifier = create(store)
    approve(store, identifier)
    monkeypatch.setattr(review.runner, "OUTPUT_LIMIT", 123)
    with pytest.raises(review.ReviewError, match="policy_or_contract_changed"):
        store.execute(identifier)
    executor.assert_not_called()


@pytest.mark.parametrize("args", [{}, {"extra": "x", "text": "x"}, {"text": 1}, {"text": True}])
def test_argument_contract_has_no_silent_coercion(store, args):
    with pytest.raises(review.ReviewError):
        store.create(SPEC, SCRIPTS, args, ContainerPolicy(IMAGE))


@pytest.mark.parametrize("kind,value", [("integer", True), ("number", True), ("object", {1: "x"}),
                                      ("array", [float("nan")]), ("array", [(1, 2)])])
def test_only_strict_json_values(store, kind, value):
    spec = {"name": "fixture", "args": [{"name": "x", "type": kind}]}
    with pytest.raises(ValueError):
        store.create(spec, SCRIPTS, {"x": value}, ContainerPolicy(IMAGE))


@pytest.mark.parametrize("scripts", [{"tool.py": "if :"}, {"tool.py": "print(1)", "extra.py": ""},
                                      {"tool.py": "print(1)", "requirements.txt": "package"}])
def test_invalid_scripts_and_dependencies_refused(store, scripts):
    with pytest.raises((ValueError, PermissionError)):
        store.create(SPEC, scripts, ARGS, ContainerPolicy(IMAGE))


@pytest.mark.parametrize("policy", [None, {"image": IMAGE}, True])
def test_policy_metadata_cannot_grant_rights(store, policy):
    with pytest.raises(PermissionError):
        store.create(SPEC, SCRIPTS, ARGS, policy)


def test_approval_is_not_transferable_between_proposals(store):
    first = create(store)
    second = create(store)
    approve(store, first)
    with pytest.raises(PermissionError):
        store.execute(second)


@pytest.mark.parametrize("approved", [False, True])
def test_cancel_is_final(store, approved, executor):
    identifier = create(store)
    if approved:
        approve(store, identifier)
    store.cancel(identifier)
    assert store.inspect(identifier)["state"] == "cancelled"
    with pytest.raises(review.ReviewError):
        approve(store, identifier)
    with pytest.raises(PermissionError):
        store.execute(identifier)
    executor.assert_not_called()


def test_interrupted_approval_rolls_back(store, monkeypatch):
    identifier = create(store)
    original = store._transaction

    @contextmanager
    def interrupted():
        with original() as db:
            yield db
            raise KeyboardInterrupt()

    monkeypatch.setattr(store, "_transaction", interrupted)
    with pytest.raises(KeyboardInterrupt):
        approve(store, identifier)
    assert store.inspect(identifier)["state"] == "pending"


def test_execute_uses_exact_snapshot_only_once(store, executor):
    identifier = create(store)
    approve(store, identifier)
    executor.side_effect = None
    executor.return_value.run.return_value = SUCCESS
    assert store.execute(identifier) == SUCCESS
    executor.assert_called_once_with(ContainerPolicy(IMAGE))
    executor.return_value.run.assert_called_once_with(SCRIPTS, ARGS)
    assert store.inspect(identifier)["result"] == SUCCESS
    with pytest.raises(PermissionError):
        review.ReviewStore(store.path).execute(identifier)
    with pytest.raises(review.ReviewError):
        approve(store, identifier)


def test_concurrent_claims_from_separate_store_instances_have_one_winner(store, executor):
    identifier = create(store)
    approve(store, identifier)
    executor.side_effect = None
    executor.return_value.run.return_value = SUCCESS

    def attempt(_):
        try:
            review.ReviewStore(store.path).execute(identifier)
            return "executed"
        except PermissionError:
            return "refused"

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(attempt, range(8)))
    assert outcomes.count("executed") == 1 and outcomes.count("refused") == 7
    executor.return_value.run.assert_called_once()


def _process_attempt(arguments):
    path, identifier = arguments
    # Spawned workers cannot inherit pytest patches. Use a synthetic executor;
    # this test exercises the on-disk claim, not generated code or Docker.
    review.runner.ContainerExecutor = Mock()
    review.runner.ContainerExecutor.return_value.run.return_value = SUCCESS
    try:
        review.ReviewStore(path).execute(identifier)
        return "executed"
    except PermissionError:
        return "refused"


def test_concurrent_processes_have_one_winner(store):
    identifier = create(store)
    approve(store, identifier)
    with multiprocessing.get_context("spawn").Pool(4) as pool:
        outcomes = pool.map(_process_attempt, [(str(store.path), identifier)] * 4)
    assert outcomes.count("executed") == 1 and outcomes.count("refused") == 3


@pytest.mark.parametrize("error", [ContainerError("engine_missing"), ContainerError("cleanup_unconfirmed", "owned-fixture"),
                                   RuntimeError("synthetic failure"), KeyboardInterrupt()])
def test_execution_error_or_interruption_never_replays(store, executor, error):
    identifier = create(store)
    approve(store, identifier)
    executor.side_effect = None
    executor.return_value.run.side_effect = error
    with pytest.raises(type(error)):
        store.execute(identifier)
    record = store.inspect(identifier)
    if isinstance(error, ContainerError):
        assert record["state"] == "finished"
        assert record["result"] == {"error": error.code, "resource": error.resource}
    else:
        assert record["state"] == "claimed" and record["result"] is None
    with pytest.raises(PermissionError):
        store.execute(identifier)
    executor.return_value.run.assert_called_once()


def test_failed_receipt_write_preserves_consumption(store, monkeypatch, executor):
    identifier = create(store)
    approve(store, identifier)
    executor.side_effect = None
    executor.return_value.run.return_value = SUCCESS
    monkeypatch.setattr(store, "_finish", Mock(side_effect=sqlite3.OperationalError("synthetic disk full")))
    with pytest.raises(sqlite3.OperationalError):
        store.execute(identifier)
    assert store.inspect(identifier)["state"] == "claimed"
    with pytest.raises(PermissionError):
        review.ReviewStore(store.path).execute(identifier)
    executor.return_value.run.assert_called_once()


def test_cleanup_identity_survives_receipt_failure(store, monkeypatch, executor):
    identifier = create(store)
    approve(store, identifier)
    executor.side_effect = None
    executor.return_value.run.side_effect = ContainerError("cleanup_unconfirmed", "owned-fixture")
    monkeypatch.setattr(store, "_finish", Mock(side_effect=sqlite3.OperationalError("synthetic disk full")))
    with pytest.raises(ContainerError) as caught:
        store.execute(identifier)
    assert caught.value.resource == "owned-fixture"
    assert store.inspect(identifier)["state"] == "claimed"
    with pytest.raises(PermissionError):
        store.execute(identifier)


def test_cannot_cancel_after_claim(store, executor):
    identifier = create(store)
    approve(store, identifier)

    def run(scripts, args):
        assert store.inspect(identifier)["state"] == "claimed"
        with pytest.raises(review.ReviewError, match="not_cancellable"):
            store.cancel(identifier)
        return SUCCESS

    executor.side_effect = None
    executor.return_value.run.side_effect = run
    store.execute(identifier)


def test_failed_claim_commit_never_calls_executor(store, monkeypatch, executor):
    identifier = create(store)
    approve(store, identifier)
    original = store._transaction

    @contextmanager
    def failed_commit():
        with original() as db:
            yield db
            raise sqlite3.OperationalError("synthetic commit failure")

    monkeypatch.setattr(store, "_transaction", failed_commit)
    with pytest.raises(sqlite3.OperationalError):
        store.execute(identifier)
    assert store.inspect(identifier)["state"] == "approved"
    executor.assert_not_called()


@pytest.mark.parametrize("response", ["n\n", "", "\n"])
def test_cli_cancelled_confirmation_does_not_approve(store, response):
    identifier = create(store)
    result = CliRunner().invoke(cli.app, ["review", "--store", str(store.path), "approve", identifier,
                                         "--digest", store.inspect(identifier)["digest"]], input=response)
    assert result.exit_code != 0
    assert store.inspect(identifier)["state"] == "pending"


def test_cli_full_fake_provider_flow(store, monkeypatch, executor):
    from alita import llm
    client = Mock()
    client.generate.side_effect = [json.dumps(SPEC), SCRIPTS["tool.py"] + "REQUIREMENTS: none"]
    factory = Mock(return_value=client)
    monkeypatch.setattr(llm, "OllamaClient", factory)
    runner = CliRunner()
    prefix = ["review", "--store", str(store.path)]
    draft = runner.invoke(cli.app, prefix + ["propose", "synthetic", "--container-image", IMAGE])
    assert draft.exit_code == 0, draft.output
    data = json.loads(draft.output)
    factory.assert_called_once_with(model=None)
    assert client.generate.call_count == 2
    executor.assert_not_called()
    record = runner.invoke(cli.app, prefix + ["inspect", data["id"], "--json"])
    assert record.exit_code == 0, record.output
    assert json.loads(record.output)["document"]["args"] == ARGS
    approval = runner.invoke(cli.app, prefix + ["approve", data["id"], "--digest", data["digest"], "--yes"])
    assert approval.exit_code == 0, approval.output
    executor.assert_not_called()
    executor.side_effect = None
    executor.return_value.run.return_value = SUCCESS
    execution = runner.invoke(cli.app, prefix + ["execute", data["id"]])
    assert execution.exit_code == 0, execution.output
    assert json.loads(execution.output) == SUCCESS
    assert runner.invoke(cli.app, prefix + ["execute", data["id"]]).exit_code == 2


def test_cli_does_not_render_source_as_terminal_controls_or_rich_markup(store):
    identifier = store.create(SPEC, {"tool.py": "# \x1b[31m [link=https://example.invalid]demo[/link]\nprint(1)"},
                              ARGS, ContainerPolicy(IMAGE))
    result = CliRunner().invoke(cli.app, ["review", "--store", str(store.path), "inspect", identifier])
    assert result.exit_code == 0, result.output
    assert "\x1b" not in result.output
    assert "[link=https://example.invalid]demo[/link]" in result.output


@pytest.mark.parametrize("identifier", ["../bad", "", "a" * 32])
def test_invalid_or_missing_ids(store, identifier):
    with pytest.raises(review.ReviewError):
        store.inspect(identifier)


def test_unknown_schema_version_is_not_overwritten(store):
    with sqlite3.connect(store.path) as db:
        db.execute("PRAGMA user_version=99")
    with pytest.raises(review.ReviewError, match="unsupported_review_store_version"):
        review.ReviewStore(store.path)


def test_nonzero_exit_is_consumed_and_cli_fails(store, executor):
    identifier = create(store)
    approve(store, identifier)
    executor.side_effect = None
    executor.return_value.run.return_value = dict(SUCCESS, returncode=1, stderr="fixture failure")
    result = CliRunner().invoke(cli.app, ["review", "--store", str(store.path), "execute", identifier])
    assert result.exit_code == 1, result.output
    assert store.inspect(identifier)["state"] == "finished"
    with pytest.raises(PermissionError):
        store.execute(identifier)
