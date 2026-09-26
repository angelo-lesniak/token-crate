"""Unit tests for the host doctor: the judgement on hand-built facts, the
report of run(), and gather() against a controlled PATH with fake tools."""

from __future__ import annotations

import contextlib
import dataclasses
import io
import os
import shutil
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.support import SOURCE_ROOT
from tokencrate import doctor, env
from tokencrate.doctor import Finding, GpuFacts, HostFacts
from tokencrate.engine import EngineFacts

MIN_DRIVER_MAJOR = 580
DEVICE = "nvidia.com/gpu=all"
NOTE = "       CDI checks read configuration only; the first up and bash bin/tokencrate smoke prove device resolution."
STORAGE = [
    ("models", "/srv/models", True, True),
    ("agents", "/srv/agents", True, True),
    ("skills", "/srv/skills", True, True),
    ("local-skills", "/srv/local-skills", True, True),
]


def podman_facts(**changes: object) -> EngineFacts:
    facts = EngineFacts(
        name="podman",
        present=True,
        version_line="podman version 6.1.0-fake",
        reachable=True,
        provider="podman-compose version 1.6.0-fake",
        rootless="true",
        runtime="crun",
        keeps_cdi=True,
    )
    return dataclasses.replace(facts, **changes)


def docker_facts(**changes: object) -> EngineFacts:
    facts = EngineFacts(
        name="docker",
        present=True,
        version_line="Docker version 29.0.0-fake",
        reachable=True,
        provider="Docker Compose version v2.40.0-fake",
        server_version="29.0.0",
    )
    return dataclasses.replace(facts, **changes)


def healthy_facts(**changes: object) -> HostFacts:
    """The host of the healthy case: rootless Podman with crun and
    podman-compose, a 32 GB card on a new driver, CDI in place."""
    facts = HostFacts(
        git_present=True,
        uname="Linux x86_64",
        engine=podman_facts(),
        gpu=GpuFacts("610.57.04", 32607, 31000, "Fake RTX 5090"),
        nvidia_ctk_present=True,
        cdi_devices=[DEVICE],
        cdi_spec_driver=None,
        ram_kb=65832904,
        storage=list(STORAGE),
        port="4208",
        port_in_use=False,
        own_container_holds_port=False,
    )
    return dataclasses.replace(facts, **changes)


def evaluate(
    facts: HostFacts,
    *,
    gpu_wanted: bool = True,
    min_driver_major: int = MIN_DRIVER_MAJOR,
    required_vram_gib: int | None = None,
    required_ram_gib: int | None = None,
    preset: str | None = None,
    build_wait: str | None = None,
    device: str = DEVICE,
) -> list[str]:
    """The findings rendered the way run() prints them."""
    findings = doctor.evaluate(
        facts,
        gpu_wanted=gpu_wanted,
        min_driver_major=min_driver_major,
        required_vram_gib=required_vram_gib,
        required_ram_gib=required_ram_gib,
        preset=preset,
        build_wait=build_wait,
        device=device,
    )
    return [doctor.format_finding(finding) for finding in findings]


def failures(lines: list[str]) -> list[str]:
    return [line for line in lines if line.startswith("[fail] ")]


def warnings(lines: list[str]) -> list[str]:
    return [line for line in lines if line.startswith("[warn] ")]


