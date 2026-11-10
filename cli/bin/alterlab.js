#!/usr/bin/env node
"use strict";

const { spawnSync } = require("node:child_process");

const RUNNERS = [
  ["uvx", ["alterlab"]],
  ["pipx", ["run", "alterlab"]],
];

for (const [cmd, prefix] of RUNNERS) {
  const res = spawnSync(cmd, [...prefix, ...process.argv.slice(2)], {
    stdio: "inherit",
  });
  if (res.error && res.error.code === "ENOENT") continue;
  if (res.error) {
    console.error(`alterlab: failed to run ${cmd}: ${res.error.message}`);
    process.exit(1);
  }
  process.exit(res.status === null ? 1 : res.status);
}

console.error(
  "alterlab: neither `uvx` nor `pipx` is installed. Install uv (https://docs.astral.sh/uv/) " +
    "or pipx, or run `pip install alterlab`."
);
process.exit(127);
