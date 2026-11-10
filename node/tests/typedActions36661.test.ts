/**
 * Coverage for #36661: typed browser actions serialise to the exact API JSON,
 * and `action_results` is typed (including `screenshot_url`).
 */
import MockAdapter from "axios-mock-adapter";
import {
  ActionResult,
  Actions,
  AlterLab,
  ScrapeAction,
  ScrapeActionType,
} from "../src/index";

const silentLogger = {
  debug: () => undefined,
  info: () => undefined,
  warn: () => undefined,
  error: () => undefined,
};

function makeClient() {
  const client = new AlterLab({
    apiKey: "sk_test_dummy",
    logger: silentLogger,
    maxRetries: 1,
  });
  const mock = new MockAdapter(
    (client as unknown as { client: unknown }).client as never,
  );
  return { client, mock };
}

const ACTION_RESULTS: ActionResult[] = [
  { index: 0, type: "click", success: true, error: null, result: null },
  { index: 1, type: "evaluate", success: true, result: "Example Domain" },
  {
    index: 2,
    type: "screenshot",
    success: true,
    screenshot_url: "https://alterlab.io/downloads/screenshots/a.png",
  },
];

describe("Actions builders (#36661)", () => {
  const cases: Array<[ScrapeAction, Record<string, unknown>]> = [
    [
      Actions.wait({ milliseconds: 1000 }),
      { type: "wait", milliseconds: 1000 },
    ],
    [Actions.wait({ selector: "#app" }), { type: "wait", selector: "#app" }],
    [
      Actions.wait({ milliseconds: 5000, selector: "#app" }),
      { type: "wait", milliseconds: 5000, selector: "#app" },
    ],
    [Actions.waitFor("#x"), { type: "wait_for", selector: "#x" }],
    [
      Actions.waitFor("#x", 2000),
      { type: "wait_for", selector: "#x", timeout: 2000 },
    ],
    [Actions.click("button.more"), { type: "click", selector: "button.more" }],
    [
      Actions.fill("input[name=q]", "shoes"),
      { type: "fill", selector: "input[name=q]", value: "shoes" },
    ],
    [Actions.press("Enter"), { type: "press", key: "Enter" }],
    [Actions.scroll(), { type: "scroll" }],
    [Actions.scroll("up", 3), { type: "scroll", direction: "up", amount: 3 }],
    [Actions.infiniteScroll(), { type: "infinite_scroll" }],
    [
      Actions.infiniteScroll({
        max_scrolls: 5,
        delay: 500,
        end_selector: ".end",
      }),
      {
        type: "infinite_scroll",
        max_scrolls: 5,
        delay: 500,
        end_selector: ".end",
      },
    ],
    [Actions.screenshot(), { type: "screenshot" }],
    [Actions.screenshot(false), { type: "screenshot", full_page: false }],
    [
      Actions.evaluate("document.title"),
      { type: "evaluate", script: "document.title" },
    ],
    [Actions.dismissConsent(), { type: "dismiss_consent" }],
    [
      Actions.dismissConsent("reject"),
      { type: "dismiss_consent", mode: "reject" },
    ],
  ];

  it.each(cases)("%j serialises to the exact API JSON", (action, expected) => {
    expect(JSON.parse(JSON.stringify(action))).toEqual(expected);
  });

  it("narrows the union on the type discriminator", () => {
    const action: ScrapeAction = Actions.evaluate("1 + 1");
    const kind: ScrapeActionType = action.type;
    expect(kind).toBe("evaluate");
    if (action.type === "evaluate") {
      expect(action.script).toBe("1 + 1");
    }
  });
});

describe("scrape with typed actions (#36661)", () => {
  it("sends typed actions under advanced.actions and returns typed action_results", async () => {
    const { client, mock } = makeClient();
    const bodies: Record<string, unknown>[] = [];
    mock.onPost("/api/v1/scrape").reply((config) => {
      bodies.push(JSON.parse(config.data ?? "{}"));
      return [
        200,
        { url: "https://example.com", action_results: ACTION_RESULTS },
      ];
    });

    const result = await client.scrape({
      url: "https://example.com",
      render_js: true,
      actions: [
        Actions.click("button.more"),
        { type: "evaluate", script: "document.title" },
        Actions.screenshot(),
      ],
    });

    const advanced = bodies[0].advanced as Record<string, unknown>;
    expect(advanced.actions).toEqual([
      { type: "click", selector: "button.more" },
      { type: "evaluate", script: "document.title" },
      { type: "screenshot" },
    ]);

    const results: ActionResult[] = result.action_results ?? [];
    expect(results).toHaveLength(3);
    expect(results[1].result).toBe("Example Domain");
    const screenshotUrl: string | null | undefined = results[2].screenshot_url;
    expect(screenshotUrl).toBe(
      "https://alterlab.io/downloads/screenshots/a.png",
    );
  });
});
