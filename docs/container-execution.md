# Contained Execution

## Explicit Selection

`--container-image sha256:<64 lowercase hex characters>` selects the contained
standard-library profile for that command. `ContainerPolicy` is the corresponding
explicit Python API value. Supplying both this and unsafe host consent is refused.
Generated metadata, registry manifests and requirements cannot choose a mode.
No mode means the existing default-deny behavior. A direct model answer without
tool execution remains available; this feature does not change model-service trust.

The operator must approve the local image. An immutable ID prevents tag drift
between selection and execution; it does not prove image provenance or patch level.
The executor never pulls/builds an image. Image-declared volumes are refused.
The selected image must provide the ordinary Linux `env` and Python paths used
by the launcher. Python runs with isolated/no-site flags and no package installer.

Only empty requirements are supported in this profile. The manager tells the
generators to use stdlib-only JSON-input tools, but those prompts are not the
security boundary: dependency attempts are rejected in code. Supporting reviewed
offline dependency profiles would need a separate design and qualification.

## Verified Configuration

The Docker context must resolve to a local Unix socket or Windows named pipe;
TCP/SSH endpoints and `DOCKER_HOST` overrides are refused. After verification,
control calls pin that endpoint and remove context/TLS environment overrides.
The daemon must report Linux, cgroup v2, memory/swap/CPU/PID controls and seccomp.
An unsupported engine fails closed; Windows native containers are not supported.

Each invocation creates one new container and checks its immutable ID, name,
owner label, image, command and security/resource configuration before start:

| Control | Value |
| --- | --- |
| User/group | 65534:65534 |
| Root filesystem | Read-only |
| User bind mounts, volumes, devices, ports | None |
| Network | none |
| PID/IPC/cgroup namespaces | Private PID/default; IPC none; cgroup private |
| Capabilities | All dropped |
| Privilege escalation | no-new-privileges |
| Seccomp | Trusted daemon's enabled default profile |
| Memory / memory+swap | 128 MiB / 128 MiB |
| CPU | 0.5 CPU quota |
| PID count | 32 |
| File descriptors | 64 |
| File size / core dump | 8 MiB / disabled |
| Work directory | 16 MiB tmpfs; nosuid,nodev,noexec; UID/GID65534 |
| Combined captured stdout/stderr | 65,536 raw bytes |
| Execution time | 10 seconds by default; explicit API range1..60 |
| Restart / Docker log storage | Disabled / none |

Docker's runtime still supplies its ordinary internal mounts/devices. No operator
filesystem path is mounted into the tool. The launcher starts with an empty
environment plus fixed PATH/TMPDIR, so neither host nor image environment values
are inherited by the Python tool. Explicit JSON inputs remain visible to the tool.
Generated source files may be retained in the owner's ordinary `.runs`/registry
directories; the container receives only bounded source/arguments over stdin.

The source executes inside the container, never through a host Python fallback.
Input JSON is bounded to320,000 bytes and source to256,000 bytes. User/tool data is
not interpolated into a host shell command. Docker commands use argument arrays.
No automatic dependency installation, model-output execution approval or retry.

## Failure And Cleanup

Concurrent pipe drains bound captured output. Exceeding output/time limits kills
the owned container and reports a nonzero result; an OOM result is also a failure.
Failed executions are not registered as working tools. No request is replayed.
Returned text removes terminal control and Unicode formatting characters except
newline/tab. The byte cap applies before UTF-8 replacement decoding, so invalid
UTF-8 can expand the returned string; captured raw bytes remain bounded.

All ordinary success/failure paths attempt removal by inspected immutable ID,
with its owner label/name checked again. Cleanup failure overrides apparent tool
success and reports the owned resource name for investigation. No prune, broad
name deletion or removal of a different owner's object is used.

The execution deadline starts after container creation, at attachment. Preflight,
create/control timeouts and cleanup add separate latency; it is not a universal
wall-clock deadline. A daemon outage, ambiguous create result, hard parent kill or
OS failure can prevent confirmed cleanup. Reconcile the reported name/owner label
on that same trusted engine before removing anything; never replay the whole call
blindly. The default Docker daemon is privileged even though the tool is not.

## Threat Model And Evidence

The host, local daemon, operator-owned registry paths and selected image are trusted.
This does not defend against a hostile local administrator, host file races,
malicious images or an unpatched kernel/runtime escape. Containers share a kernel;
use a dedicated disposable engine/VM and least-privileged service account for
untrusted workloads. No resistance to all malicious code or multi-tenant production
security is claimed. Tool output is untrusted text, not an instruction to the host.

Default tests verify refusal, parameter validation, mode propagation, ownership
and the pre-start policy checks without Docker. Actual CI tests inspect controls
from inside containers and exercise filesystem/environment/network boundaries,
PID pressure, file/tmpfs limits, OOM, timeout and output overflow. A manager fixture
also creates, runs, registers and reuses a tool through the actual container path.
Fixtures are hand-written and use
only temporary synthetic data; no customer data or model-generated code is run.
Linux CI is the actual engine qualification. Windows CLI guard tests do not prove
a particular Docker Desktop/VM deployment until its actual suite has been run.
