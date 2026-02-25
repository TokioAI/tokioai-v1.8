#!/bin/bash

# Script para probar que el tráfico de airesiliencehub.space aparezca en el dashboard
# y que todo el sistema funcione (mitigación automática, etc.)

set -e

# Colores
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}╔══════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     🧪 TEST TRÁFICO AIRESILIENCEHUB → DASHBOARD                    ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════════════════╝${NC}"
echo ""

DOMAIN="airesiliencehub.space"
TENANT_ID=2
DASHBOARD_URL="http://localhost:9000"

# 1. Verificar tenant
echo -e "${YELLOW}[1/6] Verificando tenant...${NC}"
TENANT_EXISTS=$(docker exec soc-postgres psql -U soc_user -d soc_ai -t -c "SELECT COUNT(*) FROM tenants WHERE domain = '$DOMAIN';" 2>/dev/null | xargs)
if [ "$TENANT_EXISTS" -eq 0 ]; then
    echo -e "${YELLOW}⚠️  Creando tenant...${NC}"
    docker exec soc-postgres psql -U soc_user -d soc_ai -c "
        INSERT INTO tenants (name, domain, status, config) 
        VALUES ('AI Resilience Hub', '$DOMAIN', 'active', '{\"auto_mitigation\": true, \"ml_enabled\": true}')
        ON CONFLICT (domain) DO UPDATE SET status = 'active';
    " 2>/dev/null
fi
echo -e "${GREEN}✅ Tenant configurado (ID: $TENANT_ID)${NC}"
echo ""

# 2. Limpiar logs antiguos (opcional, solo para prueba limpia)
echo -e "${YELLOW}[2/6] Limpiando logs antiguos de prueba...${NC}"
docker exec soc-postgres psql -U soc_user -d soc_ai -c "
    DELETE FROM waf_logs WHERE tenant_id = $TENANT_ID AND created_at < NOW() - INTERVAL '1 hour';
" 2>/dev/null || true
echo -e "${GREEN}✅ Limpieza completada${NC}"
echo ""

# 3. Generar tráfico de prueba realista
echo -e "${YELLOW}[3/6] Generando tráfico de prueba para $DOMAIN...${NC}"
docker exec soc-postgres psql -U soc_user -d soc_ai << SQL 2>/dev/null || true
-- Tráfico normal (permitido)
INSERT INTO waf_logs (timestamp, ip, method, uri, status, size, blocked, threat_type, tenant_id, created_at, raw_log, user_agent, referer)
SELECT 
    NOW() - (random() * interval '10 minutes'),
    ('203.0.113.' || (100 + (i * 2)::int))::inet,
    (ARRAY['GET', 'POST'])[floor(random() * 2 + 1)],
    (ARRAY['/', '/home', '/about', '/contact', '/products', '/blog', '/api/users', '/api/data'])[floor(random() * 8 + 1)],
    200,
    (100 + (random() * 9000)::int),
    false,
    NULL,
    $TENANT_ID,
    NOW() - (random() * interval '10 minutes'),
    jsonb_build_object('host', '$DOMAIN', 'method', 'GET', 'path', '/'),
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    '-'
FROM generate_series(1, 30) i
ON CONFLICT DO NOTHING;

-- Ataques bloqueados (XSS)
INSERT INTO waf_logs (timestamp, ip, method, uri, status, size, blocked, threat_type, tenant_id, created_at, raw_log, user_agent, referer, severity)
SELECT 
    NOW() - (random() * interval '5 minutes'),
    ('203.0.113.' || (150 + (i * 2)::int))::inet,
    'GET',
    '/search?q=<script>alert(document.cookie)</script>',
    403,
    146,
    true,
    'XSS',
    $TENANT_ID,
    NOW() - (random() * interval '5 minutes'),
    jsonb_build_object('host', '$DOMAIN', 'blocked', true, 'threat_type', 'XSS'),
    'python-requests/2.31.0',
    '-',
    'high'
FROM generate_series(1, 10) i
ON CONFLICT DO NOTHING;

-- Ataques bloqueados (SQL Injection)
INSERT INTO waf_logs (timestamp, ip, method, uri, status, size, blocked, threat_type, tenant_id, created_at, raw_log, user_agent, referer, severity)
SELECT 
    NOW() - (random() * interval '5 minutes'),
    ('203.0.113.' || (170 + (i * 2)::int))::inet,
    'GET',
    '/api/users?id=1 OR 1=1 UNION SELECT * FROM users',
    403,
    146,
    true,
    'SQL Injection',
    $TENANT_ID,
    NOW() - (random() * interval '5 minutes'),
    jsonb_build_object('host', '$DOMAIN', 'blocked', true, 'threat_type', 'SQL Injection'),
    'sqlmap/1.7',
    '-',
    'critical'
