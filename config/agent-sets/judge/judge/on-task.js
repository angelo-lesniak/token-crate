// The on-task check: an edit the model judges unrelated to the request is
// shown to the user only; it is skipped while another question is pending.
import { yesNo } from "./calls.js";

const EDIT_TOOLS = new Set(["write", "edit"]);
const QUESTIONS = {
  onTask: yesNo("Is `edit` part of the work `request` asks for?", "Part of the requested work", "Unrelated to the request"),
};

export class OnTaskCheck {
  #judge;

  constructor(judge) {
    this.#judge = judge;
  }

  // Not awaited: the notice is for the user, so the tool result does not wait for it.
  observe(request, event, ctx) {
    if (!EDIT_TOOLS.has(event.toolName) || event.isError || !request) return;
    const edit = { tool: event.toolName, path: event.input?.path, input: JSON.stringify(event.input).slice(0, 3000) };
    this.#judge
      .ask({ request, edit }, QUESTIONS, { optional: true, signal: ctx.signal })
      .then((answers) => {
        if (answers?.onTask?.noul < 0.3) ctx.ui.notify(`judge: an edit by ${event.toolName} looks unrelated to the request`, "warning");
      })
      .catch(() => {});
  }
}
