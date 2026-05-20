"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  LayoutDashboard,
  Server,
  Settings as SettingsIcon,
  FileText,
} from "lucide-react";

import { api } from "@/lib/api";

const NAV = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/environments", label: "Environments", icon: Server },
  { href: "/reports", label: "Reports", icon: FileText },
  { href: "/settings", label: "Settings", icon: SettingsIcon },
] as const;

function isActiveStatus(status: string | undefined): boolean {
  return status === "queued" || status === "running";
}

export function Sidebar() {
  const envs = useQuery({
    queryKey: ["environments"],
    queryFn: () => api.listEnvironments(),
    refetchInterval: (query) => {
      const data = query.state.data ?? [];
      const anyActive = data.some((e) => isActiveStatus(e.latest_scan?.status));
      return anyActive ? 5_000 : false;
    },
  });

  const activeScanCount = (envs.data ?? []).filter((e) =>
    isActiveStatus(e.latest_scan?.status),
  ).length;

  return (
    <aside className="w-56 shrink-0 border-r border-[var(--color-border)] bg-[var(--color-card)]">
      <div className="flex h-14 items-center gap-2 border-b border-[var(--color-border)] px-4">
        <div className="size-6 rounded bg-[var(--color-savings)]" aria-hidden />
        <span className="font-mono text-sm font-semibold tracking-tight">steward</span>
      </div>
      <nav className="flex flex-col gap-0.5 p-2">
        {NAV.map(({ href, label, icon: Icon }) => (
          <Link
            key={href}
            href={href}
            className="flex items-center gap-2.5 rounded px-2.5 py-1.5 text-sm text-[var(--color-muted-foreground)] hover:bg-[var(--color-accent)] hover:text-[var(--color-foreground)]"
          >
            <Icon className="size-4" />
            {label}
            {href === "/reports" && activeScanCount > 0 ? (
              <span
                className="ml-auto inline-flex items-center gap-1"
                data-testid="sidebar-active-scans"
                aria-label={`${activeScanCount} scan${activeScanCount === 1 ? "" : "s"} in progress`}
              >
                <span
                  className="size-1.5 animate-pulse rounded-full bg-[var(--color-warn)]"
                  aria-hidden
                />
                <span className="font-mono text-[10px] tabular-nums text-[var(--color-foreground)]">
                  {activeScanCount}
                </span>
              </span>
            ) : null}
          </Link>
        ))}
      </nav>
    </aside>
  );
}
