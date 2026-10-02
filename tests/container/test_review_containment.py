"""Review receipts around real contained execution of a hand-written fixture."""
import os

import pytest

from alita.container_runner import ContainerExecutor, ContainerPolicy
from alita.review import ReviewStore

pytestmark = pytest.mark.skipif(os.environ.get("ALITA_CONTAINER_TESTS") != "1",
                               reason="requires explicit disposable Docker run")


def test_reviewed_fixture_requires_approval_and_cannot_replay(tmp_path, monkeypatch):
    from alita import review

    instances = []

    def executor(policy):
        instance = ContainerExecutor(policy)
        instances.append(instance)
        return instance

    monkeypatch.setattr(review.runner, "ContainerExecutor", executor)
    store = ReviewStore(tmp_path / "reviews.sqlite3")
    identifier = store.create(
        {"name": "length", "args": [{"name": "text", "type": "string"}], "output": "Text length"},
        {"tool.py": "import json, sys\nprint(len(json.loads(sys.argv[2])['text']))\n"},
        {"text": "synthetic"}, ContainerPolicy(os.environ["ALITA_TEST_IMAGE"]))
    assert not instances
    with pytest.raises(PermissionError):
        store.execute(identifier)
    assert not instances
    store.approve(identifier, store.inspect(identifier)["digest"], confirm=True)
    assert not instances
    result = store.execute(identifier)
    assert result["returncode"] == 0 and result["stdout"].strip() == "9"
    assert store.inspect(identifier)["result"] == result
    with pytest.raises(PermissionError):
        ReviewStore(store.path).execute(identifier)
    assert len(instances) == 1
    controller = instances[0]
    remaining = controller._docker("container", "ls", "--all", "--quiet", "--filter",
                                   "label=io.alita.executor.owner=" + controller.owner)
    assert not remaining.stdout.strip(), "Owned container was not removed"
