/** #38746: `observe` is accepted on actions and `observation` is typed on ActionResult. */
import { ActionObservation, ActionResult, ScrapeAction } from "../src/index";

describe("action observation types (#38746)", () => {
  it("accepts observe on actions and types the observation", () => {
    const action: ScrapeAction = {
      type: "click",
      selector: "a",
      observe: true,
    };
    const observation: ActionObservation = {
      verified: true,
      readiness: "stable",
      route: {
        from_url: "https://a.test/",
        to_url: "https://a.test/b",
        source: "navigation",
        kind: "same_document",
        cross_origin: false,
      },
      snapshot: { title: "t", nodes: [{ role: "button", shadow: true }] },
    };
    const result: ActionResult = {
      index: 0,
      type: "click",
      success: true,
      observation,
    };
    expect(action.observe).toBe(true);
    expect(result.observation?.route?.kind).toBe("same_document");
  });
});
