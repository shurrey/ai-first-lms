"use client";

import { useEffect, useState } from "react";
import { apiJson } from "@/lib/api";
import type { AiAction, AiActionType } from "@/lib/types";

export interface AiActionQuery {
  course_id?: string;
  subject_person_id?: string;
  action_type?: AiActionType;
  limit?: number;
}

export function aiActionsPath(q: AiActionQuery): string {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(q)) if (v != null) params.set(k, String(v));
  return `/api/ai-actions?${params.toString()}`;
}

/** The badge recommendation behind a pending credential: by target row, else by person + microcredential. */
export function matchCredentialRecommendation(
  items: AiAction[], pending: { id: string; person_id: string; microcredential_id: string },
): string | null {
  const byTarget = items.find((a) => a.target_type === "pending_credentials" && a.target_id === pending.id);
  if (byTarget) return byTarget.id;
  const byCredential = items.find((a) =>
    a.subject_person_id === pending.person_id && a.output?.microcredential_id === pending.microcredential_id);
  return byCredential?.id ?? null;
}

/** Newest profile_update that wrote the insights list, else the newest profile_update. Items are newest first. */
export function matchInsightsUpdate(items: AiAction[]): string | null {
  const insights = items.find((a) => a.output && "insights" in a.output);
  return (insights ?? items[0])?.id ?? null;
}

/**
 * Loads GET /api/ai-actions for each query key (one request per distinct path).
 * Returns null while loading. A failed lookup leaves that key out of the map, so callers
 * fall back to an unlinked label; the error is logged.
 */
export function useAiActionLists(queries: AiActionQuery[] | null): Map<string, AiAction[]> | null {
  const key = queries ? Array.from(new Set(queries.map(aiActionsPath))).sort().join("\n") : null;
  const [lists, setLists] = useState<Map<string, AiAction[]> | null>(null);

  useEffect(() => {
    if (key === null) { setLists(null); return; }
    const paths = key ? key.split("\n") : [];
    let cancelled = false;
    Promise.all(paths.map((p) =>
      apiJson<{ items: AiAction[] }>(p, { reportForbidden: false })
        .then((d) => [p, d.items] as const)
        .catch((err: unknown) => {
          console.warn(`Provenance lookup failed for ${p}`, err);
          return null;
        }),
    )).then((results) => {
      if (cancelled) return;
      setLists(new Map(results.filter((r): r is readonly [string, AiAction[]] => r !== null)));
    });
    return () => { cancelled = true; };
  }, [key]);

  return lists;
}

/** The ai_action that wrote a learner's insights, or null when unknown or not readable. */
export function useInsightsActionId(personId: string | null, enabled: boolean): string | null {
  const query: AiActionQuery | null = personId && enabled
    ? { subject_person_id: personId, action_type: "profile_update", limit: 50 }
    : null;
  const lists = useAiActionLists(query ? [query] : null);
  const items = query ? lists?.get(aiActionsPath(query)) : undefined;
  return items ? matchInsightsUpdate(items) : null;
}
