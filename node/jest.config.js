/** Minimal jest config for the Node SDK's test suite (#31823).
 *
 * `rootDir` for the main `tsconfig.json` is scoped to `./src` (build output
 * only includes the published package source), so tests use a dedicated
 * `tsconfig.test.json` that widens `rootDir`/`include` to also cover
 * `./tests` without touching the published build config.
 */
module.exports = {
  testEnvironment: "node",
  roots: ["<rootDir>/tests"],
  transform: {
    "^.+\\.ts$": ["ts-jest", { tsconfig: "tsconfig.test.json" }],
  },
};
