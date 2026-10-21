"""The live panel's sampler: a bounded ring of looks at the model server.

`LiveSampler` polls the model server's loopback API for the loaded
preset's request gauges and token counters, at most every LIVE_INTERVAL
seconds and only while a page asks, into a bounded ring of samples that
holds nothing but numbers and the preset's name, with a GPU reading
beside each scrape when the host has `nvidia-smi` and LLM_GPU is true.
"""

from __future__ import annotations

import math
import shutil
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass

from ..env import Settings
from ..localhttp import http_get
from ..names import PRESET_NAME_RE
from ..runtime import model_states

# The live panel: the shortest time between two scrapes of the model
# server, the ring's length (ten minutes at that pace), and the timeout of
# each loopback request.
LIVE_INTERVAL = 2.0
LIVE_SAMPLES = 300
LIVE_TIMEOUT = 2
# What a scrape keeps of `GET /metrics?model=`: the two token counters the
# rates come from and the two request gauges. Every other line is dropped.
LIVE_COUNTERS = ("llamacpp:prompt_tokens_total", "llamacpp:tokens_predicted_total")
LIVE_GAUGES = ("llamacpp:requests_processing", "llamacpp:requests_deferred")
# The speculative-decoding counters of an MTP preset, cumulative since its
# load; absent on a preset without a draft model.
SPEC_COUNTERS = ("llamacpp:spec_decode_num_accepted_tokens_total", "llamacpp:spec_decode_num_draft_tokens_total")
# The GPU query the sampler runs beside each scrape when the host has the
# tool and LLM_GPU is true: memory in use and installed (MiB) and power
# draw (W), as numbers only, one line per GPU (the first is kept).
NVIDIA_SMI_QUERY = ("--query-gpu=memory.used,memory.total,power.draw", "--format=csv,noheader,nounits")


@dataclass
class Sample:
    """One look at the model server: wall time in seconds, whether the API
    answered, the loaded preset, whether its counters were scraped, its
    request gauges, the token rates since the previous scrape (None until
    the preset has been scraped twice, and after a counter went backwards,
    which is a restart), the share of drafted tokens the MTP preset accepted
    since its load, and the GPU's memory and power when the host reports
    them."""

    t: float
    up: bool
    model: str | None
    scraped: bool
    processing: int | None
    deferred: int | None
    prompt_rate: float | None
    generation_rate: float | None
    acceptance: float | None = None
    gpu_memory_mib: int | None = None
    gpu_memory_total_mib: int | None = None
    gpu_power_w: float | None = None


def prometheus_values(body: str, names: tuple[str, ...]) -> dict[str, float]:
    """The unlabelled samples of `names` from Prometheus text; a name whose
    value is not a finite number is absent."""
    values = {}
    for line in body.splitlines():
        name, _, rest = line.partition(" ")
        if name in names:
            try:
                value = float(rest.strip())
            except ValueError:
                continue
            if math.isfinite(value):
                values[name] = value
    return values


def nvidia_smi_command(gpu: bool) -> list[str] | None:
    """The GPU query when the stack uses the GPU and the host has the tool,
    resolved once to its absolute path; None otherwise."""
    found = shutil.which("nvidia-smi") if gpu else None
    return [found, *NVIDIA_SMI_QUERY] if found else None


def gpu_reading(command: list[str]) -> tuple[int | None, int | None, float | None]:
    """The first GPU's memory in use, its memory in all, and its power draw
    from the query's CSV line; a field that is not a number (`[N/A]`) is
    None, as is everything when the command fails or takes longer than
    the scrape timeout."""
    try:
        run = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=LIVE_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None, None, None
    if run.returncode:
        return None, None, None
    fields = [csv_number(field) for field in (run.stdout.splitlines() or [""])[0].split(",")[:3]] + [None] * 3
    memory, total, power = fields[0], fields[1], fields[2]
    return (
        int(memory) if memory is not None else None,
        int(total) if total is not None else None,
        round(power, 1) if power is not None else None,
    )


def csv_number(text: str) -> float | None:
    """A finite number from one CSV field; None for `[N/A]` and the like."""
    try:
        value = float(text.strip())
    except ValueError:
        return None
    return value if math.isfinite(value) else None


