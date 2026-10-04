"""Rubric criteria as rows (spec.md §7.2): backfill from v1 `rubrics.criteria` JSON.

`grades.scores` is derivable from criterion rows: `GRADE_SCORES_SQL` returns
`{criterion key: final_score}` for one submission, and a committed grade's `scores` equals it.
"""
from __future__ import annotations

import asyncpg

# Same namespace and name as engine.measurement.criterion_uuid, so a backfilled row keeps the
# id the measurement summary already reported for that (rubric, key).
CRITERION_NAMESPACE = "0b8f3c1e-6a2d-4e57-9a41-2f7d5c3e8b19"

# Idempotent: existing (rubric_id, key) rows are left alone. A v1 criterion
# {name, description, levels:[{label, points, description}]} becomes key = snake_case(name)
# and levels [{score, label, descriptor, points}], score 1..n by ascending points; a level
# that already carries an integer `score` keeps it.
BACKFILL_SQL = """
INSERT INTO rubric_criteria (id, rubric_id, key, description, levels)
SELECT uuid_generate_v5('0b8f3c1e-6a2d-4e57-9a41-2f7d5c3e8b19'::uuid,
                        'criterion:' || c.rubric_id::text || ':' || c.key),
       c.rubric_id, c.key, c.description, c.levels
FROM (
  SELECT DISTINCT ON (x.rubric_id, x.key) x.rubric_id, x.key, x.description, x.levels
  FROM (
    SELECT r.id AS rubric_id, t.io,
           COALESCE(
             NULLIF(lower(btrim(t.item->>'key')), ''),
             btrim(regexp_replace(lower(COALESCE(t.item->>'name', '')), '[^a-z0-9]+', '_', 'g'),
                   '_')
           ) AS key,
           COALESCE(NULLIF(t.item->>'description', ''), t.item->>'name', '') AS description,
           (SELECT COALESCE(jsonb_agg(jsonb_strip_nulls(jsonb_build_object(
                     'score', z.score, 'label', z.lv->>'label',
                     'descriptor', COALESCE(z.lv->>'descriptor', z.lv->>'description', ''),
                     'points', z.lv->'points')) ORDER BY z.score), '[]'::jsonb)
            FROM (
              SELECT l.lv,
                     CASE WHEN l.lv->>'score' ~ '^-?[0-9]+$' THEN (l.lv->>'score')::int
                          ELSE row_number() OVER (
                                 ORDER BY CASE WHEN l.lv->>'points' ~ '^-?[0-9]+([.][0-9]+)?$'
                                               THEN (l.lv->>'points')::numeric END
                                          NULLS LAST,
                                          l.lo DESC)::int
                     END AS score
              FROM jsonb_array_elements(
                     CASE WHEN jsonb_typeof(t.item->'levels') = 'array'
                          THEN t.item->'levels' ELSE '[]'::jsonb END
                   ) WITH ORDINALITY AS l(lv, lo)
              WHERE jsonb_typeof(l.lv) = 'object'
            ) z) AS levels
    FROM rubrics r
    CROSS JOIN LATERAL jsonb_array_elements(
      CASE WHEN jsonb_typeof(r.criteria) = 'array' THEN r.criteria ELSE '[]'::jsonb END
    ) WITH ORDINALITY AS t(item, io)
    WHERE jsonb_typeof(t.item) = 'object'
  ) x
  WHERE x.key <> ''
  ORDER BY x.rubric_id, x.key, x.io
) c
ON CONFLICT (rubric_id, key) DO NOTHING
"""

GRADE_SCORES_SQL = """
SELECT COALESCE(jsonb_object_agg(rc.key, cs.final_score ORDER BY rc.key), '{}'::jsonb)
FROM criterion_scores cs
JOIN rubric_criteria rc ON rc.id = cs.criterion_id
WHERE cs.submission_id = $1 AND cs.final_score IS NOT NULL
"""


async def backfill_rubric_criteria(conn: asyncpg.Connection) -> int:
    """Insert missing `rubric_criteria` rows for every rubric; returns how many were added."""
    status = await conn.execute(BACKFILL_SQL)
    return int(status.split()[-1])
