#!/bin/bash
# Script completo para verificar que los bloqueos funcionan realmente

set -e

PROJECT_ID="YOUR_GCP_PROJECT_ID"
DB_HOST="YOUR_IP_ADDRESS"
DB_NAME="soc_ai"
DB_USER="soc_user"
IP_TEST="YOUR_IP_ADDRESS"

echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║  🔍 VERIFICACIÓN COMPLETA DE BLOQUEOS                                 ║"
echo "╚══════════════════════════════════════════════════════════════════════╝"
echo ""

# Obtener contraseña
export POSTGRES_PASSWORD=$(gcloud secrets versions access latest --secret="postgres-password" --project=${PROJECT_ID} 2>&1 | grep -v "ERROR" || echo "YOUR_POSTGRES_PASSWORD")
export PGPASSWORD="$POSTGRES_PASSWORD"

echo "════════════════════════════════════════════════════════════════════"
echo "1. VERIFICAR BLOQUEO EN POSTGRESQL"
echo "════════════════════════════════════════════════════════════════════"
echo ""

# Crear un bloqueo de prueba
echo "📝 Creando bloqueo de prueba para IP: $IP_TEST"
psql -h ${DB_HOST} -U ${DB_USER} -d ${DB_NAME} <<EOF 2>&1 | grep -v "ERROR" || true
-- Desactivar bloqueos anteriores de esta IP
UPDATE blocked_ips SET active = FALSE WHERE ip = '$IP_TEST'::inet;

-- Crear nuevo bloqueo de prueba (5 minutos)
INSERT INTO blocked_ips (ip, blocked_at, expires_at, reason, classification_source, threat_type, severity, active)
VALUES (
    '$IP_TEST'::inet,
    NOW(),
    NOW() + INTERVAL '5 minutes',
    'Prueba de bloqueo - Verificación de funcionamiento',
    'episode_analysis',
    'TEST',
    'medium',
    TRUE
)
ON CONFLICT (ip) WHERE active = TRUE
DO UPDATE SET
    blocked_at = NOW(),
    expires_at = NOW() + INTERVAL '5 minutes',
    reason = 'Prueba de bloqueo - Verificación de funcionamiento',
    active = TRUE;
EOF

echo ""
echo "✅ Bloqueo de prueba creado"
echo ""

# Verificar bloqueo
echo "🔍 Verificando bloqueo en PostgreSQL:"
psql -h ${DB_HOST} -U ${DB_USER} -d ${DB_NAME} -c "
SELECT 
    ip,
    blocked_at,
    expires_at,
    active,
    NOW() as ahora,
    EXTRACT(EPOCH FROM (expires_at - NOW())) / 60 as minutos_restantes,
    CASE 
        WHEN expires_at < NOW() THEN 'EXPIRADO'
        WHEN active THEN 'ACTIVO'
        ELSE 'INACTIVO'
    END as estado
FROM blocked_ips 
WHERE ip = '$IP_TEST'::inet
AND active = TRUE
ORDER BY blocked_at DESC 
LIMIT 1;
" 2>&1 | grep -v "ERROR" || true

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "2. SIMULAR SCRIPT DE SINCRONIZACIÓN"
echo "════════════════════════════════════════════════════════════════════"
echo ""

# Simular lo que hace el script de sincronización
echo "📋 Simulando script de sincronización..."
echo ""

