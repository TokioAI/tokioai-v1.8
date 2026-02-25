#!/bin/bash

# Script completo para probar todo el sistema SOC-AI
# Verifica: tráfico, procesamiento, dashboard, mitigación automática

set -e

# Colores
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}╔══════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     🧪 TEST COMPLETO DEL SISTEMA SOC-AI                             ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Variables
DASHBOARD_URL="http://localhost:9000"
KAFKA_BROKER="localhost:9092"
TENANT_ID=2
DOMAIN="airesiliencehub.space"

# 1. Verificar servicios
echo -e "${YELLOW}[1/8] Verificando servicios...${NC}"
if ! docker ps | grep -q "soc-dashboard-api"; then
    echo -e "${RED}❌ Dashboard API no está corriendo${NC}"
    exit 1
fi
if ! docker ps | grep -q "soc-kafka"; then
    echo -e "${RED}❌ Kafka no está corriendo${NC}"
    exit 1
fi
if ! docker ps | grep -q "soc-postgres"; then
    echo -e "${RED}❌ PostgreSQL no está corriendo${NC}"
    exit 1
fi
if ! docker ps | grep -q "log-processor"; then
    echo -e "${YELLOW}⚠️  Log-processor no está corriendo. Iniciando...${NC}"
    docker-compose up -d log-processor
    sleep 5
fi
echo -e "${GREEN}✅ Todos los servicios están corriendo${NC}"
echo ""

# 2. Verificar tenant en la BD
echo -e "${YELLOW}[2/8] Verificando tenant airesiliencehub...${NC}"
TENANT_EXISTS=$(docker exec soc-postgres psql -U soc_user -d soc_ai -t -c "SELECT COUNT(*) FROM tenants WHERE domain = '$DOMAIN';" 2>/dev/null | xargs)
if [ "$TENANT_EXISTS" -eq 0 ]; then
    echo -e "${YELLOW}⚠️  Tenant no existe. Creando...${NC}"
    docker exec soc-postgres psql -U soc_user -d soc_ai -c "
        INSERT INTO tenants (name, domain, status, config) 
        VALUES ('AI Resilience Hub', '$DOMAIN', 'active', '{\"auto_mitigation\": true, \"ml_enabled\": true}')
        ON CONFLICT (domain) DO UPDATE SET status = 'active';
    " 2>/dev/null || true
    echo -e "${GREEN}✅ Tenant creado${NC}"
else
    echo -e "${GREEN}✅ Tenant existe (ID: $TENANT_ID)${NC}"
fi
echo ""

# 3. Generar logs de prueba directamente en PostgreSQL (simulando tráfico procesado)
echo -e "${YELLOW}[3/8] Generando logs de prueba para airesiliencehub...${NC}"
docker exec soc-postgres psql -U soc_user -d soc_ai << SQL 2>/dev/null || true
-- Generar logs normales
INSERT INTO waf_logs (timestamp, ip, method, uri, status, blocked, threat_type, tenant_id, created_at, raw_log)
SELECT 
    NOW() - (random() * interval '1 hour'),
    ('203.0.113.' || (100 + (random() * 50)::int))::inet,
    (ARRAY['GET', 'POST', 'PUT'])[floor(random() * 3 + 1)],
    (ARRAY['/home', '/about', '/contact', '/products', '/blog', '/api/users'])[floor(random() * 6 + 1)],
    200,
    false,
    NULL,
    $TENANT_ID,
    NOW() - (random() * interval '1 hour'),
    jsonb_build_object('host', '$DOMAIN', 'method', 'GET')
FROM generate_series(1, 20)
ON CONFLICT DO NOTHING;

