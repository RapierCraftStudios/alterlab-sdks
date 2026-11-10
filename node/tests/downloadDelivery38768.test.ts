/** #38768: download action delivery fields and ActionResult.delivery typing. */
import { Actions } from "../src/index";
import type { ActionResult, ArtifactDelivery } from "../src/index";

describe("download delivery (#38768)", () => {
  it("passes integration_id and key_template through", () => {
    const a = Actions.download({
      selector: "a.dl",
      integration_id: "123e4567-e89b-12d3-a456-426614174000",
      key_template: "x/{job_id}/{filename}",
    });
    expect(a).toEqual({
      type: "download",
      selector: "a.dl",
      integration_id: "123e4567-e89b-12d3-a456-426614174000",
      key_template: "x/{job_id}/{filename}",
    });
  });

  it("types ActionResult.delivery", () => {
    const delivery: ArtifactDelivery = {
      integration_id: "i",
      status: "failed",
      error: "upload_failed",
    };
    const r: ActionResult = {
      index: 0,
      type: "download",
      success: true,
      delivery,
    };
    expect(r.delivery?.status).toBe("failed");
  });
});