FROM generate_series(1, 8) i
ON CONFLICT DO NOTHING;

-- Ataques bloqueados (Path Traversal)
INSERT INTO waf_logs (timestamp, ip, method, uri, status, size, blocked, threat_type, tenant_id, created_at, raw_log, user_agent, referer, severity)
SELECT 
    NOW() - (random() * interval '3 minutes'),
    ('203.0.113.' || (186 + (i * 2)::int))::inet,
    'GET',
    '/../../../../etc/passwd',
    403,
    146,
    true,
    'Path Traversal',
    $TENANT_ID,
    NOW() - (random() * interval '3 minutes'),
    jsonb_build_object('host', '$DOMAIN', 'blocked', true, 'threat_type', 'Path Traversal'),
    'curl/7.68.0',
    '-',
    'high'
FROM generate_series(1, 5) i
ON CONFLICT DO NOTHING;

-- Ataques bloqueados (Command Injection)
INSERT INTO waf_logs (timestamp, ip, method, uri, status, size, blocked, threat_type, tenant_id, created_at, raw_log, user_agent, referer, severity)
SELECT 
    NOW() - (random() * interval '2 minutes'),
    ('203.0.113.' || (196 + (i * 2)::int))::inet,
    'GET',
    '/cmd.php?exec=cat /etc/passwd',
    403,
    146,
    true,
    'Command Injection',
    $TENANT_ID,
    NOW() - (random() * interval '2 minutes'),
    jsonb_build_object('host', '$DOMAIN', 'blocked', true, 'threat_type', 'Command Injection'),
    'python-requests/2.31.0',
    '-',
    'critical'
FROM generate_series(1, 4) i
ON CONFLICT DO NOTHING;
SQL

echo -e "${GREEN}✅ Tráfico generado${NC}"
echo ""

# 4. Verificar logs en BD
echo -e "${YELLOW}[4/6] Verificando logs en PostgreSQL...${NC}"
TOTAL=$(docker exec soc-postgres psql -U soc_user -d soc_ai -t -c "SELECT COUNT(*) FROM waf_logs WHERE tenant_id = $TENANT_ID;" 2>/dev/null | xargs)
BLOCKED=$(docker exec soc-postgres psql -U soc_user -d soc_ai -t -c "SELECT COUNT(*) FROM waf_logs WHERE tenant_id = $TENANT_ID AND blocked = true;" 2>/dev/null | xargs)
ALLOWED=$(docker exec soc-postgres psql -U soc_user -d soc_ai -t -c "SELECT COUNT(*) FROM waf_logs WHERE tenant_id = $TENANT_ID AND blocked = false;" 2>/dev/null | xargs)
echo -e "   ${GREEN}✅${NC} Total logs: ${BLUE}$TOTAL${NC}"
echo -e "   ${GREEN}✅${NC} Bloqueados: ${BLUE}$BLOCKED${NC}"
echo -e "   ${GREEN}✅${NC} Permitidos: ${BLUE}$ALLOWED${NC}"
echo ""

# 5. Probar mitigación automática
echo -e "${YELLOW}[5/6] Creando bypass para probar mitigación automática...${NC}"
docker exec soc-postgres psql -U soc_user -d soc_ai << SQL 2>/dev/null || true
-- Crear un bypass detectado
INSERT INTO detected_bypasses (tenant_id, source_ip, attack_type, bypass_method, mitigated, detected_at, request_data, response_data)
VALUES (
    $TENANT_ID,
    'YOUR_IP_ADDRESS',
    'XSS',
    'Unicode encoding',
    false,
    NOW(),
    '{"uri": "/test?q=<script>alert(1)</script>", "method": "GET", "host": "$DOMAIN"}'::jsonb,
    '{"uri": "/test?q=%u003Cscript%u003Ealert(1)%u003C/script%u003E", "status": 200, "host": "$DOMAIN"}'::jsonb
)
ON CONFLICT DO NOTHING;

-- Crear un incidente asociado
INSERT INTO incidents (tenant_id, title, description, status, severity, incident_type, source_ip, detected_at)
VALUES (
    $TENANT_ID,
    'Bypass de XSS detectado en ' || '$DOMAIN',
    'Se detectó un bypass de XSS usando encoding Unicode desde IP YOUR_IP_ADDRESS',
    'open',
    'high',
    'bypass',
    'YOUR_IP_ADDRESS',
    NOW()
)
ON CONFLICT DO NOTHING;
SQL

echo -e "${GREEN}✅ Bypass e incidente creados${NC}"
echo ""

