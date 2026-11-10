/**
 * Retrieval helpers for private browser-download artifacts (#30596).
 *
 * `download` actions store the captured file privately and return `artifact`
 * metadata on the action result. These helpers fetch that metadata, mint a
 * short-lived signed URL and save the bytes locally.
 */
import axios, { AxiosRequestConfig } from "axios";
import { createWriteStream } from "node:fs";
import { rename, unlink } from "node:fs/promises";
import { pipeline } from "node:stream/promises";
import type { ArtifactMetadata } from "./actions";

/** Response of `GET /api/v1/artifacts/{id}/url`; `url` is always absolute. */
export interface ArtifactUrl {
  artifact_id: string;
  url: string;
  expires_in: number;
  filename: string;
  media_type: string;
  size_bytes: number;
}

/** What the helpers need from the client: its retrying request fn and base URL. */
export interface ArtifactTransport {
  request: <T>(config: AxiosRequestConfig) => Promise<T>;
  baseUrl: string;
}

function artifactPath(artifactId: string): string {
  if (typeof artifactId !== "string" || artifactId.length === 0) {
    throw new Error("artifactId must be a non-empty string");
  }
  return `/api/v1/artifacts/${encodeURIComponent(artifactId)}`;
}

/** Metadata of an artifact you own (`GET /api/v1/artifacts/{id}`). */
export async function getArtifact(
  transport: ArtifactTransport,
  artifactId: string,
): Promise<ArtifactMetadata> {
  return transport.request<ArtifactMetadata>({
    method: "GET",
    url: artifactPath(artifactId),
  });
}

/**
 * Mint a short-lived signed download URL. A relative `url` (local storage
 * backend) is resolved against the client's base URL.
 */
export async function getArtifactUrl(
  transport: ArtifactTransport,
  artifactId: string,
): Promise<ArtifactUrl> {
  const data = await transport.request<ArtifactUrl>({
    method: "GET",
    url: `${artifactPath(artifactId)}/url`,
  });
  return {
    ...data,
    url: new URL(
      data.url,
      transport.baseUrl.replace(/\/+$/, "") + "/",
    ).toString(),
  };
}

/**
 * Save an artifact to `path` and return the path written. The signed URL is
 * fetched without the API key; bytes stream to `<path>.part` and are renamed
 * on success so a failed download never leaves a truncated file.
 */
export async function downloadArtifact(
  transport: ArtifactTransport,
  artifactId: string,
  path: string,
): Promise<string> {
  const info = await getArtifactUrl(transport, artifactId);
  const partial = `${path}.part`;
  try {
    const response = await axios.get(info.url, { responseType: "stream" });
    await pipeline(response.data, createWriteStream(partial));
    await rename(partial, path);
  } catch (error) {
    await unlink(partial).catch(() => undefined);
    throw error;
  }
  return path;
}
