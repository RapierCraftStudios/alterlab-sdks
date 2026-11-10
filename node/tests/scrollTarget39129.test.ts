/** #39129: scroll action carries target_selector (API ScrollAction mirror). */
import MockAdapter from "axios-mock-adapter";
import { Actions, AlterLab, ScrapeAction } from "../src/index";

const silentLogger = {
  debug: () => undefined,
  info: () => undefined,
  warn: () => undefined,
  error: () => undefined,
};

describe("scroll target_selector (#39129)", () => {
  it("serialises target_selector via the builder", () => {
    expect(Actions.scroll(undefined, undefined, ".row-42")).toEqual({
      type: "scroll",
      target_selector: ".row-42",
    });
  });

  it("omits target_selector when unset", () => {
    expect(Actions.scroll()).toEqual({ type: "scroll" });
    expect(Actions.scroll("up", 3)).toEqual({
      type: "scroll",
      direction: "up",
      amount: 3,
    });
  });

  it("sends a literal typed action unchanged", async () => {
    const client = new AlterLab({
      apiKey: "sk_test_dummy",
      logger: silentLogger,
      maxRetries: 1,
    });
    const mock = new MockAdapter(
      (client as unknown as { client: unknown }).client as never,
    );
    const bodies: Record<string, unknown>[] = [];
    mock.onPost("/api/v1/scrape").reply((config) => {
      bodies.push(JSON.parse(config.data ?? "{}"));
      return [200, { url: "https://example.com" }];
    });
    const action: ScrapeAction = { type: "scroll", target_selector: "#x" };
    await client.scrape({
      url: "https://example.com",
      render_js: true,
      actions: [action],
    });
    const advanced = bodies[0].advanced as Record<string, unknown>;
    expect(advanced.actions).toEqual([
      { type: "scroll", target_selector: "#x" },
    ]);
  });
});
