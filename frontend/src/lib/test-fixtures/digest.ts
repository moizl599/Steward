/**
 * Shared digest fixtures for scan-report component tests.
 *
 * ``trivialCriticalDigest`` matches scan #4 from the live verification run:
 * a 15-minute-old kubecost-test cluster with $1.47/24h cost, 8% overall
 * efficiency, and 3 idle workloads. The other two fixtures exist so tests
 * can exercise the healthy-grade and mediocre-grade code paths without
 * reaching for the wider digest schema.
 */

import type { Digest, EfficiencyGrade, ClusterScale } from "@/lib/digest";

const trivialIdleWorkloads = [
  {
    name: "kube-system/Deployment/coredns",
    namespace: "kube-system",
    controller_kind: "Deployment",
    controller: "coredns",
    cpu_util: 0.005,
    mem_util: 0.082,
    cost_usd: 0.42,
    impact_usd: 0.42,
  },
  {
    name: "default/Deployment/nginx",
    namespace: "default",
    controller_kind: "Deployment",
    controller: "nginx",
    cpu_util: 0.0,
    mem_util: 0.013,
    cost_usd: 0.17,
    impact_usd: 0.17,
  },
  {
    name: "default/Deployment/redis",
    namespace: "default",
    controller_kind: "Deployment",
    controller: "redis",
    cpu_util: 0.004,
    mem_util: 0.009,
    cost_usd: 0.15,
    impact_usd: 0.15,
  },
];

export const trivialCriticalDigest: Digest = {
  window: "24h",
  total_cost_usd: 1.47,
  monthly_run_rate_usd: 44.24,
  cluster_scale: "trivial" satisfies ClusterScale,
  efficiency_grade: "critical" satisfies EfficiencyGrade,
  analysis_hints: {
    idle_workload_count: 3,
    over_provisioned_count: 0,
    pvc_waste_count: 0,
    anomaly_count: 0,
    efficiency_grade: "critical",
    cluster_scale: "trivial",
  },
  cluster_efficiency: { cpu: 0.035, memory: 0.475, overall: 0.083 },
  cluster_breakdown: {
    idle_pool_cost_usd: 0.6,
    unallocated_cost_usd: 0.0,
    unmounted_cost_usd: 0.0,
  },
  top_namespaces_by_cost: [
    { namespace: "kubecost", cost_usd: 0.8, share: 0.544 },
    { namespace: "kube-system", cost_usd: 0.42, share: 0.286 },
    { namespace: "default", cost_usd: 0.15, share: 0.098 },
    { namespace: "__idle__", cost_usd: 0.1, share: 0.072 },
  ],
  idle_workloads: trivialIdleWorkloads,
  over_provisioned: [],
  pvc_waste: [],
  anomalies: [],
  savings_signals: {},
  truncated: false,
  truncated_counts: {},
};

export const healthyProductionDigest: Digest = {
  window: "7d",
  total_cost_usd: 8420.0,
  monthly_run_rate_usd: 36085.71,
  cluster_scale: "production",
  efficiency_grade: "healthy",
  analysis_hints: {
    idle_workload_count: 0,
    over_provisioned_count: 0,
    pvc_waste_count: 0,
    anomaly_count: 0,
    efficiency_grade: "healthy",
    cluster_scale: "production",
  },
  cluster_efficiency: { cpu: 0.58, memory: 0.62, overall: 0.61 },
  cluster_breakdown: {
    idle_pool_cost_usd: 120.0,
    unallocated_cost_usd: 30.0,
    unmounted_cost_usd: 0.0,
  },
  top_namespaces_by_cost: [
    { namespace: "production-api", cost_usd: 3200.0, share: 0.38 },
    { namespace: "data-platform", cost_usd: 2800.0, share: 0.33 },
    { namespace: "ml-training", cost_usd: 1500.0, share: 0.178 },
    { namespace: "kube-system", cost_usd: 920.0, share: 0.109 },
  ],
  idle_workloads: [],
  over_provisioned: [],
  pvc_waste: [],
  anomalies: [],
  savings_signals: {},
  truncated: false,
  truncated_counts: {},
};

export const mediocreSmallDigest: Digest = {
  window: "30d",
  total_cost_usd: 480.0,
  monthly_run_rate_usd: 480.0,
  cluster_scale: "small",
  efficiency_grade: "mediocre",
  analysis_hints: {
    idle_workload_count: 1,
    over_provisioned_count: 2,
    pvc_waste_count: 1,
    anomaly_count: 0,
    efficiency_grade: "mediocre",
    cluster_scale: "small",
  },
  cluster_efficiency: { cpu: 0.42, memory: 0.31, overall: 0.36 },
  cluster_breakdown: {
    idle_pool_cost_usd: 35.0,
    unallocated_cost_usd: 6.0,
    unmounted_cost_usd: 0.0,
  },
  top_namespaces_by_cost: [
    { namespace: "staging", cost_usd: 240.0, share: 0.5 },
    { namespace: "tools", cost_usd: 140.0, share: 0.292 },
    { namespace: "default", cost_usd: 60.0, share: 0.125 },
    { namespace: "monitoring", cost_usd: 40.0, share: 0.083 },
  ],
  idle_workloads: [
    {
      name: "staging/Deployment/legacy-worker",
      namespace: "staging",
      controller_kind: "Deployment",
      controller: "legacy-worker",
      cpu_util: 0.02,
      mem_util: 0.05,
      cost_usd: 35.0,
      impact_usd: 35.0,
    },
  ],
  over_provisioned: [
    {
      name: "tools/Deployment/ci-runner",
      namespace: "tools",
      controller_kind: "Deployment",
      controller: "ci-runner",
      cpu_util: 0.18,
      mem_util: 0.22,
      cost_usd: 80.0,
      impact_usd: 40.0,
    },
    {
      name: "staging/StatefulSet/redis",
      namespace: "staging",
      controller_kind: "StatefulSet",
      controller: "redis",
      cpu_util: 0.15,
      mem_util: 0.18,
      cost_usd: 50.0,
      impact_usd: 25.0,
    },
  ],
  pvc_waste: [
    {
      name: "Disk/staging-pv-bloated",
      cost_usd: 25.0,
      bytes_provisioned: 100_000_000_000,
      bytes_used: 8_000_000_000,
      utilization: 0.08,
      impact_usd: 23.0,
    },
  ],
  anomalies: [],
  savings_signals: {},
  truncated: false,
  truncated_counts: {},
};
