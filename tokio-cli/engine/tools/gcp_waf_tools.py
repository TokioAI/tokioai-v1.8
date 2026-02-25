"""
GCP WAF Deploy/Destroy Tool — Full Stack Plug & Play
=====================================================

Usa Google Cloud Python SDK (no requiere terraform ni gcloud CLI).
Solo necesita: GCP_PROJECT_ID + GCP_SA_KEY_JSON (service account key).

Despliega stack completo en GCP:
  ModSecurity/Nginx, Kafka, Zookeeper, PostgreSQL,
  Dashboard, Realtime Processor, Log Processor, Cloudflare Tunnel

La Raspberry Pi NUNCA descarga logs — consulta GCP PostgreSQL remotamente.

Actions:
  setup    — Verifica prerrequisitos y guía al usuario
  deploy   — Deploy stack completo en GCP
  destroy  — Destruir infra GCP, restaurar DNS
  status   — Ver estado del deployment
  query    — Consulta remota a PostgreSQL GCP (read-only)
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import shutil
import uuid
import re
import time as _time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
_GCP_PROJECT = os.getenv("GCP_PROJECT_ID", "").strip()
_GCP_REGION = os.getenv("GCP_REGION", "us-central1").strip()
_GCP_ZONE = os.getenv("GCP_ZONE", "us-central1-a").strip()
_GCP_MACHINE_TYPE = os.getenv("GCP_MACHINE_TYPE", "e2-medium").strip()
_GCP_SA_KEY_PATH = os.getenv("GCP_SA_KEY_JSON", "").strip()

_STATE_FILE = Path(os.getenv("TOKIO_GCP_STATE", "/workspace/cli/gcp-waf-state.json"))

_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
_OWNER_CHAT_ID = os.getenv("TELEGRAM_OWNER_ID", "").strip()

_HOSTINGER_API_KEY = os.getenv("HOSTINGER_API_KEY", "").strip()
_CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
_CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
_CLOUDFLARED_TUNNEL_TOKEN = os.getenv("CLOUDFLARED_TUNNEL_TOKEN", "").strip()

_DASHBOARD_USER = os.getenv("DASHBOARD_USERNAME", "admin")
_DASHBOARD_PASS = os.getenv("DASHBOARD_PASSWORD_HASH", "admin123")
_PG_USER = os.getenv("GCP_POSTGRES_USER", "soc_user")
_PG_PASS = os.getenv("GCP_POSTGRES_PASSWORD", "changeme_gcp_2026")
_PG_DB = os.getenv("GCP_POSTGRES_DB", "soc_ai")

_GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
_LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _notify(msg: str) -> None:
    if not _BOT_TOKEN or not _OWNER_CHAT_ID:
        return
    try:
        import requests
        requests.post(
            f"https://api.telegram.org/bot{_BOT_TOKEN}/sendMessage",
            json={"chat_id": _OWNER_CHAT_ID, "text": msg, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception:
        pass


def _load_state() -> Dict[str, Any]:
    try:
        if _STATE_FILE.exists():
            return json.loads(_STATE_FILE.read_text())
    except Exception:
        pass
    return {"deployments": {}}


def _save_state(state: Dict[str, Any]) -> None:
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def _get_compute_client():
    """Get Google Cloud Compute client using service account or default creds."""
    try:
        from google.cloud import compute_v1
        from google.oauth2 import service_account

        if _GCP_SA_KEY_PATH and os.path.exists(_GCP_SA_KEY_PATH):
            creds = service_account.Credentials.from_service_account_file(
                _GCP_SA_KEY_PATH,
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
            return compute_v1, creds
        else:
            # Try default credentials (GOOGLE_APPLICATION_CREDENTIALS env)
            return compute_v1, None
    except ImportError:
        return None, None


def _wait_for_operation(compute_v1, creds, project: str, zone: str, operation_name: str, timeout: int = 300):
    """Wait for a GCP zone operation to complete."""
    client = compute_v1.ZoneOperationsClient(credentials=creds) if creds else compute_v1.ZoneOperationsClient()
    start = _time.time()
    while _time.time() - start < timeout:
        op = client.get(project=project, zone=zone, operation=operation_name)
        if op.status == compute_v1.Operation.Status.DONE:
            if op.error:
                errors = [e.message for e in op.error.errors]
                raise RuntimeError(f"Operation failed: {'; '.join(errors)}")
            return op
        _time.sleep(3)
    raise TimeoutError(f"Operation {operation_name} timed out after {timeout}s")


def _wait_for_region_op(compute_v1, creds, project: str, region: str, operation_name: str, timeout: int = 120):
    """Wait for a GCP region operation to complete."""
    client = compute_v1.RegionOperationsClient(credentials=creds) if creds else compute_v1.RegionOperationsClient()
    start = _time.time()
    while _time.time() - start < timeout:
        op = client.get(project=project, region=region, operation=operation_name)
        if op.status == compute_v1.Operation.Status.DONE:
            if op.error:
                errors = [e.message for e in op.error.errors]
                raise RuntimeError(f"Region op failed: {'; '.join(errors)}")
            return op
        _time.sleep(3)
    raise TimeoutError(f"Region operation timed out after {timeout}s")


def _wait_for_global_op(compute_v1, creds, project: str, operation_name: str, timeout: int = 120):
    """Wait for a GCP global operation to complete."""
    client = compute_v1.GlobalOperationsClient(credentials=creds) if creds else compute_v1.GlobalOperationsClient()
    start = _time.time()
    while _time.time() - start < timeout:
        op = client.get(project=project, operation=operation_name)
        if op.status == compute_v1.Operation.Status.DONE:
            if op.error:
                errors = [e.message for e in op.error.errors]
                raise RuntimeError(f"Global op failed: {'; '.join(errors)}")
            return op
        _time.sleep(3)
    raise TimeoutError(f"Global operation timed out after {timeout}s")


# ---------------------------------------------------------------------------
# VM Startup Script (installs Docker, runs full stack)
# ---------------------------------------------------------------------------

def _startup_script(domain: str, backend_url: str) -> str:
    """Startup script that Docker-composes the full WAF stack inside the VM."""
    compose_content = _docker_compose_yaml(domain, backend_url)
    init_sql = _init_db_sql()
    nginx_logging = _nginx_logging_conf()
    nginx_site = _nginx_site_conf(domain, backend_url)
    log_proc = _log_processor_py()
    rt_proc = _realtime_processor_py()
    dash_app = _dashboard_app_py()
    dash_db = _dashboard_db_py()

    # Escape single quotes for embedding in bash heredoc
    def esc(s):
        return s.replace("'", "'\"'\"'")

    return f'''#!/bin/bash
set -e
exec > /var/log/tokio-startup.log 2>&1
echo "=== TokioAI WAF Startup — $(date) ==="

# Install Docker
if ! command -v docker &>/dev/null; then
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker && systemctl start docker
fi

# Install docker-compose v2
if ! docker compose version &>/dev/null; then
    apt-get update && apt-get install -y docker-compose-plugin
fi

mkdir -p /opt/tokio-waf && cd /opt/tokio-waf

# Write docker-compose.yml
cat > docker-compose.yml << 'COMPOSEEOF'
{compose_content}
COMPOSEEOF

# Write init SQL
cat > init-db.sql << 'SQLEOF'
{init_sql}
SQLEOF

# Write nginx configs
cat > nginx-logging.conf << 'NLOGEOF'
{nginx_logging}
NLOGEOF

cat > nginx-site.conf << 'NSITEEOF'
{nginx_site}
NSITEEOF

# Write log-processor.py
cat > log-processor.py << 'LPEOF'
{log_proc}
LPEOF

# Write realtime-processor.py
cat > realtime-processor.py << 'RPEOF'
{rt_proc}
RPEOF

# Write minimal dashboard app
cat > dashboard-app.py << 'DASHEOF'
{dash_app}
DASHEOF

# Write dashboard db helper
cat > dashboard-db.py << 'DBEOF'
{dash_db}
DBEOF

echo "=== Starting base stack (without SSL) ==="
# Remove SSL server block temporarily for initial start (no certs yet)
sed -i '/listen 443 ssl/,/^}}/d' /opt/tokio-waf/nginx-site.conf

docker compose up -d || docker-compose up -d

# Wait for nginx to be ready
sleep 10

echo "=== Obtaining SSL certificate ==="
apt-get update && apt-get install -y certbot
certbot certonly --standalone -d {domain} --non-interactive --agree-tos -m admin@{domain} --http-01-port 9080 || true

# If certbot standalone fails, try webroot
if [ ! -f /etc/letsencrypt/live/{domain}/fullchain.pem ]; then
    docker compose stop waf-proxy || true
    certbot certonly --standalone -d {domain} --non-interactive --agree-tos -m admin@{domain} || true
fi

# Copy certs to docker volume
if [ -f /etc/letsencrypt/live/{domain}/fullchain.pem ]; then
    CERT_VOL=$(docker volume inspect tokio-waf_letsencrypt --format '{{{{.Mountpoint}}}}')
    mkdir -p "$CERT_VOL/live/{domain}"
    cp /etc/letsencrypt/live/{domain}/fullchain.pem "$CERT_VOL/live/{domain}/"
    cp /etc/letsencrypt/live/{domain}/privkey.pem "$CERT_VOL/live/{domain}/"
    chmod 644 "$CERT_VOL/live/{domain}/"*

    # Restore SSL config
    cat >> /opt/tokio-waf/nginx-site.conf << 'SSLEOF'

server {{
    listen 443 ssl;
    server_name {domain} www.{domain};
    server_tokens off;
    ssl_certificate /etc/letsencrypt/live/{domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{domain}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    access_log /var/log/nginx/waf-access.log waf_json;
    error_log /var/log/nginx/error.log warn;
    location /health {{ access_log off; return 200 "ok\\n"; add_header Content-Type text/plain; }}
    location / {{
        proxy_pass {backend_url};
        proxy_set_header Host {domain};
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_ssl_verify off;
        proxy_ssl_server_name on;
        proxy_ssl_name {domain};
    }}
}}
SSLEOF
    echo "SSL certificate obtained and configured!"
else
    echo "WARNING: Could not obtain SSL certificate"
fi

# Restart with SSL config
docker compose restart waf-proxy || docker-compose restart waf-proxy

# Certbot auto-renewal cron
echo "0 3 * * * certbot renew --quiet && docker compose -f /opt/tokio-waf/docker-compose.yml restart waf-proxy" | crontab -

echo "=== TokioAI WAF Startup Complete — $(date) ==="
'''


def _docker_compose_yaml(domain: str, backend_url: str) -> str:
    return f'''version: '3.9'
services:
  postgres:
    image: postgres:15-alpine
    container_name: tokio-gcp-postgres
    environment:
      POSTGRES_DB: {_PG_DB}
      POSTGRES_USER: {_PG_USER}
      POSTGRES_PASSWORD: {_PG_PASS}
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./init-db.sql:/docker-entrypoint-initdb.d/001_init.sql:ro
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U {_PG_USER}"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  zookeeper:
    image: confluentinc/cp-zookeeper:7.5.0
    container_name: tokio-gcp-zookeeper
    environment:
      ZOOKEEPER_CLIENT_PORT: 2181
      ZOOKEEPER_TICK_TIME: 2000
    restart: unless-stopped

  kafka:
    image: confluentinc/cp-kafka:7.5.0
    container_name: tokio-gcp-kafka
    depends_on: [zookeeper]
    environment:
      KAFKA_BROKER_ID: 1
      KAFKA_ZOOKEEPER_CONNECT: zookeeper:2181
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://kafka:9092
      KAFKA_LISTENER_SECURITY_PROTOCOL_MAP: PLAINTEXT:PLAINTEXT
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
      KAFKA_AUTO_CREATE_TOPICS_ENABLE: "true"
    restart: unless-stopped

  waf-proxy:
    image: nginx:alpine
    container_name: tokio-gcp-waf-proxy
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - modsec_logs:/var/log/nginx
      - ./nginx-logging.conf:/etc/nginx/conf.d/00-logging.conf:ro
      - ./nginx-site.conf:/etc/nginx/conf.d/default.conf:ro
      - letsencrypt:/etc/letsencrypt:ro
    depends_on: [kafka]
    restart: unless-stopped

  log-processor:
    image: python:3.11-slim
    container_name: tokio-gcp-log-processor
    volumes:
      - modsec_logs:/logs:ro
      - ./log-processor.py:/app/log-processor.py:ro
    working_dir: /app
    command: bash -c "pip install kafka-python && python3 log-processor.py"
    environment:
      KAFKA_BOOTSTRAP_SERVERS: kafka:9092
      KAFKA_TOPIC_WAF_LOGS: waf-logs
      MODSEC_LOG_PATH: /logs/waf-access.log
    depends_on: [waf-proxy, kafka]
    restart: on-failure

  realtime-processor:
    image: python:3.11-slim
    container_name: tokio-gcp-realtime-processor
    volumes:
      - ./realtime-processor.py:/app/realtime-processor.py:ro
    working_dir: /app
    command: bash -c "pip install kafka-python psycopg2-binary requests && python3 -u realtime-processor.py"
    environment:
      KAFKA_BOOTSTRAP_SERVERS: kafka:9092
      KAFKA_TOPIC_WAF_LOGS: waf-logs
      KAFKA_CONSUMER_GROUP: gcp-realtime-group
      PYTHONUNBUFFERED: "1"
      BLOCK_THRESHOLD: "50"
      BLOCK_WINDOW_SEC: "300"
      EPISODE_MIN_REQUESTS: "3"
      EPISODE_WINDOW_SEC: "600"
      POSTGRES_HOST: postgres
      POSTGRES_PORT: "5432"
      POSTGRES_DB: {_PG_DB}
      POSTGRES_USER: {_PG_USER}
      POSTGRES_PASSWORD: {_PG_PASS}
    depends_on: [postgres, kafka]
    restart: on-failure

  dashboard-api:
    image: python:3.11-slim
    container_name: tokio-gcp-dashboard-api
    ports:
      - "8000:8000"
    volumes:
      - ./dashboard-app.py:/app/app.py:ro
      - ./dashboard-db.py:/app/db.py:ro
    working_dir: /app
    command: bash -c "pip install fastapi uvicorn psycopg2-binary pydantic PyJWT && uvicorn app:app --host YOUR_IP_ADDRESS --port 8000"
    environment:
      POSTGRES_HOST: postgres
      POSTGRES_PORT: "5432"
      POSTGRES_DB: {_PG_DB}
      POSTGRES_USER: {_PG_USER}
      POSTGRES_PASSWORD: {_PG_PASS}
      DASHBOARD_USER: {_DASHBOARD_USER}
      DASHBOARD_PASSWORD: {_DASHBOARD_PASS}
      JWT_SECRET: tokioai-waf-jwt-secret-2026
      PYTHONUNBUFFERED: "1"
    depends_on: [postgres]
    restart: unless-stopped

volumes:
  pgdata:
  modsec_logs:
  letsencrypt:
'''


def _init_db_sql() -> str:
    return '''
CREATE TABLE IF NOT EXISTS waf_logs (
    id BIGSERIAL PRIMARY KEY, timestamp TIMESTAMPTZ DEFAULT NOW(),
    ip TEXT, method TEXT, uri TEXT, status INTEGER,
    body_bytes_sent INTEGER DEFAULT 0, request_time REAL DEFAULT 0,
    user_agent TEXT, referer TEXT, host TEXT,
    upstream_status TEXT, modsec_messages TEXT,
    raw_log JSONB, tenant_id TEXT DEFAULT 'default',
    severity TEXT DEFAULT 'info', blocked BOOLEAN DEFAULT FALSE,
    classification_source TEXT DEFAULT 'NONE',
    owasp_code TEXT, owasp_name TEXT, sig_id TEXT,
    threat_type TEXT, action TEXT DEFAULT 'log_only',
    confidence REAL,
    kafka_offset BIGINT, kafka_partition INTEGER
);
CREATE TABLE IF NOT EXISTS tenants (
    id SERIAL PRIMARY KEY, name TEXT UNIQUE NOT NULL, domain TEXT NOT NULL,
    backend_url TEXT, created_at TIMESTAMPTZ DEFAULT NOW(), active BOOLEAN DEFAULT TRUE
);
CREATE TABLE IF NOT EXISTS episodes (
    id BIGSERIAL PRIMARY KEY, episode_id TEXT UNIQUE,
    tenant_id TEXT DEFAULT 'default', start_time TIMESTAMPTZ, end_time TIMESTAMPTZ,
    src_ip TEXT, attack_type TEXT, severity TEXT DEFAULT 'medium',
    total_requests INTEGER DEFAULT 0, blocked_requests INTEGER DEFAULT 0,
    sample_uris TEXT, intelligence_analysis TEXT,
    status TEXT DEFAULT 'active', ml_label TEXT, ml_confidence DOUBLE PRECISION,
    description TEXT, owasp_code TEXT, owasp_name TEXT, risk_score REAL DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(), updated_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS blocked_ips (
    id SERIAL PRIMARY KEY, ip TEXT NOT NULL, reason TEXT,
    blocked_at TIMESTAMPTZ DEFAULT NOW(), expires_at TIMESTAMPTZ,
    active BOOLEAN DEFAULT TRUE, tenant_id TEXT DEFAULT 'default',
    blocked_by TEXT DEFAULT 'system', threat_type TEXT,
    severity TEXT DEFAULT 'medium', episode_id TEXT,
    auto_blocked BOOLEAN DEFAULT FALSE, block_type TEXT DEFAULT 'manual',
    risk_score REAL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS block_audit_log (
    id BIGSERIAL PRIMARY KEY, ip TEXT NOT NULL, action TEXT NOT NULL,
    reason TEXT, performed_by TEXT DEFAULT 'system',
    tenant_id TEXT DEFAULT 'default',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_waf_logs_ts ON waf_logs(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_waf_logs_ip ON waf_logs(ip);
CREATE INDEX IF NOT EXISTS idx_waf_logs_sev ON waf_logs(severity);
CREATE INDEX IF NOT EXISTS idx_waf_logs_tt ON waf_logs(threat_type);
CREATE INDEX IF NOT EXISTS idx_waf_logs_ow ON waf_logs(owasp_code);
CREATE INDEX IF NOT EXISTS idx_episodes_start ON episodes(start_time DESC);
CREATE INDEX IF NOT EXISTS idx_episodes_status ON episodes(status);
CREATE INDEX IF NOT EXISTS idx_blocked_ip ON blocked_ips(ip);
CREATE INDEX IF NOT EXISTS idx_blocked_active ON blocked_ips(active);
'''


def _nginx_logging_conf() -> str:
    return r'''log_format waf_json escape=json '{"timestamp":"$time_iso8601","ip":"$remote_addr","method":"$request_method","uri":"$request_uri","status":$status,"size":$body_bytes_sent,"request_time":$request_time,"user_agent":"$http_user_agent","referer":"$http_referer","host":"$host","upstream_status":"$upstream_status"}';'''


def _nginx_site_conf(domain: str, backend_url: str) -> str:
    return f'''server {{
    listen 80;
    server_name {domain} www.{domain} _;
    server_tokens off;
    access_log /var/log/nginx/waf-access.log waf_json;
    error_log /var/log/nginx/error.log warn;
    location /health {{ access_log off; return 200 "ok\\n"; add_header Content-Type text/plain; }}
    
    # Dashboard WAF - Proxy al dashboard en puerto 8000
    location /dashboard/ {{
        proxy_pass http://localhost:8000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Port $server_port;
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
        # WebSocket support
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }}
    
    # API del dashboard
    location /api/ {{
        proxy_pass http://localhost:8000/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }}
    
    location / {{
        proxy_pass {backend_url};
        proxy_set_header Host {domain};
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_ssl_verify off;
        proxy_ssl_server_name on;
        proxy_ssl_name {domain};
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }}
}}

server {{
    listen 443 ssl;
    server_name {domain} www.{domain};
    server_tokens off;
    ssl_certificate /etc/letsencrypt/live/{domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{domain}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    access_log /var/log/nginx/waf-access.log waf_json;
    error_log /var/log/nginx/error.log warn;
    location /health {{ access_log off; return 200 "ok\\n"; add_header Content-Type text/plain; }}
    
    # Dashboard WAF - Proxy al dashboard en puerto 8000
    location /dashboard/ {{
        proxy_pass http://localhost:8000/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $host;
        proxy_set_header X-Forwarded-Port $server_port;
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
        # WebSocket support
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }}
    
    # API del dashboard
    location /api/ {{
        proxy_pass http://localhost:8000/api/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }}
    
    location / {{
        proxy_pass {backend_url};
        proxy_set_header Host {domain};
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_ssl_verify off;
        proxy_ssl_server_name on;
        proxy_ssl_name {domain};
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }}
}}'''


def _log_processor_py() -> str:
    return r'''#!/usr/bin/env python3
"""Tail nginx access.log and push JSON lines to Kafka."""
import json, os, time, sys, subprocess
from kafka import KafkaProducer
KAFKA = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:9092")
TOPIC = os.getenv("KAFKA_TOPIC_WAF_LOGS", "waf-logs")
LOG = os.getenv("MODSEC_LOG_PATH", "/logs/waf-access.log")
def main():
    print(f"[log-processor] Waiting for {LOG}...")
    while not os.path.exists(LOG):
        time.sleep(2)
    print(f"[log-processor] Found {LOG}, connecting to Kafka at {KAFKA}...")
    producer = None
    for i in range(30):
        try:
            producer = KafkaProducer(bootstrap_servers=KAFKA.split(","),
                                     value_serializer=lambda v: json.dumps(v).encode())
            break
        except Exception as e:
            print(f"[log-processor] Kafka not ready ({e}), retrying...")
            time.sleep(5)
    if not producer:
        print("[log-processor] Failed to connect to Kafka"); sys.exit(1)
    print(f"[log-processor] Connected. Tailing {LOG}...")
    # Use subprocess tail -F for robust following (handles log rotation)
    proc = subprocess.Popen(["tail", "-n", "0", "-F", LOG],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            text=True)
    count = 0
    for line in proc.stdout:
        line = line.strip()
        if not line: continue
        try:
            data = json.loads(line)
            producer.send(TOPIC, value=data)
            count += 1
            if count % 100 == 0:
                print(f"[log-processor] Sent {count} events to Kafka")
        except json.JSONDecodeError:
            pass  # skip non-JSON lines
        except Exception as e:
            print(f"[log-processor] Error: {e}")
if __name__ == "__main__": main()
'''


def _realtime_processor_py() -> str:
    """SOC-Grade Realtime Processor v4 with OWASP + WAF Signatures + Episodes + Auto-blocking."""
    # Try repo template first, then /tmp fallbacks
    for p in (
        Path(__file__).parent / "gcp_templates" / "realtime_processor.py",
        Path("/tmp/gcp-rt-processor-v4.py"),
        Path("/tmp/gcp-realtime-processor-v3.py"),
    ):
        if p.exists():
            return p.read_text()
    # Inline fallback
    return r'''#!/usr/bin/env python3
"""TokioAI Realtime Processor v3 — SOC-Grade Classification, Episodes, Auto-blocking."""
import json, os, sys, time, re, hashlib
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from kafka import KafkaConsumer
import psycopg2
from psycopg2.extras import RealDictCursor
PG=dict(host=os.getenv("POSTGRES_HOST","postgres"),port=int(os.getenv("POSTGRES_PORT","5432")),
    dbname=os.getenv("POSTGRES_DB","soc_ai"),user=os.getenv("POSTGRES_USER","soc_user"),
    password=os.getenv("POSTGRES_PASSWORD","changeme_gcp_2026"))
KAFKA_SERVERS=os.getenv("KAFKA_BOOTSTRAP_SERVERS","kafka:9092")
TOPIC=os.getenv("KAFKA_TOPIC_WAF_LOGS","waf-logs")
GROUP=os.getenv("KAFKA_CONSUMER_GROUP","gcp-realtime-group")
BLOCK_THRESHOLD=int(os.getenv("BLOCK_THRESHOLD","50"))
BLOCK_WINDOW=int(os.getenv("BLOCK_WINDOW_SEC","300"))
BLOCK_DURATION_HR=int(os.getenv("BLOCK_DURATION_HR","24"))
EPISODE_WINDOW=int(os.getenv("EPISODE_WINDOW_SEC","600"))
EPISODE_MIN_REQUESTS=int(os.getenv("EPISODE_MIN_REQUESTS","3"))
INTERNAL_IPS={"YOUR_IP_ADDRESS","::1","YOUR_IP_ADDRESS","YOUR_IP_ADDRESS","YOUR_IP_ADDRESS"}
THREAT_RULES=[
    ("lfi_rce","critical",0.95,[r"(?i)(/etc/passwd|/etc/shadow|/etc/hosts|/proc/self|/dev/null)",r"(?i)(\.\.\/|\.\.\\|%2e%2e|%252e|\.\.%2f)",r"(?i)(/bin/sh|/bin/bash|/usr/bin|cmd\.exe|powershell)"]),
    ("sqli","critical",0.93,[r"(?i)(union\s+(all\s+)?select|select\s+.*\s+from\s|insert\s+into|drop\s+table|delete\s+from)",r"(?i)('\s*or\s+'|'\s*=\s*'|\".*--|;\s*drop\s|;\s*delete\s)",r"(?i)(\bexec\b\s*\(|\bxp_cmdshell|\bsp_executesql|\bwaitfor\s+delay)",r"(?i)(benchmark\s*\(|sleep\s*\(\d|information_schema|sys\.objects)"]),
    ("xss","critical",0.92,[r"(?i)(<script[\s>]|javascript\s*:|onerror\s*=|onload\s*=|onmouseover\s*=)",r"(?i)(eval\s*\(|document\.cookie|document\.write|window\.location)",r"(?i)(alert\s*\(|confirm\s*\(|prompt\s*\(|String\.fromCharCode)"]),
    ("cmdi","critical",0.94,[r"(?i)(\|\s*cat\s|\|\s*ls\s|\|\s*whoami|\|\s*id\s|\|\s*uname)",r"(?i)(\bwget\s+http|\bcurl\s+http|\bnc\s+-[elp]|\bping\s+-c)"]),
    ("scanner","high",0.88,[r"(?i)(wp-login\.php|wp-admin|xmlrpc\.php|wp-config\.php|wp-includes)",r"(?i)(phpmyadmin|adminer|phpinfo\.php|server-status|server-info)",r"(?i)(/\.env|/\.git|/\.htaccess|/\.DS_Store|/\.svn|/\.hg)",r"(?i)(/config\.php|/configuration\.php|/settings\.php|/database\.yml)",r"(?i)(cgi-bin/|/shell|/c99|/r57|/webshell|/backdoor)",r"(?i)(/actuator|/swagger|/api-docs|/graphql|/debug|/trace)",r"(?i)(/solr/|/jenkins|/manager/html|/jmx-console|/admin-console)",r"(?i)(/telescope|/horizon|/nova-api|/_debugbar|/elfinder)"]),
    ("scanner_ua","high",0.85,[r"(?i)(nikto|sqlmap|nmap|dirbuster|gobuster|wpscan|masscan|nuclei|zgrab)",r"(?i)(hydra|metasploit|burp|owasp|acunetix|netsparker|qualys|openvas)",r"(?i)(whatweb|wapiti|skipfish|arachni|w3af|vega|zap)"]),
    ("brute_force","high",0.82,[r"(?i)^/+login",r"(?i)^/+signin",r"(?i)^/+auth",r"(?i)^/+admin/?$",r"(?i)^/+administrator",r"(?i)(api/+token|api/+auth|oauth/+token|api/+login)"]),
    ("probe","medium",0.75,[r"(?i)\.(php|asp|aspx|jsp|cgi|pl|py|rb|sh|bat|cmd|exe)(\?|$)",r"(?i)\.(sql|bak|backup|old|orig|save|swp|tmp|log|conf)(\?|$)"]),
    ("bot","low",0.60,[r"(?i)(bot|crawl|spider|slurp|baiduspider|yandex|duckduck|bing)",r"(?i)(semrush|ahrefs|mj12bot|dotbot|petalbot|bytespider|gptbot)"]),
]
SEVERITY_ORDER={"info":0,"low":1,"medium":2,"high":3,"critical":4}
def _sev_rank(s): return SEVERITY_ORDER.get(s,0)
def classify_request(method,uri,status,user_agent,ip,host,request_time=0,size=0):
    threats=[];text_uri=uri or "";text_ua=user_agent or "";status=int(status or 0)
    for threat_type,severity,confidence,patterns in THREAT_RULES:
        for pat in patterns:
            target=text_ua if threat_type in("scanner_ua","bot") else text_uri
            if re.search(pat,target):
                threats.append((threat_type,severity,confidence));break
    if host and re.match(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}",host): threats.append(("recon_ip","medium",0.70))
    if method=="POST" and text_uri in("/","") and status in(301,302,400,403,404,405): threats.append(("exploit_attempt","high",0.78))
    if not method or not text_uri: threats.append(("malformed","medium",0.72))
    if status==403: threats.append(("blocked_attempt","medium",0.65))
    if status==401 and re.search(r"(?i)(login|auth|admin|api/token)",text_uri): threats.append(("brute_force","high",0.80))
    if request_time and float(request_time)>10: threats.append(("slow_attack","medium",0.65))
    if size and int(size)>1000000: threats.append(("data_exfil","high",0.70))
    if not threats: return "info",None,None,[]
    threats.sort(key=lambda t:(_sev_rank(t[1]),t[2]),reverse=True)
    p=threats[0];conf=p[2]
    if len(threats)>1: conf=min(0.99,conf+0.05*(len(threats)-1))
    return p[1],p[0],conf,[(t[0],t[1]) for t in threats]
class IPTracker:
    def __init__(self): self.windows=defaultdict(list);self.threats=defaultdict(list);self.request_count=defaultdict(int)
    def add(self,ip,ts,threat_type=None,uri=None,severity="info"):
        now=time.time();self.windows[ip].append(now);self.request_count[ip]+=1
        cutoff=now-max(BLOCK_WINDOW,EPISODE_WINDOW)
        self.windows[ip]=[t for t in self.windows[ip] if t>cutoff]
        if threat_type and severity!="info":
            self.threats[ip].append((now,threat_type,uri,severity))
            self.threats[ip]=[(t,tt,u,s) for t,tt,u,s in self.threats[ip] if t>cutoff]
    def should_block(self,ip):
        recent=[t for t in self.windows.get(ip,[]) if t>time.time()-BLOCK_WINDOW]
        return len(recent)>=BLOCK_THRESHOLD
    def get_episode_data(self,ip):
        threats=self.threats.get(ip,[])
        if len(threats)<EPISODE_MIN_REQUESTS: return None
        types=[t[1] for t in threats];uris=list(set(t[2] for t in threats if t[2]))[:10]
        severities=[t[3] for t in threats]
        return {"type":max(set(types),key=types.count),"count":len(threats),"uris":uris,
                "severity":max(set(severities),key=_sev_rank),"start":threats[0][0],"end":threats[-1][0],
                "types_breakdown":{t:types.count(t) for t in set(types)}}
tracker=IPTracker()
def _notify(msg):
    BOT_TOKEN=os.getenv("TELEGRAM_BOT_TOKEN","");OWNER_CHAT_ID=os.getenv("TELEGRAM_OWNER_CHAT_ID","")
    if not BOT_TOKEN or not OWNER_CHAT_ID: return
    try:
        import requests
        requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",json={"chat_id":OWNER_CHAT_ID,"text":msg,"parse_mode":"Markdown"},timeout=10)
    except: pass
def get_pg():
    for i in range(30):
        try: c=psycopg2.connect(**PG);c.autocommit=True;return c
        except Exception as e: print(f"[rt] DB not ready ({e})");time.sleep(3)
    sys.exit(1)
def ensure_schema(conn):
    cur=conn.cursor()
    for sql in ["ALTER TABLE blocked_ips ADD COLUMN IF NOT EXISTS episode_id TEXT",
                "ALTER TABLE blocked_ips ADD COLUMN IF NOT EXISTS auto_blocked BOOLEAN DEFAULT false",
                "ALTER TABLE episodes ADD COLUMN IF NOT EXISTS ml_label TEXT",
                "ALTER TABLE episodes ADD COLUMN IF NOT EXISTS ml_confidence DOUBLE PRECISION",
                "ALTER TABLE episodes ADD COLUMN IF NOT EXISTS description TEXT",
                "ALTER TABLE episodes ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT NOW()",
                "ALTER TABLE episodes ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'active'",
                """CREATE TABLE IF NOT EXISTS block_audit_log (id BIGSERIAL PRIMARY KEY,ip TEXT NOT NULL,action TEXT NOT NULL,reason TEXT,performed_by TEXT DEFAULT 'system',created_at TIMESTAMPTZ DEFAULT NOW())"""]:
        try: cur.execute(sql)
        except: pass
    cur.close();print("[rt] Schema verified")
def insert_waf_log(cur,event,severity,ml_label,ml_confidence):
    try:
        cur.execute("INSERT INTO waf_logs(timestamp,ip,method,uri,status,body_bytes_sent,user_agent,host,referer,request_time,severity,blocked,raw_log,classification_source) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (event.get("timestamp"),event.get("ip","unknown"),event.get("method",""),event.get("uri",""),int(event.get("status",0)),
             int(event.get("size",event.get("body_bytes_sent",0))),event.get("user_agent",""),event.get("host",""),event.get("referer",""),
             float(event.get("request_time",0)),severity,False,json.dumps(event,default=str),ml_label or "NONE"))
    except Exception as e: print(f"[rt] Insert err: {e}")
def upsert_episode(cur,ip,ep_data,ml_label,ml_confidence):
    key=f"{ip}-{ep_data['type']}-{int(ep_data['start']//300)}"
    ep_id="ep-"+hashlib.md5(key.encode()).hexdigest()[:12]
    uris_str=json.dumps(ep_data["uris"][:10]) if ep_data.get("uris") else "[]"
    desc=f"{ep_data['type']} from {ip} — {ep_data['count']} malicious requests, severity: {ep_data['severity']}"
    if ep_data.get("types_breakdown"):
        desc+=" ["+", ".join(f"{k}:{v}" for k,v in ep_data["types_breakdown"].items())+"]"
    try:
        cur.execute("""INSERT INTO episodes(episode_id,attack_type,severity,src_ip,start_time,end_time,total_requests,sample_uris,status,ml_label,ml_confidence,description)
            VALUES(%s,%s,%s,%s,to_timestamp(%s),to_timestamp(%s),%s,%s,'active',%s,%s,%s)
            ON CONFLICT(episode_id) DO UPDATE SET end_time=to_timestamp(%s),total_requests=%s,sample_uris=%s,
            severity=CASE WHEN episodes.severity='critical' THEN 'critical' ELSE %s END,
            ml_label=COALESCE(%s,episodes.ml_label),ml_confidence=GREATEST(%s,episodes.ml_confidence),description=%s,updated_at=NOW()""",
            (ep_id,ep_data["type"],ep_data["severity"],ip,ep_data["start"],ep_data["end"],ep_data["count"],uris_str,ml_label,ml_confidence,desc,
             ep_data["end"],ep_data["count"],uris_str,ep_data["severity"],ml_label,ml_confidence,desc))
        return ep_id
    except Exception as e: print(f"[rt] Episode err: {e}");return None
def auto_block_ip(cur,ip,reason,episode_id=None,threat_type=None,severity="high"):
    if ip in INTERNAL_IPS: return False
    try:
        cur.execute("SELECT id FROM blocked_ips WHERE ip=%s AND active=true",(ip,))
        if cur.fetchone(): return False
        expires=datetime.now(timezone.utc)+timedelta(hours=BLOCK_DURATION_HR)
        cur.execute("INSERT INTO blocked_ips(ip,reason,expires_at,active,threat_type,severity,episode_id,auto_blocked) VALUES(%s,%s,%s,true,%s,%s,%s,true)",
            (ip,reason,expires,threat_type,severity,episode_id))
        cur.execute("INSERT INTO block_audit_log(ip,action,reason,performed_by) VALUES(%s,'block',%s,'tokioai-auto')",(ip,reason))
        print(f"[rt] AUTO-BLOCKED {ip}: {reason}");_notify(f"*Auto-Block* IP: `{ip}`\nRazón: {reason}\nSeveridad: {severity}")
        return True
    except Exception as e: print(f"[rt] Block err: {e}");return False
def expire_old_blocks(cur):
    try:
        cur.execute("UPDATE blocked_ips SET active=false WHERE active=true AND expires_at IS NOT NULL AND expires_at<NOW() RETURNING ip")
        for r in cur.fetchall():
            cur.execute("INSERT INTO block_audit_log(ip,action,reason,performed_by) VALUES(%s,'unblock','Expired','tokioai-auto')",(r[0],))
    except: pass
def resolve_old_episodes(cur):
    try: cur.execute("UPDATE episodes SET status='resolved',updated_at=NOW() WHERE status='active' AND end_time<NOW()-INTERVAL '30 minutes'")
    except: pass
def main():
    print("="*60);print("[rt] TokioAI Realtime Processor v3 — SOC-Grade");print("="*60)
    print(f"[rt] Kafka: {KAFKA_SERVERS}, Topic: {TOPIC}, Group: {GROUP}")
    print(f"[rt] Block threshold: {BLOCK_THRESHOLD} reqs / {BLOCK_WINDOW}s")
    print(f"[rt] Episode: min {EPISODE_MIN_REQUESTS} threats in {EPISODE_WINDOW}s")
    print(f"[rt] Threat rules: {len(THREAT_RULES)} categories")
    conn=get_pg();ensure_schema(conn);print("[rt] PostgreSQL OK")
    consumer=None
    for i in range(30):
        try:
            consumer=KafkaConsumer(TOPIC,bootstrap_servers=KAFKA_SERVERS.split(","),group_id=GROUP+"-v3",
                auto_offset_reset="earliest",value_deserializer=lambda m:json.loads(m.decode("utf-8")),consumer_timeout_ms=5000);break
        except Exception as e: print(f"[rt] Kafka not ready ({e})");time.sleep(5)
    if not consumer: print("[rt] FATAL: Kafka failed");sys.exit(1)
    print(f"[rt] Consuming '{TOPIC}' OK");processed=0;classified=0;episodes_n=0;blocks_n=0;last_maint=time.time();last_report=time.time()
    while True:
        try:
            for tp,msgs in consumer.poll(timeout_ms=2000).items():
                for msg in msgs:
                    e=msg.value;ip=e.get("ip","unknown")
                    severity,ml_label,ml_conf,all_t=classify_request(e.get("method"),e.get("uri"),e.get("status"),e.get("user_agent"),ip,e.get("host"),e.get("request_time",0),e.get("size",e.get("body_bytes_sent",0)))
                    if ip not in INTERNAL_IPS and ip not in("unknown","-",""): tracker.add(ip,time.time(),ml_label,e.get("uri"),severity)
                    cur=conn.cursor();insert_waf_log(cur,e,severity,ml_label,ml_conf)
                    if severity!="info": classified+=1
                    if ip not in INTERNAL_IPS and ip not in("unknown","-",""):
                        ep_data=tracker.get_episode_data(ip)
                        if ep_data:
                            ep_id=upsert_episode(cur,ip,ep_data,ml_label,ml_conf)
                            if ep_id: episodes_n+=1
                            if tracker.should_block(ip):
                                if auto_block_ip(cur,ip,f"Rate limit: {len(tracker.windows[ip])} reqs/{BLOCK_WINDOW}s",episode_id=ep_id,threat_type=ml_label or "rate_limit",severity=severity): blocks_n+=1
                    cur.close();processed+=1
            now=time.time()
            if now-last_maint>60: cur=conn.cursor();expire_old_blocks(cur);resolve_old_episodes(cur);cur.close();last_maint=now
            if now-last_report>300: print(f"[rt] Stats: {processed} processed, {classified} threats, {episodes_n} episodes, {blocks_n} blocks");last_report=now
        except psycopg2.OperationalError: print("[rt] DB reconnecting...");conn=get_pg()
        except Exception as ex: print(f"[rt] Error: {ex}");time.sleep(1)
if __name__=="__main__": main()
'''


def _dashboard_app_py() -> str:
    """Full dashboard FastAPI app v2 with JWT auth, filters, Fibonacci logo."""
    # Try repo template first, then /tmp fallback
    for p in (
        Path(__file__).parent / "gcp_templates" / "dashboard_app.py",
        Path("/tmp/gcp-dashboard-v2.py"),
    ):
        if p.exists():
            return p.read_text()
    # Inline minimal fallback
    return r'''#!/usr/bin/env python3
"""TokioAI WAF Dashboard v2"""
import os,json,secrets,time
from datetime import datetime,timedelta,timezone
from typing import Optional
from fastapi import FastAPI,Query,Request,HTTPException,Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse,JSONResponse
from fastapi.security import HTTPBearer,HTTPAuthorizationCredentials
from pydantic import BaseModel
import psycopg2
from psycopg2.extras import RealDictCursor
import jwt as pyjwt
DASH_USER=os.getenv("DASHBOARD_USER","admin")
DASH_PASS=os.getenv("DASHBOARD_PASSWORD","PrXtjL5EXrnP27wUwSz6dIoW")
JWT_SECRET=os.getenv("JWT_SECRET",secrets.token_hex(32))
PG=dict(host=os.getenv("POSTGRES_HOST","postgres"),port=int(os.getenv("POSTGRES_PORT","5432")),dbname=os.getenv("POSTGRES_DB","soc_ai"),user=os.getenv("POSTGRES_USER","soc_user"),password=os.getenv("POSTGRES_PASSWORD","changeme_gcp_2026"))
app=FastAPI(title="TokioAI WAF",docs_url=None,redoc_url=None)
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_methods=["*"],allow_headers=["*"])
security=HTTPBearer(auto_error=False)
def get_db():c=psycopg2.connect(**PG);c.autocommit=True;return c
class LoginReq(BaseModel):username:str;password:str
def create_token(u):return pyjwt.encode({"sub":u,"exp":datetime.now(timezone.utc)+timedelta(hours=24)},JWT_SECRET,algorithm="HS256")
def verify_token(creds:Optional[HTTPAuthorizationCredentials]=Depends(security)):
    if not creds:raise HTTPException(401,"Token needed")
    try:return pyjwt.decode(creds.credentials,JWT_SECRET,algorithms=["HS256"])["sub"]
    except:raise HTTPException(401,"Invalid token")
@app.post("/api/auth/login")
def login(r:LoginReq):
    if r.username==DASH_USER and r.password==DASH_PASS:return {"token":create_token(r.username)}
    raise HTTPException(401,"Bad credentials")
@app.get("/health")
def health():
    try:c=get_db();c.close();return {"status":"healthy"}
    except Exception as e:return {"status":"degraded","error":str(e)}
@app.get("/api/summary")
def summary(user:str=Depends(verify_token)):
    try:
        c=get_db();cur=c.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT COUNT(*) total,COUNT(CASE WHEN blocked THEN 1 END) blocked,COUNT(DISTINCT ip) unique_ips,COUNT(CASE WHEN severity='critical' THEN 1 END) critical,COUNT(CASE WHEN severity='high' THEN 1 END) high,COUNT(CASE WHEN severity='medium' THEN 1 END) medium FROM waf_logs WHERE timestamp>NOW()-INTERVAL '24h'")
        r=cur.fetchone();cur.execute("SELECT COUNT(*) c FROM episodes WHERE status='active'");ep=cur.fetchone()
        cur.execute("SELECT COUNT(*) c FROM blocked_ips WHERE active=true");bl=cur.fetchone()
        cur.close();c.close();return {**r,"active_episodes":ep["c"],"active_blocks":bl["c"]}
    except Exception as e:return {"error":str(e)}
@app.get("/api/attacks/recent")
def recent(limit:int=100,severity:Optional[str]=None,ip:Optional[str]=None,search:Optional[str]=None,user:str=Depends(verify_token)):
    try:
        c=get_db();cur=c.cursor(cursor_factory=RealDictCursor);cl=["timestamp>NOW()-INTERVAL '24h'"];p=[]
        if severity:cl.append("severity=%s");p.append(severity)
        if ip:cl.append("ip=%s");p.append(ip)
        if search:cl.append("(uri ILIKE %s OR ip ILIKE %s)");s=f"%{search}%";p.extend([s,s])
        w=" WHERE "+" AND ".join(cl);q=f"SELECT timestamp,ip,method,uri,status,severity,blocked,host,threat_type,owasp_code FROM waf_logs{w} ORDER BY timestamp DESC LIMIT %s"
        p.append(limit);cur.execute(q,p);rows=cur.fetchall();cur.close();c.close()
        return [{k:str(v) if v is not None else None for k,v in r.items()} for r in rows]
    except Exception as e:return {"error":str(e)}
@app.get("/api/episodes")
def episodes(limit:int=30,user:str=Depends(verify_token)):
    try:
        c=get_db();cur=c.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM episodes ORDER BY start_time DESC LIMIT %s",(limit,))
        rows=cur.fetchall();cur.close();c.close();return [{k:str(v) if v is not None else None for k,v in r.items()} for r in rows]
    except:return []
@app.get("/api/blocked")
def blocked(user:str=Depends(verify_token)):
    try:
        c=get_db();cur=c.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM blocked_ips WHERE active=true ORDER BY blocked_at DESC LIMIT 100")
        rows=cur.fetchall();cur.close();c.close();return [{k:str(v) if v is not None else None for k,v in r.items()} for r in rows]
    except:return []
@app.get("/",response_class=HTMLResponse)
def index():return "<html><body><h1>TokioAI WAF Dashboard</h1><p>Login at /api/auth/login</p></body></html>"
'''


def _dashboard_db_py() -> str:
    """Minimal db helper for dashboard."""
    return r'''import os, psycopg2
from psycopg2.extras import RealDictCursor
PG = dict(host=os.getenv("POSTGRES_HOST","postgres"),port=int(os.getenv("POSTGRES_PORT","5432")),
    dbname=os.getenv("POSTGRES_DB","soc_ai"),user=os.getenv("POSTGRES_USER","soc_user"),
    password=os.getenv("POSTGRES_PASSWORD","changeme_gcp_2026"))
def _get_postgres_conn(): return psycopg2.connect(**PG)
def _return_postgres_conn(c): c.close()
'''


# ---------------------------------------------------------------------------
# Setup Check
# ---------------------------------------------------------------------------

def _setup(params: Dict[str, Any]) -> Dict[str, Any]:
    """Check prerequisites and guide user through GCP setup."""
    issues = []
    ready = []

    # Check GCP Project ID
    if _GCP_PROJECT:
        ready.append(f"✅ GCP_PROJECT_ID: `{_GCP_PROJECT}`")
    else:
        issues.append(
            "❌ GCP_PROJECT_ID no configurado.\n"
            "   → Agregá `GCP_PROJECT_ID=tu-project-id` al archivo .env"
        )

    # Check Service Account Key
    if _GCP_SA_KEY_PATH and os.path.exists(_GCP_SA_KEY_PATH):
        ready.append(f"✅ GCP_SA_KEY_JSON: `{_GCP_SA_KEY_PATH}`")
    elif _GCP_SA_KEY_PATH:
        issues.append(f"❌ GCP_SA_KEY_JSON apunta a `{_GCP_SA_KEY_PATH}` pero el archivo no existe")
    else:
        issues.append(
            "❌ GCP_SA_KEY_JSON no configurado.\n"
            "   → Creá una Service Account en GCP Console:\n"
            "     1. Ir a console.cloud.google.com → IAM → Service Accounts\n"
            "     2. Crear cuenta con rol 'Compute Admin'\n"
            "     3. Generar clave JSON y descargarla\n"
            "     4. Agregá `GCP_SA_KEY_JSON=/ruta/al/key.json` al .env"
        )

    # Check Python SDK
    try:
        from google.cloud import compute_v1  # noqa
        ready.append("✅ google-cloud-compute SDK instalado")
    except ImportError:
        issues.append(
            "❌ google-cloud-compute no instalado.\n"
            "   → Se instalará automáticamente en el próximo build"
        )

    # Check Hostinger API
    if _HOSTINGER_API_KEY:
        ready.append("✅ HOSTINGER_API_KEY configurado")
    else:
        issues.append("⚠️ HOSTINGER_API_KEY no configurado (DNS no se actualizará automáticamente)")

    # Check Cloudflare
    if _CLOUDFLARED_TUNNEL_TOKEN:
        ready.append("✅ CLOUDFLARED_TUNNEL_TOKEN configurado")
    else:
        issues.append("⚠️ CLOUDFLARED_TUNNEL_TOKEN no configurado (tunnel no se desplegará en GCP)")

    all_ok = len([i for i in issues if i.startswith("❌")]) == 0

    return {
        "ok": all_ok,
        "ready": ready,
        "issues": issues,
        "message": (
            "Todo listo para desplegar en GCP 🚀" if all_ok
            else "Faltan configuraciones para desplegar en GCP. Ver 'issues' arriba."
        ),
        "next_steps": (
            [] if all_ok else [
                "1. Configurá las variables faltantes en el .env de la Raspberry Pi",
                "2. Reiniciá el contenedor: docker restart tokio-ai-cli",
                "3. Volvé a ejecutar: gcp_waf setup",
            ]
        ),
    }


# ---------------------------------------------------------------------------
# Deploy using Python SDK — Auto-Scaling Architecture
# ---------------------------------------------------------------------------
# Architecture:
#   Instance Template → MIG (auto-heal + autoscale) → Network LB (static IP)
#   Each VM: Nginx WAF + Log Processor + Kafka + PG + Dashboard + RT Processor
#   MIG auto-heals on failure, autoscales on CPU > 70%
# ---------------------------------------------------------------------------

def _ensure_network(compute_v1, creds, project: str, network_name: str) -> str:
    """Create VPC network if not exists. Returns network URL."""
    client = compute_v1.NetworksClient(credentials=creds) if creds else compute_v1.NetworksClient()
    try:
        client.get(project=project, network=network_name)
        return "existed"
    except Exception:
        net = compute_v1.Network(name=network_name, auto_create_subnetworks=False)
        op = client.insert(project=project, network_resource=net)
        _wait_for_global_op(compute_v1, creds, project, op.name)
        return "created"


def _ensure_subnet(compute_v1, creds, project: str, region: str, subnet_name: str, network_name: str) -> str:
    """Create subnet if not exists."""
    client = compute_v1.SubnetworksClient(credentials=creds) if creds else compute_v1.SubnetworksClient()
    try:
        client.get(project=project, region=region, subnetwork=subnet_name)
        return "existed"
    except Exception:
        sub = compute_v1.Subnetwork(
            name=subnet_name, ip_cidr_range="YOUR_IP_ADDRESS/24", region=region,
            network=f"projects/{project}/global/networks/{network_name}",
        )
        op = client.insert(project=project, region=region, subnetwork_resource=sub)
        _wait_for_region_op(compute_v1, creds, project, region, op.name)
        return "created"


def _ensure_firewall(compute_v1, creds, project: str, fw_name: str, network_name: str) -> str:
    """Create firewall allowing WAF ports + GCP health check ranges.
    
    SECURITY: Port 22 (SSH) is NOT exposed publicly. Use GCP IAP or restrict to specific IPs.
    """
    client = compute_v1.FirewallsClient(credentials=creds) if creds else compute_v1.FirewallsClient()
    try:
        existing = client.get(project=project, firewall=fw_name)
        # Verificar si el firewall existente tiene el puerto 22 y actualizarlo
        needs_update = False
        for allowed in existing.allowed:
            if "22" in allowed.ports:
                needs_update = True
                break
        
        if needs_update:
            # Actualizar firewall existente: remover puerto 22 y puertos internos (5432, 8000)
            # Solo mantener puertos web públicos (80, 443)
            existing.allowed = [
                compute_v1.Allowed(I_p_protocol="tcp", ports=["80", "443"]),
            ]
            op = client.update(project=project, firewall=fw_name, firewall_resource=existing)
            _wait_for_global_op(compute_v1, creds, project, op.name)
            return "updated (removed port 22)"
        return "existed"
    except Exception:
        # Crear nuevo firewall: solo puertos web públicos (80, 443)
        # PostgreSQL (5432) y Dashboard (8000) deben ser accesibles solo internamente
        # El Load Balancer maneja el enrutamiento a estos puertos
        fw = compute_v1.Firewall(
            name=fw_name,
            network=f"projects/{project}/global/networks/{network_name}",
            allowed=[
                compute_v1.Allowed(I_p_protocol="tcp", ports=["80", "443"]),
            ],
            # YOUR_IP_ADDRESS/0 for web traffic, YOUR_IP_ADDRESS/16 + YOUR_IP_ADDRESS/22 for GCP health checks
            # SECURITY: 
            # - Port 22 (SSH) NOT included - use GCP IAP for SSH access
            # - Ports 5432 (PostgreSQL) and 8000 (Dashboard) NOT included - internal only via Load Balancer
            source_ranges=["YOUR_IP_ADDRESS/0", "YOUR_IP_ADDRESS/16", "YOUR_IP_ADDRESS/22"],
            target_tags=["tokio-waf"],
        )
        op = client.insert(project=project, firewall_resource=fw)
        _wait_for_global_op(compute_v1, creds, project, op.name)
        return "created"


def _ensure_static_ip(compute_v1, creds, project: str, region: str, ip_name: str) -> str:
    """Reserve regional static IP. Returns the IP address."""
    client = compute_v1.AddressesClient(credentials=creds) if creds else compute_v1.AddressesClient()
    try:
        addr = client.get(project=project, region=region, address=ip_name)
        return addr.address
    except Exception:
        addr_res = compute_v1.Address(name=ip_name, region=region)
        op = client.insert(project=project, region=region, address_resource=addr_res)
        _wait_for_region_op(compute_v1, creds, project, region, op.name)
        addr = client.get(project=project, region=region, address=ip_name)
        return addr.address


def _ensure_health_check(compute_v1, creds, project: str, hc_name: str) -> str:
    """Create HTTP health check on dashboard port /health."""
    client = compute_v1.HealthChecksClient(credentials=creds) if creds else compute_v1.HealthChecksClient()
    try:
        client.get(project=project, health_check=hc_name)
        return "existed"
    except Exception:
        hc = compute_v1.HealthCheck(
            name=hc_name, type_="HTTP",
            http_health_check=compute_v1.HTTPHealthCheck(port=8000, request_path="/health"),
            check_interval_sec=30, timeout_sec=10,
            healthy_threshold=2, unhealthy_threshold=3,
        )
        op = client.insert(project=project, health_check_resource=hc)
        _wait_for_global_op(compute_v1, creds, project, op.name)
        return "created"


def _ensure_instance_template(compute_v1, creds, project: str, zone: str,
                              template_name: str, startup: str,
                              network_name: str, subnet_name: str, region: str) -> str:
    """Create instance template for WAF VMs."""
    client = compute_v1.InstanceTemplatesClient(credentials=creds) if creds else compute_v1.InstanceTemplatesClient()
    try:
        client.get(project=project, instance_template=template_name)
        return "existed"
    except Exception:
        tmpl = compute_v1.InstanceTemplate(
            name=template_name,
            properties=compute_v1.InstanceProperties(
                machine_type=_GCP_MACHINE_TYPE,
                tags=compute_v1.Tags(items=["tokio-waf"]),
                disks=[compute_v1.AttachedDisk(
                    auto_delete=True, boot=True,
                    initialize_params=compute_v1.AttachedDiskInitializeParams(
                        source_image="projects/ubuntu-os-cloud/global/images/family/ubuntu-2204-lts",
                        disk_size_gb=40, disk_type="pd-ssd",
                    ),
                )],
                network_interfaces=[compute_v1.NetworkInterface(
                    subnetwork=f"projects/{project}/regions/{region}/subnetworks/{subnet_name}",
                    access_configs=[compute_v1.AccessConfig(name="External NAT", type_="ONE_TO_ONE_NAT")],
                )],
                metadata=compute_v1.Metadata(
                    items=[compute_v1.Items(key="startup-script", value=startup)],
                ),
                labels={"managed-by": "tokioai"},
                service_accounts=[compute_v1.ServiceAccount(
                    scopes=["https://www.googleapis.com/auth/cloud-platform"],
                )],
            ),
        )
        op = client.insert(project=project, instance_template_resource=tmpl)
        _wait_for_global_op(compute_v1, creds, project, op.name)
        return "created"


def _ensure_mig(compute_v1, creds, project: str, zone: str,
                mig_name: str, template_name: str, hc_name: str,
                base_name: str, target_size: int = 1) -> str:
    """Create Managed Instance Group with auto-healing."""
    client = compute_v1.InstanceGroupManagersClient(credentials=creds) if creds else compute_v1.InstanceGroupManagersClient()
    try:
        client.get(project=project, zone=zone, instance_group_manager=mig_name)
        return "existed"
    except Exception:
        mig = compute_v1.InstanceGroupManager(
            name=mig_name,
            instance_template=f"projects/{project}/global/instanceTemplates/{template_name}",
            target_size=target_size,
            base_instance_name=base_name,
            auto_healing_policies=[compute_v1.InstanceGroupManagerAutoHealingPolicy(
                health_check=f"projects/{project}/global/healthChecks/{hc_name}",
                initial_delay_sec=600,  # 10 min for startup script to finish
            )],
            named_ports=[
                compute_v1.NamedPort(name="http", port=80),
                compute_v1.NamedPort(name="https", port=443),
                compute_v1.NamedPort(name="dashboard", port=8000),
            ],
        )
        op = client.insert(project=project, zone=zone, instance_group_manager_resource=mig)
        _wait_for_operation(compute_v1, creds, project, zone, op.name, timeout=600)
        return "created"


def _ensure_autoscaler(compute_v1, creds, project: str, zone: str,
                       as_name: str, mig_name: str,
                       min_replicas: int = 1, max_replicas: int = 3) -> str:
    """Create autoscaler for MIG based on CPU utilization."""
    client = compute_v1.AutoscalersClient(credentials=creds) if creds else compute_v1.AutoscalersClient()
    try:
        client.get(project=project, zone=zone, autoscaler=as_name)
        return "existed"
    except Exception:
        autoscaler = compute_v1.Autoscaler(
            name=as_name,
            target=f"projects/{project}/zones/{zone}/instanceGroupManagers/{mig_name}",
            autoscaling_policy=compute_v1.AutoscalingPolicy(
                min_num_replicas=min_replicas,
                max_num_replicas=max_replicas,
                cpu_utilization=compute_v1.AutoscalingPolicyCpuUtilization(
                    utilization_target=0.7,  # Scale when CPU > 70%
                ),
                cool_down_period_sec=180,
            ),
        )
        op = client.insert(project=project, zone=zone, autoscaler_resource=autoscaler)
        _wait_for_operation(compute_v1, creds, project, zone, op.name)
        return "created"


def _ensure_network_lb(compute_v1, creds, project: str, region: str, zone: str,
                       bs_name: str, fr_name_http: str, fr_name_https: str,
                       fr_name_dash: str, mig_name: str, hc_name: str,
                       waf_ip: str) -> List[str]:
    """Create Regional TCP Network Load Balancer (Backend Service + Forwarding Rules)."""
    results = []

    # Backend Service (Regional, TCP, EXTERNAL)
    bs_client = compute_v1.RegionBackendServicesClient(credentials=creds) if creds else compute_v1.RegionBackendServicesClient()
    try:
        bs_client.get(project=project, region=region, backend_service=bs_name)
        results.append("backend-service (existed)")
    except Exception:
        bs = compute_v1.BackendService(
            name=bs_name,
            backends=[compute_v1.Backend(
                group=f"projects/{project}/zones/{zone}/instanceGroups/{mig_name}",
            )],
            health_checks=[f"projects/{project}/global/healthChecks/{hc_name}"],
            load_balancing_scheme="EXTERNAL",
            protocol="TCP",
        )
        op = bs_client.insert(project=project, region=region, backend_service_resource=bs)
        _wait_for_region_op(compute_v1, creds, project, region, op.name)
        results.append("backend-service created")

    # Forwarding Rules (one per port range for external NLB)
    fr_client = compute_v1.ForwardingRulesClient(credentials=creds) if creds else compute_v1.ForwardingRulesClient()
    bs_url = f"projects/{project}/regions/{region}/backendServices/{bs_name}"

    for fr_name, port_range, label in [
        (fr_name_http, "80", "HTTP"),
        (fr_name_https, "443", "HTTPS"),
        (fr_name_dash, "8000", "Dashboard"),
    ]:
        try:
            fr_client.get(project=project, region=region, forwarding_rule=fr_name)
            results.append(f"FR-{label} (existed)")
        except Exception:
            fr = compute_v1.ForwardingRule(
                name=fr_name,
                I_p_address=waf_ip,
                I_p_protocol="TCP",
                port_range=port_range,
                backend_service=bs_url,
                load_balancing_scheme="EXTERNAL",
            )
            op = fr_client.insert(project=project, region=region, forwarding_rule_resource=fr)
            _wait_for_region_op(compute_v1, creds, project, region, op.name)
            results.append(f"FR-{label} created")

    return results


def _get_mig_instance_ip(compute_v1, creds, project: str, zone: str, mig_name: str, timeout: int = 300) -> str:
    """Wait for MIG to create an instance and return its external IP."""
    mig_client = compute_v1.InstanceGroupManagersClient(credentials=creds) if creds else compute_v1.InstanceGroupManagersClient()
    inst_client = compute_v1.InstancesClient(credentials=creds) if creds else compute_v1.InstancesClient()
    start = _time.time()
    while _time.time() - start < timeout:
        try:
            instances = mig_client.list_managed_instances(
                project=project, zone=zone, instance_group_manager=mig_name
            )
            for inst in instances:
                if inst.instance_status == "RUNNING":
                    # Get instance name from URL
                    inst_name = inst.instance.split("/")[-1]
                    instance = inst_client.get(project=project, zone=zone, instance=inst_name)
                    for ni in instance.network_interfaces:
                        for ac in ni.access_configs:
                            if ac.nat_i_p:
                                return ac.nat_i_p
        except Exception:
            pass
        _time.sleep(10)
    return ""


def _deploy(params: Dict[str, Any]) -> Dict[str, Any]:
    """Deploy full WAF stack in GCP with auto-scaling architecture.

    Architecture: Instance Template → MIG (auto-heal + autoscale) → Network LB
    - min_replicas=1 (cost-effective), max_replicas=3 (handles attacks)
    - Auto-heals if VM crashes (MIG recreates from template)
    - Scales up when CPU > 70% (DDoS, heavy traffic)
    """
    domain = params.get("domain", "").strip()
    backend_url = params.get("backend_url", "").strip()
    mode = params.get("mode", "auto").strip().lower()  # "auto" (MIG+LB) or "simple" (single VM)
    max_replicas = int(params.get("max_replicas", 3))

    if not domain:
        return {"ok": False, "error": "domain es requerido (ej: tokioia.com)"}
    if not backend_url:
        return {"ok": False, "error": "backend_url es requerido (ej: https://YOUR_IP_ADDRESS)"}

    if not _GCP_PROJECT:
        return {
            "ok": False,
            "error": (
                "GCP_PROJECT_ID no configurado. Necesitás:\n"
                "1. GCP_PROJECT_ID=tu-project-id en .env\n"
                "2. GCP_SA_KEY_JSON=/ruta/key.json en .env\n"
                "Usá `gcp_waf setup` para ver el estado completo."
            ),
        }

    compute_v1, creds = _get_compute_client()
    if compute_v1 is None:
        return {
            "ok": False,
            "error": "google-cloud-compute no instalado. pip install google-cloud-compute google-auth",
        }

    state = _load_state()
    existing = state["deployments"].get(domain)
    if existing and existing.get("status") == "active":
        return {"ok": True, "message": f"Ya hay un deployment activo para {domain}", "deployment": existing}

    deploy_id = f"deploy-{uuid.uuid4().hex[:8]}"
    safe_name = re.sub(r'[^a-z0-9]', '-', domain.lower())[:30]
    project = _GCP_PROJECT
    region = _GCP_REGION
    zone = _GCP_ZONE

    # Resource names
    network_name = f"tokio-waf-{safe_name}"
    subnet_name = f"tokio-waf-sub-{safe_name}"
    fw_name = f"tokio-waf-allow-{safe_name}"
    ip_name = f"tokio-waf-ip-{safe_name}"

    _notify(f"🚀 Desplegando *TokioAI WAF* auto-escalable en GCP para `{domain}`...")
    steps = []

    try:
        # --- Phase 1: Network Infrastructure ---
        r = _ensure_network(compute_v1, creds, project, network_name)
        steps.append(f"network ({r})")

        r = _ensure_subnet(compute_v1, creds, project, region, subnet_name, network_name)
        steps.append(f"subnet ({r})")

        r = _ensure_firewall(compute_v1, creds, project, fw_name, network_name)
        steps.append(f"firewall ({r})")

        waf_ip = _ensure_static_ip(compute_v1, creds, project, region, ip_name)
        steps.append(f"IP estática: {waf_ip}")

        if mode == "simple":
            # --- Simple Mode: Single VM with static IP ---
            return _deploy_simple_vm(
                compute_v1, creds, project, region, zone,
                domain, backend_url, safe_name, deploy_id,
                network_name, subnet_name, fw_name, ip_name, waf_ip,
                steps, state,
            )

        # --- Phase 2: Auto-Scaling Infrastructure ---
        hc_name = f"tokio-waf-hc-{safe_name}"
        template_name = f"tokio-waf-tmpl-{safe_name}"
        mig_name = f"tokio-waf-mig-{safe_name}"
        as_name = f"tokio-waf-as-{safe_name}"
        bs_name = f"tokio-waf-bs-{safe_name}"
        fr_name_http = f"tokio-waf-fr-http-{safe_name}"
        fr_name_https = f"tokio-waf-fr-https-{safe_name}"
        fr_name_dash = f"tokio-waf-fr-dash-{safe_name}"

        # Health Check (monitors dashboard /health endpoint)
        r = _ensure_health_check(compute_v1, creds, project, hc_name)
        steps.append(f"health-check ({r})")

        # Instance Template (reproducible VM config)
        startup = _startup_script(domain, backend_url)
        r = _ensure_instance_template(
            compute_v1, creds, project, zone, template_name,
            startup, network_name, subnet_name, region,
        )
        steps.append(f"instance-template ({r})")

        # Managed Instance Group (auto-healing)
        r = _ensure_mig(compute_v1, creds, project, zone, mig_name, template_name, hc_name, f"tokio-waf-{safe_name}")
        steps.append(f"MIG ({r})")

        # Autoscaler (CPU-based scaling)
        r = _ensure_autoscaler(compute_v1, creds, project, zone, as_name, mig_name, 1, max_replicas)
        steps.append(f"autoscaler min=1 max={max_replicas} ({r})")

        # Network Load Balancer (static IP → MIG)
        lb_results = _ensure_network_lb(
            compute_v1, creds, project, region, zone,
            bs_name, fr_name_http, fr_name_https, fr_name_dash,
            mig_name, hc_name, waf_ip,
        )
        steps.extend(lb_results)

        # --- Phase 3: DNS + Notifications ---
        dns_result = {"ok": False, "message": "DNS update skipped"}
        if _HOSTINGER_API_KEY and waf_ip:
            try:
                from .hostinger_tools import hostinger_dns
                dns_raw = hostinger_dns("upsert_record", {
                    "domain": domain, "type": "A", "host": "", "value": waf_ip, "ttl": 300,
                })
                dns_result = json.loads(dns_raw) if isinstance(dns_raw, str) else dns_raw
                steps.append(f"DNS: {domain} → {waf_ip}")
            except Exception as e:
                dns_result = {"ok": False, "error": str(e)}

        # Wait for first MIG instance to come up
        mig_vm_ip = _get_mig_instance_ip(compute_v1, creds, project, zone, mig_name, timeout=120)
        if mig_vm_ip:
            steps.append(f"MIG VM arrancando: {mig_vm_ip}")

        # Save state
        deployment = {
            "deploy_id": deploy_id,
            "domain": domain,
            "backend_url": backend_url,
            "status": "active",
            "architecture": "autoscaled",
            "waf_ip": waf_ip,
            "mig_vm_ip": mig_vm_ip,
            "postgres_host": waf_ip,
            "postgres_port": 5432,
            "postgres_db": _PG_DB,
            "postgres_user": _PG_USER,
            "postgres_password": _PG_PASS,
            "dashboard_url": f"http://{waf_ip}:8000",
            "network_name": network_name,
            "subnet_name": subnet_name,
            "firewall_name": fw_name,
            "ip_name": ip_name,
            "hc_name": hc_name,
            "template_name": template_name,
            "mig_name": mig_name,
            "autoscaler_name": as_name,
            "backend_service_name": bs_name,
            "fr_names": [fr_name_http, fr_name_https, fr_name_dash],
            "gcp_project": project,
            "gcp_region": region,
            "gcp_zone": zone,
            "max_replicas": max_replicas,
            "created_at": datetime.now().isoformat(),
            "steps": steps,
            "dns_update": dns_result,
        }
        state["deployments"][domain] = deployment
        _save_state(state)

        _notify(
            f"✅ *TokioAI WAF* auto-escalable desplegado para `{domain}`\n\n"
            f"🌐 LB IP: `{waf_ip}`\n"
            f"📊 Dashboard: http://{waf_ip}:8000\n"
            f"🗄️ PostgreSQL: `{waf_ip}:5432`\n"
            f"⚡ Auto-scale: 1→{max_replicas} VMs (CPU>70%)\n"
            f"🛡️ Auto-heal: MIG recrea VMs si fallan\n"
            f"🔐 DNS: {'✅' if dns_result.get('ok') else '⏳'}\n\n"
            f"Pasos: {len(steps)}"
        )

        return {
            "ok": True,
            "deploy_id": deploy_id,
            "domain": domain,
            "waf_ip": waf_ip,
            "dashboard_url": f"http://{waf_ip}:8000",
            "postgres_dsn": f"postgresql://{_PG_USER}:{_PG_PASS}@{waf_ip}:5432/{_PG_DB}",
            "architecture": "autoscaled",
            "autoscaling": {"min": 1, "max": max_replicas, "target_cpu": "70%"},
            "steps": steps,
            "dns_update": dns_result,
            "message": (
                f"WAF auto-escalable desplegado en GCP. LB IP: {waf_ip}\n"
                f"Auto-heal: ✅ | Autoscale: 1→{max_replicas} VMs | Health check: cada 30s"
            ),
        }

    except Exception as e:
        _notify(f"❌ Error desplegando WAF auto-escalable en GCP: {e}")
        return {"ok": False, "error": str(e), "steps_done": steps}


def _deploy_simple_vm(compute_v1, creds, project, region, zone,
                      domain, backend_url, safe_name, deploy_id,
                      network_name, subnet_name, fw_name, ip_name, waf_ip,
                      steps, state) -> Dict[str, Any]:
    """Legacy simple single-VM deployment (no auto-scaling)."""
    instance_name = f"tokio-waf-{safe_name}"
    inst_client = compute_v1.InstancesClient(credentials=creds) if creds else compute_v1.InstancesClient()
    try:
        inst_client.get(project=project, zone=zone, instance=instance_name)
        steps.append("VM (ya existía)")
    except Exception:
        startup = _startup_script(domain, backend_url)
        instance = compute_v1.Instance(
            name=instance_name,
            machine_type=f"zones/{zone}/machineTypes/{_GCP_MACHINE_TYPE}",
            tags=compute_v1.Tags(items=["tokio-waf"]),
            disks=[compute_v1.AttachedDisk(
                auto_delete=True, boot=True,
                initialize_params=compute_v1.AttachedDiskInitializeParams(
                    source_image="projects/ubuntu-os-cloud/global/images/family/ubuntu-2204-lts",
                    disk_size_gb=40, disk_type=f"zones/{zone}/diskTypes/pd-ssd",
                ),
            )],
            network_interfaces=[compute_v1.NetworkInterface(
                subnetwork=f"projects/{project}/regions/{region}/subnetworks/{subnet_name}",
                access_configs=[compute_v1.AccessConfig(
                    name="External NAT", nat_i_p=waf_ip, type_="ONE_TO_ONE_NAT",
                )],
            )],
            metadata=compute_v1.Metadata(
                items=[compute_v1.Items(key="startup-script", value=startup)],
            ),
            labels={"managed-by": "tokioai", "domain": safe_name, "deploy-id": deploy_id},
            service_accounts=[compute_v1.ServiceAccount(
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )],
        )
        op = inst_client.insert(project=project, zone=zone, instance_resource=instance)
        _wait_for_operation(compute_v1, creds, project, zone, op.name, timeout=300)
        steps.append("VM creada y arrancando")

    dns_result = {"ok": False, "message": "DNS update skipped"}
    if _HOSTINGER_API_KEY and waf_ip:
        try:
            from .hostinger_tools import hostinger_dns
            dns_raw = hostinger_dns("upsert_record", {
                "domain": domain, "type": "A", "host": "", "value": waf_ip, "ttl": 300,
            })
            dns_result = json.loads(dns_raw) if isinstance(dns_raw, str) else dns_raw
            steps.append(f"DNS: {domain} → {waf_ip}")
        except Exception as e:
            dns_result = {"ok": False, "error": str(e)}

    deployment = {
        "deploy_id": deploy_id, "domain": domain, "backend_url": backend_url,
        "status": "active", "architecture": "simple",
        "waf_ip": waf_ip, "postgres_host": waf_ip, "postgres_port": 5432,
        "postgres_db": _PG_DB, "postgres_user": _PG_USER, "postgres_password": _PG_PASS,
        "dashboard_url": f"http://{waf_ip}:8000",
        "instance_name": instance_name, "network_name": network_name,
        "subnet_name": subnet_name, "firewall_name": fw_name, "ip_name": ip_name,
        "gcp_project": project, "gcp_region": region, "gcp_zone": zone,
        "created_at": datetime.now().isoformat(), "steps": steps, "dns_update": dns_result,
    }
    state["deployments"][domain] = deployment
    _save_state(state)

    _notify(
        f"✅ *TokioAI WAF* (simple) desplegado para `{domain}`\n"
        f"🌐 IP: `{waf_ip}` | 📊 Dashboard: http://{waf_ip}:8000"
    )
    return {
        "ok": True, "deploy_id": deploy_id, "domain": domain,
        "waf_ip": waf_ip, "dashboard_url": f"http://{waf_ip}:8000",
        "architecture": "simple", "steps": steps, "dns_update": dns_result,
        "message": f"WAF simple desplegado en GCP. IP: {waf_ip}",
    }


# ---------------------------------------------------------------------------
# Destroy — Handles both simple and autoscaled architectures
# ---------------------------------------------------------------------------

def _safe_delete(desc: str, fn, steps: list):
    """Run a delete function, catching errors. Appends result to steps."""
    try:
        fn()
        steps.append(f"✅ {desc}")
    except Exception as e:
        err_str = str(e)
        if "was not found" in err_str or "404" in err_str:
            steps.append(f"⏭️ {desc} (no existía)")
        else:
            steps.append(f"⚠️ {desc}: {err_str[:100]}")


def _destroy(params: Dict[str, Any]) -> Dict[str, Any]:
    """Destroy GCP WAF infra and restore DNS. Handles simple + autoscaled."""
    domain = params.get("domain", "").strip()
    if not domain:
        return {"ok": False, "error": "domain es requerido"}

    state = _load_state()
    dep = state["deployments"].get(domain)
    if not dep or dep.get("status") != "active":
        return {"ok": False, "error": f"No hay deployment activo para {domain}"}

    compute_v1, creds = _get_compute_client()
    if compute_v1 is None:
        return {"ok": False, "error": "google-cloud-compute no instalado"}

    project = dep.get("gcp_project", _GCP_PROJECT)
    region = dep.get("gcp_region", _GCP_REGION)
    zone = dep.get("gcp_zone", _GCP_ZONE)
    arch = dep.get("architecture", "simple")

    _notify(f"🔥 Destruyendo *TokioAI WAF* ({arch}) en GCP para `{domain}`...")
    steps = []

    # --- Autoscaled architecture: delete LB → Autoscaler → MIG → Template → HC ---
    if arch == "autoscaled":
        # 1. Delete Forwarding Rules
        fr_client = compute_v1.ForwardingRulesClient(credentials=creds) if creds else compute_v1.ForwardingRulesClient()
        for fr_name in dep.get("fr_names", []):
            _safe_delete(f"Forwarding Rule {fr_name}", lambda n=fr_name: (
                _wait_for_region_op(compute_v1, creds, project, region,
                    fr_client.delete(project=project, region=region, forwarding_rule=n).name)
            ), steps)

        # 2. Delete Backend Service
        bs_name = dep.get("backend_service_name", "")
        if bs_name:
            bs_client = compute_v1.RegionBackendServicesClient(credentials=creds) if creds else compute_v1.RegionBackendServicesClient()
            _safe_delete("Backend Service", lambda: (
                _wait_for_region_op(compute_v1, creds, project, region,
                    bs_client.delete(project=project, region=region, backend_service=bs_name).name)
            ), steps)

        # 3. Delete Autoscaler
        as_name = dep.get("autoscaler_name", "")
        if as_name:
            as_client = compute_v1.AutoscalersClient(credentials=creds) if creds else compute_v1.AutoscalersClient()
            _safe_delete("Autoscaler", lambda: (
                _wait_for_operation(compute_v1, creds, project, zone,
                    as_client.delete(project=project, zone=zone, autoscaler=as_name).name)
            ), steps)

        # 4. Delete MIG (also deletes VMs)
        mig_name = dep.get("mig_name", "")
        if mig_name:
            mig_client = compute_v1.InstanceGroupManagersClient(credentials=creds) if creds else compute_v1.InstanceGroupManagersClient()
            _safe_delete("MIG + VMs", lambda: (
                _wait_for_operation(compute_v1, creds, project, zone,
                    mig_client.delete(project=project, zone=zone, instance_group_manager=mig_name).name, timeout=600)
            ), steps)

        # 5. Delete Instance Template
        tmpl_name = dep.get("template_name", "")
        if tmpl_name:
            tmpl_client = compute_v1.InstanceTemplatesClient(credentials=creds) if creds else compute_v1.InstanceTemplatesClient()
            _safe_delete("Instance Template", lambda: (
                _wait_for_global_op(compute_v1, creds, project,
                    tmpl_client.delete(project=project, instance_template=tmpl_name).name)
            ), steps)

        # 6. Delete Health Check
        hc_name = dep.get("hc_name", "")
        if hc_name:
            hc_client = compute_v1.HealthChecksClient(credentials=creds) if creds else compute_v1.HealthChecksClient()
            _safe_delete("Health Check", lambda: (
                _wait_for_global_op(compute_v1, creds, project,
                    hc_client.delete(project=project, health_check=hc_name).name)
            ), steps)

    else:
        # --- Simple architecture: just delete the VM ---
        inst_name = dep.get("instance_name", "")
        if inst_name:
            inst_client = compute_v1.InstancesClient(credentials=creds) if creds else compute_v1.InstancesClient()
            _safe_delete("VM", lambda: (
                _wait_for_operation(compute_v1, creds, project, zone,
                    inst_client.delete(project=project, zone=zone, instance=inst_name).name, timeout=300)
            ), steps)

    # --- Common: Release IP, Firewall, Subnet, Network ---
    ip_name = dep.get("ip_name", "")
    if ip_name:
        addr_client = compute_v1.AddressesClient(credentials=creds) if creds else compute_v1.AddressesClient()
        _safe_delete("IP estática", lambda: (
            _wait_for_region_op(compute_v1, creds, project, region,
                addr_client.delete(project=project, region=region, address=ip_name).name)
        ), steps)

    fw_name = dep.get("firewall_name", "")
    if fw_name:
        fw_client = compute_v1.FirewallsClient(credentials=creds) if creds else compute_v1.FirewallsClient()
        _safe_delete("Firewall", lambda: (
            _wait_for_global_op(compute_v1, creds, project,
                fw_client.delete(project=project, firewall=fw_name).name)
        ), steps)

    subnet_name = dep.get("subnet_name", "")
    if subnet_name:
        sub_client = compute_v1.SubnetworksClient(credentials=creds) if creds else compute_v1.SubnetworksClient()
        _safe_delete("Subnet", lambda: (
            _wait_for_region_op(compute_v1, creds, project, region,
                sub_client.delete(project=project, region=region, subnetwork=subnet_name).name)
        ), steps)

    network_name = dep.get("network_name", "")
    if network_name:
        net_client = compute_v1.NetworksClient(credentials=creds) if creds else compute_v1.NetworksClient()
        _safe_delete("Network", lambda: (
            _wait_for_global_op(compute_v1, creds, project,
                net_client.delete(project=project, network=network_name).name)
        ), steps)

    # --- Restore DNS ---
    dns_result = {"ok": False, "message": "DNS restore skipped"}
    backend_url = dep.get("backend_url", "")
    if _HOSTINGER_API_KEY and backend_url:
        try:
            ip_match = re.search(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', backend_url)
            if ip_match:
                from .hostinger_tools import hostinger_dns
                dns_raw = hostinger_dns("upsert_record", {
                    "domain": domain, "type": "A", "host": "",
                    "value": ip_match.group(1), "ttl": 300,
                })
                dns_result = json.loads(dns_raw) if isinstance(dns_raw, str) else dns_raw
                steps.append(f"DNS restaurado: {ip_match.group(1)}")
        except Exception as e:
            dns_result = {"ok": False, "error": str(e)}

    # --- Update state ---
    dep["status"] = "destroyed"
    dep["destroyed_at"] = datetime.now().isoformat()
    dep["destroy_steps"] = steps
    state["deployments"][domain] = dep
    _save_state(state)

    _notify(
        f"💥 *TokioAI WAF* ({arch}) destruido para `{domain}`\n"
        f"DNS: {'✅' if dns_result.get('ok') else '⏳'} | Pasos: {len(steps)}"
    )

    return {"ok": True, "domain": domain, "architecture": arch, "steps": steps,
            "dns_restore": dns_result,
            "message": f"Infra GCP ({arch}) eliminada. {domain} restaurado a Hostinger."}


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def _status(params: Dict[str, Any]) -> Dict[str, Any]:
    domain = params.get("domain", "").strip()
    state = _load_state()
    if domain:
        dep = state["deployments"].get(domain)
        return {"ok": True, "deployment": dep} if dep else {"ok": True, "status": "not_deployed"}
    return {
        "ok": True,
        "deployments": [
            {"domain": d, "status": i.get("status"), "waf_ip": i.get("waf_ip"), "created_at": i.get("created_at")}
            for d, i in state["deployments"].items()
        ],
    }


# ---------------------------------------------------------------------------
# Query (remote — no data downloaded to Raspberry Pi)
# ---------------------------------------------------------------------------

def _query(params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Query WAF logs usando endpoints internos del dashboard (seguro)
    o conexión directa como fallback si el dashboard no está disponible.
    """
    domain = params.get("domain", "").strip()
    query = params.get("query", "").strip()
    analysis = params.get("analysis", "").strip()
    ip = params.get("ip", "").strip()
    days = int(params.get("days", 1))

    state = _load_state()
    dep = state["deployments"].get(domain) if domain else None
    if not dep:
        for d, info in state["deployments"].items():
            if info.get("status") == "active":
                dep = info; domain = d; break

    if not dep or dep.get("status") != "active":
        return {"ok": False, "error": "No hay deployment GCP activo. Usá gcp_waf deploy primero."}

    # Obtener URL del dashboard y token de autenticación
    dashboard_url = dep.get("dashboard_url", f"http://{dep.get('waf_ip', 'localhost')}:8000")
    automation_token = os.getenv("AUTOMATION_API_TOKEN", "").strip()
    
    # Intentar usar endpoint interno del dashboard (más seguro)
    if ip:
        try:
            import requests
            # Usar endpoint interno para búsqueda por IP
            api_url = f"{dashboard_url}/api/internal/search-waf-logs"
            headers = {}
            if automation_token:
                headers["X-Automation-Token"] = automation_token
            
            params_req = {
                "ip": ip,
                "days": days,
                "limit": 1000
            }
            
            resp = requests.post(api_url, json=params_req, headers=headers, timeout=30)
            
            if resp.status_code == 200:
                data = resp.json()
                if data.get("success"):
                    logs = data.get("logs", [])
                    # Convertir a formato compatible con la respuesta esperada
                    formatted_data = []
                    for log in logs:
                        formatted_data.append({
                            "timestamp": log.get("timestamp") or log.get("created_at"),
                            "ip": log.get("ip"),
                            "method": log.get("method", ""),
                            "uri": log.get("uri", ""),
                            "status": log.get("status"),
                            "severity": log.get("severity"),
                            "blocked": log.get("blocked"),
                            "threat_type": log.get("threat_type"),
                            "host": log.get("host", ""),
                        })
                    
                    return {
                        "ok": True,
                        "domain": domain,
                        "rows": len(formatted_data),
                        "columns": list(formatted_data[0].keys()) if formatted_data else [],
                        "data": formatted_data,
                        "message": f"Encontrados {len(formatted_data)} registros para IP {ip}",
                        "source": "dashboard_api"  # Indicar que vino del API
                    }
                else:
                    # Si el API falla, continuar con conexión directa
                    logger.warning(f"Dashboard API retornó error: {data.get('error')}")
            else:
                logger.warning(f"Dashboard API no disponible (HTTP {resp.status_code}), usando fallback")
        except Exception as e:
            logger.warning(f"Error usando dashboard API: {e}, usando conexión directa como fallback")
    
    # Fallback: conexión directa a PostgreSQL (solo si el dashboard no está disponible)
    predefined = {
        "top_ips": "SELECT ip, COUNT(*) as hits FROM waf_logs WHERE ip NOT IN ('unknown','-') GROUP BY ip ORDER BY hits DESC LIMIT 20",
        "top_attacks": "SELECT ip, uri, severity, COUNT(*) FROM waf_logs WHERE severity IN ('critical','high') GROUP BY ip,uri,severity ORDER BY 4 DESC LIMIT 20",
        "recent_blocks": "SELECT ip, reason, blocked_at, threat_type, severity FROM blocked_ips WHERE active=true ORDER BY blocked_at DESC LIMIT 20",
        "episodes": "SELECT episode_id, src_ip, attack_type, severity, total_requests, start_time FROM episodes ORDER BY start_time DESC LIMIT 20",
        "summary": "SELECT COUNT(*) total, COUNT(CASE WHEN blocked THEN 1 END) blocked, COUNT(DISTINCT ip) ips, COUNT(CASE WHEN severity='critical' THEN 1 END) critical, MIN(timestamp) first_log, MAX(timestamp) last_log FROM waf_logs",
        "hourly_traffic": "SELECT date_trunc('hour',timestamp) hour, COUNT(*) reqs, COUNT(CASE WHEN blocked THEN 1 END) blocked, COUNT(DISTINCT ip) ips FROM waf_logs WHERE timestamp>NOW()-INTERVAL '24h' GROUP BY 1 ORDER BY 1 DESC",
    }

    # Si se especifica una IP y no se usó el API, usar SQL directo
    if ip:
        sql = f"""SELECT timestamp, ip, method, uri, status, severity, blocked, threat_type, owasp_code, sig_id, host, user_agent 
                  FROM waf_logs 
                  WHERE (ip = %s OR ip::text ILIKE %s) 
                    AND (timestamp >= NOW() - INTERVAL '{days} days' OR created_at >= NOW() - INTERVAL '{days} days')
                  ORDER BY COALESCE(timestamp, created_at) DESC 
                  LIMIT 1000"""
        sql_params = [ip, f"%{ip}%"]
    elif analysis and analysis.lower() in predefined:
        sql = predefined[analysis.lower()]
        sql_params = []
    elif query:
        if not query.strip().upper().startswith("SELECT"):
            return {"ok": False, "error": "Solo se permiten consultas SELECT (read-only)."}
        sql = query
        sql_params = []
    else:
        return {"ok": False, "error": f"Especificá 'analysis', 'query' o 'ip'. Disponibles: {', '.join(predefined.keys())}"}

    # Intentar conexión directa (fallback)
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        
        # Intentar usar el dashboard URL primero (si está en la misma red)
        postgres_host = dep.get("postgres_host", dep.get("waf_ip"))
        
        # Si el host es la IP pública y está bloqueada, intentar usar localhost si estamos en la VM
        # o usar el endpoint del dashboard
        conn = psycopg2.connect(
            host=postgres_host,
            port=int(dep.get("postgres_port", 5432)),
            dbname=dep.get("postgres_db", _PG_DB),
            user=dep.get("postgres_user", _PG_USER),
            password=dep.get("postgres_password", _PG_PASS),
            connect_timeout=15,
        )
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            if sql_params:
                cur.execute(sql, sql_params)
            else:
                cur.execute(sql)
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description] if cur.description else []
            
            formatted_data = []
            for r in rows[:1000]:
                row_dict = {}
                for k, v in r.items():
                    if v is None:
                        row_dict[k] = None
                    elif isinstance(v, (datetime,)):
                        row_dict[k] = v.isoformat()
                    else:
                        row_dict[k] = str(v)
                formatted_data.append(row_dict)
            
            if len(rows) == 0 and ip:
                debug_sql = "SELECT COUNT(*) as total FROM waf_logs WHERE ip = %s OR ip::text ILIKE %s"
                cur.execute(debug_sql, [ip, f"%{ip}%"])
                debug_result = cur.fetchone()
                total_count = debug_result.get("total", 0) if debug_result else 0
                
                return {
                    "ok": True,
                    "domain": domain,
                    "rows": 0,
                    "columns": cols,
                    "data": [],
                    "message": f"No se encontraron registros para IP {ip} en los últimos {days} días. Total histórico: {total_count} registros.",
                    "debug": {
                        "ip_searched": ip,
                        "days": days,
                        "total_historical": total_count,
                    }
                }
            
            return {
                "ok": True, 
                "domain": domain, 
                "rows": len(rows), 
                "columns": cols,
                "data": formatted_data,
                "message": f"Encontrados {len(rows)} registros" + (f" para IP {ip}" if ip else ""),
                "source": "postgresql_direct"
            }
        finally:
            cur.close()
            conn.close()
    except Exception as e:
        logger.error(f"Error en gcp_waf query: {e}", exc_info=True)
        error_msg = str(e)
        
        # Mensaje más claro si es timeout o conexión rechazada
        if "timeout" in error_msg.lower() or "timed out" in error_msg.lower():
            return {
                "ok": False, 
                "error": f"Timeout conectando a PostgreSQL. El puerto 5432 está bloqueado por seguridad. Usá el endpoint del dashboard API en su lugar.",
                "suggestion": "El dashboard API debería estar disponible en el deployment. Verifica que el dashboard esté corriendo."
            }
        elif "connection" in error_msg.lower() or "refused" in error_msg.lower() or "ECONNREFUSED" in error_msg:
            return {
                "ok": False,
                "error": f"No se pudo conectar a PostgreSQL en {postgres_host}:5432. El puerto está bloqueado por seguridad.",
                "suggestion": "Usa el endpoint interno del dashboard API. Verifica que AUTOMATION_API_TOKEN esté configurado."
            }
        else:
            return {
                "ok": False, 
                "error": f"Error conectando a PostgreSQL: {error_msg}",
                "suggestion": "Verifica que el deployment esté activo y que PostgreSQL esté accesible, o usa el dashboard API."
            }