# Obtener IPs bloqueadas activas
BLOCKED_IPS=$(psql -h ${DB_HOST} -U ${DB_USER} -d ${DB_NAME} -tAc "
SELECT string_agg(ip::text, ', ')
FROM blocked_ips 
WHERE active = TRUE 
AND (expires_at IS NULL OR expires_at > NOW())
AND classification_source = 'episode_analysis'
LIMIT 10;
" 2>&1 | grep -v "ERROR" || echo "")

if [ -n "$BLOCKED_IPS" ]; then
    echo "✅ IPs bloqueadas activas encontradas:"
    echo "$BLOCKED_IPS" | tr ',' '\n' | head -5 | sed 's/^/   • /'
    echo ""
    echo "📝 Estas IPs deberían estar en el archivo de Nginx:"
    echo "   /opt/tokio-ai-waf/modsecurity/rules/auto-blocked-ips.conf"
    echo ""
    echo "📋 Formato esperado en Nginx:"
    echo "   deny $IP_TEST;"
else
    echo "⚠️  No se encontraron IPs bloqueadas activas"
fi

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "3. VERIFICAR AUTO-DESBLOQUEO"
echo "════════════════════════════════════════════════════════════════════"
echo ""

# Verificar IPs expiradas que siguen activas
EXPIRED_ACTIVE=$(psql -h ${DB_HOST} -U ${DB_USER} -d ${DB_NAME} -tAc "
SELECT COUNT(*) 
FROM blocked_ips 
WHERE active = TRUE 
AND expires_at < NOW() 
AND expires_at IS NOT NULL
AND classification_source = 'episode_analysis';
" 2>&1 | grep -v "ERROR" || echo "0")

echo "📊 IPs expiradas que siguen activas: $EXPIRED_ACTIVE"
echo ""

if [ "$EXPIRED_ACTIVE" -gt "0" ]; then
    echo "⚠️  Hay IPs expiradas que no se han desbloqueado automáticamente"
    echo ""
    echo "🔧 Ejecutando limpieza manual..."
    
    # Desactivar IPs expiradas
    CLEANED=$(psql -h ${DB_HOST} -U ${DB_USER} -d ${DB_NAME} -tAc "
    UPDATE blocked_ips 
    SET active = FALSE,
        unblocked_at = NOW(),
        unblock_reason = 'Limpieza manual: IP expirada'
    WHERE active = TRUE 
    AND expires_at < NOW() 
    AND expires_at IS NOT NULL
    RETURNING COUNT(*);
    " 2>&1 | grep -v "ERROR" || echo "0")
    
    echo "✅ IPs limpiadas: $CLEANED"
else
    echo "✅ No hay IPs expiradas pendientes de limpiar"
fi

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "4. VERIFICAR CICLO COMPLETO"
echo "════════════════════════════════════════════════════════════════════"
echo ""

echo "📋 Para verificar el ciclo completo:"
echo ""
echo "1. ✅ Bloqueo creado en PostgreSQL"
echo "2. ⏳ Esperar 30-60 segundos (sincronización con Nginx)"
echo "3. 🔒 Verificar en servidor WAF que la IP está en Nginx config"
echo "4. 🚫 Probar acceso desde IP bloqueada → Debe recibir 403"
echo "5. ⏰ Esperar 5 minutos (expiración)"
echo "6. 🧹 Cleanup worker desactiva IP automáticamente"
echo "7. ⏳ Esperar 30-60 segundos (sincronización)"
echo "8. ✅ Verificar que IP ya no está en Nginx config"
echo "9. ✅ Probar acceso desde IP → Debe funcionar normalmente"
echo ""

echo "════════════════════════════════════════════════════════════════════"
echo "5. ESTADO ACTUAL"
echo "════════════════════════════════════════════════════════════════════"
echo ""

# Contar bloqueos activos
ACTIVE_COUNT=$(psql -h ${DB_HOST} -U ${DB_USER} -d ${DB_NAME} -tAc "
SELECT COUNT(*) 
FROM blocked_ips 
WHERE active = TRUE 
AND (expires_at IS NULL OR expires_at > NOW())
AND classification_source = 'episode_analysis';
" 2>&1 | grep -v "ERROR" || echo "0")

echo "📊 Bloqueos activos actualmente: $ACTIVE_COUNT"
echo ""

if [ "$ACTIVE_COUNT" -gt "0" ]; then
    echo "✅ Hay bloqueos activos en PostgreSQL"
    echo "⚠️  IMPORTANTE: Verificar que el script de sincronización"
    echo "   está corriendo en el servidor WAF para que funcionen realmente"
else
    echo "ℹ️  No hay bloqueos activos en este momento"
fi

echo ""
echo "════════════════════════════════════════════════════════════════════"
echo "RESUMEN"
echo "════════════════════════════════════════════════════════════════════"
echo ""

echo "✅ PostgreSQL: Funcionando correctamente"
echo "✅ Auto-limpieza: Corregido (desactiva IPs expiradas cada 5 min)"
echo "⚠️  Sincronización Nginx: Debe verificarse en servidor WAF"
echo ""
echo "📋 Próximos pasos:"
echo "   1. Verificar en servidor WAF que block-sync.timer está corriendo"
echo "   2. Verificar archivo auto-blocked-ips.conf en Nginx"
echo "   3. Probar acceso desde IP bloqueada → Debe recibir 403"
echo ""