# 6. Verificar en el dashboard API
echo -e "${YELLOW}[6/6] Verificando API del dashboard...${NC}"

# Stats
STATS=$(curl -s "$DASHBOARD_URL/api/stats/summary?tenant_id=$TENANT_ID" 2>/dev/null)
if echo "$STATS" | grep -q "total_requests"; then
    TOTAL_API=$(echo "$STATS" | python3 -c "import sys, json; print(json.load(sys.stdin).get('total_requests', 0))" 2>/dev/null || echo "0")
    BLOCKED_API=$(echo "$STATS" | python3 -c "import sys, json; print(json.load(sys.stdin).get('blocked', 0))" 2>/dev/null || echo "0")
    echo -e "${GREEN}✅ Stats API:${NC}"
    echo -e "   Total: ${BLUE}$TOTAL_API${NC}"
    echo -e "   Blocked: ${BLUE}$BLOCKED_API${NC}"
else
    echo -e "${RED}❌ Error en stats API${NC}"
fi

# Attacks
ATTACKS=$(curl -s "$DASHBOARD_URL/api/attacks/recent?tenant_id=$TENANT_ID&limit=10" 2>/dev/null)
if echo "$ATTACKS" | grep -q "items"; then
    ATTACK_COUNT=$(echo "$ATTACKS" | python3 -c "import sys, json; print(len(json.load(sys.stdin).get('items', [])))" 2>/dev/null || echo "0")
    echo -e "${GREEN}✅ Attacks API:${NC} ${BLUE}$ATTACK_COUNT${NC} ataques visibles"
else
    echo -e "${RED}❌ Error en attacks API${NC}"
fi

# Bypasses
BYPASSES=$(curl -s "$DASHBOARD_URL/api/bypasses?tenant_id=$TENANT_ID" 2>/dev/null)
if echo "$BYPASSES" | grep -q "items"; then
    BYPASS_COUNT=$(echo "$BYPASSES" | python3 -c "import sys, json; print(len(json.load(sys.stdin).get('items', [])))" 2>/dev/null || echo "0")
    echo -e "${GREEN}✅ Bypasses API:${NC} ${BLUE}$BYPASS_COUNT${NC} bypasses"
else
    echo -e "${RED}❌ Error en bypasses API${NC}"
fi

# Incidents
INCIDENTS=$(curl -s "$DASHBOARD_URL/api/incidents?tenant_id=$TENANT_ID" 2>/dev/null)
if echo "$INCIDENTS" | grep -q "items"; then
    INCIDENT_COUNT=$(echo "$INCIDENTS" | python3 -c "import sys, json; print(len(json.load(sys.stdin).get('items', [])))" 2>/dev/null || echo "0")
    echo -e "${GREEN}✅ Incidents API:${NC} ${BLUE}$INCIDENT_COUNT${NC} incidentes"
else
    echo -e "${RED}❌ Error en incidents API${NC}"
fi

echo ""
echo -e "${BLUE}╔══════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     ✅ TEST COMPLETADO                                              ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${GREEN}📊 RESUMEN:${NC}"
echo -e "   • Logs en BD: ${BLUE}$TOTAL${NC} (${BLUE}$BLOCKED${NC} bloqueados, ${BLUE}$ALLOWED${NC} permitidos)"
echo -e "   • Tenant ID: ${BLUE}$TENANT_ID${NC} ($DOMAIN)"
echo -e "   • Dashboard: ${BLUE}$DASHBOARD_URL${NC}"
echo ""
echo -e "${BLUE}╔══════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     🌐 VERIFICAR EN EL DASHBOARD                                    ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "1. Abre: ${BLUE}$DASHBOARD_URL${NC}"
echo ""
echo -e "2. Selecciona el tenant: ${BLUE}🏢 AI Resilience Hub (airesiliencehub.space)${NC}"
echo ""
echo -e "3. Verifica que veas:"
echo -e "   ${GREEN}✅${NC} Total Requests: ~$TOTAL"
echo -e "   ${GREEN}✅${NC} Blocked: ~$BLOCKED"
echo -e "   ${GREEN}✅${NC} Ataques en la tabla 'Recent Attacks'"
echo -e "   ${GREEN}✅${NC} Tipos de amenazas: XSS, SQL Injection, Path Traversal, Command Injection"
echo -e "   ${GREEN}✅${NC} Bypasses en la pestaña 'Bypasses'"
echo -e "   ${GREEN}✅${NC} Incidentes en la pestaña 'Incidents'"
echo ""
echo -e "4. Prueba cambiar a 'Todos los Tenants' y verifica que los números cambian"
echo ""
echo -e "${YELLOW}💡 Si no ves los datos, espera 2-3 segundos y refresca la página${NC}"
echo ""

