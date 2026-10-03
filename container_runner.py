"""Opt-in Linux container execution. The local Docker daemon and image are trusted."""
from dataclasses import dataclass
import hashlib
import json
import math
import os
import re
import subprocess
from threading import Event, Lock, Thread
import time
from urllib.parse import urlsplit
import uuid

from .execution_policy import validate_scripts

OWNER_LABEL = "io.alita.executor.owner"
MEMORY = 128 * 1024 * 1024
PIDS = 32
NANO_CPUS = 500_000_000
OUTPUT_LIMIT = 65536
INPUT_LIMIT = 320000
TMPFS = "rw,nosuid,nodev,noexec,size=16777216,uid=65534,gid=65534,mode=0700"
BOOTSTRAP = """import json, sys
payload = sys.stdin.buffer.read(320001)
if len(payload) > 320000:
    raise SystemExit(65)
request = json.loads(payload)
sys.argv = ['tool.py', '--json', json.dumps(request['args'], ensure_ascii=False)]
exec(compile(request['code'], 'tool.py', 'exec'), {'__name__': '__main__', '__file__': 'tool.py'})
"""
COMMAND = ["-i", "PATH=/usr/local/bin:/usr/bin:/bin", "TMPDIR=/work",
           "/usr/local/bin/python", "-I", "-S", "-u", "-c", BOOTSTRAP]


class ContainerError(RuntimeError):
    def __init__(self, code, resource=None):
        self.code, self.resource = code, resource
        suffix = "" if resource is None else f"; owned resource: {resource}"
        super().__init__(f"Container executor: {code}{suffix}")


@dataclass(frozen=True)
class ContainerPolicy:
    image: str
    timeout: float = 10

    def __post_init__(self):
        if not isinstance(self.image, str) or not re.fullmatch(r"sha256:[a-f0-9]{64}", self.image):
            raise ValueError("Container image must be an explicitly approved local sha256 image ID")
        if type(self.timeout) not in (int, float) or not math.isfinite(self.timeout) or not 1 <= self.timeout <= 60:
            raise ValueError("Container timeout must be in [1, 60] seconds")


def require_execution_mode(allow_unsafe_execution, container):
    if container is None:
        from .execution_policy import require_unsafe_execution
        require_unsafe_execution(allow_unsafe_execution)
    elif type(container) is not ContainerPolicy or allow_unsafe_execution is not False:
        raise PermissionError("Choose one explicit execution mode; policy cannot come from tool metadata")
    else:
        ContainerPolicy(container.image, container.timeout)


def validate_local_endpoint(endpoint):
    if not isinstance(endpoint, str) or any(char.isspace() or char == "\x00" for char in endpoint):
        raise ContainerError("invalid_local_endpoint")
    parsed = urlsplit(endpoint)
    unix = parsed.scheme == "unix" and not parsed.netloc and parsed.path.startswith("/") and not parsed.path.startswith("//")
    pipe = re.fullmatch(r"npipe:(?://|////)\./pipe/[A-Za-z0-9_.-]+", endpoint)
    if not (unix or pipe) or parsed.query or parsed.fragment:
        raise ContainerError("local_engine_required")