# ---------------------------------------------------------------------------
# Scale — Adjust MIG size or autoscaler limits
# ---------------------------------------------------------------------------

def _scale(params: Dict[str, Any]) -> Dict[str, Any]:
    """Scale MIG: adjust min/max replicas or set target size."""
    domain = params.get("domain", "").strip()
    min_replicas = params.get("min_replicas")
    max_replicas = params.get("max_replicas")
    target_size = params.get("target_size")

    state = _load_state()
    dep = state["deployments"].get(domain) if domain else None
    if not dep:
        for d, info in state["deployments"].items():
            if info.get("status") == "active":
                dep = info; domain = d; break

    if not dep or dep.get("status") != "active":
        return {"ok": False, "error": "No hay deployment activo"}

    if dep.get("architecture") != "autoscaled":
        return {"ok": False, "error": f"El deployment de {domain} es 'simple' (sin MIG). Redesplegá con mode=auto para auto-scaling."}

    compute_v1, creds = _get_compute_client()
    if compute_v1 is None:
        return {"ok": False, "error": "google-cloud-compute no instalado"}

    project = dep.get("gcp_project", _GCP_PROJECT)
    zone = dep.get("gcp_zone", _GCP_ZONE)
    results = []

    # Update autoscaler limits
    if min_replicas is not None or max_replicas is not None:
        as_name = dep.get("autoscaler_name", "")
        if as_name:
            as_client = compute_v1.AutoscalersClient(credentials=creds) if creds else compute_v1.AutoscalersClient()
            try:
                current = as_client.get(project=project, zone=zone, autoscaler=as_name)
                policy = current.autoscaling_policy
                if min_replicas is not None:
                    policy.min_num_replicas = int(min_replicas)
                if max_replicas is not None:
                    policy.max_num_replicas = int(max_replicas)
                current.autoscaling_policy = policy
                op = as_client.update(project=project, zone=zone, autoscaler_resource=current)
                _wait_for_operation(compute_v1, creds, project, zone, op.name)
                results.append(f"Autoscaler actualizado: min={policy.min_num_replicas}, max={policy.max_num_replicas}")
                dep["max_replicas"] = policy.max_num_replicas
                _save_state(state)
            except Exception as e:
                results.append(f"Error actualizando autoscaler: {e}")

    # Set specific target size (overrides autoscaler temporarily)
    if target_size is not None:
        mig_name = dep.get("mig_name", "")
        if mig_name:
            mig_client = compute_v1.InstanceGroupManagersClient(credentials=creds) if creds else compute_v1.InstanceGroupManagersClient()
            try:
                op = mig_client.resize(project=project, zone=zone,
                    instance_group_manager=mig_name, size=int(target_size))
                _wait_for_operation(compute_v1, creds, project, zone, op.name)
                results.append(f"MIG redimensionado a {target_size} instancias")
            except Exception as e:
                results.append(f"Error redimensionando MIG: {e}")

    return {"ok": True, "domain": domain, "results": results}


