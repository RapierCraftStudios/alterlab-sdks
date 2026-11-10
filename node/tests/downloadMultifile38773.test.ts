/** #38773: multi-file download options and result typing. */
import { Actions } from "../src/index";
import type { ActionResult } from "../src/index";

describe("multi-file download (#38773)", () => {
  it("passes multi-file options through", () => {
    expect(
      Actions.download({
        selector: "a.dl",
        max_files: 3,
        max_total_bytes: 500,
        quiet_ms: 200,
        bundle: "zip",
      }),
    ).toEqual({
      type: "download",
      selector: "a.dl",
      max_files: 3,
      max_total_bytes: 500,
      quiet_ms: 200,
      bundle: "zip",
    });
  });

  it("types artifacts, bundle and scan_status", () => {
    const meta = {
      artifact_id: "a",
      filename: "f",
      media_type: "text/plain",
      size_bytes: 1,
      sha256: "x",
      status: "stored" as const,
      scan_status: "clean" as const,
    };
    const r: ActionResult = {
      index: 0,
      type: "download",
      success: true,
      artifacts: [meta],
      bundle: meta,
    };
    expect(r.artifacts?.[0].scan_status).toBe("clean");
    expect(r.bundle?.artifact_id).toBe("a");
  });
});
