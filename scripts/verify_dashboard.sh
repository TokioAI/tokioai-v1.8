#!/bin/bash
# Script para verificar que el dashboard funcione correctamente

set -e

echo "🔍 Verificando Dashboard..."
echo "=========================="
echo ""

BASE_URL="http://localhost:9000"

# Colores
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Función para verificar endpoint
check_endpoint() {
    local name=$1
    local url=$2
    local expected_field=$3
    
    echo -n "Verificando $name... "
    response=$(curl -s "$url" 2>/dev/null || echo '{"error":"connection failed"}')
    
    if echo "$response" | grep -q "$expected_field"; then
        echo -e "${GREEN}✅ OK${NC}"
        return 0
    else
        echo -e "${RED}❌ FAIL${NC}"
        echo "  Response: $(echo "$response" | head -c 200)"
        return 1
    fi
}

echo -e "${BLUE}1. Verificando endpoints básicos...${NC}"
echo ""

check_endpoint "Health" "$BASE_URL/health" '"status"'
check_endpoint "Stats Summary" "$BASE_URL/api/stats/summary?limit=10" '"total_requests"'
check_endpoint "Recent Attacks" "$BASE_URL/api/attacks/recent?limit=5" '"count"'
check_endpoint "Incidents" "$BASE_URL/api/incidents?limit=5" '"items"'
check_endpoint "Bypasses" "$BASE_URL/api/bypasses?limit=5" '"items"'
check_endpoint "Red Team Status" "$BASE_URL/api/redteam/status" '"running"'

echo ""
echo -e "${BLUE}2. Verificando nuevos endpoints (Fases 4 y 5)...${NC}"
echo ""

check_endpoint "Intelligent Red Team Analysis" "$BASE_URL/api/intelligent-redteam/analysis?tenant_id=default" '"success"'
check_endpoint "Intelligent Red Team Suggestions" "$BASE_URL/api/intelligent-redteam/suggestions?tenant_id=default" '"success"'
check_endpoint "Tenants List" "$BASE_URL/api/tenants" '"success"'
check_endpoint "Real-Time Stats" "$BASE_URL/api/real-time/stats" '"success"'

echo ""
echo -e "${BLUE}3. Verificando estructura del dashboard...${NC}"
echo ""

# Verificar que el HTML del dashboard se sirva correctamente
dashboard_response=$(curl -s "$BASE_URL/" 2>/dev/null || echo "")
if echo "$dashboard_response" | grep -q "Tokio AI"; then
    echo -e "${GREEN}✅ Dashboard HTML se sirve correctamente${NC}"
else
    echo -e "${RED}❌ Dashboard HTML no se sirve correctamente${NC}"
fi

# Verificar que las nuevas secciones estén en el HTML
if echo "$dashboard_response" | grep -q "intelligent-redteam"; then
    echo -e "${GREEN}✅ Sección Intelligent Red Team presente${NC}"
else
    echo -e "${YELLOW}⚠️  Sección Intelligent Red Team no encontrada${NC}"
fi

if echo "$dashboard_response" | grep -q "tab-tenants"; then
    echo -e "${GREEN}✅ Sección Tenants presente${NC}"
else
    echo -e "${YELLOW}⚠️  Sección Tenants no encontrada${NC}"
fi

if echo "$dashboard_response" | grep -q "tab-realtime"; then
    echo -e "${GREEN}✅ Sección Real-Time presente${NC}"
else
    echo -e "${YELLOW}⚠️  Sección Real-Time no encontrada${NC}"
fi

# Verificar funciones JavaScript
if echo "$dashboard_response" | grep -q "renderIntelligentRedTeam"; then
    echo -e "${GREEN}✅ Función renderIntelligentRedTeam presente${NC}"
else
    echo -e "${RED}❌ Función renderIntelligentRedTeam no encontrada${NC}"
fi

if echo "$dashboard_response" | grep -q "renderTenants"; then
    echo -e "${GREEN}✅ Función renderTenants presente${NC}"
else
    echo -e "${RED}❌ Función renderTenants no encontrada${NC}"
fi

if echo "$dashboard_response" | grep -q "renderRealtime"; then
    echo -e "${GREEN}✅ Función renderRealtime presente${NC}"
else
    echo -e "${RED}❌ Función renderRealtime no encontrada${NC}"
fi

echo ""
echo "=========================="
echo -e "${GREEN}✅ Verificación completada!${NC}"
echo ""
echo "📋 Resumen:"
echo "  - Endpoints básicos verificados"
echo "  - Nuevos endpoints verificados"
echo "  - Estructura del dashboard verificada"
echo ""
echo "🌐 Accede al dashboard en: $BASE_URL"



