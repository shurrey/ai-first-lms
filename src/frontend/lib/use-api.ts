"use client";

import { useQuery } from "@tanstack/react-query";
import { ApiError, apiJson } from "./api";

/** GET `path` via apiJson; pass null to skip. `forbidden` is true on a 403. */
export function useApiGet<T>(path: string | null) {
  const query = useQuery({
    queryKey: ["api", path],
    queryFn: () => apiJson<T>(path as string),
    enabled: path !== null,
    retry: false,
  });
  return {
    data: query.data,
    loading: query.isLoading,
    error: query.error,
    forbidden: query.error instanceof ApiError && query.error.isForbidden,
    refetch: query.refetch,
  };
}
