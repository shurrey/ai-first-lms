FROM python:3.12-slim

WORKDIR /app

# Install build deps for asyncpg etc.
RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

# Copy engine source
COPY src/engine/ /app/engine/

# Copy contracts (needed for manifest loading)
COPY contracts/ /app/contracts/

# Copy agents source (engine imports agent manifests)
COPY src/agents/ /app/agents/

ENV PYTHONPATH=/app
EXPOSE 8000

CMD ["uvicorn", "engine.__main__:app", "--host", "0.0.0.0", "--port", "8000"]
