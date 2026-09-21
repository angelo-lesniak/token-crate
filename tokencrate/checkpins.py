"""Report the latest eligible upstream versions of the pins in pins.env next to the current ones."""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from . import TokenCrateError

MAX_RESPONSE_BYTES = 16 * 1024 * 1024
# A safety limit on pagination. GHCR lists every tag of ggml-org/llama.cpp
# (about 12,000 in September 2026, growing by about ten per build) in pages
# of 1000; Docker Hub pages hold 100.
MAX_API_PAGES = 200
USER_AGENT = "TokenCrate-pins-check"
STABLE_TAG_RE = r"(\d+(?:\.\d+)+)"
LLAMA_CPP_REPOSITORY = "ggml-org/llama.cpp"
# The server image tags: `server-<family>-b<build>`; the family (cuda13) is
# a manual choice and stays, the build number is what the check resolves.
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
COMPONENTS = ("llama-cpp", "pi", "omp", "node", "bun")
NPM_PACKAGES = {
    "pi": ("PI_VERSION", "@earendil-works/pi-coding-agent"),
    "omp": ("OMP_VERSION", "@oh-my-pi/pi-coding-agent"),
}


@dataclass(frozen=True)
class Resolution:
    component: str
    key: str
    current: str
    latest: str
    notes: tuple[str, ...] = ()
    # The manifest digest of `latest`, for the <name>_DIGEST pin beside the
    # tag. Empty for a version pin that has none, and for a current pin,
    # which is not pasted anywhere.
    digest: str = ""


