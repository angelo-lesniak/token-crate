// The client of the judge service (llama.cpp's /v1/systemone). The judge
// answers one request at a time, so this sends one at a time too. Advice is
// optional: a name that does not resolve means no judge, and it is not asked
// again in this process. A refused or dropped connection, a timeout, or an
// HTTP error skips that check only, so a judge that restarts is asked again
// once it is back; three such failures with no answer in between count as no
// judge, so an absent or hung one costs three attempts and not one per check.
// Before every question, /v1/models must name kev-4b: an address on the
// default network can pass to another container when the judge is
// recreated, and a server that answers with other models is not the judge
// and is not asked again; one still loading (503) is asked at the next check.
// The first failure, and giving up after three, are recorded once each as a
// `judge` entry in the session file, which the model never reads.

const TIMEOUT_MS = 5000;
// The judge service's --alias (compose.yaml).
const MODEL = "kev-4b";
// Name lookups that fail: the judge service is off.
const NO_JUDGE = new Set(["ENOTFOUND", "EAI_AGAIN"]);
const MAX_FAILURES = 3;

export class Judge {
  #origin;
  #appendEntry;
  #unreachable = false;
  #recorded = false;
  #failures = 0; // since the last answer
  // The questions pending or waiting; each waits for the one before.
  #pending = 0;
  #queue = Promise.resolve();

  constructor(origin, appendEntry) {
    this.#origin = origin;
    this.#appendEntry = appendEntry;
  }

  // `optional` questions (on task) are skipped while another is pending;
  // the others wait their turn.
  async ask(state, questions, { optional = false, signal } = {}) {
    if (this.#unreachable || (optional && this.#pending > 0)) return undefined;
    this.#pending++;
    const previous = this.#queue;
    let release;
    this.#queue = new Promise((resolve) => (release = resolve));
    try {
      await previous;
      if (this.#unreachable || !(await this.#identified(signal))) return undefined;
      const response = await this.#fetch(
        "/v1/systemone",
        { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ state, questions }) },
        signal,
      );
      if (!response.ok) {
        this.#record(`HTTP ${response.status}: ${(await response.text()).slice(0, 300)}`);
        this.#failed();
        return undefined;
      }
      const answers = (await response.json())?.answers;
      this.#failures = 0;
      return answers;
    } catch (error) {
      // An abort is the user's, not the judge's.
      if (error.name === "AbortError") return undefined;
      this.#record(`${error.name}: ${error.cause?.code ?? error.message}`);
      if (NO_JUDGE.has(error.cause?.code)) this.#unreachable = true;
      else this.#failed();
      return undefined;
    } finally {
      this.#pending--;
      release();
    }
  }

  #fetch(path, init, signal) {
    const signals = [AbortSignal.timeout(TIMEOUT_MS), ...(signal ? [signal] : [])];
    return fetch(`${this.#origin}${path}`, { ...init, signal: AbortSignal.any(signals) });
  }

  #failed() {
    if (++this.#failures < MAX_FAILURES) return;
    this.#unreachable = true;
    this.#appendEntry("judge", { url: this.#origin, failure: `${MAX_FAILURES} failed requests in a row; not asked again` });
  }

  #record(failure) {
    if (this.#recorded) return;
    this.#recorded = true;
    this.#appendEntry("judge", { url: this.#origin, failure });
  }

  // Whether the server is the judge; a server that answers with other
  // models is not asked again, one that is loading is asked at the next check.
  async #identified(signal) {
    const response = await this.#fetch("/v1/models", {}, signal);
    if (!response.ok) {
      this.#record(`HTTP ${response.status} from /v1/models`);
      if (response.status !== 503) this.#failed();
      return false;
    }
    const models = (await response.json())?.data ?? [];
    if (!models.some((model) => model.id === MODEL || model.aliases?.includes(MODEL))) {
      this.#unreachable = true;
      this.#record(`/v1/models does not name ${MODEL}: ${JSON.stringify(models.map((model) => model.id)).slice(0, 300)}`);
      return false;
    }
    return true;
  }
}
