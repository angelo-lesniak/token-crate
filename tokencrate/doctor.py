"""Host checks: the facts behind `doctor` and the judgement on them.

`gather` runs the probes (tools, engine, GPU, CDI, memory, storage, port) and
returns :class:`HostFacts`; `evaluate` turns the facts into findings, one per
check, in the order the report prints them; `run` prints the report and
returns the exit status (1 when a `[fail]` line was printed). Keeping the
judgement free of subprocesses lets the tests build the facts by hand instead
of putting fake engines on PATH.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from . import TokenCrateError
from .engine import (
    COMPOSE_PLUGIN_DROPS_CDI,
    INSTALL_PODMAN_COMPOSE,
    NO_USABLE_ENGINE,
    SERVICE_LABEL,
    Engine,
    EngineFacts,
    publishes,
    run_tool,
    select,
    tool_output,
    unsupported_engine,
)
from .env import Settings

DEFAULT_GPU_DEVICE = "nvidia.com/gpu=all"
# Gateway mode `isolated` (compose.docker.yaml) keeps host services off the
# internal networks; older Engines cannot create such a network.
DOCKER_MIN_MAJOR = 28
# Podman 6 (netavark 2) keeps bridge networks apart, which the network
# layout relies on for an --egress session; older Podman forwards between
# bridges.
PODMAN_MIN_MAJOR = 6
# Where nvidia-ctk writes CDI specifications; a spec names the driver's libcuda.
CDI_DIRECTORIES = ("/etc/cdi", "/var/run/cdi")
LIBCUDA_RE = re.compile(r"libcuda\.so\.([0-9]+\.[0-9.]+)")
CDI_GENERATE = "sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml"
CDI_NOTE = (
    "       CDI checks read configuration only; the first up and bash bin/tokencrate smoke prove device resolution."
)
NVIDIA_SMI_QUERY = [
    "nvidia-smi",
    "--query-gpu=driver_version,memory.total,memory.free,name",
    "--format=csv,noheader,nounits",
]


@dataclass
class GpuFacts:
    """nvidia-smi's answer for the first GPU; memory is None when not numeric."""

    driver_version: str
    total_mib: int | None
    free_mib: int | None
    name: str


@dataclass
class HostFacts:
    """Everything `evaluate` judges; `gather` fills it from the host."""

    git_present: bool = False
    uname: str = ""
    engine: EngineFacts | None = None
    # Present engines when none is usable, reported one block each.
    candidates: list[EngineFacts] = field(default_factory=list)
    # A CONTAINER_ENGINE value that names no supported engine.
    unsupported_engine: str | None = None
    gpu: GpuFacts | None = None
    nvidia_ctk_present: bool = False
    cdi_devices: list[str] = field(default_factory=list)
    cdi_spec_driver: str | None = None
    # MemTotal of /proc/meminfo; None when it could not be read.
    ram_kb: int | None = None
    # (label, path, exists, writable or, for local-skills, readable)
    storage: list[tuple[str, str, bool, bool]] = field(default_factory=list)
    port: str = "4207"
    # None when the port could not be checked; port_check_cause says why.
    port_in_use: bool | None = False
    port_check_cause: str = ""
    own_container_holds_port: bool = False


@dataclass
class Finding:
    """One report line; `note` lines print without a prefix and are not counted."""

    level: str
    message: str


def format_finding(finding: Finding) -> str:
    return finding.message if finding.level == "note" else f"[{finding.level}] {finding.message}"


# --- probes -----------------------------------------------------------------


def _mib(text: str) -> int | None:
    return int(text) if re.fullmatch(r"[0-9]+", text) else None


def parse_gpu_query(output: str) -> GpuFacts | None:
    """The first line of nvidia-smi's CSV answer: driver, total MiB, free MiB,
    name (which may contain spaces)."""
    line = output.partition("\n")[0].strip()
    if not line:
        return None
    fields = [part.strip() for part in line.split(",", 3)] + ["", "", ""]
    driver, total, free, name = fields[:4]
    return GpuFacts(driver_version=driver, total_mib=_mib(total), free_mib=_mib(free), name=name)


