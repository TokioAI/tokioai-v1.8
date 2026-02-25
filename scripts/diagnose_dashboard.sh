#!/bin/bash
# Script de diagnóstico completo del dashboard

set -e

echo "🔍 Diagnóstico Completo del Dashboard"
echo "======================================"
echo ""

BASE_URL="http://localhost:9000"
TENANT_API_URL="http://localhost:8003"
WAF_URL="http://localhost:8080"

# Colores
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}1. Verificando servicios Docker...${NC}"
echo ""

if docker ps | grep -q "soc-dashboard-api"; then
    echo -e "${GREEN}✅ Dashboard API está corriendo${NC}"
else
    echo -e "${RED}❌ Dashboard API NO está corriendo${NC}"
    echo "   Ejecuta: docker-compose up -d dashboard-api"
fi

if docker ps | grep -q "soc-postgres"; then
    echo -e "${GREEN}✅ PostgreSQL está corriendo${NC}"
else
    echo -e "${RED}❌ PostgreSQL NO está corriendo${NC}"
fi

if docker ps | grep -q "soc-kafka"; then
    echo -e "${GREEN}✅ Kafka está corriendo${NC}"
else
    echo -e "${RED}❌ Kafka NO está corriendo${NC}"
fi

echo ""
echo -e "${BLUE}2. Verificando conectividad...${NC}"
echo ""

# Verificar que el dashboard responda
if curl -s "$BASE_URL/health" > /dev/null 2>&1; then
    echo -e "${GREEN}✅ Dashboard API responde en $BASE_URL${NC}"
    health=$(curl -s "$BASE_URL/health")
    echo "   Response: $health"
else
    echo -e "${RED}❌ Dashboard API NO responde en $BASE_URL${NC}"
    echo "   Verifica que el servicio esté corriendo y el puerto 9000 esté disponible"
fi

echo ""
echo -e "${BLUE}3. Verificando endpoints del API...${NC}"
echo ""

# Verificar cada endpoint
endpoints=(
    "/api/stats/summary?limit=10"
    "/api/attacks/recent?limit=5"
    "/api/incidents?limit=5"
    "/api/bypasses?limit=5"
    "/api/intelligent-redteam/analysis?tenant_id=default"
    "/api/tenants"
    "/api/real-time/stats"
)

for endpoint in "${endpoints[@]}"; do
    echo -n "  Verificando $endpoint... "
    response=$(curl -s "$BASE_URL$endpoint" 2>/dev/null || echo '{"error":"connection failed"}')
    if echo "$response" | grep -q "error\|Error\|ERROR"; then
        echo -e "${RED}❌${NC}"
        echo "    Error: $(echo "$response" | head -c 150)"
    else
        echo -e "${GREEN}✅${NC}"
        # Mostrar un resumen de la respuesta
        if echo "$response" | grep -q '"success"'; then
            success=$(echo "$response" | grep -o '"success":[^,}]*' | head -1)
            echo "    $success"
        fi
    fi
done

echo ""
echo -e "${BLUE}4. Verificando base de datos...${NC}"
echo ""

# Verificar conexión a PostgreSQL
if docker exec soc-postgres psql -U soc_user -d soc_ai -c "SELECT COUNT(*) FROM waf_logs;" > /dev/null 2>&1; then
    echo -e "${GREEN}✅ Conexión a PostgreSQL OK${NC}"
    
    # Contar registros
    waf_logs=$(docker exec soc-postgres psql -U soc_user -d soc_ai -t -c "SELECT COUNT(*) FROM waf_logs;" 2>/dev/null | tr -d ' ')
    incidents=$(docker exec soc-postgres psql -U soc_user -d soc_ai -t -c "SELECT COUNT(*) FROM incidents;" 2>/dev/null | tr -d ' ')
    bypasses=$(docker exec soc-postgres psql -U soc_user -d soc_ai -t -c "SELECT COUNT(*) FROM detected_bypasses;" 2>/dev/null | tr -d ' ')
    
    echo "   WAF Logs: $waf_logs"
    echo "   Incidents: $incidents"
    echo "   Bypasses: $bypasses"
    
    if [ "$waf_logs" -eq "0" ]; then
        echo -e "${YELLOW}⚠️  No hay logs en la base de datos${NC}"
        echo "   Genera tráfico de prueba: curl \"$WAF_URL/?id=' OR '1'='1\""
    fi
else
    echo -e "${RED}❌ No se puede conectar a PostgreSQL${NC}"
fi

echo ""
echo -e "${BLUE}5. Verificando logs del dashboard...${NC}"
echo ""

# Ver últimos logs del dashboard
echo "Últimos 10 logs del dashboard-api:"
docker logs soc-dashboard-api --tail 10 2>&1 | tail -10 || echo "No se pudieron obtener logs"

echo ""
echo -e "${BLUE}6. Generando tráfico de prueba...${NC}"
echo ""

# Generar algunos ataques de prueba
echo "Enviando ataques de prueba al WAF..."
for i in {1..3}; do
    curl -s "$WAF_URL/?id=' OR '1'='1" > /dev/null
    curl -s "$WAF_URL/?q=<script>alert(1)</script>" > /dev/null
done

echo -e "${GREEN}✅ Tráfico de prueba enviado${NC}"
echo "   Espera 5 segundos para que se procesen..."
sleep 5

# Verificar si ahora hay datos
new_waf_logs=$(docker exec soc-postgres psql -U soc_user -d soc_ai -t -c "SELECT COUNT(*) FROM waf_logs;" 2>/dev/null | tr -d ' ')
echo "   WAF Logs después del tráfico: $new_waf_logs"

echo ""
echo "======================================"
echo -e "${GREEN}✅ Diagnóstico completado!${NC}"
echo ""
echo "📋 Resumen:"
echo "  - Servicios verificados"
echo "  - Endpoints verificados"
echo "  - Base de datos verificada"
echo "  - Tráfico de prueba generado"
echo ""
echo "🌐 Accede al dashboard en: $BASE_URL"



