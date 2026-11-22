// Removes the packages of the set that only pi needs. npm installs pi's own
// dependencies beside pi-web, but the set links the pi packages to the
// image's pi, which resolves its dependencies from its own install, so
// whatever pi-web's other dependencies do not reach is never loaded.
// Resolution follows Node's: a package's own node_modules, then each
// directory above it up to the set.
//
// Usage (in the set directory): node prune.js
"use strict";

const fs = require("node:fs");
const path = require("node:path");

const root = path.resolve("node_modules");
const linked = (name) => name.startsWith("@earendil-works/");

function manifest(directory) {
  return JSON.parse(fs.readFileSync(path.join(directory, "package.json"), "utf8"));
}

function resolve(from, name) {
  for (let directory = from; ; directory = path.dirname(directory)) {
    const candidate = path.join(directory, "node_modules", name);
    if (fs.existsSync(path.join(candidate, "package.json"))) return candidate;
    if (directory === path.dirname(root)) return null;
  }
}

const reached = new Set();
const pending = [path.join(root, "@agegr/pi-web")];
while (pending.length > 0) {
  const directory = pending.pop();
  if (reached.has(directory)) continue;
  reached.add(directory);
  const { dependencies, optionalDependencies, peerDependencies } = manifest(directory);
  for (const name of Object.keys({ ...dependencies, ...optionalDependencies, ...peerDependencies })) {
    const found = linked(name) ? null : resolve(directory, name);
    if (found) pending.push(found);
  }
}

// Every installed package directory, nested ones below their parent.
function installed(modules) {
  if (!fs.existsSync(modules)) return [];
  return fs.readdirSync(modules).flatMap((entry) => {
    if (entry === ".bin" || entry.startsWith(".")) return [];
    const names = entry.startsWith("@") ? fs.readdirSync(path.join(modules, entry)).map((name) => `${entry}/${name}`) : [entry];
    return names
      .filter((name) => !linked(name))
      .map((name) => path.join(modules, name))
      .flatMap((directory) => [directory, ...installed(path.join(directory, "node_modules"))]);
  });
}

const removed = installed(root).filter((directory) => !reached.has(directory) && fs.existsSync(directory));
for (const directory of removed) fs.rmSync(directory, { recursive: true, force: true });
for (const modules of [root, ...[...reached].map((directory) => path.join(directory, "node_modules"))]) {
  if (!fs.existsSync(modules)) continue;
  for (const entry of fs.readdirSync(modules).filter((name) => name.startsWith("@"))) {
    const scope = path.join(modules, entry);
    if (fs.readdirSync(scope).length === 0) fs.rmdirSync(scope);
  }
  const bin = path.join(modules, ".bin");
  for (const name of fs.existsSync(bin) ? fs.readdirSync(bin) : []) {
    if (!fs.existsSync(path.join(bin, name))) fs.unlinkSync(path.join(bin, name));
  }
}
console.log(`pruned ${removed.length} packages that only pi needs`);
