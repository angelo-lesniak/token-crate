// Records each request's time to first token and its duration on the
// assistant message pi writes to the transcript, in the fields oh-my-pi
// writes (`ttft` and `duration`, milliseconds), so `stats` reads both
// agents the same way. The extension registers no tool, command, or
// prompt text: the request pi sends does not change.
//
// The clock starts in `before_provider_request`, which pi fires inside the
// provider after the request is built and before it is sent, so the
// measurement covers what the user waited for the model, the provider's
// own retries included, and nothing before the request (context
// transforms, compaction). The first `message_update` is the first
// content the model streamed; `message_end` carries the final message.
// Only a completed answer that streamed something is timed: an errored or
// aborted message keeps a zeroed usage object and would enter the
// percentiles as a request, and an answer without a `message_update`
// (nothing streamed) has no first token to time.
const COMPLETED = new Set(["stop", "toolUse", "length"]);

export default function (pi) {
	let requestAt = null;
	let firstTokenAt = null;

	// A handler that returns a value replaces the request payload, so this
	// one stays a block that returns nothing.
	pi.on("before_provider_request", () => {
		requestAt = performance.now();
		firstTokenAt = null;
	});

	pi.on("message_update", () => {
		if (requestAt !== null && firstTokenAt === null) {
			firstTokenAt = performance.now();
		}
	});

	pi.on("message_end", (event) => {
		const message = event.message;
		if (message.role !== "assistant" || requestAt === null) {
			return;
		}
		const startedAt = requestAt;
		requestAt = null;
		if (firstTokenAt === null || !COMPLETED.has(message.stopReason)) {
			return;
		}
		const endedAt = performance.now();
		return {
			message: {
				...message,
				ttft: Math.round(firstTokenAt - startedAt),
				duration: Math.round(endedAt - startedAt),
			},
		};
	});
}
