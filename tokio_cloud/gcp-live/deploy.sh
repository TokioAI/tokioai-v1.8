#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════════════
# TokioAI WAF — Deploy Script (GCP VM)
# Syncs local gcp-live/ files to the GCP VM and restarts containers safely
# ═══════════════════════════════════════════════════════════════════════════════
set -euo pipefail

# ─── Config ───────────────────────────────────────────────────────────────────
GCP_HOST="${GCP_HOST:-YOUR_GCP_VM_IP}"
GCP_USER="${GCP_USER:-YOUR_SSH_USER}"
GCP_DIR="/opt/tokio-waf"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/google_compute_engine}"
SSH_CMD="ssh -i $SSH_KEY -o StrictHostKeyChecking=no -o ConnectTimeout=10"
SCP_CMD="scp -i $SSH_KEY -o StrictHostKeyChecking=no"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR="/opt/tokio-waf/backups/$TIMESTAMP"

# Telegram notification (optional)
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TELEGRAM_CHAT_ID="${TELEGRAM_OWNER_CHAT_ID:-}"

# ─── Colors ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log()   { echo -e "${CYAN}[deploy]${NC} $1"; }
ok()    { echo -e "${GREEN}[OK]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
fail()  { echo -e "${RED}[FAIL]${NC} $1"; }

notify() {
    if [ -n "$TELEGRAM_BOT_TOKEN" ] && [ -n "$TELEGRAM_CHAT_ID" ]; then
        curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
            -d chat_id="$TELEGRAM_CHAT_ID" \
            -d text="$1" \
            -d parse_mode="Markdown" > /dev/null 2>&1 || true
    fi
}

# ─── Files to deploy ──────────────────────────────────────────────────────────
FILES=(
    "docker-compose.yml"
    "nginx.conf"
    "realtime-processor.py"
    "dashboard-app.py"
    "dashboard-db.py"
    "geoip_helper.py"
    "init-db.sql"
    "log-processor.py"
)

# ─── Pre-flight checks ───────────────────────────────────────────────────────
log "TokioAI WAF Deploy — $TIMESTAMP"
log "Target: $GCP_USER@$GCP_HOST:$GCP_DIR"
echo ""

# Check all files exist locally
log "Checking local files..."
for f in "${FILES[@]}"; do
    if [ ! -f "$SCRIPT_DIR/$f" ]; then
        fail "Missing: $SCRIPT_DIR/$f"
        exit 1
    fi
done
ok "All ${#FILES[@]} files present"

# Test SSH connection
log "Testing SSH connection..."
if ! $SSH_CMD "$GCP_USER@$GCP_HOST" "echo ok" > /dev/null 2>&1; then
    fail "Cannot connect to $GCP_HOST"
    exit 1
fi
ok "SSH connection OK"

# Check containers are running
log "Checking current container status..."
CONTAINERS=$($SSH_CMD "$GCP_USER@$GCP_HOST" "sudo docker ps --format '{{.Names}} {{.Status}}'" 2>/dev/null)
echo "$CONTAINERS"
echo ""

# ─── Confirm ──────────────────────────────────────────────────────────────────
echo -e "${YELLOW}This will deploy to PRODUCTION (${GCP_HOST}).${NC}"
read -p "Continue? [y/N] " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    log "Aborted."
    exit 0
fi

# ─── Backup ───────────────────────────────────────────────────────────────────
log "Creating backup at $BACKUP_DIR..."
$SSH_CMD "$GCP_USER@$GCP_HOST" "sudo mkdir -p $BACKUP_DIR && sudo cp $GCP_DIR/*.py $GCP_DIR/*.yml $GCP_DIR/*.conf $GCP_DIR/*.sql $BACKUP_DIR/ 2>/dev/null; echo 'Backup done'"
ok "Backup created"

# ─── Upload files ─────────────────────────────────────────────────────────────
log "Uploading files..."
for f in "${FILES[@]}"; do
    $SCP_CMD "$SCRIPT_DIR/$f" "$GCP_USER@$GCP_HOST:/tmp/tokio-deploy-$f"
    $SSH_CMD "$GCP_USER@$GCP_HOST" "sudo cp /tmp/tokio-deploy-$f $GCP_DIR/$f && rm /tmp/tokio-deploy-$f"
    ok "  $f"
done
ok "All files uploaded"

# ─── Restart containers (one by one, zero-downtime) ───────────────────────────
log "Restarting containers..."
notify "🔄 *Deploy Started* — $TIMESTAMP"

# 1. Realtime processor (safe to restart, will reconnect to Kafka)
log "  Restarting realtime-processor..."
$SSH_CMD "$GCP_USER@$GCP_HOST" "cd $GCP_DIR && sudo docker compose restart realtime-processor" 2>/dev/null
ok "  realtime-processor restarted"

# 2. Dashboard API (safe to restart)
log "  Restarting dashboard-api..."
$SSH_CMD "$GCP_USER@$GCP_HOST" "cd $GCP_DIR && sudo docker compose restart dashboard-api" 2>/dev/null
ok "  dashboard-api restarted"

# 3. Log processor (will reconnect to Kafka)
log "  Restarting log-processor..."
$SSH_CMD "$GCP_USER@$GCP_HOST" "cd $GCP_DIR && sudo docker compose restart log-processor" 2>/dev/null
ok "  log-processor restarted"

# 4. Nginx WAF proxy (reload config without downtime)
log "  Reloading nginx config..."
$SSH_CMD "$GCP_USER@$GCP_HOST" "sudo docker exec tokio-gcp-waf-proxy nginx -t 2>&1 && sudo docker exec tokio-gcp-waf-proxy nginx -s reload" 2>/dev/null
if [ $? -eq 0 ]; then
    ok "  nginx config reloaded"
else
    warn "  nginx config test failed, restarting container..."
    $SSH_CMD "$GCP_USER@$GCP_HOST" "cd $GCP_DIR && sudo docker compose restart waf-proxy" 2>/dev/null
fi

# ─── Health checks ────────────────────────────────────────────────────────────
log "Running health checks..."
sleep 5

# Check all containers are up
HEALTH=$($SSH_CMD "$GCP_USER@$GCP_HOST" "sudo docker ps --format '{{.Names}} {{.Status}}'" 2>/dev/null)
echo "$HEALTH"

RUNNING=$(echo "$HEALTH" | grep -c "Up" || true)
if [ "$RUNNING" -ge 7 ]; then
    ok "All 7 containers running"
else
    warn "Only $RUNNING/7 containers running"
fi

# Check dashboard health endpoint
DASH_HEALTH=$($SSH_CMD "$GCP_USER@$GCP_HOST" "curl -s http://localhost:8000/health" 2>/dev/null || echo "failed")
if echo "$DASH_HEALTH" | grep -q "healthy"; then
    ok "Dashboard health: OK"
else
    warn "Dashboard health: $DASH_HEALTH"
fi

# Check nginx health
NGINX_HEALTH=$($SSH_CMD "$GCP_USER@$GCP_HOST" "curl -s http://localhost/health" 2>/dev/null || echo "failed")
if echo "$NGINX_HEALTH" | grep -q "ok"; then
    ok "Nginx health: OK"
else
    warn "Nginx health: $NGINX_HEALTH"
fi

# ─── Final report ─────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════${NC}"
echo -e "${GREEN} Deploy Complete — $TIMESTAMP${NC}"
echo -e "${GREEN} Containers: $RUNNING/7 running${NC}"
echo -e "${GREEN} Backup: $BACKUP_DIR${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════${NC}"

notify "✅ *Deploy Complete* — $TIMESTAMP
Containers: $RUNNING/7 running
Backup: \`$BACKUP_DIR\`"

# ─── Rollback instructions ───────────────────────────────────────────────────
echo ""
echo "To rollback:"
echo "  ssh -i $SSH_KEY $GCP_USER@$GCP_HOST"
echo "  sudo cp $BACKUP_DIR/* $GCP_DIR/"
echo "  cd $GCP_DIR && sudo docker compose restart"