class EvaluateTests(unittest.TestCase):
    def test_healthy_podman_host_passes_every_check(self) -> None:
        lines = evaluate(healthy_facts(), required_vram_gib=24, required_ram_gib=1)
        self.assertEqual(failures(lines), [])
        self.assertEqual(warnings(lines), [])
        self.assertEqual(lines[0], "[ok] checking the GPU path (LLM_GPU=true)")
        for expected in (
            "[ok] git is available",
            "[ok] Linux on x86-64",
            "[ok] podman version 6.1.0-fake",
            "[ok] podman engine is reachable",
            "[ok] podman-compose version 1.6.0-fake",
            "[ok] Podman 6 meets the tested minimum (6)",
            "[ok] Podman engine is rootless",
            "[ok] Podman uses crun",
            "[ok] the Podman compose provider keeps CDI device requests",
            "[ok] NVIDIA GPU: Fake RTX 5090, driver 610.57.04, 32607 MiB",
            "[ok] NVIDIA driver 610.57.04 satisfies the pinned minimum major 580",
            "[ok] GPU memory 32 GiB covers the preset requirement of 24 GiB",
            "[ok] system memory 63 GiB covers the preset requirement of 1 GiB",
            "[ok] the CDI configuration lists the requested NVIDIA device: nvidia.com/gpu=all",
            NOTE,
            "[ok] models directory exists: /srv/models",
            "[ok] local-skills directory exists: /srv/local-skills",
        ):
            self.assertIn(expected, lines)

    def test_findings_follow_the_report_order(self) -> None:
        lines = evaluate(healthy_facts(), preset="qwen3.8-27b-q4", required_vram_gib=24, required_ram_gib=1)
        order = [
            "[ok] checking the GPU path (LLM_GPU=true)",
            "[ok] checking host requirements of preset qwen3.8-27b-q4",
            "[ok] git is available",
            "[ok] podman version 6.1.0-fake",
            "[ok] NVIDIA GPU: Fake RTX 5090, driver 610.57.04, 32607 MiB",
            "[ok] system memory 63 GiB covers the preset requirement of 1 GiB",
            "[ok] the CDI configuration lists the requested NVIDIA device: nvidia.com/gpu=all",
            NOTE,
            "[ok] models directory exists: /srv/models",
        ]
        self.assertEqual([line for line in lines if line in order], order)

    def test_a_preset_that_waits_for_a_newer_build_warns_after_its_line(self) -> None:
        wait = "waits for an unreleased llama.cpp build (pinned: b10920)"
        lines = evaluate(healthy_facts(), preset="glm", required_vram_gib=24, build_wait=wait)
        self.assertEqual(failures(lines), [])
        self.assertEqual(warnings(lines), [f"[warn] preset glm {wait}; up leaves it out of the router"])
        self.assertEqual(
            lines.index(warnings(lines)[0]), lines.index("[ok] checking host requirements of preset glm") + 1
        )

    def test_the_preset_line_is_absent_without_a_preset(self) -> None:
        lines = evaluate(healthy_facts())
        self.assertFalse(any("checking host requirements" in line for line in lines))
        self.assertFalse(any("preset requirement" in line for line in lines))

    def test_docker_compose_plugin_under_podman_fails_when_the_gpu_is_wanted(self) -> None:
        facts = healthy_facts(engine=podman_facts(provider="Docker Compose version v2.40.0-fake", keeps_cdi=False))
        lines = evaluate(facts)
        self.assertEqual(
            failures(lines),
            [
                "[fail] the Podman compose provider is the Docker Compose plugin, which drops CDI GPU devices; "
                "install podman-compose or set LLM_GPU=false for CPU-only checks"
            ],
        )

    def test_docker_compose_plugin_under_podman_warns_when_the_gpu_is_off(self) -> None:
        facts = healthy_facts(engine=podman_facts(provider="Docker Compose version v2.40.0-fake", keeps_cdi=False))
        lines = evaluate(facts, gpu_wanted=False)
        self.assertEqual(failures(lines), [])
        self.assertEqual(
            warnings(lines),
            [
                "[warn] LLM_GPU=false: llama-server runs on the CPU; the GPU checks are skipped",
                "[warn] the Podman compose provider is the Docker Compose plugin, which drops CDI GPU devices "
                "(LLM_GPU=false, so this only matters later)",
            ],
        )

    def test_rootful_podman_fails(self) -> None:
        lines = evaluate(healthy_facts(engine=podman_facts(rootless="false")))
        self.assertEqual(failures(lines), ["[fail] the supported Podman path requires a rootless engine"])

    def test_podman_without_crun_fails_and_names_the_runtime(self) -> None:
        lines = evaluate(healthy_facts(engine=podman_facts(runtime="runc")))
        self.assertEqual(failures(lines), ["[fail] rootless Podman with keep-id requires crun (detected: runc)"])
        lines = evaluate(healthy_facts(engine=podman_facts(rootless="", runtime="")))
        self.assertIn("[fail] rootless Podman with keep-id requires crun (detected: unknown)", lines)

    def test_docker_skips_the_podman_only_checks(self) -> None:
        lines = evaluate(healthy_facts(engine=docker_facts()))
        self.assertEqual(failures(lines), [])
        self.assertIn("[ok] Docker version 29.0.0-fake", lines)
        self.assertIn("[ok] docker engine is reachable", lines)
        self.assertIn("[ok] Docker Compose version v2.40.0-fake", lines)
        self.assertIn(
            "[ok] Docker Engine 29.0.0 keeps host services off the agents network "
            "(gateway mode isolated needs 28 or newer)",
            lines,
        )
        self.assertFalse(any("Podman" in line for line in lines))

    def test_docker_older_than_28_fails_the_gateway_mode_check(self) -> None:
        for version in ("27.5.1", ""):
            lines = evaluate(healthy_facts(engine=docker_facts(server_version=version)))
            self.assertEqual(
                failures(lines),
                [
                    f"[fail] Docker Engine {version or 'unknown'} is older than 28; the agents network cannot hide "
                    "the host (compose.docker.yaml needs gateway mode isolated)"
                ],
            )

    def test_engine_block_stops_at_the_first_missing_piece(self) -> None:
        lines = evaluate(healthy_facts(engine=podman_facts(present=False)))
        self.assertEqual(failures(lines), ["[fail] podman was not found"])
        self.assertNotIn("[ok] podman version 6.1.0-fake", lines)

        lines = evaluate(healthy_facts(engine=podman_facts(reachable=False)))
        self.assertEqual(failures(lines), ["[fail] podman engine is not reachable"])
        # The cause the engine gave is the difference between a dead end and a fix.
        lines = evaluate(healthy_facts(engine=podman_facts(reachable=False, error="cannot connect to Podman")))
        self.assertEqual(failures(lines), ["[fail] podman engine is not reachable: cannot connect to Podman"])
        self.assertIn("[ok] podman version 6.1.0-fake", lines)

        lines = evaluate(healthy_facts(engine=podman_facts(provider="")))
        self.assertEqual(failures(lines), ["[fail] podman has no working Compose provider"])
        self.assertIn("[ok] podman engine is reachable", lines)
        self.assertNotIn("[ok] Podman engine is rootless", lines)

    def test_no_usable_engine_reports_every_present_candidate(self) -> None:
        candidates = [podman_facts(reachable=False), docker_facts(provider="")]
        lines = evaluate(healthy_facts(engine=None, candidates=candidates))
        self.assertEqual(
            failures(lines),
            [
                "[fail] neither Podman nor Docker has both a reachable engine and Compose provider",
                "[fail] podman engine is not reachable",
                "[fail] docker has no working Compose provider",
            ],
        )
        self.assertIn("[ok] Docker version 29.0.0-fake", lines)
        self.assertIn("[ok] docker engine is reachable", lines)

    def test_unsupported_container_engine_fails(self) -> None:
        lines = evaluate(healthy_facts(engine=None, unsupported_engine="containerd", cdi_spec_driver="600.00.01"))
        self.assertEqual(failures(lines), ["[fail] unsupported CONTAINER_ENGINE=containerd"])
        self.assertFalse(any("CDI spec references" in line for line in lines))

    def test_auto_detected_engine_is_reported_as_reachable(self) -> None:
        lines = evaluate(healthy_facts(engine=podman_facts()), required_vram_gib=24)
        self.assertEqual(failures(lines), [])
        self.assertIn("[ok] podman engine is reachable", lines)
        self.assertIn("[ok] Podman uses crun", lines)

    def test_old_driver_fails_against_the_pinned_minimum(self) -> None:
        lines = evaluate(healthy_facts(gpu=GpuFacts("570.12", 32607, 31000, "Fake RTX 5090")), min_driver_major=580)
        self.assertEqual(
            failures(lines),
            ["[fail] NVIDIA driver 570.12 is older than the pinned minimum major 580 (CUDA_MIN_DRIVER_MAJOR)"],
        )

    def test_unparseable_driver_version_counts_as_too_old(self) -> None:
        lines = evaluate(healthy_facts(gpu=GpuFacts("N/A", 32607, 31000, "Fake")))
        self.assertIn(
            "[fail] NVIDIA driver N/A is older than the pinned minimum major 580 (CUDA_MIN_DRIVER_MAJOR)", lines
        )

    def test_a_24_gb_card_covers_a_24_gib_preset(self) -> None:
        # The card reports 24564 MiB; half a GiB of slack makes it cover 24 GiB.
        # With 24000 MiB free the same slack still warns.
        lines = evaluate(healthy_facts(gpu=GpuFacts("610.57.04", 24564, 24000, "Fake RTX 4090")), required_vram_gib=24)
        self.assertEqual(failures(lines), [])
        self.assertIn("[ok] GPU memory 24 GiB covers the preset requirement of 24 GiB", lines)
        self.assertEqual(
            warnings(lines),
            ["[warn] only 23 GiB of GPU memory is free right now; the preset needs 24 GiB (close other GPU programs)"],
        )
        lines = evaluate(healthy_facts(gpu=GpuFacts("610.57.04", 24564, 24100, "Fake RTX 4090")), required_vram_gib=24)
        self.assertEqual(warnings(lines), [])

    def test_small_gpu_fails_and_warns_about_free_memory(self) -> None:
        lines = evaluate(healthy_facts(gpu=GpuFacts("610.57.04", 16384, 16000, "Fake RTX 5070")), required_vram_gib=24)
        self.assertEqual(
            failures(lines),
            ["[fail] GPU memory 16 GiB is below the preset requirement of 24 GiB; choose a smaller preset"],
        )
        self.assertEqual(
            warnings(lines),
            ["[warn] only 16 GiB of GPU memory is free right now; the preset needs 24 GiB (close other GPU programs)"],
        )

    def test_busy_gpu_warns_but_passes(self) -> None:
        lines = evaluate(healthy_facts(gpu=GpuFacts("610.57.04", 32607, 8000, "Fake RTX 5090")), required_vram_gib=24)
        self.assertEqual(failures(lines), [])
        self.assertEqual(
            warnings(lines),
            ["[warn] only 8 GiB of GPU memory is free right now; the preset needs 24 GiB (close other GPU programs)"],
        )

    def test_unknown_gpu_memory_skips_the_memory_checks(self) -> None:
        lines = evaluate(healthy_facts(gpu=GpuFacts("610.57.04", None, None, "Fake")), required_vram_gib=24)
        self.assertIn("[ok] NVIDIA GPU: Fake, driver 610.57.04, memory unknown", lines)
        self.assertFalse(any("GPU memory" in line for line in lines))

    def test_missing_gpu_stack_fails_when_the_gpu_is_wanted(self) -> None:
        lines = evaluate(healthy_facts(gpu=None, nvidia_ctk_present=False, cdi_devices=[]))
        self.assertEqual(
            failures(lines),
            [
                "[fail] nvidia-smi found no NVIDIA GPU (missing tool or driver); the supported GPU path is unavailable",
                "[fail] nvidia-ctk was not found; install the NVIDIA Container Toolkit and generate CDI devices",
            ],
        )

    def test_the_gpu_and_cdi_checks_are_skipped_when_the_gpu_is_off(self) -> None:
        lines = evaluate(healthy_facts(gpu=None, nvidia_ctk_present=False, cdi_devices=[]), gpu_wanted=False)
        self.assertEqual(failures(lines), [])
        self.assertEqual(
            warnings(lines), ["[warn] LLM_GPU=false: llama-server runs on the CPU; the GPU checks are skipped"]
        )
        self.assertFalse(any("nvidia" in line.lower() or "CDI configuration" in line for line in lines))

    def test_missing_cdi_device_names_the_requested_device(self) -> None:
        lines = evaluate(healthy_facts(cdi_devices=["nvidia.com/gpu=0"]), device="nvidia.com/gpu=1")
        self.assertEqual(
            failures(lines),
            [
                "[fail] the CDI configuration does not list nvidia.com/gpu=1; "
                "run: sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml"
            ],
        )
        lines = evaluate(healthy_facts(cdi_devices=["nvidia.com/gpu=0", "nvidia.com/gpu=1"]), device="nvidia.com/gpu=1")
        self.assertIn("[ok] the CDI configuration lists the requested NVIDIA device: nvidia.com/gpu=1", lines)

    def test_stale_cdi_spec_warns_under_podman_only(self) -> None:
        stale = healthy_facts(cdi_spec_driver="600.00.01")
        self.assertEqual(
            warnings(evaluate(stale)),
            [
                "[warn] the CDI spec references driver 600.00.01 but the host runs 610.57.04; "
                "regenerate it: sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml"
            ],
        )
        self.assertEqual(warnings(evaluate(healthy_facts(cdi_spec_driver="610.57.04"))), [])
        self.assertEqual(warnings(evaluate(dataclasses.replace(stale, engine=docker_facts()))), [])
        self.assertEqual(warnings(evaluate(dataclasses.replace(stale, engine=None))), [])

    def test_the_cdi_note_is_a_plain_line_between_the_cdi_and_storage_findings(self) -> None:
        findings = doctor.evaluate(
            healthy_facts(),
            gpu_wanted=True,
            min_driver_major=MIN_DRIVER_MAJOR,
            required_vram_gib=None,
            required_ram_gib=None,
            preset=None,
            build_wait=None,
            device=DEVICE,
        )
        index = findings.index(Finding("note", NOTE))
        self.assertEqual(
            findings[index - 1].message, f"the CDI configuration lists the requested NVIDIA device: {DEVICE}"
        )
        self.assertEqual(findings[index + 1].message, "models directory exists: /srv/models")
        self.assertEqual(doctor.format_finding(findings[index]), NOTE)

    def test_system_memory_allows_five_percent_slack(self) -> None:
        # 65832904 kB is what a 64 GB machine reports: 62.8 GiB, printed as 63.
        lines = evaluate(healthy_facts(ram_kb=65832904), required_ram_gib=64)
        self.assertIn("[ok] system memory 63 GiB covers the preset requirement of 64 GiB", lines)
        lines = evaluate(healthy_facts(ram_kb=65832904), required_ram_gib=96)
        self.assertEqual(failures(lines), ["[fail] system memory 63 GiB is below the preset requirement of 96 GiB"])
        # A 128 GB machine reports about 125.6 GiB; a preset that asks for
        # 128 must pass there, which is what the slack is for.
        lines = evaluate(healthy_facts(ram_kb=131700000), required_ram_gib=128)
        self.assertIn("[ok] system memory 126 GiB covers the preset requirement of 128 GiB", lines)
        # The 96 GB validation host reports 97883376 kB (93.35 GiB, 97.2
        # percent of the installed size); 3 percent of slack passed it by
        # 0.2 GiB, which a firmware reservation would have turned into a
        # failure, so the slack is 5 percent (91.2 GiB for 96).
        lines = evaluate(healthy_facts(ram_kb=97883376), required_ram_gib=96)
        self.assertIn("[ok] system memory 93 GiB covers the preset requirement of 96 GiB", lines)
        lines = evaluate(healthy_facts(ram_kb=96 * 1048576 * 95 // 100 - 1), required_ram_gib=96)
        self.assertEqual(failures(lines), ["[fail] system memory 91 GiB is below the preset requirement of 96 GiB"])
        lines = evaluate(healthy_facts(ram_kb=None), required_ram_gib=1)
        self.assertEqual(failures(lines), ["[fail] system memory could not be read from /proc/meminfo"])
        # The check does not depend on the GPU path.
        lines = evaluate(healthy_facts(ram_kb=65832904), gpu_wanted=False, required_ram_gib=96)
        self.assertEqual(failures(lines), ["[fail] system memory 63 GiB is below the preset requirement of 96 GiB"])

    def test_missing_tools_and_platform_warn(self) -> None:
        # up runs the checks and needs neither to start the stack.
        lines = evaluate(healthy_facts(git_present=False, uname="Darwin arm64"))
        self.assertEqual(failures(lines), [])
        self.assertEqual(
            warnings(lines),
            [
                "[warn] git is required by skills fetch",
                "[warn] TokenCrate supports Linux on x86-64 (uname reports: Darwin arm64)",
            ],
        )

    def test_podman_older_than_6_warns(self) -> None:
        lines = evaluate(healthy_facts(engine=podman_facts(version_line="podman version 5.4.2")))
        self.assertEqual(failures(lines), [])
        self.assertIn(
            "[warn] Podman podman version 5.4.2 is older than 6, which is the oldest version TokenCrate is tested on; "
            "run bash bin/tokencrate smoke --agent pi --egress while a browser UI runs to check the network boundary",
            lines,
        )

    def test_storage_directories_are_reported_per_label(self) -> None:
        storage = [
            ("models", "/srv/models", False, False),
            ("agents", "/srv/agents", True, False),
            ("skills", "/srv/skills", True, True),
            ("local-skills", "/srv/local-skills", True, False),
        ]
        lines = evaluate(healthy_facts(storage=storage))
        self.assertEqual(
            warnings(lines),
            ["[warn] models directory does not exist yet: /srv/models (bin/tokencrate init creates it)"],
        )
        self.assertEqual(
            failures(lines),
            [
                "[fail] agents directory is not writable: /srv/agents",
                "[fail] local-skills directory is not readable: /srv/local-skills",
            ],
        )
        self.assertIn("[ok] skills directory exists: /srv/skills", lines)

    def test_a_list_setting_that_names_no_set_warns(self) -> None:
        # A stale .env (LLM_AGENT_SETS=preset) passes every host check;
        # the first agent start would refuse it, doctor says so first.
        problems = [
            ("LLM_AGENT_SETS", "names no known set: preset (run: bash bin/tokencrate agent-sets list)"),
            ("LLM_SKILL_SETS", "unsafe LLM_SKILL_SETS name: 'a b'"),
        ]
        lines = evaluate(healthy_facts(set_problems=problems))
        self.assertEqual(
            warnings(lines),
            [
                "[warn] LLM_AGENT_SETS names no known set: preset (run: bash bin/tokencrate agent-sets list)",
                "[warn] LLM_SKILL_SETS unsafe LLM_SKILL_SETS name: 'a b'",
            ],
        )
        self.assertEqual(failures(lines), [])

    def test_port_in_use_fails_unless_our_own_llama_container_holds_it(self) -> None:
        lines = evaluate(healthy_facts(port="4300", port_in_use=True, own_container_holds_port=False))
        self.assertEqual(failures(lines), ["[fail] host port 4300 is already in use"])
        lines = evaluate(healthy_facts(port="4300", port_in_use=True, own_container_holds_port=True))
        self.assertEqual(warnings(lines), [])
        self.assertEqual(failures(lines), [])


class RunTests(unittest.TestCase):
    def run_doctor(self, facts: HostFacts, environ: dict[str, str]) -> tuple[int, str]:
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copy(SOURCE_ROOT / ".env.example", tmp)
            settings = env.load(Path(tmp), environ=environ)
        with (
            mock.patch("tokencrate.doctor.gather", return_value=facts) as gather,
            contextlib.redirect_stdout(io.StringIO()) as stdout,
        ):
            status = doctor.run(
                settings,
                min_driver_major=MIN_DRIVER_MAJOR,
                preset="qwen3.8-27b-q4",
                required_vram_gib=24,
                required_ram_gib=1,
            )
        gather.assert_called_once_with(settings)
        return status, stdout.getvalue()

    def test_healthy_report_exits_zero(self) -> None:
        status, output = self.run_doctor(healthy_facts(), {"LLM_GPU": "true"})
        self.assertEqual(status, 0)
        lines = output.splitlines()
        self.assertEqual(lines[0], "== TokenCrate host doctor ==")
        self.assertEqual(lines[1], "[ok] checking the GPU path (LLM_GPU=true)")
        self.assertEqual(lines[2], "[ok] checking host requirements of preset qwen3.8-27b-q4")
        self.assertIn(NOTE, lines)
        self.assertEqual(lines[-2], "")
        self.assertEqual(lines[-1], "Doctor completed with 0 failure(s) and 0 warning(s).")

    def test_failures_set_the_exit_status(self) -> None:
        facts = healthy_facts(gpu=None, nvidia_ctk_present=False, cdi_devices=[], port_in_use=True)
        status, output = self.run_doctor(facts, {"LLM_GPU": "true"})
        self.assertEqual(status, 1)
        self.assertTrue(output.endswith("\nDoctor completed with 3 failure(s) and 0 warning(s).\n"))
        self.assertIn("[fail] host port 4208 is already in use\n", output)

    def test_gpu_off_skips_the_gpu_checks(self) -> None:
        facts = healthy_facts(gpu=None, nvidia_ctk_present=False, cdi_devices=[])
        status, output = self.run_doctor(facts, {"LLM_GPU": "false"})
        self.assertEqual(status, 0)
        self.assertIn("[warn] LLM_GPU=false: llama-server runs on the CPU; the GPU checks are skipped\n", output)
        self.assertTrue(output.endswith("\nDoctor completed with 0 failure(s) and 1 warning(s).\n"))

    def test_the_requested_gpu_device_comes_from_the_settings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shutil.copy(SOURCE_ROOT / ".env.example", tmp)
            Path(tmp, ".env").write_text("GPU_DEVICE=nvidia.com/gpu=1\n", encoding="utf-8")
            settings = env.load(Path(tmp), environ={})
        facts = healthy_facts(cdi_devices=["nvidia.com/gpu=1"])
        with (
            mock.patch("tokencrate.doctor.gather", return_value=facts),
            contextlib.redirect_stdout(io.StringIO()) as stdout,
        ):
            status = doctor.run(
                settings, min_driver_major=580, preset=None, required_vram_gib=None, required_ram_gib=None
            )
        self.assertEqual(status, 0)
        self.assertIn(
            "[ok] the CDI configuration lists the requested NVIDIA device: nvidia.com/gpu=1\n", stdout.getvalue()
        )


FAKE_NVIDIA_SMI = """\
import sys

if "--query-gpu=driver_version,memory.total,memory.free,name" not in sys.argv:
    sys.exit(1)
print("610.57.04, 32607, 31000, Fake RTX 5090 Ti")
"""

# Answers like the real engine: --version, info, the combined rootless/runtime
# format, `compose version` with the provider's line last, and `ps`.
FAKE_PODMAN = """\
import json
import os
import sys

args = sys.argv[1:]
if args[:1] == ["--version"]:
    print("podman version 6.1.0-fake")
elif args[:1] == ["info"]:
    if os.environ.get("FAKE_PODMAN_INFO") == "fail":
        sys.exit(125)
    print("true/crun" if args[1:2] == ["--format"] else "fake podman info")
elif args[:2] == ["compose", "version"]:
    print("podman version 6.1.0-fake")
    print("podman-compose version 1.6.0-fake")
elif args[:1] == ["ps"]:
    print("0123456789ab")
elif args[:1] == ["inspect"]:
    print(json.dumps({
        "Config": {"Labels": {
            "com.docker.compose.project": "tokencrate", "com.docker.compose.service": "llama"
        }},
        "NetworkSettings": {"Ports": {"8080/tcp": [{"HostIp": "127.0.0.1", "HostPort": "4207"}]}}
    }))
else:
    sys.exit(1)
"""


class GatherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "root"
        self.root.mkdir()
        shutil.copy(SOURCE_ROOT / ".env.example", self.root)
        self.bin_dir = self.tmp / "bin"
        self.bin_dir.mkdir()

    def fake(self, name: str, body: str) -> None:
        # The interpreter's own path in the shebang keeps the fake independent
        # of PATH, which the tests restrict to the fake directory.
        path = self.bin_dir / name
        path.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
        path.chmod(0o755)

    def settings(self, **environ: str) -> env.Settings:
        return env.load(self.root, environ={"PATH": str(self.bin_dir), **environ})

    def test_gather_parses_the_gpu_query_from_a_fake_nvidia_smi(self) -> None:
        # No engine on the restricted PATH: neither candidate is present.
        self.fake("nvidia-smi", FAKE_NVIDIA_SMI)
        facts = doctor.gather(self.settings(LLM_GPU="true"))
        self.assertEqual(facts.gpu, GpuFacts("610.57.04", 32607, 31000, "Fake RTX 5090 Ti"))
        # MemTotal is read on every host; this one reports whatever it has.
        self.assertIsInstance(facts.ram_kb, int)
        self.assertIsNone(facts.engine)
        self.assertEqual(facts.candidates, [])
        self.assertFalse(facts.own_container_holds_port)
        self.assertFalse(facts.nvidia_ctk_present)
        self.assertEqual(facts.cdi_devices, [])
        self.assertFalse(facts.git_present)
        self.assertEqual(facts.uname, "")
        self.assertIsInstance(facts.port_in_use, bool)
        self.assertEqual(facts.port, "4207")
        self.assertEqual([item[0] for item in facts.storage], ["models", "agents", "skills", "local-skills"])
        self.assertEqual(facts.storage[0], ("models", str(self.root / "data" / "models"), False, False))

    def test_gather_judges_the_port_with_the_bind_the_start_makes(self) -> None:
        # A loopback listener occupies the port the way a service would;
        # once it is gone, the same port is free. No `ss` is consulted.
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            port = str(listener.getsockname()[1])
            self.assertTrue(doctor.gather(self.settings(LLM_PORT=port)).port_in_use)
        self.assertFalse(doctor.gather(self.settings(LLM_PORT=port)).port_in_use)

    def test_gather_skips_the_gpu_probes_when_the_gpu_is_off(self) -> None:
        self.fake("nvidia-smi", FAKE_NVIDIA_SMI)
        facts = doctor.gather(self.settings(LLM_GPU="false"))
        self.assertIsNone(facts.gpu)
        self.assertFalse(facts.nvidia_ctk_present)
        self.assertEqual(facts.cdi_devices, [])

    def test_gather_auto_detects_a_usable_podman_and_sees_its_llama_container(self) -> None:
        self.fake("podman", FAKE_PODMAN)
        facts = doctor.gather(self.settings())
        self.assertEqual(
            facts.engine,
            EngineFacts(
                name="podman",
                present=True,
                version_line="podman version 6.1.0-fake",
                reachable=True,
                provider="podman-compose version 1.6.0-fake",
                rootless="true",
                runtime="crun",
                keeps_cdi=True,
            ),
        )
        self.assertEqual(facts.candidates, [])
        self.assertTrue(facts.own_container_holds_port)
        self.assertFalse(doctor.gather(self.settings(LLM_PORT="4307")).own_container_holds_port)
        self.assertIsNone(facts.gpu)

    def test_gather_lists_present_candidates_when_none_is_usable(self) -> None:
        self.fake("podman", FAKE_PODMAN)
        facts = doctor.gather(self.settings(FAKE_PODMAN_INFO="fail"))
        self.assertIsNone(facts.engine)
        self.assertEqual(
            facts.candidates,
            [
                EngineFacts(
                    name="podman",
                    present=True,
                    version_line="podman version 6.1.0-fake",
                    reachable=False,
                    error="exit status 125",
                )
            ],
        )
        self.assertFalse(facts.own_container_holds_port)

    def test_gather_honours_the_requested_engine(self) -> None:
        self.fake("podman", FAKE_PODMAN)
        facts = doctor.gather(self.settings(CONTAINER_ENGINE="docker"))
        self.assertEqual(facts.engine, EngineFacts(name="docker"))
        facts = doctor.gather(self.settings(CONTAINER_ENGINE="containerd"))
        self.assertIsNone(facts.engine)
        self.assertEqual(facts.unsupported_engine, "containerd")
        facts = doctor.gather(self.settings(CONTAINER_ENGINE="podman"))
        assert facts.engine is not None
        self.assertTrue(facts.engine.reachable)

    def test_storage_facts_reflect_the_directories(self) -> None:
        (self.root / "data" / "models").mkdir(parents=True)
        (self.root / "local" / "skills").mkdir(parents=True)
        (self.root / "local" / "skills").chmod(0o000)
        self.addCleanup((self.root / "local" / "skills").chmod, 0o755)
        facts = doctor.gather(self.settings())
        by_label = {label: (exists, accessible) for label, _, exists, accessible in facts.storage}
        self.assertEqual(by_label["models"], (True, True))
        self.assertEqual(by_label["agents"], (False, False))
        if os.getuid() != 0:
            self.assertEqual(by_label["local-skills"], (True, False))


class HelperTests(unittest.TestCase):
    def test_parse_gpu_query_keeps_the_full_name_and_drops_non_numeric_memory(self) -> None:
        self.assertEqual(
            doctor.parse_gpu_query("580.65.06, 24564, 24000, NVIDIA GeForce RTX 4090\nignored second line\n"),
            GpuFacts("580.65.06", 24564, 24000, "NVIDIA GeForce RTX 4090"),
        )
        self.assertEqual(
            doctor.parse_gpu_query("580.65.06, [N/A], [N/A], Fake\n"), GpuFacts("580.65.06", None, None, "Fake")
        )
        self.assertIsNone(doctor.parse_gpu_query("\n"))

    def test_cdi_spec_driver_reads_the_first_libcuda_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cdi = Path(tmp, "cdi")
            cdi.mkdir()
            Path(cdi, "nvidia.yaml").write_text(
                "containerEdits:\n  mounts:\n  - hostPath: /usr/lib/libcuda.so.610.57.04\n", encoding="utf-8"
            )
            missing = str(Path(tmp, "missing"))
            self.assertEqual(doctor.cdi_spec_driver((missing, str(cdi))), "610.57.04")
            self.assertIsNone(doctor.cdi_spec_driver((missing,)))


if __name__ == "__main__":
    unittest.main()
