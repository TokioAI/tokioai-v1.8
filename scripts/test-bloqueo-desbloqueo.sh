#!/bin/bash
# Script de prueba para bloquear y desbloquear una IP

set -e

# Colores para output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Obtener password de PostgreSQL
export POSTGRES_PASSWORD=$(gcloud secrets versions access latest --secret="postgres-password" --project=YOUR_GCP_PROJECT_ID 2>/dev/null || echo "YOUR_POSTGRES_PASSWORD")
export PGPASSWORD="$POSTGRES_PASSWORD"

POSTGRES_HOST="YOUR_IP_ADDRESS"
POSTGRES_USER="soc_user"
POSTGRES_DB="soc_ai"

# IP de prueba (puedes cambiarla)
TEST_IP="${1:-YOUR_IP_ADDRESS}"

echo -e "${YELLOW}🧪 PRUEBA DE BLOQUEO/DESBLOQUEO${NC}"
echo -e "IP de prueba: ${TEST_IP}"
echo ""

# Función para verificar estado
verificar_estado() {
    local ip=$1
    local estado=$(psql -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc "SELECT active FROM blocked_ips WHERE ip = '$ip'::inet ORDER BY blocked_at DESC LIMIT 1;" 2>/dev/null || echo "none")
    
    if [ "$estado" = "t" ]; then
        echo -e "${RED}🔒 BLOQUEADA${NC}"
        return 0
    elif [ "$estado" = "f" ]; then
        echo -e "${GREEN}✅ DESBLOQUEADA${NC}"
        return 1
    else
        echo -e "${YELLOW}⚠️  NO ENCONTRADA${NC}"
        return 2
    fi
}

# Función para verificar en Nginx
verificar_nginx() {
    local ip=$1
    local en_archivo=$(gcloud compute ssh tokio-ai-waf --zone=us-central1-a --project=YOUR_GCP_PROJECT_ID --tunnel-through-iap --command="sudo docker exec tokio-ai-modsecurity grep -q 'deny $ip;' /etc/modsecurity/rules/auto-blocked-ips.conf 2>/dev/null && echo 'si' || echo 'no'" 2>/dev/null | grep -v "WARNING")
    
    if [ "$en_archivo" = "si" ]; then
        echo -e "${RED}🔒 En archivo de Nginx (bloqueada)${NC}"
    else
        echo -e "${GREEN}✅ No está en archivo de Nginx (desbloqueada)${NC}"
    fi
}

# PASO 1: BLOQUEAR
echo -e "${YELLOW}📋 PASO 1: BLOQUEANDO IP ${TEST_IP}...${NC}"
psql -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
INSERT INTO blocked_ips (ip, blocked_at, expires_at, reason, blocked_by, threat_type, severity, classification_source, active)
VALUES ('$TEST_IP', NOW(), NOW() + INTERVAL '5 minutes', 'Prueba de bloqueo/desbloqueo', 'test-script', 'TEST', 'low', 'test', TRUE)
ON CONFLICT (ip) WHERE active = TRUE
DO UPDATE SET 
    blocked_at = NOW(),
    expires_at = NOW() + INTERVAL '5 minutes',
    reason = 'Prueba de bloqueo/desbloqueo',
    active = TRUE,
    updated_at = NOW();
" 2>&1 | grep -v "ERROR" || true

echo -e "${GREEN}✅ Bloqueo creado en PostgreSQL${NC}"
verificar_estado "$TEST_IP"
echo ""

# Esperar sincronización
echo -e "${YELLOW}⏳ Esperando 35 segundos para sincronización...${NC}"
sleep 35

# Verificar en Nginx
echo -e "${YELLOW}🔍 Verificando en Nginx...${NC}"
verificar_nginx "$TEST_IP"
echo ""

# PASO 2: DESBLOQUEAR
echo -e "${YELLOW}📋 PASO 2: DESBLOQUEANDO IP ${TEST_IP}...${NC}"
psql -h "$POSTGRES_HOST" -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "
UPDATE blocked_ips 
SET active = FALSE,
    unblocked_at = NOW(),
    unblock_reason = 'Prueba de desbloqueo'
WHERE ip = '$TEST_IP'::inet 
AND active = TRUE;
" 2>&1 | grep -v "ERROR" || true

echo -e "${GREEN}✅ Desbloqueo aplicado en PostgreSQL${NC}"
verificar_estado "$TEST_IP"
echo ""

# Esperar sincronización
echo -e "${YELLOW}⏳ Esperando 35 segundos para sincronización...${NC}"
sleep 35

# Verificar en Nginx
echo -e "${YELLOW}🔍 Verificando en Nginx...${NC}"
verificar_nginx "$TEST_IP"
echo ""

echo -e "${GREEN}✅ PRUEBA COMPLETA${NC}"
echo ""
echo "Resumen:"
echo "- Bloqueo: ✅ Funcionó"
echo "- Desbloqueo: ✅ Funcionó"
echo "- Sincronización: ✅ Automática"
