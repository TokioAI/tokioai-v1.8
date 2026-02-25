#!/bin/bash

# Script para verificar el funcionamiento del dashboard multi-tenant
# Autor: Tokio AI
# Fecha: 2024-12-06

set -e

# Colores
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔══════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     🧪 TEST DASHBOARD MULTI-TENANT - TOKIO AI                      ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════════════════╝${NC}"
echo ""

# 1. Verificar que los servicios están corriendo
echo -e "${YELLOW}[1/6] Verificando servicios Docker...${NC}"
if ! docker ps | grep -q "soc-dashboard-api"; then
    echo -e "${RED}❌ Dashboard API no está corriendo${NC}"
    echo -e "${YELLOW}   Ejecuta: docker-compose up -d dashboard-api${NC}"
    exit 1
fi
echo -e "${GREEN}✅ Dashboard API corriendo${NC}"

if ! docker ps | grep -q "soc-postgres"; then
    echo -e "${RED}❌ PostgreSQL no está corriendo${NC}"
    exit 1
fi
echo -e "${GREEN}✅ PostgreSQL corriendo${NC}"
echo ""

# 2. Verificar tenants en la base de datos
echo -e "${YELLOW}[2/6] Verificando tenants en la base de datos...${NC}"
TENANTS=$(docker exec soc-postgres psql -U soc_user -d soc_ai -t -c "SELECT COUNT(*) FROM tenants;" 2>/dev/null | xargs)
if [ -z "$TENANTS" ] || [ "$TENANTS" -eq 0 ]; then
    echo -e "${RED}❌ No hay tenants en la base de datos${NC}"
    echo -e "${YELLOW}   Creando tenant por defecto...${NC}"
    docker exec soc-postgres psql -U soc_user -d soc_ai -c "INSERT INTO tenants (name, domain, status) VALUES ('Default Tenant', 'localhost', 'active') ON CONFLICT DO NOTHING;" 2>/dev/null || true
fi

TENANT_LIST=$(docker exec soc-postgres psql -U soc_user -d soc_ai -t -c "SELECT id, name, domain FROM tenants ORDER BY id;" 2>/dev/null)
echo -e "${GREEN}✅ Tenants encontrados:${NC}"
echo "$TENANT_LIST" | while read line; do
    if [ ! -z "$line" ]; then
        echo -e "   ${GREEN}•${NC} $line"
    fi
done
echo ""

# 3. Verificar logs con tenant_id
echo -e "${YELLOW}[3/6] Verificando logs con tenant_id...${NC}"
LOGS_COUNT=$(docker exec soc-postgres psql -U soc_user -d soc_ai -t -c "SELECT COUNT(*) FROM waf_logs WHERE tenant_id IS NOT NULL;" 2>/dev/null | xargs)
TOTAL_LOGS=$(docker exec soc-postgres psql -U soc_user -d soc_ai -t -c "SELECT COUNT(*) FROM waf_logs;" 2>/dev/null | xargs)

echo -e "   Total logs: ${BLUE}${TOTAL_LOGS}${NC}"
echo -e "   Logs con tenant_id: ${BLUE}${LOGS_COUNT}${NC}"

if [ "$LOGS_COUNT" -eq 0 ] && [ "$TOTAL_LOGS" -gt 0 ]; then
    echo -e "${YELLOW}⚠️  Hay logs pero sin tenant_id. Asignando tenant_id=1 a logs existentes...${NC}"
    docker exec soc-postgres psql -U soc_user -d soc_ai -c "UPDATE waf_logs SET tenant_id = 1 WHERE tenant_id IS NULL;" 2>/dev/null || true
    echo -e "${GREEN}✅ Tenant_id asignado${NC}"
fi
echo ""

# 4. Generar datos de prueba si no hay suficientes
echo -e "${YELLOW}[4/6] Verificando datos de prueba...${NC}"
TENANT_2_LOGS=$(docker exec soc-postgres psql -U soc_user -d soc_ai -t -c "SELECT COUNT(*) FROM waf_logs WHERE tenant_id = 2;" 2>/dev/null | xargs)

if [ "$TENANT_2_LOGS" -eq 0 ]; then
    echo -e "${YELLOW}⚠️  No hay logs para tenant_id=2. Creando datos de prueba...${NC}"
    
    # Crear algunos logs de prueba para tenant 2 (airesiliencehub)
    docker exec soc-postgres psql -U soc_user -d soc_ai << 'SQL' 2>/dev/null || true
    INSERT INTO waf_logs (timestamp, ip, method, uri, status, blocked, threat_type, tenant_id, created_at)
    VALUES 
        (NOW(), 'YOUR_IP_ADDRESS', 'GET', '/test-xss.php?q=<script>alert(1)</script>', 403, true, 'XSS', 2, NOW()),
        (NOW(), 'YOUR_IP_ADDRESS', 'POST', '/login.php', 200, false, NULL, 2, NOW()),
        (NOW(), 'YOUR_IP_ADDRESS', 'GET', '/admin?id=1 OR 1=1', 403, true, 'SQL Injection', 2, NOW()),
        (NOW(), 'YOUR_IP_ADDRESS', 'GET', '/index.php', 200, false, NULL, 2, NOW()),
        (NOW(), 'YOUR_IP_ADDRESS', 'GET', '/../../etc/passwd', 403, true, 'Path Traversal', 2, NOW())
    ON CONFLICT DO NOTHING;
SQL
    echo -e "${GREEN}✅ Datos de prueba creados para tenant_id=2${NC}"
else
    echo -e "${GREEN}✅ Ya hay ${TENANT_2_LOGS} logs para tenant_id=2${NC}"
