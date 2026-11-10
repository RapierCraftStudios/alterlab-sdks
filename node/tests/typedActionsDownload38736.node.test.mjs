// #38736: typed `download` action. node:test via Node's built-in type stripping.
import assert from "node:assert/strict";
import { test } from "node:test";

import { Actions } from "../src/actions.ts";

test("download emits only set fields", () => {
  assert.deepEqual(Actions.download({ selector: "a.dl" }), {
    type: "download",
    selector: "a.dl",
  });
  assert.deepEqual(
    Actions.download({ url: "https://example.com/f.pdf", timeout_ms: 2000, max_bytes: 9 }),
    { type: "download", url: "https://example.com/f.pdf", timeout_ms: 2000, max_bytes: 9 },
  );
  assert.deepEqual(Actions.download({ selector: "a", frame: ["iframe#a"] }), {
    type: "download",
    selector: "a",
    frame: ["iframe#a"],
  });
});