def validate_payload(scripts, args):
    validate_scripts(scripts)
    if scripts.get("requirements.txt", "").strip():
        raise PermissionError("Container profile supports standard-library tools only; dependency installation is disabled")
    if not isinstance(args, dict) or not all(isinstance(key, str) for key in args):
        raise ValueError("Tool arguments must be a JSON object with string keys")
    payload = json.dumps({"code": scripts["tool.py"], "args": args}, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(payload) > INPUT_LIMIT:
        raise ValueError("Container input exceeds the size limit")
    return payload


def _display_text(data):
    # Tool output is untrusted terminal data; preserve text, not control sequences.
    text = bytes(data).decode("utf-8", errors="replace")
    return "".join(char for char in text if char in "\n\t" or char.isprintable())


class ContainerExecutor:
    def __init__(self, policy):
        require_execution_mode(False, policy)
        self.policy = policy
        self.endpoint = None
        self.owner = uuid.uuid4().hex
        self.name = "alita-box-" + self.owner
        self.container_id = None
        self._attempted = False

    def _docker(self, *args, check=True, timeout=15):
        command = ["docker"]
        if self.endpoint:
            command += ["--host", self.endpoint]
        try:
            result = subprocess.run(command + list(args), capture_output=True, timeout=timeout, env=self._environment())
        except (OSError, subprocess.TimeoutExpired):
            raise ContainerError("control_unavailable", self.name if self._attempted else None) from None
        if check and result.returncode:
            raise ContainerError("control_failed", self.name if self._attempted else None)
        return result

    def _json(self, *args):
        try:
            return json.loads(self._docker(*args).stdout)
        except (ValueError, UnicodeError):
            raise ContainerError("invalid_control_response") from None

    def _environment(self):
        env = os.environ.copy()
        if self.endpoint:
            for key in ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"):
                env.pop(key, None)
        return env

    def check_engine(self):
        if os.environ.get("DOCKER_HOST"):
            raise ContainerError("docker_host_override_refused")
        contexts = self._json("context", "inspect")
        try:
            endpoint = contexts[0]["Endpoints"]["docker"]["Host"]
        except (KeyError, IndexError, TypeError):
            raise ContainerError("invalid_docker_context") from None
        validate_local_endpoint(endpoint)
        self.endpoint = endpoint
        info = self._json("info", "--format", "{{json .}}")
        if (info.get("OSType") != "linux" or info.get("CgroupVersion") != "2"
                or any(info.get(key) is not True for key in ("MemoryLimit", "SwapLimit", "CpuCfsQuota", "PidsLimit"))
                or not any((option == "name=seccomp" or option.startswith("name=seccomp,")) and "unconfined" not in option
                           for option in info.get("SecurityOptions", []))):
            raise ContainerError("required_kernel_controls_unavailable")
        return self

    def preflight(self):
        self.check_engine()
        image = self._json("image", "inspect", self.policy.image)[0]
        if (image.get("Id") != self.policy.image or image.get("Os") != "linux"
                or image.get("Config", {}).get("Volumes")):
            raise ContainerError("image_not_supported")
        return self

    def _create_arguments(self):
        return ["create", "--name", self.name, "--label", f"{OWNER_LABEL}={self.owner}",
                "--network", "none", "--read-only", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges=true", "--user", "65534:65534",
                "--workdir", "/work", "--tmpfs", "/work:" + TMPFS,
                "--pids-limit", str(PIDS), "--memory", str(MEMORY), "--memory-swap", str(MEMORY),
                "--cpus", "0.5", "--ulimit", "nofile=64:64", "--ulimit", "fsize=8388608:8388608",
                "--ulimit", "core=0:0", "--ipc", "none", "--cgroupns", "private",
                "--init", "--log-driver", "none", "--restart", "no", "--no-healthcheck",
                "--entrypoint", "/usr/bin/env", "--interactive", self.policy.image, *COMMAND]

    def _owned(self):
        item = self._json("container", "inspect", self.container_id or self.name)[0]
        identifier = item.get("Id", "")
        if (not re.fullmatch(r"[a-f0-9]{64}", identifier)
                or (self.container_id is not None and identifier != self.container_id)
                or item.get("Name") != "/" + self.name
                or item.get("Config", {}).get("Labels", {}).get(OWNER_LABEL) != self.owner):
            raise ContainerError("ownership_mismatch", self.name)
        return item

    def _verify_policy(self, item):
        host, config = item["HostConfig"], item["Config"]
        expected = {"ReadonlyRootfs": True, "Privileged": False, "NetworkMode": "none",
                    "Memory": MEMORY, "MemorySwap": MEMORY, "NanoCpus": NANO_CPUS, "PidsLimit": PIDS,
                    "PidMode": "", "IpcMode": "none", "CgroupnsMode": "private", "UTSMode": "",
                    "Init": True, "PublishAllPorts": False}
        if any(host.get(key) != value for key, value in expected.items()):
            raise ContainerError("container_limits_mismatch", self.name)
        if (item.get("Image") != self.policy.image or item.get("State", {}).get("Status") != "created"
                or config.get("User") != "65534:65534" or config.get("WorkingDir") != "/work"
                or config.get("Entrypoint") != ["/usr/bin/env"] or config.get("Cmd") != COMMAND
                or config.get("Tty") is not False or config.get("OpenStdin") is not True
                or host.get("CapDrop") != ["ALL"] or host.get("CapAdd")
                or host.get("SecurityOpt") not in (["no-new-privileges=true"], ["no-new-privileges"])
                or host.get("Tmpfs") != {"/work": TMPFS}
                or host.get("LogConfig", {}).get("Type") != "none"
                or host.get("RestartPolicy", {}).get("Name") != "no"
                or any(host.get(key) for key in ("Binds", "Mounts", "VolumesFrom", "Devices", "DeviceRequests",
                                               "Links", "GroupAdd", "PortBindings", "UsernsMode"))
                or any(mount.get("Type") != "tmpfs" or mount.get("Destination") != "/work"
                       for mount in item.get("Mounts", []))):
            raise ContainerError("container_boundary_mismatch", self.name)
        limits = {entry["Name"]: (entry["Soft"], entry["Hard"]) for entry in host.get("Ulimits", [])}
        if any(limits.get(key) != value for key, value in {"nofile": (64, 64), "fsize": (8388608, 8388608), "core": (0, 0)}.items()):
            raise ContainerError("container_ulimits_mismatch", self.name)

    def _remove(self):
        item = self._owned()
        self._docker("container", "rm", "--force", "--volumes", item["Id"])
        remaining = self._docker("container", "ls", "--all", "--quiet", "--no-trunc",
                                 "--filter", f"label={OWNER_LABEL}={self.owner}")
        if remaining.stdout.strip():
            raise ContainerError("cleanup_unconfirmed", self.name)

    def run(self, scripts, args):
        payload = validate_payload(scripts, args)
        if self._attempted:
            raise ContainerError("executor_already_used")
        self.preflight()
        self._attempted = True
        try:
            identifier = self._docker(*self._create_arguments()).stdout.decode("ascii").strip()
            if not re.fullmatch(r"[a-f0-9]{64}", identifier):
                raise ContainerError("invalid_container_id", self.name)
            self.container_id = identifier
            self._verify_policy(self._owned())
            return self._execute(payload)
        finally:
            try:
                self._remove()
            except Exception:
                raise ContainerError("cleanup_unconfirmed", self.name) from None

    def _execute(self, payload):
        process = subprocess.Popen(["docker", "--host", self.endpoint, "start", "--attach", "--interactive", self.container_id],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0,
                                   env=self._environment())
        output, lock, exceeded = {"stdout": bytearray(), "stderr": bytearray()}, Lock(), Event()
        io_failed = Event()
        def read(stream, name):
            try:
                while chunk := stream.read(4096):
                    with lock:
                        remaining = OUTPUT_LIMIT - sum(len(value) for value in output.values())
                        output[name].extend(chunk[:remaining])
                        if len(chunk) > remaining:
                            exceeded.set()
            except OSError:
                io_failed.set()
        def write():
            try:
                view = memoryview(payload)
                while view:
                    written = process.stdin.write(view)
                    if not written:
                        break
                    view = view[written:]
            except (OSError, BrokenPipeError):
                pass
            finally:
                try:
                    process.stdin.close()
                except OSError:
                    pass
        threads = [Thread(target=read, args=(process.stdout, "stdout"), daemon=True),
                   Thread(target=read, args=(process.stderr, "stderr"), daemon=True),
                   Thread(target=write, daemon=True)]
        outcome = "exited"
        deadline = time.monotonic() + self.policy.timeout
        try:
            for thread in threads:
                thread.start()
            while process.poll() is None:
                if exceeded.is_set() or io_failed.is_set() or time.monotonic() >= deadline:
                    outcome = "output_limit" if exceeded.is_set() else "io_failure" if io_failed.is_set() else "timeout"
                    break
                time.sleep(0.02)
        finally:
            try:
                if process.poll() is None:
                    try:
                        item = self._owned()
                        if item["State"]["Running"]:
                            self._docker("container", "kill", item["Id"])
                    finally:
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=5)
            finally:
                for thread in threads:
                    if thread.ident is not None:
                        thread.join(timeout=5)
                process.stdin.close()
                process.stdout.close()
                process.stderr.close()
        if any(thread.is_alive() for thread in threads):
            raise ContainerError("io_cleanup_failed", self.name)
        item = self._owned()
        if item["State"]["Running"] or item["State"]["Status"] != "exited":
            raise ContainerError("container_did_not_finish", self.name)
        if exceeded.is_set():
            outcome = "output_limit"
        elif io_failed.is_set():
            outcome = "io_failure"
        elif item["State"].get("OOMKilled"):
            outcome = "memory_limit"
        return {"returncode": item["State"]["ExitCode"] if outcome == "exited" else 124,
                "stdout": _display_text(output["stdout"]),
                "stdout_sha256": hashlib.sha256(output["stdout"]).hexdigest(),
                "stdout_bytes": len(output["stdout"]),
                "stderr": _display_text(output["stderr"]),
                "execution": "container", "outcome": outcome}