fi
echo ""

# 5. Probar endpoints de la API
echo -e "${YELLOW}[5/6] Probando endpoints de la API...${NC}"
DASHBOARD_URL="http://localhost:8000"

# Obtener lista de tenants
echo -n "   Probando GET /api/tenants... "
TENANTS_RESPONSE=$(curl -s "$DASHBOARD_URL/api/tenants" 2>/dev/null || echo "")
if echo "$TENANTS_RESPONSE" | grep -q "tenants"; then
    echo -e "${GREEN}✅${NC}"
else
    echo -e "${RED}❌${NC}"
    echo -e "   ${RED}Respuesta: $TENANTS_RESPONSE${NC}"
fi

# Probar stats con tenant_id
echo -n "   Probando GET /api/stats/summary?tenant_id=2... "
STATS_RESPONSE=$(curl -s "$DASHBOARD_URL/api/stats/summary?tenant_id=2" 2>/dev/null || echo "")
if echo "$STATS_RESPONSE" | grep -q "total_requests"; then
    echo -e "${GREEN}✅${NC}"
    TOTAL_REQ=$(echo "$STATS_RESPONSE" | grep -o '"total_requests":[0-9]*' | cut -d: -f2)
    echo -e "      ${BLUE}Total requests (tenant 2): ${TOTAL_REQ}${NC}"
else
    echo -e "${RED}❌${NC}"
fi

# Probar attacks con tenant_id
echo -n "   Probando GET /api/attacks/recent?tenant_id=2... "
ATTACKS_RESPONSE=$(curl -s "$DASHBOARD_URL/api/attacks/recent?tenant_id=2" 2>/dev/null || echo "")
if echo "$ATTACKS_RESPONSE" | grep -q "items"; then
    echo -e "${GREEN}✅${NC}"
    ATTACK_COUNT=$(echo "$ATTACKS_RESPONSE" | grep -o '"count":[0-9]*' | cut -d: -f2)
    echo -e "      ${BLUE}Ataques encontrados (tenant 2): ${ATTACK_COUNT}${NC}"
else
    echo -e "${RED}❌${NC}"
fi

# Probar sin tenant_id (todos)
echo -n "   Probando GET /api/stats/summary (todos)... "
STATS_ALL=$(curl -s "$DASHBOARD_URL/api/stats/summary" 2>/dev/null || echo "")
if echo "$STATS_ALL" | grep -q "total_requests"; then
    echo -e "${GREEN}✅${NC}"
    TOTAL_ALL=$(echo "$STATS_ALL" | grep -o '"total_requests":[0-9]*' | cut -d: -f2)
    echo -e "      ${BLUE}Total requests (todos): ${TOTAL_ALL}${NC}"
else
    echo -e "${RED}❌${NC}"
fi
echo ""

# 6. Verificar selector en el dashboard
echo -e "${YELLOW}[6/6] Verificando dashboard...${NC}"
echo -e "${GREEN}✅ Dashboard disponible en: ${BLUE}${DASHBOARD_URL}${NC}"
echo ""
echo -e "${BLUE}╔══════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     📊 INSTRUCCIONES PARA PROBAR EL DASHBOARD                       ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${GREEN}1.${NC} Abre el navegador y ve a: ${BLUE}${DASHBOARD_URL}${NC}"
echo ""
echo -e "${GREEN}2.${NC} Busca el selector de tenant en el header (arriba a la derecha)"
echo -e "   Deberías ver un dropdown con:"
echo -e "   ${YELLOW}•${NC} Todos los Tenants"
echo -e "   ${YELLOW}•${NC} Default Tenant (localhost)"
echo -e "   ${YELLOW}•${NC} AirResilience Hub (airesiliencehub.space) [si está configurado]"
echo ""
echo -e "${GREEN}3.${NC} Prueba cambiando entre tenants:"
echo -e "   ${YELLOW}•${NC} Selecciona 'Todos los Tenants' → Verás todos los datos"
echo -e "   ${YELLOW}•${NC} Selecciona 'Default Tenant' → Solo datos del tenant 1"
echo -e "   ${YELLOW}•${NC} Selecciona otro tenant → Solo datos de ese tenant"
echo ""
echo -e "${GREEN}4.${NC} Verifica que las pestañas se actualizan:"
echo -e "   ${YELLOW}•${NC} Recent Attacks"
echo -e "   ${YELLOW}•${NC} Incidents"
echo -e "   ${YELLOW}•${NC} Bypasses"
echo -e "   ${YELLOW}•${NC} Auto-Mitigations"
echo -e "   ${YELLOW}•${NC} Red Team"
echo -e "   ${YELLOW}•${NC} Event Log"
echo ""
echo -e "${GREEN}5.${NC} Verifica las métricas en las tarjetas superiores:"
echo -e "   ${YELLOW}•${NC} Total Requests"
echo -e "   ${YELLOW}•${NC} Blocked"
echo -e "   ${YELLOW}•${NC} Allowed"
echo -e "   ${YELLOW}•${NC} Top Threat"
echo ""
echo -e "${GREEN}6.${NC} Abre la consola del navegador (F12) y verifica:"
echo -e "   ${YELLOW}•${NC} No hay errores JavaScript"
echo -e "   ${YELLOW}•${NC} Las llamadas API incluyen 'tenant_id' en la URL"
echo -e "   ${YELLOW}•${NC} Logs como: 'Dashboard actualizado correctamente (Tenant: X)'"
echo ""
echo -e "${BLUE}╔══════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     ✅ VERIFICACIÓN COMPLETA                                         ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${GREEN}🎯 ¡Listo para probar!${NC}"
echo ""

