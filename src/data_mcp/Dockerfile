FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

# Copy data_mcp source
COPY src/data_mcp/ /app/data_mcp/

ENV PYTHONPATH=/app

# Default; overridden per-container via docker-compose command
CMD ["python", "-m", "data_mcp.mcp_servers.content.server"]
