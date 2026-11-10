// ---------------------------------------------------------------------------
// Typed browser actions (#36661)
//
// Mirrors the `ScrapeAction` discriminated union in
// services/api/app/schemas/scrape.py. Keys are the API's snake_case names, so a
// typed action serialises to the exact request JSON. Selectors are CSS, or
// XPath when prefixed with `//` or `xpath=`.
// ---------------------------------------------------------------------------

/** Fields every browser action accepts (#36652). */
export interface ActionCommon {
  /**
   * API default true. false marks the action required: with
   * `actions_on_error: "abort"` its failure stops the sequence and fails the
   * request.
   */
  optional?: boolean;
  /**
   * API default false. true = after a successful state-changing action, wait
   * for the page to settle and return an `observation` (URL, route change,
   * readiness, bounded snapshot) in `action_results` (#30579).
   */
  observe?: boolean;
}

/** Per-action timeout for click/fill/evaluate (#36652). */
export interface ActionTimeout {
  /** Timeout in ms, 100-30000 (API default 10000). */
  timeout_ms?: number;
}

/**
 * Target an element inside an `<iframe>` (#36692): the iframe's selector, or a
 * list of 1-3 selectors for nested frames, outermost first.
 */
export interface ActionFrame {
  /** Selector of the `<iframe>` that contains the target; a list targets nested frames, outermost first. */
  frame?: string | string[];
}

/**
 * Wait for a fixed delay (`milliseconds`, 100-30000), or until `selector` is
 * visible. With both set, `milliseconds` is the selector wait timeout.
 */
export interface WaitAction extends ActionCommon, ActionFrame {
  type: "wait";
  milliseconds?: number;
  selector?: string;
}

/** Element state awaited by `wait_for`; `hidden` / `detached` wait for disappearance. */
export type WaitForState = "visible" | "hidden" | "attached" | "detached";

/** Wait for an element to reach `state` (API default `visible`; fails on timeout). */
export interface WaitForAction extends ActionCommon, ActionFrame {
  type: "wait_for";
  /** CSS selector to wait for (max 500 chars). */
  selector: string;
  /** Timeout in ms, 1000-30000 (API default 10000). */
  timeout?: number;
  /** Element state to wait for (API default `visible`). */
  state?: WaitForState;
}

/** Click the element matching a CSS selector. */
export interface ClickAction extends ActionCommon, ActionTimeout, ActionFrame {
  type: "click";
  selector: string;
}

/** Fill an input field with a value (max 5000 chars). */
export interface FillAction extends ActionCommon, ActionTimeout, ActionFrame {
  type: "fill";
  selector: string;
  value: string;
}

/**
 * Press a keyboard key (e.g. `"Enter"`, `"Tab"`, `"Escape"`), on `selector`
 * when set, otherwise on the page.
 */
export interface PressAction extends ActionCommon, ActionFrame {
  type: "press";
  key: string;
  selector?: string;
}

/** Scroll the page by `amount` viewport heights (1-20, API default 1). */
export interface ScrollAction extends ActionCommon {
  type: "scroll";
  direction?: "down" | "up";
  amount?: number;
  /**
   * CSS selector (max 500 chars) to scroll into view, e.g. a row of a
   * virtualised list. When set, `direction` and `amount` are ignored.
   */
  target_selector?: string;
}

/** Scroll repeatedly until end of content or `max_scrolls` is reached. */
export interface InfiniteScrollAction extends ActionCommon {
  type: "infinite_scroll";
  /** Maximum scroll iterations, 1-50 (API default 10). */
  max_scrolls?: number;
  /** Delay between scrolls in ms, 200-5000 (API default 1000). */
  delay?: number;
  /** CSS selector that marks the end of content. */
  end_selector?: string;
}

/**
 * Capture a screenshot at this point in the sequence. The image is returned as
 * `screenshot_url` on the matching action result.
 */
export interface ScreenshotAction extends ActionCommon {
  type: "screenshot";
  /** Capture the full page (API default) or just the viewport. */
  full_page?: boolean;
}

/**
 * Run JavaScript in the page context (max 5120 chars); its return value is the
 * action result. Network APIs and dynamic code execution are rejected.
 */
export interface EvaluateAction extends ActionCommon, ActionTimeout {
  type: "evaluate";
  script: string;
}

