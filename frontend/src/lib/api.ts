/**
 * API client. All backend calls funnel through here.
 * Zod schemas mirror Pydantic models on the backend.
 */

import { z } from "zod";

import { RawDataSchema } from "@/lib/digest";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const ScanStatusSchema = z.enum(["queued", "running", "completed", "failed"]);
export type ScanStatus = z.infer<typeof ScanStatusSchema>;

export const LatestScanSchema = z.object({
  id: z.number(),
  status: ScanStatusSchema,
  window: z.string(),
  total_cost_usd: z.number().nullable(),
  started_at: z.string().nullable(),
  completed_at: z.string().nullable(),
  created_at: z.string(),
  finding_count: z.number().nullable().optional(),
});
export type LatestScan = z.infer<typeof LatestScanSchema>;

export const EnvironmentSchema = z.object({
  id: z.number(),
  name: z.string(),
  kubecost_url: z.string(),
  aws_region: z.string(),
  cluster_name: z.string().nullable(),
  last_connection_check: z.string().nullable(),
  last_connection_ok: z.boolean(),
  last_connection_error: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
  latest_scan: LatestScanSchema.nullable(),
});
export type Environment = z.infer<typeof EnvironmentSchema>;

export const ConnectionTestResultSchema = z.object({
  ok: z.boolean(),
  message: z.string(),
  kubecost_version: z.string().nullable().optional(),
  latency_ms: z.number().nullable().optional(),
});
export type ConnectionTestResult = z.infer<typeof ConnectionTestResultSchema>;

export const ScanSchema = z.object({
  id: z.number(),
  environment_id: z.number(),
  status: ScanStatusSchema,
  progress_message: z.string().nullable(),
  error_message: z.string().nullable(),
  window: z.string(),
  total_cost_usd: z.number().nullable(),
  started_at: z.string().nullable(),
  completed_at: z.string().nullable(),
  created_at: z.string(),
});
export type Scan = z.infer<typeof ScanSchema>;

export const ScanWithEnvSchema = ScanSchema.extend({
  environment_name: z.string().nullable(),
  finding_count: z.number().nullable(),
});
export type ScanWithEnv = z.infer<typeof ScanWithEnvSchema>;

export const OllamaModelInfoSchema = z.object({
  name: z.string(),
  size_bytes: z.number().nullable(),
  family: z.string().nullable(),
  parameter_size: z.string().nullable(),
  modified_at: z.string().nullable(),
  is_default: z.boolean(),
});
export type OllamaModelInfo = z.infer<typeof OllamaModelInfoSchema>;

export const PromptTemplateSchema = z.object({
  name: z.string(),
  content: z.string(),
  path: z.string(),
});
export type PromptTemplate = z.infer<typeof PromptTemplateSchema>;

export const RagDocumentSchema = z.object({
  source_file: z.string(),
  chunk_count: z.number(),
});
export type RagDocument = z.infer<typeof RagDocumentSchema>;

export const SeveritySchema = z.enum(["critical", "high", "medium", "low", "info"]);
export type Severity = z.infer<typeof SeveritySchema>;

export const FindingSchema = z.object({
  title: z.string(),
  severity: SeveritySchema,
  category: z.string(),
  impact_usd: z.number().nullable().optional(),
  affected_resource: z.string().nullable().optional(),
  recommendation: z.string(),
  rationale: z.string().nullable().optional(),
  digest_reference: z.string().nullable().optional(),
});
export type Finding = z.infer<typeof FindingSchema>;

export const ReportSchema = z.object({
  id: z.number(),
  scan_id: z.number(),
  executive_summary: z.string(),
  findings: z.array(FindingSchema),
  estimated_monthly_savings_usd: z.number().nullable(),
  model_used: z.string(),
  duration_ms: z.number().int().nullable(),
  prompt_tokens: z.number().int().nullable(),
  completion_tokens: z.number().int().nullable(),
  created_at: z.string(),
});
export type Report = z.infer<typeof ReportSchema>;

// ---- error model -----------------------------------------------------------

/**
 * FastAPI 422 response body. Each entry pinpoints which field failed.
 * The ``loc`` array typically looks like ``["body", "kubecost_url"]``.
 */
export const FastAPIValidationErrorSchema = z.object({
  detail: z.array(
    z.object({
      loc: z.array(z.union([z.string(), z.number()])),
      msg: z.string(),
      type: z.string(),
    }),
  ),
});