class LiveSampler:
    """The ring of samples behind `/live`. A snapshot scrapes the model
    server first when the previous scrape is at least `interval` old, so
    however many pages poll, the API sees one request pair per interval
    and none while no page is open. Only a preset that `GET /models`
    reported loaded on this and the previous snapshot is asked for its
    counters: a scrape routes to the preset, and asking for one that just
    unloaded would load it again. The lock covers the ring and the timing
    only, never a request, so a slow router or GPU query delays one poll,
    not every page; one scrape runs at a time, so samples stay in order
    and the previous counters belong to the scrape before."""

    def __init__(
        self,
        settings: Settings,
        interval: float = LIVE_INTERVAL,
        clock=time.monotonic,
        gpu_command: list[str] | None = None,
    ) -> None:
        self.settings = settings
        self.interval = interval
        self.clock = clock
        self.gpu_command = gpu_command
        self.samples: deque[Sample] = deque(maxlen=LIVE_SAMPLES)
        self.lock = threading.Lock()
        self.scraped_at: float | None = None
        self.scraping = False
        self.loaded: str | None = None
        self.previous: tuple[str, dict[str, float], float] | None = None

    def snapshot(self) -> list[Sample]:
        with self.lock:
            now = self.clock()
            due = not self.scraping and (self.scraped_at is None or now - self.scraped_at >= self.interval)
            if due:
                self.scraped_at = now
                self.scraping = True
        if due:
            try:
                sample = self.scrape()
                if self.gpu_command:
                    sample.gpu_memory_mib, sample.gpu_memory_total_mib, sample.gpu_power_w = gpu_reading(
                        self.gpu_command
                    )
            finally:
                with self.lock:
                    self.scraping = False
            with self.lock:
                self.samples.append(sample)
        with self.lock:
            return list(self.samples)

    def loaded_preset(self) -> tuple[bool, str | None]:
        """Whether the API answers, and the loaded preset's validated name:
        the router holds one loaded model, the first by name if it ever
        reports several. Only a name that is a preset's reaches a URL."""
        states = model_states(self.settings)
        if states is None:
            return False, None
        loaded = sorted(name for name, state in states.items() if state == "loaded" and PRESET_NAME_RE.fullmatch(name))
        return True, loaded[0] if loaded else None

    def scrape(self) -> Sample:
        up, model = self.loaded_preset()
        sample = Sample(time.time(), up, model, False, None, None, None, None)
        settled = up and model is not None and model == self.loaded
        self.loaded = model
        if not settled:
            self.previous = None
            return sample
        body = http_get(f"{self.settings.service_url}/metrics?model={model}", timeout=LIVE_TIMEOUT)
        if body is None:
            self.previous = None
            return sample
        sample.scraped = True
        gauges = prometheus_values(body, LIVE_GAUGES)
        counters = prometheus_values(body, LIVE_COUNTERS)
        spec = prometheus_values(body, SPEC_COUNTERS)
        at = self.clock()
        sample.processing = int(gauges[LIVE_GAUGES[0]]) if LIVE_GAUGES[0] in gauges else None
        sample.deferred = int(gauges[LIVE_GAUGES[1]]) if LIVE_GAUGES[1] in gauges else None
        if all(name in spec for name in SPEC_COUNTERS) and spec[SPEC_COUNTERS[1]] > 0:
            sample.acceptance = round(min(1.0, spec[SPEC_COUNTERS[0]] / spec[SPEC_COUNTERS[1]]), 3)
        # A rate needs both counters in this scrape and the previous one of
        # the same preset; a counter that went backwards is a restart.
        complete = all(name in counters for name in LIVE_COUNTERS)
        if complete and self.previous and self.previous[0] == model and at > self.previous[2]:
            deltas = [counters[name] - self.previous[1][name] for name in LIVE_COUNTERS]
            if min(deltas) >= 0:
                elapsed = at - self.previous[2]
                sample.prompt_rate = round(deltas[0] / elapsed, 1)
                sample.generation_rate = round(deltas[1] / elapsed, 1)
        self.previous = (model, counters, at) if complete else None
        return sample
