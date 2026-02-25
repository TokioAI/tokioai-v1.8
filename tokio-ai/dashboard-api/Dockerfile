FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy dashboard code
COPY . .

# Copy tokio-core for v3.0 CLI integration (optional, mounted as volume in docker-compose)
# COPY ../../tokio-core /app/tokio-core/ 2>/dev/null || echo "tokio-core not found, skipping"

# Create data directory for alerts and events
RUN mkdir -p /data

# Expose port (Cloud Run uses 8080)
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8080}/health || exit 1

# Use PORT from Cloud Run or 8080 by default
CMD ["sh", "-c", "PORT=${PORT:-8080} && uvicorn app:app --host 0.0.0.0 --port $PORT"]
