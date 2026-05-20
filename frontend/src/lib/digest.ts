/**
 * Typed shape of the digest payload returned by ``GET /scans/:id/digest``.
 *
 * The API client returns ``Record<string, unknown> | null`` so the response
 * stays loosely-typed at the network boundary. Pages call :func:`parseDigest`
 * to lift the unknown into a strongly-typed :class:`Digest`. A safeParse
 * failure means the backend shape drifted; callers degrade gracefully.
 */

import { z } from "zod";

export const ClusterScaleSchema = z.enum(["trivial", "small", "production"]);
export type ClusterScale = z.infer<typeof ClusterScaleSchema>;

export const EfficiencyGradeSchema = z.enum([
  "healthy",
  "mediocre",
  "poor",
  "critical",
]);
export type EfficiencyGrade = z.infer<typeof EfficiencyGradeSchema>;

export const NamespaceCostSchema = z.object({
  namespace: z.string(),
  cost_usd: z.number(),
  share: z.number(),
});
export type NamespaceCost = z.infer<typeof NamespaceCostSchema>;

const WorkloadCommonSchema = z.object({
  name: z.string(),
  namespace: z.string().nullable(),
  controller_kind: z.string().nullable(),
  controller: z.string().nullable(),
  cpu_util: z.number(),
  mem_util: z.number(),
  cost_usd: z.number(),
  impact_usd: z.number(),
});
export type IdleWorkload = z.infer<typeof WorkloadCommonSchema>;
export type OverProvWorkload = IdleWorkload;
export const IdleWorkloadSchema = WorkloadCommonSchema;
export const OverProvWorkloadSchema = WorkloadCommonSchema;

export const PvcWasteSchema = z.object({
  name: z.string(),
  cost_usd: z.number(),
  bytes_provisioned: z.number(),
  bytes_used: z.number(),
  utilization: z.number(),
  impact_usd: z.number(),
});
export type PvcWaste = z.infer<typeof PvcWasteSchema>;

export const AnalysisHintsSchema = z.object({
  idle_workload_count: z.number(),
  over_provisioned_count: z.number(),
  pvc_waste_count: z.number(),
  anomaly_count: z.number(),
  efficiency_grade: EfficiencyGradeSchema,
  cluster_scale: ClusterScaleSchema,
});
export type AnalysisHints = z.infer<typeof AnalysisHintsSchema>;

export const ClusterEfficiencySchema = z.object({
  cpu: z.number(),
  memory: z.number(),
  overall: z.number(),
});
export type ClusterEfficiency = z.infer<typeof ClusterEfficiencySchema>;

export const ClusterBreakdownSchema = z.object({
  idle_pool_cost_usd: z.number(),
  unallocated_cost_usd: z.number(),
  unmounted_cost_usd: z.number(),
});
export type ClusterBreakdown = z.infer<typeof ClusterBreakdownSchema>;

export const DigestSchema = z.object({
  window: z.string(),
  total_cost_usd: z.number(),
  monthly_run_rate_usd: z.number(),
  cluster_scale: ClusterScaleSchema,
  efficiency_grade: EfficiencyGradeSchema,
  analysis_hints: AnalysisHintsSchema,
  cluster_efficiency: ClusterEfficiencySchema,
  cluster_breakdown: ClusterBreakdownSchema,
  top_namespaces_by_cost: z.array(NamespaceCostSchema),
  idle_workloads: z.array(IdleWorkloadSchema),
  over_provisioned: z.array(OverProvWorkloadSchema),
  pvc_waste: z.array(PvcWasteSchema),
  anomalies: z.array(z.unknown()),
  savings_signals: z.record(z.string(), z.unknown()),
  truncated: z.boolean(),
  truncated_counts: z.record(z.string(), z.number()),
});
export type Digest = z.infer<typeof DigestSchema>;

export function parseDigest(raw: unknown): Digest | null {
  if (raw == null) return null;
  const result = DigestSchema.safeParse(raw);
  return result.success ? result.data : null;
}

/**
 * Bucket a 0..1 efficiency ratio to the same grade names the backend uses.
 * Used by dials to colour each resource independently (e.g. memory healthy
 * while CPU is critical on the same scan).
 */
export function gradeFromRatio(ratio: number): EfficiencyGrade {
  if (ratio >= 0.5) return "healthy";
  if (ratio >= 0.3) return "mediocre";
  if (ratio >= 0.15) return "poor";
  return "critical";
}

/** ``raw_data`` shape returned by the scan worker. Either has the four
 * Kubecost slices, or a ``{truncated, original_bytes}`` sentinel when the
 * serialized blob exceeded the 256 KB cap. ``passthrough`` so unknown
 * future fields don't fail validation. */
export const RawDataSchema = z
  .object({
    allocation: z.unknown().optional(),
    prior_allocation: z.unknown().optional(),
    assets: z.unknown().optional(),
    savings: z.unknown().optional(),
    truncated: z.boolean().optional(),
    original_bytes: z.number().optional(),
  })
  .passthrough();
export type RawData = z.infer<typeof RawDataSchema>;
