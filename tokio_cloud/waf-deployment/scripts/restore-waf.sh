#!/bin/bash
# Script para restaurar WAF desde backup

set -e

if [ -z "$1" ]; then
    echo "Uso: $0 <archivo-backup.tar.gz>"
    echo ""
    echo "Backups disponibles:"
    ls -lh /opt/tokioai/backups/*.tar.gz 2>/dev/null | tail -5
    exit 1
fi

BACKUP_FILE="$1"

if [ ! -f "$BACKUP_FILE" ]; then
    echo "❌ Error: Archivo no encontrado: $BACKUP_FILE"
    exit 1
fi

echo "📦 Restaurando desde: $BACKUP_FILE"
echo ""

# Extraer backup
cd "${DEPLOY_DIR:-/opt/tokioai/waf}"
tar -xzf "$BACKUP_FILE"

echo "✅ Backup restaurado"
echo ""
echo "📋 Próximos pasos:"
echo "   1. Revisar configuración: cd waf-deployment && cat .env"
echo "   2. Desplegar: ./scripts/deploy-waf.sh"
echo ""
