/**
 * Coverage for #40828: getBatchStatus sends include/limit/offset.
 */
import MockAdapter from "axios-mock-adapter";
import { AlterLab } from "../src/index";

const silentLogger = {
  debug: () => undefined,
  info: () => undefined,
  warn: () => undefined,
  error: () => undefined,
};

function setup() {
  const client = new AlterLab({
    apiKey: "sk_test",
    logger: silentLogger,
  } as never);
  const mock = new MockAdapter((client as any).client);
  mock.onGet(/batch\/b1/).reply(200, { batch_id: "b1", status: "processing" });
  return { client, mock };
}

describe("getBatchStatus include/paging (#40828)", () => {
  it("sends include, limit and offset as query params", async () => {
    const { client, mock } = setup();
    await client.getBatchStatus("b1", {
      include: "counts",
      limit: 10,
      offset: 20,
    });
    expect(mock.history.get[0].params).toEqual({
      include: "counts",
      limit: 10,
      offset: 20,
    });
  });

  it("sends no params without options", async () => {
    const { client, mock } = setup();
    await client.getBatchStatus("b1");
    expect(mock.history.get[0].params).toBeUndefined();
  });
});
