"use client";

import { useQuery } from "@tanstack/react-query";
import { CircleAlert } from "lucide-react";

import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api } from "@/lib/api";
import { formatDateTime } from "@/lib/utils";

export default function SettingsPage() {
  return (
    <div className="mx-auto max-w-5xl px-8 py-12">
      <div className="border-b border-[var(--color-border)] pb-6">
        <p className="font-mono text-xs uppercase tracking-widest text-[var(--color-muted-foreground)]">
          Configuration
        </p>
        <h1 className="mt-2 font-display text-3xl font-bold tracking-tight">
          Settings
        </h1>
        <p className="mt-2 text-sm text-[var(--color-muted-foreground)]">
          Read-only view for v1. To modify these resources, edit the backing
          files and restart the backend container.
        </p>
      </div>

      <OllamaSection />
      <PromptSection />
      <RagSection />
    </div>
  );
}

function OllamaSection() {
  const models = useQuery({
    queryKey: ["settings", "ollama-models"],
    queryFn: () => api.listOllamaModels(),
  });

  return (
    <Section
      eyebrow="Ollama"
      title="Local models"
      description="Models pulled on the local Ollama daemon. The default is what new scans will use."
    >
      {models.isLoading ? (
        <Skeleton className="h-24 w-full" />
      ) : models.isError ? (
        <ErrorRow message={(models.error as Error).message} />
      ) : models.data && models.data.length > 0 ? (
        <div className="overflow-hidden rounded-md border border-[var(--color-border)]">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Name</TableHead>
                <TableHead>Family</TableHead>
                <TableHead>Params</TableHead>
                <TableHead className="text-right">Size</TableHead>
                <TableHead>Modified</TableHead>
                <TableHead></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {models.data.map((m) => (
                <TableRow key={m.name}>
                  <TableCell className="font-mono text-sm">{m.name}</TableCell>
                  <TableCell className="font-mono text-xs text-[var(--color-muted-foreground)]">
                    {m.family ?? "—"}
                  </TableCell>
                  <TableCell className="font-mono text-xs text-[var(--color-muted-foreground)]">
                    {m.parameter_size ?? "—"}
                  </TableCell>
                  <TableCell className="text-right font-mono text-xs tabular-nums">
                    {m.size_bytes != null ? formatBytes(m.size_bytes) : "—"}
                  </TableCell>
                  <TableCell className="font-mono text-xs text-[var(--color-muted-foreground)]">
                    {m.modified_at ? formatDateTime(m.modified_at) : "—"}
                  </TableCell>
                  <TableCell className="text-right">
                    {m.is_default ? (
                      <span className="rounded border border-[var(--color-savings)]/40 bg-[var(--color-savings)]/10 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-[var(--color-savings)]">
                        default
                      </span>
                    ) : null}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      ) : (
        <EmptyRow message="No models pulled yet — run `docker compose exec ollama ollama pull qwen2.5:7b-instruct`." />
      )}
    </Section>
  );
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let v = bytes;
  let unit = -1;
  do {
    v /= 1024;
    unit++;
  } while (v >= 1024 && unit < units.length - 1);
  return `${v.toFixed(1)} ${units[unit]}`;
}

function PromptSection() {
  const tpl = useQuery({
    queryKey: ["settings", "prompt-template"],
    queryFn: () => api.getPromptTemplate(),
  });

  return (
    <Section
      eyebrow="Prompt"
      title="System prompt template"
      description="The persona + constraints fed to every LLM call. Treat as load-bearing — edits should be reviewed."
    >
      {tpl.isLoading ? (
        <Skeleton className="h-48 w-full" />
      ) : tpl.isError ? (
        <ErrorRow message={(tpl.error as Error).message} />
      ) : tpl.data ? (
        <div>
          <p className="mb-2 font-mono text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)]">
            {tpl.data.path}
          </p>
          <pre
            data-testid="prompt-pre"
            className="max-h-96 overflow-auto rounded-md border border-[var(--color-border)] bg-[var(--color-background)] p-4 font-mono text-xs leading-relaxed text-[var(--color-foreground)]/90"
          >
            {tpl.data.content}
          </pre>
        </div>
      ) : null}
    </Section>
  );
}

function RagSection() {
  const docs = useQuery({
    queryKey: ["settings", "rag-documents"],
    queryFn: () => api.listRagDocuments(),
  });

  return (
    <Section
      eyebrow="Knowledge base"
      title="RAG corpus"
      description="FinOps reference material indexed in ChromaDB. Each scan retrieves a few snippets per finding category."
    >
      {docs.isLoading ? (
        <Skeleton className="h-24 w-full" />
      ) : docs.isError ? (
        <ErrorRow message={(docs.error as Error).message} />
      ) : docs.data && docs.data.length > 0 ? (
        <div className="overflow-hidden rounded-md border border-[var(--color-border)]">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Source file</TableHead>
                <TableHead className="text-right">Chunks</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {docs.data.map((d) => (
                <TableRow key={d.source_file}>
                  <TableCell className="font-mono text-sm">{d.source_file}</TableCell>
                  <TableCell className="text-right font-mono text-xs tabular-nums">
                    {d.chunk_count}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      ) : (
        <EmptyRow message="Corpus is empty — drop markdown files into infra/chromadb/seed/ and restart the backend." />
      )}
    </Section>
  );
}

function Section({
  eyebrow,
  title,
  description,
  children,
}: {
  eyebrow: string;
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mt-12">
      <div className="border-b border-[var(--color-border)] pb-4">
        <p className="font-mono text-[10px] uppercase tracking-widest text-[var(--color-muted-foreground)]">
          {eyebrow}
        </p>
        <h2 className="mt-1 font-display text-xl font-bold tracking-tight">
          {title}
        </h2>
        <p className="mt-1 max-w-prose text-sm text-[var(--color-muted-foreground)]">
          {description}
        </p>
      </div>
      <div className="mt-4">{children}</div>
    </section>
  );
}

function ErrorRow({ message }: { message: string }) {
  return (
    <div className="flex items-center gap-2 rounded border border-[var(--color-destructive)]/40 bg-[var(--color-destructive)]/10 px-3 py-2 text-sm text-[var(--color-destructive)]">
      <CircleAlert className="size-4" />
      {message}
    </div>
  );
}

function EmptyRow({ message }: { message: string }) {
  return (
    <div className="rounded border border-dashed border-[var(--color-border)] bg-[var(--color-card)]/40 px-4 py-6 text-center text-sm text-[var(--color-muted-foreground)]">
      {message}
    </div>
  );
}
