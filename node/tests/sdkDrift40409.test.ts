/**
 * Coverage for #40409: SDK types expose the `cost_usd` field added by #40388.
 */
import MockAdapter from "axios-mock-adapter";
import { readFileSync } from "fs";
import { join } from "path";
import { AlterLab } from "../src/index";
import type { ScrapeResponse } from "../src/index";
import type { BatchStatusResponse } from "../src/transport.generated";

const silentLogger = {
  debug: () => undefined,
  info: () => undefined,
  warn: () => undefined,
  error: () => undefined,
};

describe("cost_usd (#40409)", () => {
  it("transport.generated.ts declares cost_usd on batch responses", () => {
    const src = readFileSync(
      join(__dirname, "../src/transport.generated.ts"),
      "utf8",
    );
    expect(src).toMatch(/cost_usd: string;/);
  });

  it("types accept cost_usd and responses pass it through", async () => {
    const client = new AlterLab({
      apiKey: "sk_test",
      logger: silentLogger,
    } as never);
    const mock = new MockAdapter((client as any).client);
    const body = {
      batch_id: "b1",
      status: "completed",
      credits_used: 2500,
      cost_usd: "0.002500",
    };
    mock.onGet(/batch\/b1/).reply(200, body);
    const res = (await client.getBatchStatus("b1")) as BatchStatusResponse;
    expect(res.cost_usd).toBe("0.002500");
    const s: Partial<ScrapeResponse> = {
      credits_used: 4000,
      cost_usd: "0.004000",
    };
    expect(s.cost_usd).toBe("0.004000");
  });
});