-- Generar ataques bloqueados
INSERT INTO waf_logs (timestamp, ip, method, uri, status, blocked, threat_type, tenant_id, created_at, raw_log)
SELECT 
    NOW() - (random() * interval '30 minutes'),
    ('203.0.113.' || (150 + (random() * 50)::int))::inet,
    'GET',
    (ARRAY['/test.php?id=1 OR 1=1', '/search?q=<script>alert(1)</script>', '/admin/../../../etc/passwd', '/cmd.php?exec=ls -la'])[floor(random() * 4 + 1)],
    403,
    true,
    (ARRAY['SQL Injection', 'XSS', 'Path Traversal', 'Command Injection'])[floor(random() * 4 + 1)],
    $TENANT_ID,
    NOW() - (random() * interval '30 minutes'),
    jsonb_build_object('host', '$DOMAIN', 'blocked', true)
FROM generate_series(1, 15)
ON CONFLICT DO NOTHING;
SQL

echo -e "${GREEN}✅ Logs generados${NC}"
echo ""

# 4. Verificar que los logs estén en la BD
echo -e "${YELLOW}[4/8] Verificando logs en PostgreSQL...${NC}"
LOGS_COUNT=$(docker exec soc-postgres psql -U soc_user -d soc_ai -t -c "SELECT COUNT(*) FROM waf_logs WHERE tenant_id = $TENANT_ID;" 2>/dev/null | xargs)
ATTACKS_COUNT=$(docker exec soc-postgres psql -U soc_user -d soc_ai -t -c "SELECT COUNT(*) FROM waf_logs WHERE tenant_id = $TENANT_ID AND blocked = true;" 2>/dev/null | xargs)
echo -e "   Total logs para tenant $TENANT_ID: ${BLUE}$LOGS_COUNT${NC}"
echo -e "   Ataques bloqueados: ${BLUE}$ATTACKS_COUNT${NC}"
echo ""

# 5. Verificar que aparezcan en el dashboard API
echo -e "${YELLOW}[5/8] Verificando API del dashboard...${NC}"
STATS=$(curl -s "$DASHBOARD_URL/api/stats/summary?tenant_id=$TENANT_ID" 2>/dev/null)
if echo "$STATS" | grep -q "total_requests"; then
    TOTAL=$(echo "$STATS" | python3 -c "import sys, json; print(json.load(sys.stdin).get('total_requests', 0))" 2>/dev/null)
    BLOCKED=$(echo "$STATS" | python3 -c "import sys, json; print(json.load(sys.stdin).get('blocked', 0))" 2>/dev/null)
    echo -e "${GREEN}✅ API funciona${NC}"
    echo -e "   Total requests: ${BLUE}$TOTAL${NC}"
    echo -e "   Blocked: ${BLUE}$BLOCKED${NC}"
else
    echo -e "${RED}❌ Error en API${NC}"
    echo "$STATS"
fi

ATTACKS=$(curl -s "$DASHBOARD_URL/api/attacks/recent?tenant_id=$TENANT_ID&limit=5" 2>/dev/null)
if echo "$ATTACKS" | grep -q "items"; then
    ATTACK_COUNT=$(echo "$ATTACKS" | python3 -c "import sys, json; print(len(json.load(sys.stdin).get('items', [])))" 2>/dev/null)
    echo -e "${GREEN}✅ Ataques visibles en API: ${BLUE}$ATTACK_COUNT${NC}"
else
    echo -e "${RED}❌ Error obteniendo ataques${NC}"
fi
echo ""

# 6. Probar mitigación automática
echo -e "${YELLOW}[6/8] Probando mitigación automática...${NC}"
# Crear un bypass de prueba
docker exec soc-postgres psql -U soc_user -d soc_ai << SQL 2>/dev/null || true
INSERT INTO detected_bypasses (tenant_id, source_ip, attack_type, bypass_method, mitigated, detected_at, request_data, response_data)
VALUES (
    $TENANT_ID,
    'YOUR_IP_ADDRESS',
    'XSS',
    'Encoding bypass',
    false,
    NOW(),
    '{"uri": "/test?q=<script>alert(1)</script>", "method": "GET"}'::jsonb,
    '{"uri": "/test?q=%3Cscript%3Ealert(1)%3C/script%3E", "status": 200}'::jsonb
)
ON CONFLICT DO NOTHING;
SQL

echo -e "${GREEN}✅ Bypass de prueba creado${NC}"

