#!/bin/bash
# Script de pruebas completo para el sistema Tokio AI ACIS

echo "🧪 =========================================="
echo "🧪 PRUEBAS DEL SISTEMA TOKIO AI ACIS"
echo "🧪 =========================================="
echo ""

# Colores
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Variables
WAF_URL="http://localhost:8080"
DASHBOARD_API="http://localhost:9000"
TENANT_ID=1

echo -e "${BLUE}📋 FASE 1: Verificar servicios${NC}"
echo "----------------------------------------"
docker compose ps --format "table {{.Name}}\t{{.Status}}" | grep -E "NAME|soc-"
echo ""

echo -e "${BLUE}📋 FASE 2: Generar ataques para detectar bypasses${NC}"
echo "----------------------------------------"
echo "Generando ataques que serán bloqueados inicialmente..."

# Ataque SQLi que será bloqueado
echo "1. Ataque SQLi (será bloqueado):"
curl -sS "$WAF_URL/?id=' OR '1'='1" -o /dev/null -w "Status: %{http_code}\n"
sleep 2

# Ataque XSS que será bloqueado
echo "2. Ataque XSS (será bloqueado):"
curl -sS "$WAF_URL/?q=<script>alert('XSS')</script>" -o /dev/null -w "Status: %{http_code}\n"
sleep 2

# Ahora intentar un bypass con URL encoding
echo ""
echo -e "${YELLOW}3. Intentando bypass con URL encoding (puede pasar):${NC}"
curl -sS "$WAF_URL/?id=%27%20OR%20%271%27%3D%271" -o /dev/null -w "Status: %{http_code}\n"
sleep 2

# Bypass con case variation
echo "4. Intentando bypass con case variation:"
curl -sS "$WAF_URL/?id=' Or '1'='1" -o /dev/null -w "Status: %{http_code}\n"
sleep 2

echo ""
echo -e "${GREEN}✅ Ataques generados. Esperando 10 segundos para que se procesen...${NC}"
sleep 10

echo ""
echo -e "${BLUE}📋 FASE 3: Verificar logs en base de datos${NC}"
echo "----------------------------------------"
echo "Consultando logs recientes..."
docker compose exec -T postgres psql -U soc_user -d soc_ai -c "
SELECT 
    COUNT(*) as total_logs,
    COUNT(*) FILTER (WHERE blocked = true) as bloqueados,
    COUNT(*) FILTER (WHERE blocked = false) as permitidos
FROM waf_logs 
WHERE timestamp > NOW() - INTERVAL '5 minutes';
"

echo ""
echo -e "${BLUE}📋 FASE 4: Ejecutar detección de bypasses manualmente${NC}"
echo "----------------------------------------"
echo "Forzando ejecución del detector de bypasses..."
# Esto se ejecuta automáticamente cada 5 minutos, pero podemos verificar los logs
docker logs soc-threat-detection --tail 20 2>&1 | grep -E "bypass|mitigación|incidente" || echo "Esperando próximo ciclo de detección..."

echo ""
echo -e "${BLUE}📋 FASE 5: Probar herramientas Red Team${NC}"
echo "----------------------------------------"
echo "Ejecutando prueba Red Team desde el SOC AI Assistant..."

# Probar Red Team
curl -sS -X POST "$DASHBOARD_API/api/mcp/chat" \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"Ejecuta una prueba Red Team de tipo XSS en el tenant 1 contra http://localhost:8080"}' | \
  python3 -c "import sys, json; d=json.load(sys.stdin); print('✅ Respuesta:', d.get('response', '')[:200])"

echo ""
echo ""
echo -e "${BLUE}📋 FASE 6: Verificar incidentes creados${NC}"
echo "----------------------------------------"
docker compose exec -T postgres psql -U soc_user -d soc_ai -c "
SELECT 
    id,
    title,
    status,
    severity,
    incident_type,
    detected_at
FROM incidents 
ORDER BY detected_at DESC 
LIMIT 5;
"

echo ""
echo -e "${BLUE}📋 FASE 7: Verificar bypasses detectados${NC}"
echo "----------------------------------------"
docker compose exec -T postgres psql -U soc_user -d soc_ai -c "
SELECT 
    id,
    source_ip,
    attack_type,
    bypass_method,
    mitigated,
    detected_at
FROM detected_bypasses 
ORDER BY detected_at DESC 
LIMIT 5;
"

echo ""
echo -e "${BLUE}📋 FASE 8: Verificar reglas ModSecurity generadas${NC}"
echo "----------------------------------------"
if [ -f "modsecurity/rules/auto-mitigation-rules.conf" ]; then
    echo "Reglas en archivo:"
    grep -c "SecRule" modsecurity/rules/auto-mitigation-rules.conf || echo "0 reglas"
    echo ""
    echo "Últimas 3 reglas:"
    tail -30 modsecurity/rules/auto-mitigation-rules.conf | grep -A 5 "SecRule" | head -20
else
    echo "Archivo de reglas aún no creado (se creará cuando se detecte un bypass)"
fi

echo ""
echo -e "${BLUE}📋 FASE 9: Verificar reglas en base de datos${NC}"
echo "----------------------------------------"
docker compose exec -T postgres psql -U soc_user -d soc_ai -c "
SELECT 
    id,
    rule_name,
    rule_type,
    enabled,
    created_by,
    created_at
FROM tenant_rules 
WHERE created_by = 'auto-mitigation-system'
ORDER BY created_at DESC 
LIMIT 5;
"

echo ""
echo -e "${BLUE}📋 FASE 10: Consultar desde SOC AI Assistant${NC}"
echo "----------------------------------------"
echo "Preguntando al SOC AI Assistant sobre incidentes recientes..."
curl -sS -X POST "$DASHBOARD_API/api/mcp/chat" \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"Muéstrame los últimos incidentes de seguridad"}' | \
  python3 -c "import sys, json; d=json.load(sys.stdin); print('✅ Respuesta:', d.get('response', '')[:300])"

echo ""
echo ""
echo -e "${GREEN}✅ =========================================="
echo -e "${GREEN}✅ PRUEBAS COMPLETADAS"
echo -e "${GREEN}✅ ==========================================${NC}"
echo ""
echo "📊 Resumen:"
echo "- Verifica los logs del servicio threat-detection para ver detecciones"
echo "- Revisa la base de datos para ver incidentes y bypasses"
echo "- Las reglas ModSecurity se generan automáticamente cuando se detectan bypasses"
echo ""
echo "💡 Para ver logs en tiempo real:"
echo "   docker logs -f soc-threat-detection"


