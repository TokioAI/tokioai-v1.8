#!/bin/bash
# Monitoreo simple en tiempo real

IP="YOUR_IP_ADDRESS"
PROJECT_ID="YOUR_GCP_PROJECT_ID"
DB_HOST="YOUR_IP_ADDRESS"
DB_NAME="soc_ai"
DB_USER="soc_user"

export POSTGRES_PASSWORD=$(gcloud secrets versions access latest --secret="postgres-password" --project=${PROJECT_ID} 2>&1 | grep -v "ERROR" || echo "YOUR_POSTGRES_PASSWORD")
export PGPASSWORD="$POSTGRES_PASSWORD"

echo "🔍 Monitoreando IP: $IP"
echo "Presiona Ctrl+C para detener"
echo ""

while true; do
    TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
    
    RESULT=$(psql -h ${DB_HOST} -U ${DB_USER} -d ${DB_NAME} -tAc "
    SELECT 
        CASE 
            WHEN active = TRUE AND expires_at > NOW() THEN 'BLOQUEADA'
            WHEN active = TRUE AND expires_at < NOW() THEN 'EXPIRADA'
            WHEN active = FALSE AND unblocked_at IS NOT NULL THEN 'DESBLOQUEADA'
            ELSE 'NO_BLOQUEADA'
        END,
        COALESCE(blocked_at::text, ''),
        COALESCE(expires_at::text, ''),
        COALESCE(unblocked_at::text, ''),
        COALESCE(reason, ''),
        COALESCE(unblock_reason, '')
    FROM blocked_ips 
    WHERE ip = '$IP'::inet
    ORDER BY blocked_at DESC 
    LIMIT 1;
    " 2>&1 | grep -v "ERROR")
    
    if [ -z "$RESULT" ]; then
        echo "[$TIMESTAMP] Estado: NO BLOQUEADA (esperando ataque...)"
    else
        ESTADO=$(echo "$RESULT" | cut -d'|' -f1)
        BLOCKED_AT=$(echo "$RESULT" | cut -d'|' -f2)
        EXPIRES_AT=$(echo "$RESULT" | cut -d'|' -f3)
        UNBLOCKED_AT=$(echo "$RESULT" | cut -d'|' -f4)
        REASON=$(echo "$RESULT" | cut -d'|' -f5)
        UNBLOCK_REASON=$(echo "$RESULT" | cut -d'|' -f6)
        
        case "$ESTADO" in
            "BLOQUEADA")
                NOW_EPOCH=$(date +%s)
                EXP_EPOCH=$(date -d "$EXPIRES_AT" +%s 2>/dev/null || echo "0")
                if [ "$EXP_EPOCH" -gt 0 ]; then
                    REMAINING=$((EXP_EPOCH - NOW_EPOCH))
                    MIN=$((REMAINING / 60))
                    SEC=$((REMAINING % 60))
                    echo "🚫 [$TIMESTAMP] ⚠️  BLOQUEADA! Expira en: ${MIN}m ${SEC}s | Razón: $REASON"
                else
                    echo "🚫 [$TIMESTAMP] ⚠️  BLOQUEADA! | Razón: $REASON"
                fi
                ;;
            "EXPIRADA")
                echo "⏰ [$TIMESTAMP] ⚠️  EXPIRADA - Esperando auto-desbloqueo..."
                ;;
            "DESBLOQUEADA")
                echo "✅ [$TIMESTAMP] ✅ DESBLOQUEADA! Razón: $UNBLOCK_REASON"
                echo ""
                echo "✅ PRUEBA COMPLETADA - IP desbloqueada automáticamente"
                break
                ;;
            *)
                echo "[$TIMESTAMP] Estado: NO BLOQUEADA (esperando ataque...)"
                ;;
        esac
    fi
    
    sleep 5
done