/**
 * Remove the cookie consent overlay. `hide` (API default) leaves consent state
 * unchanged; `accept` / `reject` click the CMP's own button first.
 */
export interface DismissConsentAction extends ActionCommon {
  type: "dismiss_consent";
  mode?: "hide" | "accept" | "reject";
}

/** Choose a `<select>` option by `value` or `label` (exactly one). */
export interface SelectAction extends ActionCommon, ActionFrame {
  type: "select";
  selector: string;
  value?: string;
  label?: string;
}

/** Move the pointer over an element, e.g. to open a hover menu. */
export interface HoverAction extends ActionCommon, ActionFrame {
  type: "hover";
  selector: string;
}

/** Scroll an element into view, e.g. a row of a virtualized list. */
export interface ScrollIntoViewAction extends ActionCommon, ActionFrame {
  type: "scroll_into_view";
  selector: string;
  block?: "start" | "center" | "end" | "nearest";
}

/** Click the first element whose visible text matches `text`. */
export interface ClickTextAction extends ActionCommon, ActionFrame {
  type: "click_text";
  text: string;
  /** Match the whole text case-sensitively (API default: substring). */
  exact?: boolean;
}

/**
 * Read the first matching element's visible text, or `attribute`, into
 * `action_results[i].result` (max 5000 chars; null when the attribute is absent).
 */
export interface ExtractAction extends ActionCommon, ActionFrame {
  type: "extract";
  selector: string;
  attribute?: string;
}

/** Check a checkbox or radio button. */
export interface CheckAction extends ActionCommon, ActionFrame {
  type: "check";
  selector: string;
}

/** Uncheck a checkbox. */
export interface UncheckAction extends ActionCommon, ActionFrame {
  type: "uncheck";
  selector: string;
}

/** Wait for a page load event (API default `load`). */
export interface WaitEventAction extends ActionCommon {
  type: "wait_event";
  event?: "load" | "domcontentloaded" | "networkidle";
  /** Timeout in ms, 1000-30000 (API default 10000). */
  timeout?: number;
}

/**
 * Return a capped map of the visible page elements (#39585). Delivered as
 * `element_map` on the matching action result.
 */
export interface InspectAction extends ActionCommon {
  type: "inspect";
  /** Maximum number of elements returned, 1-500 (API default 200). */
  max_elements?: number;
}

/**
 * Capture the page HTML or markdown at this step (#36692). Delivered as
 * `snapshot_url` on the matching action result.
 */
export interface SnapshotAction extends ActionCommon {
  type: "snapshot";
  /** Capture the rendered HTML (API default) or its markdown conversion. */
  format?: "html" | "markdown";
}

/**
 * Capture one file download started by the page (#30596). Exactly one of
 * `selector` (clicked to start the download) or `url` (opened in a fresh tab)
 * is required; `frame` only applies with `selector`. Delivered as `artifact`
 * metadata on the matching action result.
 */
export interface DownloadAction extends ActionCommon, ActionFrame {
  type: "download";
  /** Element to click that starts the download (max 500 chars). */
  selector?: string;
  /** Absolute http(s) URL of a download link to open (max 2048 chars). */
  url?: string;
  /** Time to wait for the download to finish, in ms, 1000-30000 (API default 15000). */
  timeout_ms?: number;
  /** Reject files larger than this, 1-104857600 bytes. */
  max_bytes?: number;
  /** Active S3 storage integration (UUID) you own; the file is also delivered there. */
  integration_id?: string;
  /** Delivery object key: `[A-Za-z0-9._-]` segments plus `{artifact_id}`, `{job_id}`, `{filename}` (max 200; needs `integration_id`). */
  key_template?: string;
  /** Capture up to this many files started by the trigger, 1-10 (default 1). */
  max_files?: number;
  /** Aggregate size limit across all files, 1-104857600 bytes (needs `max_files` > 1). */
  max_total_bytes?: number;
  /** Multi-file: stop collecting after this many ms without a new download, 100-10000 (default 1000). */
  quiet_ms?: number;
  /** `"zip"` also stores one ZIP of all captured files, returned as `bundle` (needs `max_files` > 1). */
  bundle?: "none" | "zip";
}

