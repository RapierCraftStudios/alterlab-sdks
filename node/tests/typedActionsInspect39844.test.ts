/** #39844: inspect action and element_map result field (API InspectAction mirror). */
import { Actions, ActionResult, ScrapeAction } from "../src/index";

describe("inspect action (#39844)", () => {
  it("omits max_elements when unset", () => {
    expect(Actions.inspect()).toEqual({ type: "inspect" });
  });

  it("serialises max_elements", () => {
    expect(Actions.inspect(500)).toEqual({
      type: "inspect",
      max_elements: 500,
    });
  });

  it("is assignable to ScrapeAction and ActionResult carries element_map", () => {
    const action: ScrapeAction = { type: "inspect", max_elements: 10 };
    const result: ActionResult = {
      index: 0,
      type: action.type,
      success: true,
      element_map: { total: 1 },
      truncated: false,
    };
    expect(result.element_map).toEqual({ total: 1 });
  });
});
