#!/usr/bin/env bash
# Smoke test: verify every service in the compose stack responds healthy.
# Run after `docker compose up`.
set -euo pipefail

PASS=0
FAIL=0
TOTAL=0

check_http() {
  local name="$1"
  local url="$2"
  local expected_code="${3:-200}"
  TOTAL=$((TOTAL + 1))
  echo -n "  $name ($url)... "
  # Retry up to 5 times with 2s sleep
  for attempt in 1 2 3 4 5; do
    CODE=$(curl -s -o /dev/null -w "%{http_code}" "$url" 2>/dev/null || echo "000")
    if [ "$CODE" = "$expected_code" ]; then
      echo "OK (${CODE})"
      PASS=$((PASS + 1))
      return 0
    fi
    sleep 2
  done
  echo "FAIL (got ${CODE}, expected ${expected_code})"
  FAIL=$((FAIL + 1))
  return 1
}

check_pg() {
  TOTAL=$((TOTAL + 1))
  echo -n "  Postgres (pg_isready)... "
  if pg_isready -h "${POSTGRES_HOST:-localhost}" -p "${POSTGRES_PORT:-5432}" -U "${POSTGRES_USER:-lms}" > /dev/null 2>&1; then
    echo "OK"
    PASS=$((PASS + 1))
    return 0
  fi
  echo "FAIL"
  FAIL=$((FAIL + 1))
  return 1
}

echo "=== Smoke tests: all services ==="
echo ""

# Postgres
echo "Database:"
check_pg || true
echo ""

# MCP servers
echo "MCP servers:"
check_http "content"        "http://localhost:7001/healthz" || true
check_http "roster"         "http://localhost:7002/healthz" || true
check_http "assessments"    "http://localhost:7003/healthz" || true
check_http "analytics"      "http://localhost:7004/healthz" || true
check_http "sis"            "http://localhost:7005/healthz" || true
check_http "communications" "http://localhost:7006/healthz" || true
check_http "standards"      "http://localhost:7007/healthz" || true
echo ""

# Orchestrator
echo "Orchestrator:"
check_http "orchestrator"   "http://localhost:8000/healthz" || true
echo ""

# Frontend
echo "Frontend:"
check_http "frontend"       "http://localhost:3000/healthz" || true
echo ""

# Observability
echo "Observability:"
check_http "grafana"        "http://localhost:3001/api/health" || true
check_http "tempo"          "http://localhost:3200/status" || true
check_http "prometheus"     "http://localhost:9090/-/ready" || true
echo ""

# Summary
echo "=== Summary: ${PASS}/${TOTAL} passed, ${FAIL} failed ==="

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
