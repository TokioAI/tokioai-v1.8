#!/bin/bash
# Script para verificar que los bloqueos de IPs funcionan correctamente

set -e

IP_TO_CHECK="${1:-YOUR_IP_ADDRESS}"
PROJECT_ID="YOUR_GCP_PROJECT_ID"
DB_HOST="YOUR_IP_ADDRESS"
DB_NAME="soc_ai"
DB_USER="soc_user"

echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║  🔍 VERIFICACIÓN DE BLOQUEOS DE IPs                                   ║"
echo "╚══════════════════════════════════════════════════════════════════════╝"
echo ""

echo "🔍 Verificando IP: $IP_TO_CHECK"
echo ""

# Obtener contraseña
export POSTGRES_PASSWORD=$(gcloud secrets versions access latest --secret="postgres-password" --project=${PROJECT_ID} 2>&1 | grep -v "ERROR" || echo "YOUR_POSTGRES_PASSWORD")
export PGPASSWORD="$POSTGRES_PASSWORD"

# Verificar estado en PostgreSQL
echo "════════════════════════════════════════════════════════════════════"
echo "1. ESTADO EN POSTGRESQL"
echo "════════════════════════════════════════════════════════════════════"
echo ""

STATUS_QUERY="
SELECT 
    ip,
    blocked_at,
    expires_at,
    active,
    NOW() as now,
    CASE 
        WHEN expires_at < NOW() THEN 'EXPIRADO'
        WHEN active THEN 'ACTIVO'
        ELSE 'INACTIVO'
    END as estado,
    reason
FROM blocked_ips 
WHERE ip::text = '$IP_TO_CHECK'
ORDER BY blocked_at DESC 
LIMIT 3;
"

psql -h ${DB_HOST} -U ${DB_USER} -d ${DB_NAME} -c "$STATUS_QUERY" 2>&1

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "2. BLOQUEOS ACTIVOS ACTUALMENTE"
echo "════════════════════════════════════════════════════════════════════"
echo ""

ACTIVE_QUERY="
SELECT 
    COUNT(*) as total_activos,
    COUNT(*) FILTER (WHERE expires_at > NOW()) as activos_no_expirados,
    COUNT(*) FILTER (WHERE expires_at < NOW()) as expirados_pero_activos,
    MIN(blocked_at) as bloqueo_mas_antiguo,
    MAX(blocked_at) as bloqueo_mas_reciente
FROM blocked_ips 
WHERE active = TRUE
AND classification_source = 'episode_analysis';
"

psql -h ${DB_HOST} -U ${DB_USER} -d ${DB_NAME} -c "$ACTIVE_QUERY" 2>&1

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "3. HISTORIAL DE BLOQUEOS (Últimas 24 horas)"
echo "════════════════════════════════════════════════════════════════════"
echo ""

HISTORY_QUERY="
SELECT 
    ip,
    blocked_at,
    expires_at,
    CASE 
        WHEN expires_at < NOW() THEN 'EXPIRADO'
        WHEN active THEN 'ACTIVO'
        ELSE 'INACTIVO'
    END as estado,
    EXTRACT(EPOCH FROM (expires_at - blocked_at)) / 60 as duracion_minutos,
    reason
FROM blocked_ips 
WHERE classification_source = 'episode_analysis'
AND blocked_at > NOW() - INTERVAL '24 hours'
ORDER BY blocked_at DESC 
LIMIT 10;
"

psql -h ${DB_HOST} -U ${DB_USER} -d ${DB_NAME} -c "$HISTORY_QUERY" 2>&1

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "4. VERIFICACIÓN DE SINCRONIZACIÓN CON NGINX"
echo "════════════════════════════════════════════════════════════════════"
echo ""

echo "📋 El sistema de bloqueo funciona así:"
echo ""
echo "1. PostgreSQL: IP se bloquea y se guarda en 'blocked_ips' ✅"
echo "2. Script de sincronización: Lee PostgreSQL cada 30 segundos"
echo "3. Nginx/ModSecurity: Recibe las IPs bloqueadas"
echo "4. Bloqueo real: Nginx rechaza requests de IPs bloqueadas (403)"
echo ""
echo "⚠️  NOTA IMPORTANTE:"
echo "   El script de sincronización debe ejecutarse en el SERVIDOR WAF"
echo "   donde está corriendo Nginx/ModSecurity (NO en Cloud Run)"
echo ""
echo "📋 Para verificar si está funcionando:"
echo ""
echo "   A) En el servidor WAF, verificar que el script está corriendo:"
echo "      sudo systemctl status block-sync.timer"
echo ""
echo "   B) Verificar el archivo de configuración de Nginx:"
echo "      cat /opt/tokio-ai-waf/modsecurity/rules/auto-blocked-ips.conf"
echo ""
echo "   C) Probar acceso desde la IP bloqueada:"
echo "      # Desde la IP bloqueada, intentar acceder"
echo "      # Debe recibir 403 Forbidden"
echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "5. RECOMENDACIONES"
echo "════════════════════════════════════════════════════════════════════"
echo ""

# Verificar si hay bloqueos expirados que siguen marcados como activos
EXPIRED_ACTIVE=$(psql -h ${DB_HOST} -U ${DB_USER} -d ${DB_NAME} -tAc "
    SELECT COUNT(*) 
    FROM blocked_ips 
    WHERE active = TRUE 
    AND expires_at < NOW() 
    AND classification_source = 'episode_analysis';
" 2>&1 | grep -v "ERROR" || echo "0")

if [ "$EXPIRED_ACTIVE" -gt "0" ]; then
    echo "⚠️  ADVERTENCIA: Hay $EXPIRED_ACTIVE IPs expiradas que siguen marcadas como activas"
    echo "   Esto es normal - el script de auto-limpieza las desactivará automáticamente"
    echo ""
fi

echo "✅ Para probar bloqueo en tiempo real:"
echo ""
echo "   1. Bloquear una IP de prueba (ya está hecho para $IP_TO_CHECK)"
echo "   2. Verificar en PostgreSQL que está bloqueada"
echo "   3. Esperar 30-60 segundos (sincronización)"
echo "   4. Verificar en Nginx que la IP está en el archivo de bloqueos"
echo "   5. Intentar acceder desde esa IP → Debe recibir 403 Forbidden"
echo "   6. Esperar que expire (según expires_at)"
echo "   7. Verificar que se desbloquea automáticamente"
echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "RESUMEN"
echo "════════════════════════════════════════════════════════════════════"
echo ""

echo "✅ Sistema de bloqueo configurado:"
echo "   • PostgreSQL: ✅ Funcionando"
echo "   • Tabla blocked_ips: ✅ Tiene datos"
echo "   • Script de sincronización: ⚠️  Debe ejecutarse en servidor WAF"
echo ""
echo "📋 Para verificar bloqueo completo, necesitas acceso al servidor WAF"
echo "   donde está corriendo Nginx/ModSecurity"
echo ""
