// #36692: `frame` on typed selector actions and the `snapshot` action.
// node:test file: loads ../src/actions.ts through Node's built-in type stripping.
import assert from "node:assert/strict";
import { test } from "node:test";

import { Actions } from "../src/actions.ts";

const cases = [
  [(f) => Actions.wait({ selector: "#r", frame: f }), { type: "wait", selector: "#r" }],
  [(f) => Actions.waitFor("#r", { frame: f }), { type: "wait_for", selector: "#r" }],
  [(f) => Actions.click("#pay", f), { type: "click", selector: "#pay" }],
  [(f) => Actions.fill("#c", "4242", f), { type: "fill", selector: "#c", value: "4242" }],
  [(f) => Actions.press("Enter", "#q", f), { type: "press", key: "Enter", selector: "#q" }],
  [(f) => Actions.select("#s", { value: "m" }, f), { type: "select", selector: "#s", value: "m" }],
  [(f) => Actions.hover("#m", f), { type: "hover", selector: "#m" }],
  [(f) => Actions.clickText("Pay", undefined, f), { type: "click_text", text: "Pay" }],
  [(f) => Actions.extract(".p", undefined, f), { type: "extract", selector: ".p" }],
  [(f) => Actions.check("#t", f), { type: "check", selector: "#t" }],
  [(f) => Actions.uncheck("#t", f), { type: "uncheck", selector: "#t" }],
];

test("frame is emitted only when set", () => {
  for (const [build, expected] of cases) {
    assert.deepEqual(build(undefined), expected);
    assert.deepEqual(build("iframe#a"), { ...expected, frame: "iframe#a" });
    assert.deepEqual(build(["#a", "#b"]), { ...expected, frame: ["#a", "#b"] });
  }
});

test("existing builders serialise unchanged without frame", () => {
  assert.equal(JSON.stringify(Actions.click("#a")), '{"type":"click","selector":"#a"}');
  assert.equal(
    JSON.stringify(Actions.select("#s", { label: "M" })),
    '{"type":"select","selector":"#s","label":"M"}',
  );
});

test("snapshot builder", () => {
  assert.deepEqual(Actions.snapshot(), { type: "snapshot" });
  assert.deepEqual(Actions.snapshot("markdown"), { type: "snapshot", format: "markdown" });
});
