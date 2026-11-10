/**
 * Coverage for #36654: typed builders for the new browser actions serialise to
 * the exact API JSON.
 */
import { Actions, ScrapeAction } from "../src/index";

describe("Actions builders (#36654)", () => {
  const cases: Array<[ScrapeAction, Record<string, unknown>]> = [
    [
      Actions.select("select#size", { label: "M" }),
      { type: "select", selector: "select#size", label: "M" },
    ],
    [
      Actions.select("select#size", { value: "m" }),
      { type: "select", selector: "select#size", value: "m" },
    ],
    [Actions.hover(".menu"), { type: "hover", selector: ".menu" }],
    [Actions.clickText("Load more"), { type: "click_text", text: "Load more" }],
    [
      Actions.clickText("Next", true),
      { type: "click_text", text: "Next", exact: true },
    ],
    [
      Actions.extract("span.price"),
      { type: "extract", selector: "span.price" },
    ],
    [
      Actions.extract("//a[@id='x']", "href"),
      { type: "extract", selector: "//a[@id='x']", attribute: "href" },
    ],
    [Actions.check("#tos"), { type: "check", selector: "#tos" }],
    [Actions.uncheck("#news"), { type: "uncheck", selector: "#news" }],
    [Actions.waitEvent(), { type: "wait_event" }],
    [
      Actions.waitEvent("networkidle", 5000),
      { type: "wait_event", event: "networkidle", timeout: 5000 },
    ],
    [
      Actions.waitFor(".spinner", { state: "hidden" }),
      { type: "wait_for", selector: ".spinner", state: "hidden" },
    ],
    [
      Actions.waitFor(".spinner", { timeout: 2000, state: "detached" }),
      {
        type: "wait_for",
        selector: ".spinner",
        timeout: 2000,
        state: "detached",
      },
    ],
    [
      Actions.waitFor("#x", 2000),
      { type: "wait_for", selector: "#x", timeout: 2000 },
    ],
    [
      Actions.press("Enter", "input[name=q]"),
      { type: "press", key: "Enter", selector: "input[name=q]" },
    ],
  ];

  it.each(cases)("%j serialises to the exact API JSON", (action, expected) => {
    expect(JSON.parse(JSON.stringify(action))).toEqual(expected);
  });

  it("narrows the union on the new discriminators", () => {
    const action: ScrapeAction = {
      type: "extract",
      selector: "h1",
      attribute: "id",
    };
    if (action.type === "extract") {
      expect(action.attribute).toBe("id");
    }
  });
});