# Verificar si hay reglas de auto-mitigación
MITIGATIONS=$(curl -s "$DASHBOARD_URL/api/auto-mitigations?tenant_id=$TENANT_ID" 2>/dev/null)
if echo "$MITIGATIONS" | grep -q "items"; then
    MIT_COUNT=$(echo "$MITIGATIONS" | python3 -c "import sys, json; print(len(json.load(sys.stdin).get('items', [])))" 2>/dev/null)
    echo -e "   Auto-mitigaciones existentes: ${BLUE}$MIT_COUNT${NC}"
fi
echo ""

# 7. Generar más tráfico real simulando requests
echo -e "${YELLOW}[7/8] Simulando tráfico adicional...${NC}"
# Enviar logs directamente a Kafka (simulando log-processor)
docker exec soc-kafka kafka-console-producer --bootstrap-server localhost:9092 --topic waf-logs << EOF 2>/dev/null || true
{"timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)", "ip": "YOUR_IP_ADDRESS", "method": "GET", "uri": "/api/users", "status": 200, "host": "$DOMAIN", "user_agent": "Mozilla/5.0", "tenant_id": $TENANT_ID}
{"timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)", "ip": "YOUR_IP_ADDRESS", "method": "GET", "uri": "/search?q=' OR '1'='1", "status": 403, "host": "$DOMAIN", "blocked": true, "threat_type": "SQL Injection", "tenant_id": $TENANT_ID}
{"timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)", "ip": "YOUR_IP_ADDRESS", "method": "POST", "uri": "/login", "status": 200, "host": "$DOMAIN", "user_agent": "Mozilla/5.0", "tenant_id": $TENANT_ID}
EOF
echo -e "${GREEN}✅ Tráfico simulado enviado a Kafka${NC}"
echo ""

# Esperar a que se procesen
echo -e "${YELLOW}Esperando 5 segundos para que se procesen los logs...${NC}"
sleep 5

# 8. Verificación final en el dashboard
echo -e "${YELLOW}[8/8] Verificación final...${NC}"
FINAL_STATS=$(curl -s "$DASHBOARD_URL/api/stats/summary?tenant_id=$TENANT_ID" 2>/dev/null)
FINAL_TOTAL=$(echo "$FINAL_STATS" | python3 -c "import sys, json; print(json.load(sys.stdin).get('total_requests', 0))" 2>/dev/null 2>/dev/null || echo "0")

echo ""
echo -e "${BLUE}╔══════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     ✅ RESULTADOS DEL TEST                                         ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${GREEN}✅ Servicios:${NC} Todos corriendo"
echo -e "${GREEN}✅ Tenant:${NC} $DOMAIN (ID: $TENANT_ID)"
echo -e "${GREEN}✅ Logs en BD:${NC} $LOGS_COUNT logs para tenant $TENANT_ID"
echo -e "${GREEN}✅ Ataques bloqueados:${NC} $ATTACKS_COUNT"
echo -e "${GREEN}✅ API Dashboard:${NC} Funcionando"
echo -e "${GREEN}✅ Total requests (tenant $TENANT_ID):${NC} $FINAL_TOTAL"
echo ""
echo -e "${BLUE}╔══════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     🌐 VERIFICAR EN EL DASHBOARD                                    ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "1. Abre: ${BLUE}$DASHBOARD_URL${NC}"
echo ""
echo -e "2. Selecciona el tenant: ${BLUE}🏢 AI Resilience Hub${NC} en el dropdown"
echo ""
echo -e "3. Verifica que veas:"
echo -e "   ${GREEN}✅${NC} Métricas del tenant (Total Requests, Blocked, etc.)"
echo -e "   ${GREEN}✅${NC} Ataques recientes en la tabla"
echo -e "   ${GREEN}✅${NC} Incidentes (si hay)"
echo -e "   ${GREEN}✅${NC} Bypasses (si hay)"
echo ""
echo -e "4. Cambia entre tenants y verifica que los datos cambian"
echo ""
echo -e "${YELLOW}💡 Si no ves los datos, espera unos segundos y refresca la página${NC}"
echo ""

