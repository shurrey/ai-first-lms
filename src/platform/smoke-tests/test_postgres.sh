#!/usr/bin/env bash
# Smoke test: verify Postgres is up and the schema was applied.
set -euo pipefail

POSTGRES_USER="${POSTGRES_USER:-lms}"
POSTGRES_DB="${POSTGRES_DB:-lms_db}"
POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"

echo "=== Postgres smoke test ==="

# 1. Check connectivity
echo -n "Checking connectivity... "
if pg_isready -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" > /dev/null 2>&1; then
  echo "OK"
else
  echo "FAIL: Postgres not ready at ${POSTGRES_HOST}:${POSTGRES_PORT}"
  exit 1
fi

# 2. Check pgvector extension
echo -n "Checking pgvector extension... "
RESULT=$(PGPASSWORD="${POSTGRES_PASSWORD:-lms_dev}" psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT 1 FROM pg_extension WHERE extname='vector';" 2>/dev/null)
if [ "$RESULT" = "1" ]; then
  echo "OK"
else
  echo "FAIL: pgvector extension not installed"
  exit 1
fi

# 3. Check core tables exist
echo -n "Checking core tables... "
TABLES="nodes edges persons enrollments evidence attestations sessions turns events_log"
for table in $TABLES; do
  EXISTS=$(PGPASSWORD="${POSTGRES_PASSWORD:-lms_dev}" psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT 1 FROM information_schema.tables WHERE table_name='${table}';" 2>/dev/null)
  if [ "$EXISTS" != "1" ]; then
    echo "FAIL: table '${table}' not found"
    exit 1
  fi
done
echo "OK (${TABLES})"

# 4. Check LMS projection views
echo -n "Checking LMS views... "
VIEWS="courses modules assignments gradebook"
for view in $VIEWS; do
  EXISTS=$(PGPASSWORD="${POSTGRES_PASSWORD:-lms_dev}" psql -h "$POSTGRES_HOST" -p "$POSTGRES_PORT" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT 1 FROM information_schema.views WHERE table_name='${view}';" 2>/dev/null)
  if [ "$EXISTS" != "1" ]; then
    echo "FAIL: view '${view}' not found"
    exit 1
  fi
done
echo "OK (${VIEWS})"

echo "=== All Postgres smoke tests passed ==="
