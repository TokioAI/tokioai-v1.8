#!/bin/bash
# Script para monitorear el bloqueo y desbloqueo de una IP en tiempo real

IP_TO_MONITOR="${1}"
PROJECT_ID="YOUR_GCP_PROJECT_ID"
DB_HOST="YOUR_IP_ADDRESS"
DB_NAME="soc_ai"
DB_USER="soc_user"

if [ -z "$IP_TO_MONITOR" ]; then
    echo "❌ Error: Debes proporcionar una IP para monitorear"
    echo "Uso: $0 <IP_ADDRESS>"
    exit 1
fi

echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║  🔍 MONITOREO EN TIEMPO REAL DE BLOQUEO DE IP                        ║"
echo "╚══════════════════════════════════════════════════════════════════════╝"
echo ""
echo "📋 IP monitoreada: $IP_TO_MONITOR"
echo "⏰ Iniciando monitoreo en tiempo real..."
echo "   (Presiona Ctrl+C para detener)"
echo ""

# Obtener contraseña
export POSTGRES_PASSWORD=$(gcloud secrets versions access latest --secret="postgres-password" --project=${PROJECT_ID} 2>&1 | grep -v "ERROR" || echo "YOUR_POSTGRES_PASSWORD")
export PGPASSWORD="$POSTGRES_PASSWORD"

# Variables de estado
LAST_STATE=""
LAST_UPDATE=""
BLOCK_STARTED=""

# Función para obtener estado actual
get_current_state() {
    psql -h ${DB_HOST} -U ${DB_USER} -d ${DB_NAME} -tAc "
    SELECT 
        CASE 
            WHEN active = TRUE AND expires_at > NOW() THEN 'BLOQUEADA'
            WHEN active = TRUE AND expires_at < NOW() THEN 'EXPIRADA_PENDIENTE'
            WHEN active = FALSE AND unblocked_at IS NOT NULL THEN 'DESBLOQUEADA'
            ELSE 'NO_BLOQUEADA'
        END as estado,
        blocked_at,
        expires_at,
        unblocked_at,
        unblock_reason,
        reason
    FROM blocked_ips 
    WHERE ip = '$IP_TO_MONITOR'::inet
    ORDER BY blocked_at DESC 
    LIMIT 1;
    " 2>&1 | grep -v "ERROR"
}

# Función para mostrar estado
show_status() {
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    local state=$(get_current_state)
    
    if [ -z "$state" ] || [ "$state" = "NO_BLOQUEADA" ]; then
        if [ "$LAST_STATE" != "NO_BLOQUEADA" ]; then
            echo ""
            echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            echo "⏰ [$timestamp] Estado: NO BLOQUEADA"
            echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            LAST_STATE="NO_BLOQUEADA"
        fi
        return
    fi
    
    # Parsear resultado (formato: estado|blocked_at|expires_at|unblocked_at|unblock_reason|reason)
    local estado=$(echo "$state" | cut -d'|' -f1)
    local blocked_at=$(echo "$state" | cut -d'|' -f2)
    local expires_at=$(echo "$state" | cut -d'|' -f3)
    local unblocked_at=$(echo "$state" | cut -d'|' -f4)
    local unblock_reason=$(echo "$state" | cut -d'|' -f5)
    local reason=$(echo "$state" | cut -d'|' -f6)
    
    case "$estado" in
        "BLOQUEADA")
            if [ "$LAST_STATE" != "BLOQUEADA" ]; then
                BLOCK_STARTED=$(date '+%Y-%m-%d %H:%M:%S')
                echo ""
                echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                echo "🚫 [$timestamp] ⚠️  IP BLOQUEADA DETECTADA!"
                echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                echo "   IP: $IP_TO_MONITOR"
                echo "   Bloqueada a las: $blocked_at"
                echo "   Expira a las: $expires_at"
                echo "   Razón: $reason"
                echo ""
                
                # Calcular tiempo restante
                local now_epoch=$(date +%s)
                local expires_epoch=$(date -d "$expires_at" +%s 2>/dev/null || echo "0")
                if [ "$expires_epoch" -gt 0 ]; then
                    local remaining=$((expires_epoch - now_epoch))
                    local minutes=$((remaining / 60))
                    local seconds=$((remaining % 60))
                    echo "   ⏱️  Tiempo restante: ${minutes}m ${seconds}s"
                fi
                echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                LAST_STATE="BLOQUEADA"
            else
                # Mostrar actualización periódica
                local now_epoch=$(date +%s)
                local expires_epoch=$(date -d "$expires_at" +%s 2>/dev/null || echo "0")
                if [ "$expires_epoch" -gt 0 ]; then
                    local remaining=$((expires_epoch - now_epoch))
                    local minutes=$((remaining / 60))
                    local seconds=$((remaining % 60))
                    if [ "$(date +%S)" -eq "00" ] || [ "$(date +%S)" -eq "30" ]; then
                        echo "   ⏱️  [$timestamp] Bloqueo activo - Tiempo restante: ${minutes}m ${seconds}s"
                    fi
                fi
            fi
            ;;
        "EXPIRADA_PENDIENTE")
            if [ "$LAST_STATE" != "EXPIRADA_PENDIENTE" ]; then
                echo ""
                echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                echo "⏰ [$timestamp] ⚠️  BLOQUEO EXPIRADO - Esperando auto-desbloqueo..."
                echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                echo "   IP: $IP_TO_MONITOR"
                echo "   Expiró a las: $expires_at"
                echo "   El cleanup worker desbloqueará en los próximos 5 minutos"
                echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                LAST_STATE="EXPIRADA_PENDIENTE"
            fi
            ;;
        "DESBLOQUEADA")
            if [ "$LAST_STATE" != "DESBLOQUEADA" ]; then
                echo ""
                echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                echo "✅ [$timestamp] ✅ IP DESBLOQUEADA AUTOMÁTICAMENTE!"
                echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                echo "   IP: $IP_TO_MONITOR"
                echo "   Desbloqueada a las: $unblocked_at"
                echo "   Razón: $unblock_reason"
                if [ -n "$BLOCK_STARTED" ]; then
                    echo "   Duración del bloqueo: Desde $BLOCK_STARTED hasta $unblocked_at"
                fi
                echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                echo ""
                echo "✅ PRUEBA COMPLETADA EXITOSAMENTE"
                echo "   El sistema bloqueó y desbloqueó la IP automáticamente"
                LAST_STATE="DESBLOQUEADA"
            fi
            ;;
    esac
}

# Monitoreo continuo
echo "🔍 Esperando detección de ataque..."
echo ""

while true; do
    show_status
    sleep 5  # Verificar cada 5 segundos
done
