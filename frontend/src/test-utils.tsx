import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderOptions } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 0, gcTime: 0 },
      mutations: { retry: false },
    },
  });
}

export function withQueryClient(client: QueryClient = makeQueryClient()) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

export function renderWithQuery(
  ui: ReactElement,
  options?: { client?: QueryClient } & Omit<RenderOptions, "wrapper">,
) {
  const client = options?.client ?? makeQueryClient();
  return {
    client,
    ...render(ui, { wrapper: withQueryClient(client), ...options }),
  };
}