/** Outcome of delivering a download artifact to a storage integration (#38734). */
export interface ArtifactDelivery {
  integration_id: string;
  status: "delivered" | "failed";
  key?: string | null;
  bytes?: number | null;
  /** Delivery error code when failed; the platform artifact is unaffected. */
  error?: string | null;
}

/** A privately stored browser download; fetch via GET /api/v1/artifacts/{artifact_id}/url. */
export interface ArtifactMetadata {
  artifact_id: string;
  filename: string;
  media_type: string;
  size_bytes: number;
  sha256: string;
  status: "stored";
  /** In-house content check result for the stored file. */
  scan_status?: "not_scanned" | "clean" | "quarantined";
  /** Unix time after which the artifact is deleted. */
  expires_at?: number | null;
}

/** One main-frame URL change caused by an action (URLs redacted). */
export interface RouteTransition {
  from_url: string;
  to_url: string;
  /** navigation = browser frame event; poll = URL poll fallback. */
  source: "navigation" | "poll";
  /** same_document = pushState/replaceState/popstate/hash; document = full navigation. */
  kind: "same_document" | "document";
  cross_origin: boolean;
  action_index?: number | null;
}

/** An actionable element seen after the action, including shadow DOM. */
export interface ObservedNode {
  role: string;
  text?: string;
  attrs?: Record<string, string>;
  /** Inside a shadow root. */
  shadow?: boolean;
}

/** Bounded view of the page; input values are never included. */
export interface ObservationSnapshot {
  title?: string;
  nodes?: ObservedNode[];
  /** Actionable elements found. */
  node_count?: number;
  /** node_count exceeded nodes. */
  truncated?: boolean;
  shadow_roots?: number;
  /** True when a virtualized list was only partly rendered. */
  window_only?: boolean;
}

/** What the page looked like once an action settled (`observe: true`). */
export interface ActionObservation {
  action_index?: number | null;
  /** Current URL (redacted). */
  url?: string | null;
  /** True only when the DOM settled within the budget after a successful action. */
  verified: boolean;
  readiness: "stable" | "timeout" | "error" | "not_run";
  route?: RouteTransition | null;
  transitions?: RouteTransition[];
  snapshot?: ObservationSnapshot | null;
  waited_ms?: number | null;
  /** Typed codes, e.g. stability_timeout, budget_exhausted, action_failed. */
  diagnostics?: string[];
}

/** Any browser action, discriminated by `type`. */
export type ScrapeAction =
  | WaitAction
  | WaitForAction
  | ClickAction
  | FillAction
  | PressAction
  | ScrollAction
  | InfiniteScrollAction
  | ScreenshotAction
  | EvaluateAction
  | DismissConsentAction
  | SelectAction
  | HoverAction
  | ScrollIntoViewAction
  | ClickTextAction
  | ExtractAction
  | CheckAction
  | UncheckAction
  | WaitEventAction
  | SnapshotAction
  | InspectAction
  | DownloadAction;

/** The `type` discriminator values of {@link ScrapeAction}. */
export type ScrapeActionType = ScrapeAction["type"];

/** Copy `fields` onto `base`, skipping undefined values. */
function withDefined<T extends object>(base: T, fields: object): T {
  const out: Record<string, unknown> = { ...(base as Record<string, unknown>) };
  for (const [key, value] of Object.entries(fields)) {
    if (value !== undefined) out[key] = value;
  }
  return out as T;
}

/**
 * Builders for typed browser actions.
 *
 * @example
 * actions: [
 *   Actions.click("button.load-more"),
 *   Actions.wait({ milliseconds: 1000 }),
 *   Actions.screenshot(),
 * ]
 */
