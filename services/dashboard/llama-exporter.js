// The model server's counters for the dashboard profile, on the pinned Node
// image without a build. VictoriaMetrics scrapes this process; this process
// asks the router which preset is loaded (GET /models) every POLL_MS and
// reads the counters of a preset only when two consecutive polls reported
// it loaded: a request for `/metrics?model=` routes to the preset and would
// load one that just unloaded, so a scraper that names presets blindly
// would swap models. What it serves is the last scraped `llamacpp:` lines
// whose value is a finite number, labelled with the preset, plus three
// lines of its own; a line with another name, a text value, or a label
// other than `position` is dropped, so nothing but numbers and the
// preset's name leaves the router. A read of the counters that fails or
// runs long keeps the last good lines, and `tokencrate_scrape_age_seconds`
// says how old they are.
//
// The same process is Grafana's way to the store: the query gate on
// QUERY_PORT forwards only the Prometheus read paths to VictoriaMetrics,
// so a browser page that reaches Grafana's datasource proxy as the
// anonymous viewer can query the samples and never import, delete, or
// snapshot them.
"use strict";
const http = require("node:http");

const ROUTER = process.env.LLAMA_URL || "http://llama:8080";
const STORE = process.env.STORE_URL || "http://victoriametrics:8428";
const POLL_MS = Math.max(1000, Number(process.env.POLL_MS) || 5000);
const PORT = Number(process.env.PORT) || 9100;
const QUERY_PORT = Number(process.env.QUERY_PORT) || 9101;
const MODELS_TIMEOUT_MS = 2000;
// llama-server answers /metrics between decode steps; a busy 27B slot set
// can hold one for seconds.
const METRICS_TIMEOUT_MS = 15000;
const BODY_LIMIT = 1024 * 1024;
const PRESET_RE = /^[a-z0-9][a-z0-9.-]*$/;
const LINE_RE = /^(llamacpp:[a-z_]+)(?:\{position="(\d+)"\})? (-?\d+(?:\.\d+)?(?:e[+-]?\d+)?)$/;
// What Grafana's Prometheus plugin reads; everything else is refused.
const READ_PATHS = new Set([
  "/api/v1/query",
  "/api/v1/query_range",
  "/api/v1/query_exemplars",
  "/api/v1/series",
  "/api/v1/labels",
  "/api/v1/metadata",
  "/api/v1/status/buildinfo",
]);
const LABEL_VALUES_RE = /^\/api\/v1\/label\/[A-Za-z_][A-Za-z0-9_]*\/values$/;

let loaded = null; // the preset the last poll reported loaded
let polling = false;
let served = { up: 0, preset: null, lines: [], at: 0 };

async function get(path, timeoutMs) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(ROUTER + path, { signal: controller.signal });
    return response.ok ? await response.text() : null;
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

function loadedPreset(body) {
  let payload;
  try {
    payload = JSON.parse(body);
  } catch {
    return null;
  }
  const models = payload && Array.isArray(payload.data) ? payload.data : [];
  const names = models
    .filter((m) => m && typeof m.id === "string" && PRESET_RE.test(m.id) && m.status && m.status.value === "loaded")
    .map((m) => m.id)
    .sort();
  return names.length ? names[0] : null;
}

function keep(body, preset) {
  const lines = [];
  for (const line of body.split("\n")) {
    const match = LINE_RE.exec(line.trim());
    if (match && Number.isFinite(Number(match[3]))) {
      const position = match[2] === undefined ? "" : `,position="${match[2]}"`;
      lines.push(`${match[1]}{preset="${preset}"${position}} ${match[3]}`);
    }
  }
  return lines;
}

