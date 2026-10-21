"""Report the latest eligible upstream versions of the pins in pins.env next to the current ones."""

from __future__ import annotations

import functools
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from . import TokenCrateError

MAX_RESPONSE_BYTES = 16 * 1024 * 1024
# Docker Hub answers an anonymous client's tag listing for ten pages of 100
# and refuses the eleventh (HTTP 403), so a lookup must find its answer in
# the first thousand tags, newest first.
DOCKER_HUB_PAGE_LIMIT = 10
USER_AGENT = "TokenCrate-pins-check"
STABLE_TAG_RE = r"(\d+(?:\.\d+)+)"
LLAMA_CPP_REPOSITORY = "ggml-org/llama.cpp"
# llama.cpp releases are tagged b<build>; the releases API lists them newest
# first, and the server image of a release is `server-<family>-b<build>` on
# GHCR. The family (cuda13) is a manual choice and stays, the build number
# is what the check resolves.
LLAMA_CPP_RELEASES_URL = f"https://api.github.com/repos/{LLAMA_CPP_REPOSITORY}/releases?per_page=30"
LLAMA_CPP_RELEASE_RE = re.compile(r"^b(?P<build>\d+)$")
LLAMA_CPP_TAG_RE = re.compile(r"^(?P<family>server-[a-z0-9]+)-b(?P<build>\d+)$")
# What pins.env holds beside a tag: the 64 hex characters of the manifest the
# tag points at, which is what the build pulls.
DIGEST_RE = re.compile(r"^sha256:(?P<digest>[0-9a-f]{64})$")
# The index media types first, so a tag that points at a manifest list
# resolves to the list, which is what a `FROM` line pulls.
MANIFEST_ACCEPT = ", ".join(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)


class LookupsFailed(TokenCrateError):
    """The report of a `pins check` in which at least one source could not
    be read; `report` holds every row, `failed` the component names."""

    def __init__(self, report: str, failed: list[str]) -> None:
        super().__init__(f"pins check could not read the source of: {', '.join(failed)}")
        self.report = report
        self.failed = failed


@dataclass(frozen=True)
class Resolution:
    key: str
    current: str
    latest: str
    notes: tuple[str, ...] = ()
    # The manifest digest of `latest`, for the <name>_DIGEST pin beside the
    # tag. Empty for a version pin that has none, and for a current pin,
    # which is not pasted anywhere.
    digest: str = ""


def component_name(key: str) -> str:
    """The name `pins check` takes for a pin: its key without the `_TAG` or
    `_VERSION` suffix, in lower case with hyphens (LLAMA_CPP_TAG: llama-cpp)."""
    return key.removesuffix("_TAG").removesuffix("_VERSION").lower().replace("_", "-")