def request_bytes(url: str, *, accept: str = "application/json", headers: dict[str, str] | None = None) -> bytes:
    if urllib.parse.urlsplit(url).scheme.lower() != "https":
        raise TokenCrateError(f"pin source URL must use HTTPS: {url}")
    request_headers = {"Accept": accept, "User-Agent": USER_AGENT}
    request_headers.update(headers or {})
    request = urllib.request.Request(url, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            if urllib.parse.urlsplit(response.url).scheme.lower() != "https":
                raise TokenCrateError(f"pin source redirected away from HTTPS: {url}")
            announced = response.headers.get("Content-Length")
            if announced and announced.isdigit() and int(announced) > MAX_RESPONSE_BYTES:
                raise TokenCrateError(f"pin source response is too large: {url}")
            content = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as error:
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


# --- GHCR --------------------------------------------------------------------


def ghcr_token(repository: str) -> str:
    payload = request_json(
        "https://ghcr.io/token?" + urllib.parse.urlencode({"scope": f"repository:{repository}:pull"})
    )
    token = payload.get("token") if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token:
        raise TokenCrateError("GHCR did not issue an anonymous pull token")
    return token


def ghcr_tags(repository: str) -> list[str]:
    token = ghcr_token(repository)
    headers = {"Authorization": f"Bearer {token}"}
    tags: list[str] = []
    url: str | None = f"https://ghcr.io/v2/{repository}/tags/list?n=1000"
    pages = 0
    while url:
        if pages >= MAX_API_PAGES:
            raise TokenCrateError(f"GHCR tags for {repository} exceeded the {MAX_API_PAGES}-page safety limit")
        content = request_bytes(url, headers=headers)
        try:
            payload = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise TokenCrateError("GHCR returned an invalid tag list") from error
        if not isinstance(payload, dict) or not isinstance(payload.get("tags"), list):
            raise TokenCrateError(f"GHCR returned invalid tags for {repository}")
        tags.extend(str(tag) for tag in payload["tags"])
        url = None
        pages += 1
        # GHCR paginates through the `last` query parameter; the tag list is
        # sorted, so continue while a full page came back.
        if len(payload["tags"]) >= 1000:
            last = urllib.parse.quote(str(payload["tags"][-1]), safe="")
            url = f"https://ghcr.io/v2/{repository}/tags/list?n=1000&last={last}"
    return tags


def ghcr_manifest_digest(repository: str, tag: str) -> str:
    """The digest of what the tag points at. A manifest's digest is the
    sha256 of the document the registry serves, so the body is hashed here
    instead of trusting a header."""
    headers = {"Authorization": f"Bearer {ghcr_token(repository)}"}
    reference = urllib.parse.quote(tag, safe="")
    content = request_bytes(
        f"https://ghcr.io/v2/{repository}/manifests/{reference}", accept=MANIFEST_ACCEPT, headers=headers
    )
    return hashlib.sha256(content).hexdigest()


def resolve_llama_cpp(values: dict[str, str]) -> Resolution:
    component = "llama-cpp"
    key = "LLAMA_CPP_TAG"
    current = required_value(values, key)
    match = LLAMA_CPP_TAG_RE.fullmatch(current)
    if match is None:
        raise TokenCrateError(f"unsupported current {key}: {current}")
    family = match.group("family")
    current_build = int(match.group("build"))
    tag_pattern = re.compile(rf"^{re.escape(family)}-b(\d+)$")
    builds = [
        (int(tag_match.group(1)), tag)
        for tag in ghcr_tags(LLAMA_CPP_REPOSITORY)
        if (tag_match := tag_pattern.fullmatch(tag)) is not None
    ]
    if not builds:
        raise TokenCrateError(f"GHCR has no {family}-b* image tag for {LLAMA_CPP_REPOSITORY}")
    latest_build, latest_image_tag = max(builds)
    if latest_build < current_build:
        raise TokenCrateError(f"GHCR {LLAMA_CPP_REPOSITORY} latest build is older than the current pin")
    if latest_build == current_build:
        return Resolution(component, key, current, current)
    notes = (f"  llama.cpp build b{current_build} -> b{latest_build}: https://github.com/ggml-org/llama.cpp/releases",)
    digest = ghcr_manifest_digest(LLAMA_CPP_REPOSITORY, latest_image_tag)
    return Resolution(component, key, current, latest_image_tag, notes, digest)


# --- npm ---------------------------------------------------------------------


PACKAGE_VERSION_RE = re.compile(rf"^{STABLE_TAG_RE}$")


def resolve_npm(component: str, values: dict[str, str]) -> Resolution:
    key, package = NPM_PACKAGES[component]
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
        return Resolution(component, key, current, current)
    return Resolution(
        component,
        key,
        current,
        latest,
        (f"  Package history: https://www.npmjs.com/package/{package}?activeTab=versions",),
    )


# --- Docker Hub --------------------------------------------------------------


def docker_hub_tags(namespace: str, repository: str, search: str) -> dict[str, str]:
    """The matching tags of the image, each with the `sha256:...` reference
    of the manifest it points at; the listing carries both."""
    query = urllib.parse.urlencode({"page_size": 100, "name": search})
    url: str | None = f"https://hub.docker.com/v2/namespaces/{namespace}/repositories/{repository}/tags?{query}"
    tags: dict[str, str] = {}
    pages = 0
    while url:
        if pages >= MAX_API_PAGES:
            raise TokenCrateError(
                f"Docker Hub tags for {namespace}/{repository} exceeded the {MAX_API_PAGES}-page safety limit"
            )
        payload = request_json(url)
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            raise TokenCrateError(f"Docker Hub returned invalid tags for {namespace}/{repository}")
        tags.update(
            (str(item.get("name", "")), str(item.get("digest", "")))
            for item in payload["results"]
            if isinstance(item, dict)
        )
        next_url = payload.get("next")
        if next_url:
            next_url = str(next_url)
            parsed_next = urllib.parse.urlsplit(next_url)
            if parsed_next.scheme != "https" or parsed_next.hostname != "hub.docker.com":
                raise TokenCrateError("Docker Hub returned an unsafe pagination link")
            url = next_url
        else:
            url = None
        pages += 1
    return tags


def resolve_tag(
    component: str,
    key: str,
    values: dict[str, str],
    namespace: str,
    repository: str,
    pattern: re.Pattern[str],
    search: str,
    *,
    even_major_only: bool = False,
) -> Resolution:
    """Resolve a tag-valued pin of the Docker Hub image namespace/repository."""
    current = required_value(values, key)
    current_key = version_key(current, pattern)
    if current_key is None:
        raise TokenCrateError(f"unsupported current {key}: {current}")
    published = docker_hub_tags(namespace, repository, search)
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
        return Resolution(component, key, current, current)
    image_history = (
        f"https://hub.docker.com/_/{repository}"
        if namespace == "library"
        else f"https://hub.docker.com/r/{namespace}/{repository}/tags"
    )
    digest = manifest_digest(published[latest], f"Docker Hub {namespace}/{repository}")
    return Resolution(component, key, current, latest, (f"  Image tags: {image_history}",), digest)


def resolve_component(component: str, values: dict[str, str]) -> Resolution:
    if component == "llama-cpp":
        return resolve_llama_cpp(values)
    if component in NPM_PACKAGES:
        return resolve_npm(component, values)
    if component == "node":
        return resolve_tag(
            component,
            "NODE_TAG",
            values,
            "library",
            "node",
            re.compile(r"^(\d+(?:\.\d+)*)-bookworm-slim$"),
            "bookworm-slim",
            even_major_only=True,
        )
    if component == "bun":
        return resolve_tag(
            component,
            "BUN_TAG",
            values,
            "oven",
            "bun",
            re.compile(rf"^{STABLE_TAG_RE}-slim$"),
            "slim",
        )
    raise TokenCrateError(f"unknown pin component: {component}")


def check(selection: str, values: dict[str, str], *, waits: tuple[str, ...] = ()) -> str:
    """Resolve the selected component(s) (or all) and return the report text.

    Every source is queried before anything is reported, so a failing source
    raises and nothing partial is returned. The `waits` lines (model sets
    that need a newer llama.cpp build than the pin, from the renderer) are
    printed under the llama-cpp line, so the wait is visible on every
    check."""
    if selection != "all" and selection not in COMPONENTS:
        raise TokenCrateError(f"unknown pin component {selection!r}; choose from: {', '.join(COMPONENTS)}, all")
    selected = COMPONENTS if selection == "all" else (selection,)
    resolutions = [resolve_component(component, values) for component in selected]

    lines: list[str] = []
    newer = [resolution for resolution in resolutions if resolution.latest != resolution.current]
    for resolution in resolutions:
        if resolution.latest == resolution.current:
            lines.append(f"{resolution.component}: {resolution.current} (latest eligible)")
            continue
        lines.append(f"{resolution.component}: {resolution.current} -> {resolution.latest}")
        lines.extend(resolution.notes)
    if "llama-cpp" in selected:
        index = next(i for i, line in enumerate(lines) if line.startswith("llama-cpp: ")) + 1
        while index < len(lines) and lines[index].startswith("  "):
            index += 1
        lines[index:index] = [f"  {wait}" for wait in waits]
    if not newer:
        lines.append("pins.env has the latest eligible pins.")
    else:
        lines += ["", "Paste into pins.env:"]
        for resolution in newer:
            lines.append(f"{resolution.key}={resolution.latest}")
            if resolution.digest:
                lines.append(f"{digest_key(resolution.key)}={resolution.digest}")
    return "\n".join(lines) + "\n"
