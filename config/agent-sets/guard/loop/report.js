// What the user sees of the loop guard: a status in pi's footer and in
// pi-web, such as `guard: watching` or `guard: 2 reminders, 1 steer`, and
// one `loop-guard` entry in the session file per intervention: a reminder
// appended to a tool result, a blocked call, a steer, or the end of a run.
// The model never reads session entries. A resumed session counts its
// earlier entries.
const KEY = "loop-guard";
const KINDS = {
  reminder: ["reminder", "reminders"],
  block: ["block", "blocks"],
  steer: ["steer", "steers"],
  stop: ["stopped run", "stopped runs"],
};

export class Report {
  #pi;
  #ctx;
  #counts = Object.fromEntries(Object.keys(KINDS).map((kind) => [kind, 0]));

  constructor(pi) {
    this.#pi = pi;
  }

  // Every handler passes its ctx; session_start also counts the entries on
  // the session's branch.
  use(ctx, { count = false } = {}) {
    this.#ctx = ctx;
    if (count) {
      for (const entry of ctx?.sessionManager?.getBranch?.() ?? []) {
        if (entry.type === "custom" && entry.customType === KEY && entry.data?.kind in this.#counts) this.#counts[entry.data.kind]++;
      }
    }
    this.#show();
  }

  intervened(kind, text) {
    this.#counts[kind]++;
    this.#pi.appendEntry(KEY, { kind, text: String(text).slice(0, 500) });
    this.#show();
  }

  #show() {
    const parts = Object.entries(KINDS)
      .filter(([kind]) => this.#counts[kind] > 0)
      .map(([kind, [one, many]]) => `${this.#counts[kind]} ${this.#counts[kind] === 1 ? one : many}`);
    const text = `guard: ${parts.length > 0 ? parts.join(", ") : "watching"}`;
    try {
      this.#ctx?.ui?.setStatus?.(KEY, text);
    } catch {
      // the ctx of a session pi has replaced
    }
  }
}