def request_bytes(
    url: str, *, accept: str = "application/json", headers: dict[str, str] | None = None, missing_ok: bool = False
) -> bytes | None:
    """The response body; None for a 404 when `missing_ok` (a tag or release
    that does not exist), an error for every other failure."""
    if urllib.parse.urlsplit(url).scheme.lower() != "https":
        raise TokenCrateError(f"pin source URL must use HTTPS: {url}")
    request_headers = {"Accept": accept, "User-Agent": USER_AGENT}
    request_headers.update(headers or {})
    request = urllib.request.Request(url, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            if urllib.parse.urlsplit(response.url).scheme.lower() != "https":
                raise TokenCrateError(f"pin source redirected away from HTTPS: {url}")
            content = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as error:
        error.close()
        if missing_ok and error.code == 404:
            return None
        detail = f"HTTP {error.code}"
        response_headers = error.headers or {}
        remaining = response_headers.get("X-RateLimit-Remaining")
        retry_after = response_headers.get("Retry-After")
        if remaining is not None:
            detail += f", rate limit remaining {remaining}"
        if retry_after is not None:
            detail += f", retry after {retry_after} seconds"
        raise TokenCrateError(f"could not read pin source {url}: {detail}") from error
    except (OSError, urllib.error.URLError) as error:
        raise TokenCrateError(f"could not read pin source {url}: {error}") from error
    if len(content) > MAX_RESPONSE_BYTES:
        raise TokenCrateError(f"pin source response is too large: {url}")
    return content


def request_json(url: str, *, accept: str = "application/json", headers: dict[str, str] | None = None) -> Any:
    content = request_bytes(url, accept=accept, headers=headers)
    try:
        return json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TokenCrateError(f"pin source returned invalid JSON: {url}") from error


def version_key(value: str, pattern: re.Pattern[str]) -> tuple[int, ...] | None:
    match = pattern.fullmatch(value)
    if match is None:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def latest_tag(tags: list[str], pattern: re.Pattern[str], source: str) -> str:
    candidates = [(parsed, tag) for tag in tags if (parsed := version_key(tag, pattern)) is not None]
    if not candidates:
        raise TokenCrateError(f"{source} returned no stable version tags")
    return max(candidates)[1]


def current_is_latest(current: tuple[int, ...], latest: tuple[int, ...], source: str) -> bool:
    if latest < current:
        raise TokenCrateError(f"{source} latest eligible version is older than the current pin")
    return latest == current


def digest_key(key: str) -> str:
    """Every tag pin has a digest pin beside it (LLAMA_CPP_TAG,
    LLAMA_CPP_DIGEST), because a tag can be moved."""
    return key.removesuffix("_TAG") + "_DIGEST"


def manifest_digest(value: str, source: str) -> str:
    """The hex digest of a `sha256:...` reference, as pins.env spells it."""
    match = DIGEST_RE.fullmatch(value)
    if match is None:
        raise TokenCrateError(f"{source} returned no sha256 manifest digest")
    return match.group("digest")


def required_value(values: dict[str, str], key: str) -> str:
    value = values.get(key, "")
    if not value:
        raise TokenCrateError(f"pins.env has no value for {key}")
    return value


# --- llama.cpp: GitHub releases and GHCR -------------------------------------


def ghcr_token(repository: str) -> str:
    payload = request_json(
        "https://ghcr.io/token?" + urllib.parse.urlencode({"scope": f"repository:{repository}:pull"})
    )
    token = payload.get("token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token:
        raise TokenCrateError("GHCR did not issue an anonymous pull token")
    return token


def ghcr_manifest(repository: str, tag: str) -> bytes | None:
    """The manifest document the tag points at, or None when GHCR has no such
    tag. A manifest's digest is the sha256 of the document the registry
    serves, so the caller hashes the body instead of trusting a header."""
    headers = {"Authorization": f"Bearer {ghcr_token(repository)}"}
    reference = urllib.parse.quote(tag, safe="")
    url = f"https://ghcr.io/v2/{repository}/manifests/{reference}"
    return request_bytes(url, accept=MANIFEST_ACCEPT, headers=headers, missing_ok=True)


def llama_cpp_release_builds() -> list[int]:
    """The build numbers of the newest llama.cpp releases, newest first."""
    payload = request_json(LLAMA_CPP_RELEASES_URL, accept="application/vnd.github+json")
    if not isinstance(payload, list):
        raise TokenCrateError("GitHub returned an invalid llama.cpp release list")
    builds = [
        int(match.group("build"))
        for release in payload
        if isinstance(release, dict)
        and (match := LLAMA_CPP_RELEASE_RE.fullmatch(str(release.get("tag_name", "")))) is not None
    ]
    if not builds:
        raise TokenCrateError("GitHub listed no llama.cpp release tagged b<build>")
    return sorted(builds, reverse=True)


def resolve_llama_cpp(values: dict[str, str]) -> Resolution:
    key = "LLAMA_CPP_TAG"
    current = required_value(values, key)
    match = LLAMA_CPP_TAG_RE.fullmatch(current)
    if match is None:
        raise TokenCrateError(f"unsupported current {key}: {current}")
    family, current_build = match.group("family"), int(match.group("build"))
    builds = llama_cpp_release_builds()
    if builds[0] < current_build:
        raise TokenCrateError(f"GitHub {LLAMA_CPP_REPOSITORY} latest release is older than the current pin")
    # The newest release whose image of the pinned family GHCR serves; a
    # release whose image build failed or has not finished is skipped. The
    # manifest fetched to confirm it is the digest pin beside the tag.
    for build in builds:
        if build <= current_build:
            return Resolution(key, current, current)
        tag = f"{family}-b{build}"
        manifest = ghcr_manifest(LLAMA_CPP_REPOSITORY, tag)
        if manifest is not None:
            notes = (
                f"  llama.cpp build b{current_build} -> b{build}: https://github.com/{LLAMA_CPP_REPOSITORY}/releases",
            )
            return Resolution(key, current, tag, notes, hashlib.sha256(manifest).hexdigest())
    raise TokenCrateError(f"none of the {len(builds)} newest llama.cpp releases has a {family} image on GHCR")


# --- npm ---------------------------------------------------------------------


PACKAGE_VERSION_RE = re.compile(rf"^{STABLE_TAG_RE}$")


def resolve_npm(key: str, package: str, values: dict[str, str]) -> Resolution:
    current = required_value(values, key)
    current_key = version_key(current, PACKAGE_VERSION_RE)
    if current_key is None:
        raise TokenCrateError(f"unsupported current {key}: {current}")
    encoded = urllib.parse.quote(package, safe="@")
    payload = request_json(f"https://registry.npmjs.org/{encoded}/latest")
    latest = payload.get("version", "") if isinstance(payload, dict) else ""
    latest_key = version_key(latest, PACKAGE_VERSION_RE)
    if latest_key is None:
        raise TokenCrateError(f"npm returned no stable {package} latest version")
    if current_is_latest(current_key, latest_key, f"npm {package}"):
        return Resolution(key, current, current)
    notes = (f"  Package history: https://www.npmjs.com/package/{package}?activeTab=versions",)
    return Resolution(key, current, latest, notes)


# --- Docker Hub --------------------------------------------------------------


def docker_hub_tags(
    namespace: str, repository: str, search: str, rank: Callable[[str], tuple[int, ...] | None] | None = None
) -> dict[str, str]:
    """The matching tags of the image, newest push first, each with the
    `sha256:...` reference of the manifest it points at; the listing carries
    both. Docker Hub lists at most ten pages to an anonymous client, and
    an image such as VictoriaMetrics has over a thousand tags in one major,
    so the listing is read newest first and stops after the first page that
    adds no tag `rank` places above the best one seen (a release pushes its
    tags together, so the latest is at the front)."""
    query = urllib.parse.urlencode({"page_size": 100, "name": search, "ordering": "last_updated"})
    url: str | None = f"https://hub.docker.com/v2/namespaces/{namespace}/repositories/{repository}/tags?{query}"
    tags: dict[str, str] = {}
    best: tuple[int, ...] | None = None
    pages = 0
    while url:
        if pages >= DOCKER_HUB_PAGE_LIMIT:
            raise TokenCrateError(
                f"Docker Hub tags for {namespace}/{repository} exceeded the {DOCKER_HUB_PAGE_LIMIT}-page listing limit"
            )
        payload = request_json(url)
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            raise TokenCrateError(f"Docker Hub returned invalid tags for {namespace}/{repository}")
        page = {
            str(item.get("name", "")): str(item.get("digest", ""))
            for item in payload["results"]
            if isinstance(item, dict)
        }
        tags.update(page)
        pages += 1
        if rank is not None:
            ranked = [key for tag in page if (key := rank(tag)) is not None]
            page_best = max(ranked) if ranked else None
            if best is not None and (page_best is None or page_best <= best):
                break
            if page_best is not None:
                best = page_best if best is None else max(best, page_best)
        next_url = payload.get("next")
        if next_url:
            next_url = str(next_url)
            parsed_next = urllib.parse.urlsplit(next_url)
            if parsed_next.scheme != "https" or parsed_next.hostname != "hub.docker.com":
                raise TokenCrateError("Docker Hub returned an unsafe pagination link")
            url = next_url
        else:
            url = None
    return tags


def resolve_tag(
    key: str,
    namespace: str,
    repository: str,
    pattern: re.Pattern[str],
    values: dict[str, str],
    *,
    search: str = "",
    even_major_only: bool = False,
) -> Resolution:
    """Resolve a tag-valued pin of the Docker Hub image namespace/repository.
    `search` narrows the listing; empty, it is the pinned major (Docker Hub
    lists thousands of Grafana tags), so a new major is a manual choice."""
    current = required_value(values, key)
    current_key = version_key(current, pattern)
    if current_key is None:
        raise TokenCrateError(f"unsupported current {key}: {current}")
    published = docker_hub_tags(
        namespace, repository, search or current.split(".")[0] + ".", lambda tag: version_key(tag, pattern)
    )
    candidates = [
        tag
        for tag in published
        if (parsed := version_key(tag, pattern)) is not None
        and len(parsed) == len(current_key)
        # Node.js ships long-term-support releases on even majors only.
        and (not even_major_only or parsed[0] % 2 == 0)
    ]
    latest = latest_tag(candidates, pattern, f"Docker Hub {namespace}/{repository}")
    latest_key = version_key(latest, pattern)
    if current_is_latest(current_key, latest_key, f"Docker Hub {namespace}/{repository}"):
        return Resolution(key, current, current)
    image_history = (
        f"https://hub.docker.com/_/{repository}"
        if namespace == "library"
        else f"https://hub.docker.com/r/{namespace}/{repository}/tags"
    )
    digest = manifest_digest(published[latest], f"Docker Hub {namespace}/{repository}")
    return Resolution(key, current, latest, (f"  Image tags: {image_history}",), digest)


# One resolver per pin key the check can look up; the digest beside a tag is
# resolved with the tag. A pin of pins.env missing here is reported as such.
RESOLVERS: dict[str, Callable[[dict[str, str]], Resolution]] = {
    "LLAMA_CPP_TAG": resolve_llama_cpp,
    "PI_VERSION": functools.partial(resolve_npm, "PI_VERSION", "@earendil-works/pi-coding-agent"),
    "OMP_VERSION": functools.partial(resolve_npm, "OMP_VERSION", "@oh-my-pi/pi-coding-agent"),
    "NODE_TAG": functools.partial(
        resolve_tag,
        "NODE_TAG",
        "library",
        "node",
        re.compile(r"^(\d+(?:\.\d+)*)-bookworm-slim$"),
        search="bookworm-slim",
        even_major_only=True,
    ),
    "BUN_TAG": functools.partial(
        resolve_tag, "BUN_TAG", "oven", "bun", re.compile(rf"^{STABLE_TAG_RE}-slim$"), search="slim"
    ),
    "VICTORIAMETRICS_TAG": functools.partial(
        resolve_tag, "VICTORIAMETRICS_TAG", "victoriametrics", "victoria-metrics", re.compile(rf"^v{STABLE_TAG_RE}$")
    ),
    "GRAFANA_TAG": functools.partial(
        resolve_tag, "GRAFANA_TAG", "grafana", "grafana", re.compile(rf"^{STABLE_TAG_RE}$")
    ),
}


def check(selection: str, values: dict[str, str], *, waits: tuple[str, ...] = ()) -> str:
    """Resolve the selected pin (or every pin of pins.env) and return the report text.

    Every pin is a row, named by `component_name`; a pin without a resolver
    says so, so what the check covers is in its output. A source that
    cannot be read makes its pin's row say so and the whole report is
    raised as `LookupsFailed`, so the other pins are still reported and
    the exit status says a lookup failed. The `waits` lines (model sets that need a
    newer llama.cpp build than the pin, from the renderer) are printed under
    the llama-cpp line, so the wait is visible on every check."""
    components = {component_name(key): key for key in values if not key.endswith("_DIGEST")}
    if selection != "all" and selection not in components:
        raise TokenCrateError(f"unknown pin component {selection!r}; choose from: {', '.join(components)}, all")
    selected = components if selection == "all" else {selection: components[selection]}
    rows: dict[str, Resolution | TokenCrateError | None] = {}
    for name, key in selected.items():
        if key not in RESOLVERS:
            rows[name] = None
            continue
        try:
            rows[name] = RESOLVERS[key](values)
        except TokenCrateError as error:
            rows[name] = error

    lines: list[str] = []
    for name, resolution in rows.items():
        if resolution is None:
            lines.append(f"{name}: {values[selected[name]]} (no resolver; look it up by hand)")
        elif isinstance(resolution, TokenCrateError):
            lines.append(f"{name}: {values[selected[name]]} (lookup failed: {resolution})")
        elif resolution.latest == resolution.current:
            lines.append(f"{name}: {resolution.current} (latest eligible)")
        else:
            lines.append(f"{name}: {resolution.current} -> {resolution.latest}")
            lines.extend(resolution.notes)
    if "llama-cpp" in selected:
        index = next(i for i, line in enumerate(lines) if line.startswith("llama-cpp: ")) + 1
        while index < len(lines) and lines[index].startswith("  "):
            index += 1
        lines[index:index] = [f"  {wait}" for wait in waits]
    resolved = [resolution for resolution in rows.values() if isinstance(resolution, Resolution)]
    failed = [name for name, resolution in rows.items() if isinstance(resolution, TokenCrateError)]
    newer = [resolution for resolution in resolved if resolution.latest != resolution.current]
    if newer:
        lines += ["", "Paste into pins.env:"]
        for resolution in newer:
            lines.append(f"{resolution.key}={resolution.latest}")
            if resolution.digest:
                lines.append(f"{digest_key(resolution.key)}={resolution.digest}")
    elif len(resolved) == len(rows):
        lines.append("pins.env has the latest eligible pins.")
    elif resolved:
        lines.append("The resolved pins are the latest eligible.")
    report = "\n".join(lines) + "\n"
    if failed:
        raise LookupsFailed(report, failed)
    return report
