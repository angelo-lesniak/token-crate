// Forwards the published loopback port to the UI inside the agent
// container. It runs in its own container on the UI's internal network and
// on a publishing network of its own, because Docker never programs a
// published port for a container that sits only on an internal network. It
// is HTTP-aware for one reason: the published port must not depend on what
// the UI behind it checks about where a request comes from, so this
// forwarder refuses a request whose Host is not the published address, whose
// Origin names another site, or whose Sec-Fetch-Site says the browser sent
// it from another origin while no Origin names the UI. Without that, any web
// page open in the same browser could drive the agent through the loopback
// port. Clients that are not browsers send neither Origin nor Sec-Fetch-Site
// and are allowed.
//
// Usage: node ui-forward.js <target host> <target port> <listen port> <published port>
"use strict";

const http = require("node:http");
const net = require("node:net");

const [targetHost, targetPort, listenPort, publishedPort] = process.argv.slice(2);
if (!targetHost || !targetPort || !listenPort || !publishedPort) {
  process.stderr.write("usage: ui-forward.js <target host> <target port> <listen port> <published port>\n");
  process.exit(2);
}
const allowedHosts = new Set([`127.0.0.1:${publishedPort}`, `localhost:${publishedPort}`, `[::1]:${publishedPort}`]);
if (publishedPort === "80") {
  for (const host of ["127.0.0.1", "localhost", "[::1]"]) allowedHosts.add(host);
}

function allowed(headers) {
  if (!allowedHosts.has(headers.host || "")) return false;
  const origin = headers.origin;
  if (origin !== undefined) return origin.startsWith("http://") && allowedHosts.has(origin.slice(7));
  // Origin is set by the browser and names the page that sent the request;
  // a page cannot forge it, so an Origin of the UI itself settles the
  // question even when Sec-Fetch-Site says cross-site: the browser calls
  // the loopback names (127.0.0.1, localhost, [::1]) different sites, and
  // a page opened under one may reach the UI under another. Without an
  // Origin, a browser still names the relation between the page and the
  // request; only a page of the UI itself (same-origin) or a typed address
  // (none) may pass.
  const site = headers["sec-fetch-site"];
  return site === undefined || site === "same-origin" || site === "none";
}

// Model output reaches the page: a Markdown image or media element whose
// address names another site would make the browser send what the model
// put in that address there, past the containers' missing route out. The
// browser enforces this policy beside any the UI sends, so images and media
// load only from the UI itself and from data: and blob: addresses.
const POLICY = "img-src 'self' data: blob:; media-src 'self' data: blob:";

function withPolicy(headers) {
  const existing = headers["content-security-policy"];
  return { ...headers, "content-security-policy": existing === undefined ? POLICY : [].concat(existing, POLICY) };
}

function refuse(headers) {
  const site = headers["sec-fetch-site"] === undefined ? "" : ` (Sec-Fetch-Site: ${headers["sec-fetch-site"]})`;
  return `TokenCrate: refused a request for host ${headers.host || "(none)"} from origin ${headers.origin || "(none)"}${site}; open http://127.0.0.1:${publishedPort}/\n`;
}

const server = http.createServer((request, response) => {
  if (!allowed(request.headers)) {
    response.writeHead(403, withPolicy({ "content-type": "text/plain" }));
    response.end(refuse(request.headers));
    return;
  }
  const upstream = http.request(
    { host: targetHost, port: Number(targetPort), method: request.method, path: request.url, headers: request.headers, agent: false },
    (reply) => {
      response.writeHead(reply.statusCode, withPolicy(reply.headers));
      reply.on("error", () => response.destroy());
      reply.pipe(response);
    },
  );
  upstream.on("error", () => {
    if (!response.headersSent) response.writeHead(502, withPolicy({ "content-type": "text/plain" }));
    response.end("TokenCrate: the UI container does not answer yet\n");
  });
  request.on("error", () => upstream.destroy());
  response.on("close", () => upstream.destroy());
  request.pipe(upstream);
});

server.on("upgrade", (request, socket, head) => {
  if (!allowed(request.headers)) {
    socket.end(`HTTP/1.1 403 Forbidden\r\ncontent-type: text/plain\r\nconnection: close\r\n\r\n${refuse(request.headers)}`);
    return;
  }
  const upstream = net.connect(Number(targetPort), targetHost, () => {
    let raw = `${request.method} ${request.url} HTTP/${request.httpVersion}\r\n`;
    for (const [name, value] of Object.entries(request.headers)) {
      for (const item of Array.isArray(value) ? value : [value]) {
        raw += `${name}: ${item}\r\n`;
      }
    }
    upstream.write(raw + "\r\n");
    if (head.length) upstream.write(head);
    socket.pipe(upstream).pipe(socket);
  });
  upstream.on("error", () => socket.destroy());
  socket.on("error", () => upstream.destroy());
  upstream.on("close", () => socket.destroy());
  socket.on("close", () => upstream.destroy());
});

server.listen(Number(listenPort), "0.0.0.0", () => {
  process.stdout.write(`TokenCrate UI forwarder: ${listenPort} -> ${targetHost}:${targetPort}, published as http://127.0.0.1:${publishedPort}/\n`);
});
for (const signal of ["SIGTERM", "SIGINT"]) {
  process.on(signal, () => process.exit(0));
}
