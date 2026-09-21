"""Direct HTTP transport for the local model and browser UI services."""

from urllib.request import ProxyHandler, build_opener

# Host proxy settings apply to downloads, never to loopback API requests.
OPENER = build_opener(ProxyHandler({}))