export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;
  /** Field name → list of error messages, parsed from FastAPI 422 if applicable. */
  readonly fieldErrors: Record<string, string[]>;

  constructor(status: number, body: unknown, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
    this.fieldErrors = parseFieldErrors(body);
  }

  get isValidation(): boolean {
    return this.status === 422 || Object.keys(this.fieldErrors).length > 0;
  }
  get isClient(): boolean {
    return this.status >= 400 && this.status < 500;
  }
  get isServer(): boolean {
    return this.status >= 500;
  }
}

function parseFieldErrors(body: unknown): Record<string, string[]> {
  const parsed = FastAPIValidationErrorSchema.safeParse(body);
  if (!parsed.success) return {};
  const out: Record<string, string[]> = {};
  for (const entry of parsed.data.detail) {
    // loc[0] is "body" / "query" / "path"; field name is the next segment.
    const field = String(entry.loc[entry.loc.length - 1] ?? "_");
    (out[field] ??= []).push(entry.msg);
  }
  return out;
}

async function http<T>(
  path: string,
  init: RequestInit,
  schema: z.ZodSchema<T>,
): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(init.headers ?? {}),
      },
    });
  } catch (err) {
    throw new ApiError(
      0,
      null,
      err instanceof Error ? err.message : "network error",
    );
  }
  if (!res.ok) {
    let body: unknown = null;
    const text = await res.text();
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
    const message =
      typeof body === "object" && body && "detail" in body && typeof body.detail === "string"
        ? body.detail
        : `API ${res.status}`;
    throw new ApiError(res.status, body, message);
  }
  if (res.status === 204) return undefined as T;
  return schema.parse(await res.json());
}

// ---- public client --------------------------------------------------------

export const api = {
  listEnvironments: () =>
    http("/environments", { method: "GET" }, z.array(EnvironmentSchema)),
  createEnvironment: (data: {
    name: string;
    kubecost_url: string;
    aws_region: string;
    cluster_name?: string;
    auth_token?: string;
  }) =>
    http(
      "/environments",
      { method: "POST", body: JSON.stringify(data) },
      EnvironmentSchema,
    ),
  getEnvironment: (id: number) =>
    http(`/environments/${id}`, { method: "GET" }, EnvironmentSchema),
  testConnection: (id: number) =>
    http(
      `/environments/${id}/test-connection`,
      { method: "POST" },
      ConnectionTestResultSchema,
    ),
  triggerScan: (id: number, window: string = "7d") =>
    http(
      `/environments/${id}/scan`,
      { method: "POST", body: JSON.stringify({ window }) },
      ScanSchema,
    ),
  listScans: (envId: number) =>
    http(`/environments/${envId}/scans`, { method: "GET" }, z.array(ScanSchema)),
  getScan: (scanId: number) =>
    http(`/scans/${scanId}`, { method: "GET" }, ScanSchema),
  getReport: (scanId: number) =>
    http(`/scans/${scanId}/report`, { method: "GET" }, ReportSchema),
  getDigest: (scanId: number) =>
    http(
      `/scans/${scanId}/digest`,
      { method: "GET" },
      z.record(z.string(), z.unknown()).nullable(),
    ),
  getRawData: (scanId: number) =>
    http(
      `/scans/${scanId}/raw-data`,
      { method: "GET" },
      RawDataSchema.nullable(),
    ),
  listAllScans: (params: {
    env_id?: number | null;
    from?: string | null;
    to?: string | null;
    status?: ScanStatus | null;
  } = {}) => {
    const search = new URLSearchParams();
    if (params.env_id != null) search.set("env_id", String(params.env_id));
    if (params.from) search.set("from", params.from);
    if (params.to) search.set("to", params.to);
    if (params.status) search.set("status", params.status);
    const qs = search.toString();
    return http(
      `/scans${qs ? `?${qs}` : ""}`,
      { method: "GET" },
      z.array(ScanWithEnvSchema),
    );
  },
  listOllamaModels: () =>
    http(
      "/settings/ollama/models",
      { method: "GET" },
      z.array(OllamaModelInfoSchema),
    ),
  getPromptTemplate: () =>
    http("/settings/prompt-template", { method: "GET" }, PromptTemplateSchema),
  listRagDocuments: () =>
    http("/settings/rag/documents", { method: "GET" }, z.array(RagDocumentSchema)),
};
