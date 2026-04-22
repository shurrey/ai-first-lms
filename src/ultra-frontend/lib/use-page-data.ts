"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { fetchPageData } from "./api";
import { usePersona } from "./persona-context";

export function usePageData<T>(page: string, fallback: T): { data: T; loading: boolean } {
  const { persona } = usePersona();
  const params = useParams();
  const courseId = (params?.courseId as string) ?? "cs101";
  const [data, setData] = useState<T>(fallback);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetchPageData<T>(persona, courseId, page)
      .then((result) => setData(result))
      .catch(() => {}) // Keep fallback
      .finally(() => setLoading(false));
  }, [persona, courseId, page]);

  return { data, loading };
}
