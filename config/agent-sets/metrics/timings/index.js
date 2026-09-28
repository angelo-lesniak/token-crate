// Records each request's time to first token and its duration on the
// assistant message pi writes to the transcript, in the fields oh-my-pi
// writes (`ttft` and `duration`, milliseconds), so `stats` reads both
// agents the same way, and offers `/usage`, one line of this transcript's
// totals by the same definitions. The extension registers no tool and no
// prompt text, and a command is neither: the request pi sends does not
// change.
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

// A non-negative integer up to 2^53 as `stats.integer` reads it, else 0.
const count = (value) => (Number.isInteger(value) && value >= 0 && value <= 2 ** 53 ? value : 0);
const finite = (value) => (typeof value === "number" && Number.isFinite(value) ? value : null);
// Nearest-rank percentile of a non-empty list, as stats.py defines it.
const percentile = (values, fraction) => {
	const ordered = [...values].sort((a, b) => a - b);
	return ordered[Math.min(ordered.length - 1, Math.max(0, Math.ceil(fraction * ordered.length) - 1))];
};
const seconds = (ms) => (ms >= 10000 ? `${Math.round(ms / 1000)} s` : `${(ms / 1000).toFixed(1)} s`);

// One line for this transcript: every entry of the session file, the way
// `stats` reads it (usage numbers and metadata only, never content).
export function usageLine(entries) {
	const requests = [];
	let toolCalls = 0;
	let toolErrors = 0;
	for (const entry of entries) {
		const message = entry && entry.type === "message" ? entry.message : null;
		if (!message || typeof message !== "object") {
			continue;
		}
		if (message.role === "assistant" && message.usage && typeof message.usage === "object") {
			const usage = message.usage;
			const parts = [usage.input, usage.output, usage.cacheRead, usage.cacheWrite].map(count);
			requests.push({
				input: parts[0],
				output: parts[1],
				cacheRead: parts[2],
				context: count(usage.totalTokens) || parts[0] + parts[1] + parts[2] + parts[3],
				ttft: finite(message.ttft),
				duration: finite(message.duration),
			});
		} else if (message.role === "toolResult") {
			toolCalls += 1;
			toolErrors += message.isError ? 1 : 0;
		}
	}
	if (requests.length === 0) {
		return "usage: no requests in this transcript yet";
	}
	const sum = (key) => requests.reduce((total, request) => total + request[key], 0);
	const prompt = sum("input") + sum("cacheRead");
	const cacheShare = prompt ? `${Math.round((100 * sum("cacheRead")) / prompt)}%` : "-";
	const last = requests[requests.length - 1].context;
	const peak = Math.max(...requests.map((request) => request.context));
	const parts = [
		`${requests.length} request${requests.length === 1 ? "" : "s"}`,
		`${sum("input").toLocaleString("en-US")} in / ${sum("output").toLocaleString("en-US")} out`,
		`cache-read ${cacheShare}`,
		`context ${last.toLocaleString("en-US")} (peak ${peak.toLocaleString("en-US")})`,
	];
	const timed = requests.filter((request) => request.ttft !== null && request.duration !== null);
	if (timed.length > 0) {
		parts.push(`ttft p50 ${Math.round(percentile(timed.map((r) => r.ttft), 0.5))} ms`);
		parts.push(`duration p50 ${seconds(percentile(timed.map((r) => r.duration), 0.5))}`);
	}
	parts.push(`${toolCalls} tool${toolCalls === 1 ? "" : "s"}`, `${toolErrors} error${toolErrors === 1 ? "" : "s"}`);
	return `usage: ${parts.join(", ")}`;
}

export default function (pi) {
	let requestAt = null;
	let firstTokenAt = null;

	pi.registerCommand("usage", {
		description: "Token usage and timings of this transcript, as the stats command counts them",
		handler: async (_args, ctx) => {
			ctx.ui.notify(usageLine(ctx.sessionManager.getEntries()), "info");
		},
	});

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