def cdi_spec_driver(directories: tuple[str, ...] = CDI_DIRECTORIES) -> str | None:
    """The driver version the CDI specifications reference: the first
    `libcuda.so.<version>` found below the given directories."""
    for directory in directories:
        for dirpath, dirnames, filenames in os.walk(directory):
            dirnames.sort()
            for filename in sorted(filenames):
                try:
                    match = LIBCUDA_RE.search(Path(dirpath, filename).read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    continue
                if match:
                    return match.group(1)
    return None


def _memory_total_kb() -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemTotal:"):
                return int(line.split()[1])
    except (OSError, ValueError, IndexError):
        return None
    return None


def _storage_facts(settings: Settings) -> list[tuple[str, str, bool, bool]]:
    facts = []
    items = (
        ("models", settings.models_dir),
        ("agents", settings.agents_dir),
        ("skills", settings.skills_dir),
        ("local-skills", settings.local_skills_dir),
    )
    for label, path in items:
        # Private skills are mounted read-only, so readable is enough there.
        mode = os.R_OK | os.X_OK if label == "local-skills" else os.W_OK
        facts.append((label, str(path), path.is_dir(), os.access(path, mode)))
    return facts


def _port_in_use(port: str, env: dict[str, str]) -> tuple[bool | None, str]:
    """(in use, cause): the cause says why the check could not be made,
    which is not always a missing `ss`."""
    output, cause = run_tool(["ss", "-H", "-ltn", f"sport = :{port}"], env)
    return (None, cause) if output is None else (bool(output.strip()), "")


def _own_container_holds_port(engine: EngineFacts | None, settings: Settings) -> bool:
    """Whether this project's llama publishes the requested loopback port."""
    if engine is None or not engine.reachable:
        return False
    try:
        return any(
            (item["Config"].get("Labels") or {}).get(SERVICE_LABEL) == "llama" and publishes(item, settings.port)
            for item in Engine(engine.name, settings).containers(all_states=False)
        )
    except (TokenCrateError, OSError):
        return False


def gather(settings: Settings) -> HostFacts:
    """Run every probe. The engine comes from `engine.select`, the rule `up`
    applies through `engine.detect`: the requested engine, or the first
    usable one. What `detect` refuses on, this records, so the two cannot
    disagree. The GPU probes run only when the GPU is wanted."""
    env = settings.subprocess_env()
    path = env.get("PATH")
    selection = select(env, settings.get("CONTAINER_ENGINE"))
    port_in_use, port_check_cause = _port_in_use(settings.port, env)
    facts = HostFacts(
        git_present=shutil.which("git", path=path) is not None,
        uname=(tool_output(["uname", "-sm"], env) or "").strip(),
        engine=selection.chosen,
        candidates=list(selection.candidates),
        unsupported_engine=selection.unsupported or None,
        ram_kb=_memory_total_kb(),
        storage=_storage_facts(settings),
        port=settings.port,
        port_in_use=port_in_use,
        port_check_cause=port_check_cause,
        own_container_holds_port=_own_container_holds_port(selection.chosen, settings),
    )
    if settings.gpu:
        gpu_output = tool_output(NVIDIA_SMI_QUERY, env)
        cdi_output = tool_output(["nvidia-ctk", "cdi", "list"], env) or ""
        facts.gpu = parse_gpu_query(gpu_output) if gpu_output else None
        facts.nvidia_ctk_present = shutil.which("nvidia-ctk", path=path) is not None
        facts.cdi_devices = [line.strip() for line in cdi_output.splitlines() if line.strip()]
        facts.cdi_spec_driver = cdi_spec_driver()
    return facts


# --- judgement --------------------------------------------------------------


def _check(condition: bool, good: str, bad: str, level: str = "fail") -> Finding:
    return Finding("ok", good) if condition else Finding(level, bad)


def _host_findings(facts: HostFacts) -> list[Finding]:
    """Warnings: `up` runs the checks and stops on a failure, and it needs
    neither Git nor the supported platform to start the stack."""
    return [
        _check(facts.git_present, "git is available", "git is required by skills fetch", level="warn"),
        _check(
            facts.uname == "Linux x86_64",
            "Linux on x86-64",
            f"TokenCrate supports Linux on x86-64 (uname reports: {facts.uname})",
            level="warn",
        ),
    ]


def _engine_findings(engine: EngineFacts, gpu_wanted: bool) -> list[Finding]:
    """The gate engine.detect applies, one line per finding, plus the Docker
    Engine minimum that only `doctor` (and `up` through it) enforces, so
    that `down`, `status`, and `agent` still run on an older Engine."""
    name = engine.name
    if not engine.present:
        return [Finding("fail", f"{name} was not found")]
    findings = [Finding("ok", engine.version_line)]
    if not engine.reachable:
        cause = f": {engine.error}" if engine.error else ""
        return [*findings, Finding("fail", f"{name} engine is not reachable{cause}")]
    findings.append(Finding("ok", f"{name} engine is reachable"))
    if not engine.provider:
        return [*findings, Finding("fail", f"{name} has no working Compose provider")]
    findings.append(Finding("ok", engine.provider))
    if name == "docker":
        major = _driver_major(engine.server_version)
        findings.append(
            _check(
                major is not None and major >= DOCKER_MIN_MAJOR,
                f"Docker Engine {engine.server_version} keeps host services off the agents network "
                f"(gateway mode isolated needs {DOCKER_MIN_MAJOR} or newer)",
                f"Docker Engine {engine.server_version or 'unknown'} is older than {DOCKER_MIN_MAJOR}; "
                "the agents network cannot hide the host (compose.docker.yaml needs gateway mode isolated)",
            )
        )
        return findings
    major = _driver_major(engine.version_line.removeprefix("podman version "))
    findings.append(
        _check(
            major is not None and major >= PODMAN_MIN_MAJOR,
            f"Podman {major} keeps bridge networks apart: an --egress session cannot reach the UI networks",
            f"Podman {engine.version_line} is older than {PODMAN_MIN_MAJOR}; its bridges forward to each other, "
            "so an --egress session could reach a running browser UI",
        )
    )
    findings.append(
        _check(
            engine.rootless == "true",
            "Podman engine is rootless",
            "the supported Podman path requires a rootless engine",
        )
    )
    findings.append(
        _check(
            engine.runtime == "crun",
            "Podman uses crun",
            f"rootless Podman with keep-id requires crun (detected: {engine.runtime or 'unknown'})",
        )
    )
    if engine.keeps_cdi:
        findings.append(Finding("ok", "the Podman compose provider keeps CDI device requests"))
    elif gpu_wanted:
        findings.append(
            Finding(
                "fail",
                f"{COMPOSE_PLUGIN_DROPS_CDI}; {INSTALL_PODMAN_COMPOSE}",
            )
        )
    else:
        findings.append(
            Finding(
                "warn",
                f"{COMPOSE_PLUGIN_DROPS_CDI} (LLM_GPU=false, so this only matters later)",
            )
        )
    return findings


def _engine_selection_findings(facts: HostFacts, gpu_wanted: bool) -> list[Finding]:
    if facts.unsupported_engine is not None:
        return [Finding("fail", unsupported_engine(facts.unsupported_engine))]
    engine = facts.engine
    if engine is None:
        findings = [Finding("fail", NO_USABLE_ENGINE)]
        for candidate in facts.candidates:
            findings += _engine_findings(candidate, gpu_wanted)
        return findings
    return _engine_findings(engine, gpu_wanted)


def _driver_major(version: str) -> int | None:
    major = version.partition(".")[0]
    return int(major) if re.fullmatch(r"[0-9]+", major) else None


def _gpu_findings(facts: HostFacts, min_driver_major: int, required_vram_gib: int | None) -> list[Finding]:
    gpu = facts.gpu
    if gpu is None:
        return [
            Finding(
                "fail", "nvidia-smi found no NVIDIA GPU (missing tool or driver); the supported GPU path is unavailable"
            )
        ]
    memory = f"{gpu.total_mib} MiB" if gpu.total_mib is not None else "memory unknown"
    major = _driver_major(gpu.driver_version)
    findings = [
        Finding("ok", f"NVIDIA GPU: {gpu.name}, driver {gpu.driver_version}, {memory}"),
        _check(
            major is not None and major >= min_driver_major,
            f"NVIDIA driver {gpu.driver_version} satisfies the pinned minimum major {min_driver_major}",
            f"NVIDIA driver {gpu.driver_version} is older than the pinned minimum major {min_driver_major} "
            "(CUDA_MIN_DRIVER_MAJOR)",
        ),
    ]
    # A "24 GB" card reports about 24564 MiB: compare in MiB with half a GiB
    # of slack and print the nearest GiB.
    if required_vram_gib is not None and gpu.total_mib is not None:
        needed_mib = required_vram_gib * 1024 - 512
        total_gib = (gpu.total_mib + 512) // 1024
        findings.append(
            _check(
                gpu.total_mib >= needed_mib,
                f"GPU memory {total_gib} GiB covers the preset requirement of {required_vram_gib} GiB",
                f"GPU memory {total_gib} GiB is below the preset requirement of {required_vram_gib} GiB; "
                "choose a smaller preset",
            )
        )
        if gpu.free_mib is not None and gpu.free_mib < needed_mib:
            findings.append(
                Finding(
                    "warn",
                    f"only {(gpu.free_mib + 512) // 1024} GiB of GPU memory is free right now; "
                    f"the preset needs {required_vram_gib} GiB (close other GPU programs)",
                )
            )
    return findings


def _ram_findings(facts: HostFacts, required_ram_gib: int | None) -> list[Finding]:
    """System memory for a preset that keeps expert weights there, declared
    as the installed size. MemTotal excludes what the firmware and the
    kernel reserve (a 64 GB machine reports about 62.8 GiB, the 96 GB
    validation host 93.35 GiB, a 128 GB machine about 125.6 GiB), so the
    comparison allows 5 percent of slack and prints the nearest GiB."""
    if required_ram_gib is None:
        return []
    if facts.ram_kb is None:
        return [Finding("fail", "system memory could not be read from /proc/meminfo")]
    ram_kb = facts.ram_kb
    ram_gib = (ram_kb + 524288) // 1048576
    return [
        _check(
            ram_kb >= required_ram_gib * 1048576 * 95 // 100,
            f"system memory {ram_gib} GiB covers the preset requirement of {required_ram_gib} GiB",
            f"system memory {ram_gib} GiB is below the preset requirement of {required_ram_gib} GiB",
        )
    ]


def _cdi_findings(facts: HostFacts, device: str) -> list[Finding]:
    if facts.nvidia_ctk_present:
        findings = [
            _check(
                device in facts.cdi_devices,
                f"the CDI configuration lists the requested NVIDIA device: {device}",
                f"the CDI configuration does not list {device}; run: {CDI_GENERATE}",
            )
        ]
    else:
        findings = [
            Finding("fail", "nvidia-ctk was not found; install the NVIDIA Container Toolkit and generate CDI devices")
        ]
    # Under Podman a stale spec after a driver upgrade makes CUDA fail although
    # nvidia-smi works; docs/troubleshooting.md points at this line.
    driver = facts.gpu.driver_version if facts.gpu is not None else ""
    spec_driver = facts.cdi_spec_driver
    if facts.engine is not None and facts.engine.name == "podman" and driver and spec_driver and spec_driver != driver:
        findings.append(
            Finding(
                "warn",
                f"the CDI spec references driver {spec_driver} but the host runs {driver}; "
                f"regenerate it: {CDI_GENERATE}",
            )
        )
    findings.append(Finding("note", CDI_NOTE))
    return findings


def _storage_findings(facts: HostFacts) -> list[Finding]:
    findings = []
    for label, path, exists, accessible in facts.storage:
        if not exists:
            findings.append(
                Finding("warn", f"{label} directory does not exist yet: {path} (bin/tokencrate init creates it)")
            )
            continue
        access = "readable" if label == "local-skills" else "writable"
        findings.append(
            _check(accessible, f"{label} directory exists: {path}", f"{label} directory is not {access}: {path}")
        )
    return findings


def _network_findings(facts: HostFacts) -> list[Finding]:
    if facts.port_in_use is None:
        return [Finding("warn", f"could not check whether host port {facts.port} is in use ({facts.port_check_cause})")]
    if facts.port_in_use and not facts.own_container_holds_port:
        return [Finding("fail", f"host port {facts.port} is already in use")]
    return []


def evaluate(
    facts: HostFacts,
    *,
    gpu_wanted: bool,
    min_driver_major: int,
    required_vram_gib: int | None,
    required_ram_gib: int | None,
    preset: str | None,
    build_wait: str | None,
    device: str,
) -> list[Finding]:
    """Every check in report order. The GPU and CDI checks run only when the
    GPU is wanted (LLM_GPU=true); the memory comparisons only with a preset's
    requirements. A preset whose model set waits for a newer llama.cpp build
    (build_wait, from presets.build_wait) is a warning: the host may be fine,
    the pin is not."""
    if gpu_wanted:
        findings = [Finding("ok", "checking the GPU path (LLM_GPU=true)")]
    else:
        findings = [Finding("warn", "LLM_GPU=false: llama-server runs on the CPU; the GPU checks are skipped")]
    if preset:
        findings.append(Finding("ok", f"checking host requirements of preset {preset}"))
        if build_wait:
            findings.append(Finding("warn", f"preset {preset} {build_wait}; up leaves it out of the router"))
    findings += _host_findings(facts)
    findings += _engine_selection_findings(facts, gpu_wanted)
    if gpu_wanted:
        findings += _gpu_findings(facts, min_driver_major, required_vram_gib)
    findings += _ram_findings(facts, required_ram_gib)
    if gpu_wanted:
        findings += _cdi_findings(facts, device)
    findings += _storage_findings(facts)
    findings += _network_findings(facts)
    return findings


def run(
    settings: Settings,
    *,
    min_driver_major: int,
    preset: str | None,
    required_vram_gib: int | None,
    required_ram_gib: int | None,
    build_wait: str | None = None,
) -> int:
    """Print the doctor report; 0 when no check failed, else 1."""
    print("== TokenCrate host doctor ==", flush=True)
    facts = gather(settings)
    findings = evaluate(
        facts,
        gpu_wanted=settings.gpu,
        min_driver_major=min_driver_major,
        required_vram_gib=required_vram_gib,
        required_ram_gib=required_ram_gib,
        preset=preset,
        build_wait=build_wait,
        device=settings.get("GPU_DEVICE") or DEFAULT_GPU_DEVICE,
    )
    for finding in findings:
        print(format_finding(finding))
    failure_count = sum(1 for finding in findings if finding.level == "fail")
    warning_count = sum(1 for finding in findings if finding.level == "warn")
    print(f"\nDoctor completed with {failure_count} failure(s) and {warning_count} warning(s).", flush=True)
    return 0 if failure_count == 0 else 1