async function poll() {
  if (polling) {
    return;
  }
  polling = true;
  try {
    const models = await get("/models", MODELS_TIMEOUT_MS);
    const preset = models === null ? null : loadedPreset(models);
    const settled = preset !== null && preset === loaded;
    loaded = preset;
    const up = models === null ? 0 : 1;
    if (!settled) {
      // Nothing read: no lines, and no age for them.
      served = { up, preset: null, lines: [], at: 0 };
      return;
    }
    const metrics = await get(`/metrics?model=${encodeURIComponent(preset)}`, METRICS_TIMEOUT_MS);
    if (metrics === null) {
      // The preset is loaded either way; keep the lines read last for the
      // same preset, whose age then grows.
      const same = served.preset === preset;
      served = { up, preset, lines: same ? served.lines : [], at: same ? served.at : 0 };
      return;
    }
    served = { up, preset, lines: keep(metrics, preset), at: Date.now() };
  } finally {
    polling = false;
  }
}

function render() {
  const own = [
    `tokencrate_router_up ${served.up}`,
    served.preset ? `tokencrate_preset_loaded{preset="${served.preset}"} 1` : "tokencrate_preset_loaded 0",
  ];
  if (served.at) {
    own.push(`tokencrate_scrape_age_seconds ${((Date.now() - served.at) / 1000).toFixed(1)}`);
  }
  return `${[...own, ...served.lines].join("\n")}\n`;
}

const server = http.createServer((request, response) => {
  if (request.method !== "GET" || request.url !== "/metrics") {
    response.writeHead(404, { "Content-Type": "text/plain" });
    response.end("the counters are at /metrics\n");
    return;
  }
  response.writeHead(200, { "Content-Type": "text/plain; version=0.0.4; charset=utf-8" });
  response.end(render());
});

function readBody(request, response) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    request.on("data", (chunk) => {
      size += chunk.length;
      if (size > BODY_LIMIT) {
        response.writeHead(413, { "Content-Type": "text/plain" });
        response.end("body too large\n");
        reject(new Error("body too large"));
        request.destroy();
        return;
      }
      chunks.push(chunk);
    });
    request.on("end", () => resolve(Buffer.concat(chunks)));
    request.on("error", reject);
  });
}

// The query gate: the read paths, with their query string and form body,
// to the store; anything else answers 403 and never reaches it.
const gate = http.createServer(async (request, response) => {
  const path = (request.url || "").split("?")[0];
  const readable = READ_PATHS.has(path) || LABEL_VALUES_RE.test(path);
  if (!readable || (request.method !== "GET" && request.method !== "POST")) {
    response.writeHead(403, { "Content-Type": "text/plain" });
    response.end("the query gate forwards Prometheus read paths only\n");
    return;
  }
  // A panel that goes away or a store that hangs ends the upstream query.
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), METRICS_TIMEOUT_MS);
  // A request's own close fires once its body is read, so the socket's
  // end, before the answer went out, is the signal.
  response.on("close", () => {
    if (!response.writableEnded) {
      controller.abort();
    }
  });
  try {
    const body = request.method === "POST" ? await readBody(request, response) : undefined;
    const headers = {};
    if (request.headers["content-type"]) {
      headers["content-type"] = request.headers["content-type"];
    }
    const upstream = await fetch(STORE + request.url, { method: request.method, headers, body, signal: controller.signal });
    const text = await upstream.text();
    response.writeHead(upstream.status, { "Content-Type": upstream.headers.get("content-type") || "application/json" });
    response.end(text);
  } catch (error) {
    if (!response.headersSent) {
      response.writeHead(502, { "Content-Type": "text/plain" });
      response.end(`the store did not answer: ${error.message}\n`);
    }
  } finally {
    clearTimeout(timer);
  }
});

// Both listen on every interface of the container, where VictoriaMetrics
// and Grafana are.
server.listen(PORT, "0.0.0.0", () => {
  console.log(`llama exporter on :${PORT}, polling ${ROUTER} every ${POLL_MS} ms`);
});
gate.listen(QUERY_PORT, "0.0.0.0", () => {
  console.log(`query gate on :${QUERY_PORT} for ${STORE}`);
});
const timer = setInterval(() => void poll(), POLL_MS);
void poll();
for (const signal of ["SIGTERM", "SIGINT"]) {
  process.on(signal, () => {
    clearInterval(timer);
    gate.close();
    server.close(() => process.exit(0));
  });
}
