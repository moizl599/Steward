import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { renderWithQuery } from "@/test-utils";

import SettingsPage from "./page";

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SettingsPage", () => {
  it("renders all three sections from mock data", async () => {
    vi.spyOn(api, "listOllamaModels").mockResolvedValue([
      {
        name: "qwen2.5:7b-instruct",
        size_bytes: 4_700_000_000,
        family: "qwen2",
        parameter_size: "7B",
        modified_at: "2026-04-30T15:00:00Z",
        is_default: true,
      },
    ]);
    vi.spyOn(api, "getPromptTemplate").mockResolvedValue({
      name: "system",
      content: "# Kubernetes FinOps Analyst\n\nYou are a senior SRE.",
      path: "/app/app/prompts/system.md",
    });
    vi.spyOn(api, "listRagDocuments").mockResolvedValue([
      { source_file: "k8s-rightsizing.md", chunk_count: 4 },
    ]);

    renderWithQuery(<SettingsPage />);

    expect(await screen.findByText("qwen2.5:7b-instruct")).toBeInTheDocument();
    expect(screen.getByText("default")).toBeInTheDocument();
    expect(screen.getByText("4.4 GB")).toBeInTheDocument();
    expect(await screen.findByTestId("prompt-pre")).toHaveTextContent(
      /Kubernetes FinOps Analyst/,
    );
    expect(await screen.findByText("k8s-rightsizing.md")).toBeInTheDocument();
  });

  it("does not render write-flow stub buttons (Pull/Edit/Re-ingest)", async () => {
    vi.spyOn(api, "listOllamaModels").mockResolvedValue([]);
    vi.spyOn(api, "getPromptTemplate").mockResolvedValue({
      name: "system",
      content: "...",
      path: "/x",
    });
    vi.spyOn(api, "listRagDocuments").mockResolvedValue([]);

    renderWithQuery(<SettingsPage />);

    await screen.findByText(/Read-only view for v1/);
    expect(screen.queryByTestId("ollama-pull-button")).not.toBeInTheDocument();
    expect(screen.queryByTestId("prompt-edit-button")).not.toBeInTheDocument();
    expect(screen.queryByTestId("rag-reingest-button")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /pull new model/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^edit$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /re-ingest/i })).not.toBeInTheDocument();
  });

  it("instructs users to edit backing files and restart, not via a UI button", async () => {
    vi.spyOn(api, "listOllamaModels").mockResolvedValue([]);
    vi.spyOn(api, "getPromptTemplate").mockResolvedValue({
      name: "system",
      content: "...",
      path: "/x",
    });
    vi.spyOn(api, "listRagDocuments").mockResolvedValue([]);

    renderWithQuery(<SettingsPage />);
    expect(
      await screen.findByText(/edit the backing files and restart the backend container/i),
    ).toBeInTheDocument();
  });

  it("renders empty-row hint when no models are pulled", async () => {
    vi.spyOn(api, "listOllamaModels").mockResolvedValue([]);
    vi.spyOn(api, "getPromptTemplate").mockResolvedValue({
      name: "system",
      content: "x",
      path: "/p",
    });
    vi.spyOn(api, "listRagDocuments").mockResolvedValue([]);

    renderWithQuery(<SettingsPage />);
    expect(
      await screen.findByText(/docker compose exec ollama ollama pull qwen2\.5:7b-instruct/),
    ).toBeInTheDocument();
    expect(await screen.findByText(/Corpus is empty/)).toBeInTheDocument();
  });
});