# ---------------------------------------------------------------------------
# Block / Unblock IPs via Dashboard API
# ---------------------------------------------------------------------------

def _block(params: Dict[str, Any]) -> Dict[str, Any]:
    """Bloquear o desbloquear una IP a través de la Dashboard API."""
    import requests as _req

    ip = params.get("ip", "").strip()
    action_type = params.get("type", "block").strip().lower()  # block | unblock
    reason = params.get("reason", "Bloqueado por TokioAI")
    duration_hours = int(params.get("duration_hours", 24))

    if not ip:
        return {"ok": False, "error": "Se requiere el parámetro 'ip'"}

    # Find the dashboard API URL from state
    state = _load_state()
    dashboard_url = None
    for domain, dep in state.get("deployments", {}).items():
        vm_ip = dep.get("vm_ip", "")
        if vm_ip:
            dashboard_url = f"http://{vm_ip}:8000"
            break

    if not dashboard_url:
        return {"ok": False, "error": "No se encontró un deployment activo con dashboard"}

    # Login
    dash_user = os.environ.get("DASHBOARD_USER", "admin")
    dash_pass = os.environ.get("DASHBOARD_PASSWORD", "PrXtjL5EXrnP27wUwSz6dIoW")
    try:
        login_resp = _req.post(f"{dashboard_url}/api/auth/login",
                               json={"username": dash_user, "password": dash_pass}, timeout=10)
        token = login_resp.json().get("token")
        if not token:
            return {"ok": False, "error": "No se pudo autenticar con el dashboard"}
    except Exception as e:
        return {"ok": False, "error": f"Error conectando al dashboard: {e}"}

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    if action_type == "unblock":
        try:
            resp = _req.delete(f"{dashboard_url}/api/blocked/{ip}", headers=headers, timeout=10)
            return {"ok": True, "action": "unblock", "ip": ip, "response": resp.json()}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    else:
        try:
            resp = _req.post(f"{dashboard_url}/api/blocked",
                             json={"ip": ip, "reason": reason, "duration_hours": duration_hours},
                             headers=headers, timeout=10)
            return {"ok": True, "action": "block", "ip": ip, "duration_hours": duration_hours, "response": resp.json()}
        except Exception as e:
            return {"ok": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def gcp_waf(action: str, params: Optional[Dict[str, Any]] = None) -> str:
    """
    GCP WAF Full Stack — Auto-Scaling, Plug & Play.

    Actions:
      setup    — Verificar prerequisitos y guiar configuración
      deploy   — Deploy auto-escalable (domain, backend_url, mode=auto|simple, max_replicas=3)
      destroy  — Destruir infra completa, restaurar DNS (domain)
      status   — Estado del deployment (domain opcional)
      query    — Consulta remota a PG (analysis o query SQL)
      scale    — Escalar MIG (domain, min_replicas, max_replicas, target_size)
      block    — Bloquear/desbloquear IP (ip, type=block|unblock, reason, duration_hours)
    """
    params = params or {}
    action = (action or "").strip().lower()
    handlers = {
        "setup": _setup, "deploy": _deploy, "destroy": _destroy,
        "status": _status, "query": _query, "scale": _scale,
        "block": _block,
    }
    handler = handlers.get(action)
    if not handler:
        return json.dumps({
            "ok": False,
            "error": f"Acción '{action}' no soportada. Usa: setup|deploy|destroy|status|query|scale|block"
        }, ensure_ascii=False)
    return json.dumps(handler(params), ensure_ascii=False, indent=2, default=str)
