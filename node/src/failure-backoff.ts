/**
 * Parsing for the repeat-failure back-off 429 (`error: "repeat_failure_backoff"`).
 *
 * The API returns this uncharged 429 when the same request failed the same way
 * several times in a row. Its `detail` extends the canonical rate-limit detail
 * with `consecutive_failures`, `outcome_class`, `failure_code` and `hint`.
 */

/** Class of the repeated failure; it sets the back-off window. */
export type FailureBackoffOutcomeClass =
  "challenge" | "timeout" | "origin" | "other";

export interface FailureBackoffFields {
  consecutiveFailures: number | null;
  outcomeClass: string | null;
  failureCode: string | null;
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

/** Read the back-off fields from a 429 body's `detail`; each is null when absent or malformed. */
export function parseFailureBackoffDetail(
  detail: Record<string, unknown> | null,
): FailureBackoffFields {
  const count = detail?.consecutive_failures;
  const outcomeClass = detail?.outcome_class;
  const failureCode = detail?.failure_code;
  return {
    consecutiveFailures:
      typeof count === "number" && Number.isInteger(count) ? count : null,
    outcomeClass: typeof outcomeClass === "string" ? outcomeClass : null,
    failureCode: typeof failureCode === "string" ? failureCode : null,
  };
}

/** Return `data.detail.hint` when `data` and `data.detail` are plain objects. */
export function detailHintSource(data: unknown): unknown {
  if (!isPlainObject(data) || !isPlainObject(data.detail)) return undefined;
  return data.detail.hint;
}
