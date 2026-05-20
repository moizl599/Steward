"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Eye, EyeOff } from "lucide-react";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Input } from "@/components/ui/input";
import { ApiError, type Environment, api, type ConnectionTestResult } from "@/lib/api";
import { AWS_REGIONS } from "@/lib/aws-regions";
import { cn, formatLatency } from "@/lib/utils";

const FormSchema = z.object({
  name: z
    .string()
    .min(1, "Name is required")
    .max(255, "Max 255 characters"),
  kubecost_url: z.string().url("Must be a valid URL"),
  aws_region: z.string().min(1, "Choose a region"),
  cluster_name: z.string().max(255),
  auth_token: z.string().max(2048),
});

type FormValues = z.infer<typeof FormSchema>;

export default function NewEnvironmentPage() {
  const router = useRouter();
  const [showToken, setShowToken] = useState(false);
  const [bannerError, setBannerError] = useState<string | null>(null);
  const [connectionResult, setConnectionResult] =
    useState<ConnectionTestResult | null>(null);

  const form = useForm<FormValues>({
    resolver: zodResolver(FormSchema),
    defaultValues: {
      name: "",
      kubecost_url: "",
      aws_region: "us-east-1",
      cluster_name: "",
      auth_token: "",
    },
  });

  const submit = useMutation({
    mutationFn: async (values: FormValues): Promise<Environment> => {
      const env = await api.createEnvironment({
        name: values.name,
        kubecost_url: values.kubecost_url,
        aws_region: values.aws_region,
        cluster_name: values.cluster_name || undefined,
        auth_token: values.auth_token || undefined,
      });
      const result = await api.testConnection(env.id);
      setConnectionResult(result);
      return env;
    },
    onSuccess: (env) => {
      // Hold for a beat so the user sees the green/red status before redirect.
      setTimeout(() => router.push(`/`), 1200);
      void env;
    },
    onError: (err: unknown) => {
      if (err instanceof ApiError) {
        if (err.isValidation) {
          for (const [field, msgs] of Object.entries(err.fieldErrors)) {
            const knownField = field as keyof FormValues;
            if (knownField in form.getValues()) {
              form.setError(knownField, { message: msgs[0] });
            }
          }
          return;
        }
      }
      setBannerError(err instanceof Error ? err.message : "Unexpected error");
    },
  });

  const onSubmit = (values: FormValues) => {
    setBannerError(null);
    setConnectionResult(null);
    submit.mutate(values);
  };

  return (
    <div className="mx-auto max-w-2xl px-8 py-12">
      <p className="font-mono text-xs uppercase tracking-widest text-[var(--color-muted-foreground)]">
        Onboarding
      </p>
      <h1 className="mt-2 font-display text-3xl font-bold tracking-tight">
        Connect Kubecost
      </h1>
      <p className="mt-3 text-sm text-[var(--color-muted-foreground)]">
        Add an EKS cluster running Kubecost. We&apos;ll verify the connection and
        store the auth token encrypted at rest.
      </p>

      {bannerError ? (
        <div
          role="alert"
          className="mt-6 rounded border border-[var(--color-destructive)]/50 bg-[var(--color-destructive)]/10 px-3 py-2 text-sm text-[var(--color-destructive)]"
        >
          {bannerError}
        </div>
      ) : null}

      <Form {...form}>
        <form onSubmit={form.handleSubmit(onSubmit)} className="mt-8 space-y-6">
          <FormField
            control={form.control}
            name="name"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Name</FormLabel>
                <FormControl>
                  <Input
                    placeholder="prod-eks (acme)"
                    autoComplete="off"
                    {...field}
                  />
                </FormControl>
                <FormDescription>
                  Display name used throughout the UI. Must be unique.
                </FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />

          <FormField
            control={form.control}
            name="kubecost_url"
            render={({ field }) => (
              <FormItem>
                <FormLabel>Kubecost URL</FormLabel>
                <FormControl>
                  <Input
                    placeholder="http://kubecost.acme.internal:9090"
                    inputMode="url"
                    autoComplete="off"
                    {...field}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          <div className="grid gap-6 md:grid-cols-2">
            <FormField
              control={form.control}
              name="aws_region"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>AWS region</FormLabel>
                  <FormControl>
                    <select
                      {...field}
                      className="flex h-9 w-full rounded-md border border-[var(--color-input)] bg-transparent px-3 py-1 font-mono text-sm shadow-xs outline-none transition-colors file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-sm file:font-medium focus-visible:border-[var(--color-ring)] focus-visible:ring-[3px] focus-visible:ring-[var(--color-ring)]/50 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {AWS_REGIONS.map((r) => (
                        <option key={r.code} value={r.code}>
                          {r.label}
                        </option>
                      ))}
                    </select>
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="cluster_name"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>
                    Cluster name{" "}
                    <span className="text-[var(--color-muted-foreground)]">
                      (optional)
                    </span>
                  </FormLabel>
                  <FormControl>
                    <Input placeholder="prod-eks" autoComplete="off" {...field} />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />
          </div>

          <FormField
            control={form.control}
            name="auth_token"
            render={({ field }) => (
              <FormItem>
                <FormLabel>
                  Auth token{" "}
                  <span className="text-[var(--color-muted-foreground)]">
                    (optional)
                  </span>
                </FormLabel>
                <FormControl>
                  <div className="relative">
                    <Input
                      type={showToken ? "text" : "password"}
                      placeholder="Bearer token if Kubecost is gated"
                      autoComplete="off"
                      className="pr-10 font-mono"
                      {...field}
                    />
                    <button
                      type="button"
                      onClick={() => setShowToken((v) => !v)}
                      className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--color-muted-foreground)] hover:text-[var(--color-foreground)]"
                      aria-label={showToken ? "Hide token" : "Show token"}
                    >
                      {showToken ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                    </button>
                  </div>
                </FormControl>
                <FormDescription>
                  Stored encrypted at rest. Leave blank for unauthenticated
                  Kubecost.
                </FormDescription>
                <FormMessage />
              </FormItem>
            )}
          />

          {connectionResult ? <ConnectionPill result={connectionResult} /> : null}

          <div className="flex items-center justify-between border-t border-[var(--color-border)] pt-6">
            <Button
              type="button"
              variant="ghost"
              onClick={() => router.push("/")}
              disabled={submit.isPending}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={submit.isPending}>
              {submit.isPending ? "Connecting…" : "Add environment"}
            </Button>
          </div>
        </form>
      </Form>
    </div>
  );
}

function ConnectionPill({ result }: { result: ConnectionTestResult }) {
  return (
    <div
      role="status"
      data-testid="connection-result"
      className={cn(
        "flex items-center gap-3 rounded border px-3 py-2 text-sm",
        result.ok
          ? "border-[var(--color-savings)]/40 bg-[var(--color-savings)]/10"
          : "border-[var(--color-destructive)]/40 bg-[var(--color-destructive)]/10",
      )}
    >
      <span
        className={cn(
          "size-2 rounded-full",
          result.ok ? "bg-[var(--color-savings)]" : "bg-[var(--color-destructive)]",
        )}
        aria-hidden
      />
      <span className="flex-1 font-medium">
        {result.ok
          ? `Connected${result.kubecost_version ? ` — Kubecost ${result.kubecost_version}` : ""}`
          : `Connection failed: ${result.message}`}
      </span>
      {result.latency_ms != null ? (
        <span className="font-mono text-xs text-[var(--color-muted-foreground)]">
          {formatLatency(result.latency_ms)}
        </span>
      ) : null}
    </div>
  );
}
