/** AWS regions the cluster can live in. v1 is AWS-only per CLAUDE.md. */
export const AWS_REGIONS: readonly { code: string; label: string }[] = [
  { code: "us-east-1", label: "us-east-1 — N. Virginia" },
  { code: "us-east-2", label: "us-east-2 — Ohio" },
  { code: "us-west-1", label: "us-west-1 — N. California" },
  { code: "us-west-2", label: "us-west-2 — Oregon" },
  { code: "ca-central-1", label: "ca-central-1 — Canada Central" },
  { code: "eu-central-1", label: "eu-central-1 — Frankfurt" },
  { code: "eu-west-1", label: "eu-west-1 — Ireland" },
  { code: "eu-west-2", label: "eu-west-2 — London" },
  { code: "eu-west-3", label: "eu-west-3 — Paris" },
  { code: "eu-north-1", label: "eu-north-1 — Stockholm" },
  { code: "ap-northeast-1", label: "ap-northeast-1 — Tokyo" },
  { code: "ap-northeast-2", label: "ap-northeast-2 — Seoul" },
  { code: "ap-southeast-1", label: "ap-southeast-1 — Singapore" },
  { code: "ap-southeast-2", label: "ap-southeast-2 — Sydney" },
  { code: "ap-south-1", label: "ap-south-1 — Mumbai" },
  { code: "sa-east-1", label: "sa-east-1 — São Paulo" },
] as const;
