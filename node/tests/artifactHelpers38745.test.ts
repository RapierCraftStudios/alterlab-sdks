/** #38745: artifact retrieval helpers and the 5-download client check. */
import MockAdapter from "axios-mock-adapter";
import axios from "axios";
import { mkdtempSync, readFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Actions, AlterLab, assertDownloadActionLimit } from "../src/index";

const silentLogger = {
  debug: () => undefined,
  info: () => undefined,
  warn: () => undefined,
  error: () => undefined,
};

const META = {
  artifact_id: "art_1",
  filename: "f.pdf",
  media_type: "application/pdf",
  size_bytes: 3,
  sha256: "abc",
  status: "stored",
  expires_at: 1,
};

function makeClient() {
  const client = new AlterLab({
    apiKey: "sk_test_dummy",
    baseUrl: "https://api.example.test",
    logger: silentLogger,
    maxRetries: 1,
  });
  const mock = new MockAdapter(
    (client as unknown as { client: unknown }).client as never,
  );
  return { client, mock };
}

describe("artifact helpers (#38745)", () => {
  it("getArtifact returns metadata", async () => {
    const { client, mock } = makeClient();
    mock.onGet("/api/v1/artifacts/art_1").reply(200, META);
    expect(await client.getArtifact("art_1")).toEqual(META);
  });

  it("getArtifactUrl resolves relative signed URLs against baseUrl", async () => {
    const { client, mock } = makeClient();
    mock.onGet("/api/v1/artifacts/art_1/url").reply(200, {
      artifact_id: "art_1",
      url: "/api/v1/artifacts/art_1/content?expires=9&signature=s",
      expires_in: 60,
      filename: "f.pdf",
      media_type: "application/pdf",
      size_bytes: 3,
    });
    const info = await client.getArtifactUrl("art_1");
    expect(info.url).toBe(
      "https://api.example.test/api/v1/artifacts/art_1/content?expires=9&signature=s",
    );
  });

  it("getArtifactUrl keeps absolute presigned URLs", async () => {
    const { client, mock } = makeClient();
    mock.onGet("/api/v1/artifacts/art_1/url").reply(200, {
      artifact_id: "art_1",
      url: "https://r2.example.test/x?sig=1",
      expires_in: 60,
      filename: "f.pdf",
      media_type: "application/pdf",
      size_bytes: 3,
    });
    expect((await client.getArtifactUrl("art_1")).url).toBe(
      "https://r2.example.test/x?sig=1",
    );
  });

  it("downloadArtifact streams to disk without the API key", async () => {
    const { client, mock } = makeClient();
    mock.onGet("/api/v1/artifacts/art_1/url").reply(200, {
      artifact_id: "art_1",
      url: "https://r2.example.test/x?sig=1",
      expires_in: 60,
      filename: "f.pdf",
      media_type: "application/pdf",
      size_bytes: 3,
    });
    const { Readable } = await import("node:stream");
    const seen: Record<string, unknown>[] = [];
    const spy = jest.spyOn(axios, "get").mockImplementation(async (_u, cfg) => {
      seen.push((cfg?.headers ?? {}) as Record<string, unknown>);
      return {
        data: Readable.from([Buffer.from("abc")]),
        status: 200,
      } as never;
    });
    const dir = mkdtempSync(join(tmpdir(), "art-"));
    const out = join(dir, "f.pdf");
    expect(await client.downloadArtifact("art_1", out)).toBe(out);
    expect(readFileSync(out, "utf8")).toBe("abc");
    expect(existsSync(`${out}.part`)).toBe(false);
    expect(JSON.stringify(seen)).not.toContain("sk_test_dummy");
    spy.mockRestore();
  });

  it("downloadArtifact leaves no file on failure", async () => {
    const { client, mock } = makeClient();
    mock.onGet("/api/v1/artifacts/art_1/url").reply(404, { detail: "gone" });
    const out = join(mkdtempSync(join(tmpdir(), "art-")), "f.pdf");
    await expect(client.downloadArtifact("art_1", out)).rejects.toBeTruthy();
    expect(existsSync(out)).toBe(false);
  });
});

describe("download action limit (#38745)", () => {
  it("allows 5 and rejects 6", () => {
    const one = Actions.download({ url: "https://x.io/f" });
    expect(() => assertDownloadActionLimit(Array(5).fill(one))).not.toThrow();
    expect(() => assertDownloadActionLimit(Array(6).fill(one))).toThrow(
      /at most 5/,
    );
  });

  it("scrape() rejects 6 downloads before any request", async () => {
    const { client, mock } = makeClient();
    const one = Actions.download({ url: "https://x.io/f" });
    await expect(
      client.scrape({
        url: "https://example.com",
        render_js: true,
        actions: Array(6).fill(one),
      }),
    ).rejects.toThrow(/at most 5/);
    expect(mock.history.post.length).toBe(0);
  });
});
