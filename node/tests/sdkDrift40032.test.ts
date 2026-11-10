/**
 * Coverage for #40032: Node SDK session create/update accept the identity and
 * capture fields defined by the OpenAPI SessionCreate/SessionUpdate schemas.
 */
import MockAdapter from "axios-mock-adapter";
import { AlterLab } from "../src/index";

const silentLogger = {
  debug: () => undefined,
  info: () => undefined,
  warn: () => undefined,
  error: () => undefined,
};

const EXTRA = {
  domain_set: ["a.example.com", "b.example.com"],
  storage_state: {
    origins: [{ origin: "https://example.com", localStorage: [] }],
  },
  scopes: ["read", "write"] as Array<"read" | "write">,
  identity_profile_id: "11111111-1111-4111-8111-111111111111",
  connected_via: "extension" as const,
  capture_context: {
    user_agent: "UA",
    platform: "Linux",
    locale: "en-US",
    timezone: "UTC",
  },
};

function makeClient() {
  const client = new AlterLab({
    apiKey: "sk_test_dummy",
    logger: silentLogger,
    maxRetries: 1,
  });
  const mock = new MockAdapter(
    (client as unknown as { client: unknown }).client as never,
  );
  const bodies: Record<string, unknown>[] = [];
  const capture =
    (response: unknown) =>
    (config: { data?: string }): [number, unknown] => {
      bodies.push(JSON.parse(config.data ?? "{}"));
      return [200, response];
    };
  return { client, mock, bodies, capture };
}

describe("sessions.create / sessions.update identity and capture fields (#40032)", () => {
  it("create sends the extra fields", async () => {
    const { client, mock, bodies, capture } = makeClient();
    mock.onPost("/api/v1/sessions").reply(capture({ id: "s1" }));
    await client.sessions.create({
      name: "n",
      domain: "example.com",
      cookies: { a: "b" },
      ...EXTRA,
    });
    expect(bodies[0]).toMatchObject(EXTRA);
  });

  it("update sends the extra fields", async () => {
    const { client, mock, bodies, capture } = makeClient();
    mock.onPatch("/api/v1/sessions/s1").reply(capture({ id: "s1" }));
    await client.sessions.update("s1", EXTRA);
    expect(bodies[0]).toEqual(EXTRA);
  });
});
