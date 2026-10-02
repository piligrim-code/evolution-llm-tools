"""Prepare an explicit public dependency image on a verified local Linux engine."""
import json
import os
from pathlib import Path
import subprocess
import sys

from alita.container_runner import ContainerExecutor, ContainerPolicy


def main():
    controller = ContainerExecutor(ContainerPolicy("sha256:" + "0" * 64)).check_engine()
    # Pull is test setup only; the executor itself never pulls or builds images.
    controller._docker("pull", "python:3.12-slim", timeout=180)
    image = controller._json("image", "inspect", "python:3.12-slim")[0]
    policy = ContainerPolicy(image["Id"])
    print(json.dumps({"image_id": policy.image, "os": image["Os"], "architecture": image["Architecture"]}), flush=True)
    env = dict(os.environ, ALITA_CONTAINER_TESTS="1", ALITA_TEST_IMAGE=policy.image)
    return subprocess.run([sys.executable, "-m", "pytest", "tests/container", "-q", "--tb=short"],
                          cwd=Path(__file__).resolve().parents[1], env=env, timeout=240).returncode


if __name__ == "__main__":
    raise SystemExit(main())
