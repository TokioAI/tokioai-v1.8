#!/bin/bash
# Script de backup del WAF

set -e

BACKUP_DIR="${BACKUP_DIR:-/opt/tokioai/backups}"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="waf-backup-${DATE}.tar.gz"

echo "📦 Creando backup del WAF..."
echo ""

mkdir -p "$BACKUP_DIR"

cd "${DEPLOY_DIR:-/opt/tokioai/waf}"

# Backup de configuración (sin logs)
tar -czf "$BACKUP_DIR/$BACKUP_FILE" \
    --exclude='*.log' \
    --exclude='modsecurity/modsec-logs/*' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.git' \
    waf-deployment/

echo "✅ Backup creado: $BACKUP_DIR/$BACKUP_FILE"
echo ""
echo "📋 Para restaurar:"
echo "   tar -xzf $BACKUP_DIR/$BACKUP_FILE"
echo ""
