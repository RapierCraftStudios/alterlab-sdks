/**
 * Research jobs (`/api/v1/research`): request/response types and helpers.
 *
 * Research runs on the caller's own model key (BYOK); a missing key is rejected by the API with
 * `byok_key_required` and nothing is charged.
 */

export type ResearchEffort =
  "lite" | "standard" | "deep" | "exhaustive" | "frontier";

export type ResearchStatus =
  | "awaiting_approval"
  | "queued"
  | "running"
  | "completed"
  | "completed_partial"
  | "failed"
  | "cancelled";

/** Statuses `waitForResearch` returns on. `awaiting_approval` is included so a `plan_first` job returns its plan. */
export const RESEARCH_SETTLED_STATUSES: readonly ResearchStatus[] = [
  "awaiting_approval",
  "completed",
  "completed_partial",
  "failed",
  "cancelled",
];

export interface ResearchRequest {
  /** Research question (max 4000 characters). */
  query: string;
  effort?: ResearchEffort;
  /** Hard cap on platform spend; lowers the effort tier cap. */
  max_cost_microcents?: number;
  max_tool_calls?: number;
  max_runtime_seconds?: number;
  /** Max follow-up rounds. */
  max_depth?: number;
  max_sources?: number;
  output?: "json" | "report" | "both";
  citation_format?: string;
  output_length?: string;
  criteria?: string[];
  /** Independent sources required per field. */
  min_sources?: number;
  sources?: Record<string, unknown>;
  /** JSON Schema for the structured answer. */
  output_schema?: Record<string, unknown>;
  files?: Array<Record<string, unknown>>;
  tools?: Record<string, unknown>;
  /** Return a plan and wait for approval before any spend. */
  plan_first?: boolean;
  webhook?: Record<string, unknown>;
  /** BYOK provider for planning and synthesis. */
  provider?: string;
  model?: string;
}

export interface ResearchJob {
  id: string;
  status: ResearchStatus;
  effort: ResearchEffort;
  /** The research question. */
  query?: string | null;
  budget: Record<string, unknown>;
  cost: Record<string, unknown>;
  tool_calls: number;
  stop_reason?: string | null;
  result?: Record<string, unknown> | null;
  coverage?: Record<string, unknown> | null;
  warnings: Array<Record<string, unknown>>;
  telemetry?: Record<string, unknown> | null;
  plan?: Record<string, unknown> | null;
  /** Returned once, on create only. */
  webhook_secret?: string | null;
  error?: string | null;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface ResearchEvent {
  id?: string;
  event?: string;
  data?: unknown;
}

export interface WaitForResearchOptions {
  /** Milliseconds between polls (default 2000). */
  pollIntervalMs?: number;
  /** Give up after this many milliseconds (default 600000); the job keeps running. */
  timeoutMs?: number;
}

/** Parse a `text/event-stream` body into events; `data` is JSON-decoded when possible. */
export function parseSseEvents(text: string): ResearchEvent[] {
  const events: ResearchEvent[] = [];
  for (const block of text.replace(/\r\n/g, "\n").split("\n\n")) {
    const event: ResearchEvent = {};
    const data: string[] = [];
    for (const line of block.split("\n")) {
      if (!line || line.startsWith(":")) continue;
      const i = line.indexOf(":");
      const field = i === -1 ? line : line.slice(0, i);
      let value = i === -1 ? "" : line.slice(i + 1);
      if (value.startsWith(" ")) value = value.slice(1);
      if (field === "data") data.push(value);
      else if (field === "id") event.id = value;
      else if (field === "event") event.event = value;
    }
    if (data.length) {
      const raw = data.join("\n");
      try {
        event.data = JSON.parse(raw);
      } catch {
        event.data = raw;
      }
    }
    if (
      event.id !== undefined ||
      event.event !== undefined ||
      event.data !== undefined
    ) {
      events.push(event);
    }
  }
  return events;
}
