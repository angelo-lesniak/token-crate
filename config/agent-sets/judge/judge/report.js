// What the user sees of the judge: a status in pi's footer and in pi-web,
// such as `judge: 4 asked, 1 advised` or `judge: off, no judge service`,
// and one `judge` entry in the session file per answered question, with
// the check, the verdicts, and whether the judge advised. The model never
// reads session entries. A resumed session counts its earlier entries.
const KEY = "judge";

export class Report {
  #pi;
  #ctx;
  #asked = 0;
  #advised = 0;
  #off = "";

  constructor(pi) {
    this.#pi = pi;
  }

  // Every handler passes its ctx; session_start also counts the entries on
  // the session's branch.
  use(ctx, { count = false } = {}) {
    this.#ctx = ctx;
    if (count) {
      for (const entry of ctx?.sessionManager?.getBranch?.() ?? []) {
        if (entry.type !== "custom" || entry.customType !== KEY || !entry.data?.check) continue;
        this.#asked++;
        if (entry.data.advised) this.#advised++;
      }
    }
    this.#show();
  }

  answered(check, answers, advised) {
    this.#asked++;
    if (advised) this.#advised++;
    const verdicts = Object.fromEntries(
      Object.entries(answers).map(([key, value]) => [key, Math.round(Number(value?.noul) * 100) / 100]),
    );
    this.#pi.appendEntry(KEY, { check, verdicts, advised });
    this.#show();
  }

  off(reason) {
    this.#off = reason;
    this.#show();
  }

  #show() {
    const text = this.#off ? `judge: off, ${this.#off}` : `judge: ${this.#asked} asked, ${this.#advised} advised`;
    try {
      this.#ctx?.ui?.setStatus?.(KEY, text);
    } catch {
      // the ctx of a session pi has replaced
    }
  }
}
