FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    curl \
    jq \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app

# Copy tokio-core first (needed by requirements.txt)
COPY tokio-core /app/tokio-core

# Copy requirements and install
COPY tokio-cli/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy CLI service code
COPY tokio-cli/engine/ /app/engine/
COPY tokio-cli/api/ /app/api/
COPY tokio-cli/server.py /app/

# Create workspace directory
RUN mkdir -p /workspace/cli

# Set Python path
ENV PYTHONPATH=/app:/app/tokio-core:$PYTHONPATH

# Environment defaults
ENV TOKIO_WORKSPACE=/workspace/cli
ENV LOG_LEVEL=INFO
ENV PORT=8100

# Interactive terminal
ENV TERM=xterm-256color

# Expose ports
EXPOSE 8100 8101

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8100/health || exit 1

# Run FastAPI server
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8100", "--log-level", "info"]