export const Actions = {
  wait(options: {
    milliseconds?: number;
    selector?: string;
    frame?: string | string[];
  }): WaitAction {
    return withDefined<WaitAction>({ type: "wait" }, options);
  },
  waitFor(
    selector: string,
    timeout?:
      | number
      | { timeout?: number; state?: WaitForState; frame?: string | string[] },
  ): WaitForAction {
    const options = typeof timeout === "object" ? timeout : { timeout };
    return withDefined<WaitForAction>({ type: "wait_for", selector }, options);
  },
  click(selector: string, frame?: string | string[]): ClickAction {
    return withDefined<ClickAction>({ type: "click", selector }, { frame });
  },
  fill(selector: string, value: string, frame?: string | string[]): FillAction {
    return withDefined<FillAction>(
      { type: "fill", selector, value },
      { frame },
    );
  },
  press(
    key: string,
    selector?: string,
    frame?: string | string[],
  ): PressAction {
    return withDefined<PressAction>(
      { type: "press", key },
      { selector, frame },
    );
  },
  scroll(
    direction?: "down" | "up",
    amount?: number,
    targetSelector?: string,
  ): ScrollAction {
    return withDefined<ScrollAction>(
      { type: "scroll" },
      { direction, amount, target_selector: targetSelector },
    );
  },
  infiniteScroll(
    options: {
      max_scrolls?: number;
      delay?: number;
      end_selector?: string;
    } = {},
  ): InfiniteScrollAction {
    return withDefined<InfiniteScrollAction>(
      { type: "infinite_scroll" },
      options,
    );
  },
  screenshot(fullPage?: boolean): ScreenshotAction {
    return withDefined<ScreenshotAction>(
      { type: "screenshot" },
      { full_page: fullPage },
    );
  },
  evaluate(script: string): EvaluateAction {
    return { type: "evaluate", script };
  },
  dismissConsent(mode?: "hide" | "accept" | "reject"): DismissConsentAction {
    return withDefined<DismissConsentAction>(
      { type: "dismiss_consent" },
      { mode },
    );
  },
  select(
    selector: string,
    option: { value: string } | { label: string },
    frame?: string | string[],
  ): SelectAction {
    return withDefined<SelectAction>(
      { type: "select", selector, ...option },
      { frame },
    );
  },
  hover(selector: string, frame?: string | string[]): HoverAction {
    return withDefined<HoverAction>({ type: "hover", selector }, { frame });
  },
  scrollIntoView(
    selector: string,
    block?: "start" | "center" | "end" | "nearest",
    frame?: string | string[],
  ): ScrollIntoViewAction {
    return withDefined<ScrollIntoViewAction>(
      { type: "scroll_into_view", selector },
      { block, frame },
    );
  },
  clickText(
    text: string,
    exact?: boolean,
    frame?: string | string[],
  ): ClickTextAction {
    return withDefined<ClickTextAction>(
      { type: "click_text", text },
      { exact, frame },
    );
  },
  extract(
    selector: string,
    attribute?: string,
    frame?: string | string[],
  ): ExtractAction {
    return withDefined<ExtractAction>(
      { type: "extract", selector },
      { attribute, frame },
    );
  },
  check(selector: string, frame?: string | string[]): CheckAction {
    return withDefined<CheckAction>({ type: "check", selector }, { frame });
  },
  uncheck(selector: string, frame?: string | string[]): UncheckAction {
    return withDefined<UncheckAction>({ type: "uncheck", selector }, { frame });
  },
  waitEvent(
    event?: "load" | "domcontentloaded" | "networkidle",
    timeout?: number,
  ): WaitEventAction {
    return withDefined<WaitEventAction>(
      { type: "wait_event" },
      { event, timeout },
    );
  },
  snapshot(format?: "html" | "markdown"): SnapshotAction {
    return withDefined<SnapshotAction>({ type: "snapshot" }, { format });
  },
  inspect(maxElements?: number): InspectAction {
    return withDefined<InspectAction>(
      { type: "inspect" },
      { max_elements: maxElements },
    );
  },
  download(options: {
    selector?: string;
    url?: string;
    timeout_ms?: number;
    max_bytes?: number;
    integration_id?: string;
    key_template?: string;
    max_files?: number;
    max_total_bytes?: number;
    quiet_ms?: number;
    bundle?: "none" | "zip";
    frame?: string | string[];
    optional?: boolean;
  }): DownloadAction {
    return withDefined<DownloadAction>({ type: "download" }, options);
  },
} as const;

/** The API accepts at most this many `download` actions per request. */
export const MAX_DOWNLOAD_ACTIONS = 5;

/** Throws when `actions` holds more than {@link MAX_DOWNLOAD_ACTIONS} downloads. */
export function assertDownloadActionLimit(
  actions: readonly ScrapeAction[],
): void {
  const downloads = actions.filter((a) => a?.type === "download").length;
  if (downloads > MAX_DOWNLOAD_ACTIONS) {
    throw new Error(
      `at most ${MAX_DOWNLOAD_ACTIONS} download actions are allowed per request, got ${downloads}`,
    );
  }
}
