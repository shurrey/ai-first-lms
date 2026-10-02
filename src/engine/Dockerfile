FROM python:3.12-slim

WORKDIR /app

# gcc/libpq-dev for asyncpg; ca-certificates for update-ca-certificates below.
RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Optional corporate TLS-inspection root CA, passed as the BuildKit secret "corporate_ca"
# (compose wires it from CORPORATE_CA_PATH; see docs/setup.md). Absent or empty means none.
# Runs before pip install so dependency downloads also trust it. Secret contents are not part
# of the build cache key; the path ARG is, so changing it rebuilds this layer.
ARG CORPORATE_CA_PATH=""
RUN --mount=type=secret,id=corporate_ca,required=false \
    echo "corporate CA: ${CORPORATE_CA_PATH:-none}"; \
    if [ -s /run/secrets/corporate_ca ]; then \
      grep -q "BEGIN CERTIFICATE" /run/secrets/corporate_ca || \
        { echo "corporate_ca secret is not a PEM certificate" >&2; exit 1; }; \
      cp /run/secrets/corporate_ca /usr/local/share/ca-certificates/corporate-root.crt && \
      update-ca-certificates; \
    fi
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

# Install the exact versions pinned in uv.lock, so images match local runs and CI.
# Sources are on PYTHONPATH, so the project itself is not installed.
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv && \
    uv export --frozen --no-emit-project --no-hashes -o /tmp/requirements.txt && \
    pip install --no-cache-dir -r /tmp/requirements.txt && \
    pip uninstall -y uv && rm /tmp/requirements.txt

# Shared helpers (HTTP client factory) used by engine and data_mcp
COPY src/common/ /app/common/

# Copy engine source
COPY src/engine/ /app/engine/

# Copy contracts (needed for manifest loading)
COPY contracts/ /app/contracts/

# Copy agents source (engine imports agent manifests)
COPY src/agents/ /app/agents/

ENV PYTHONPATH=/app
EXPOSE 8000

CMD ["uvicorn", "engine.__main__:app", "--host", "0.0.0.0", "--port", "8000"]
