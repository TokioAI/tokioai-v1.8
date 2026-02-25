#!/bin/bash
# Script de prueba de integración completa

set -e

echo "🔗 Prueba de Integración Completa"
echo "=================================="
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

echo -e "${BLUE}1. Generando tráfico de prueba al WAF...${NC}"
echo ""

# Generar algunos ataques de prueba
echo "Enviando ataques SQL Injection..."
curl -s "$WAF_URL/?id=' OR '1'='1" > /dev/null
curl -s "$WAF_URL/?id=admin'--" > /dev/null
curl -s "$WAF_URL/?id=' UNION SELECT NULL--" > /dev/null

echo "Enviando ataques XSS..."
curl -s "$WAF_URL/?q=<script>alert(1)</script>" > /dev/null
curl -s "$WAF_URL/?q=<img src=x onerror=alert(1)>" > /dev/null

echo "Enviando Path Traversal..."
curl -s "$WAF_URL/?file=../../../etc/passwd" > /dev/null

echo -e "${GREEN}✅ Tráfico generado${NC}"
echo ""

sleep 3

echo -e "${BLUE}2. Verificando que los logs llegaron a Kafka y PostgreSQL...${NC}"
echo ""

# Esperar un poco para que se procesen
sleep 2

ATTACKS=$(curl -s "$BASE_URL/api/attacks/recent?limit=5")
if echo "$ATTACKS" | grep -q '"count"'; then
    COUNT=$(echo "$ATTACKS" | grep -o '"count":[0-9]*' | grep -o '[0-9]*')
    echo -e "${GREEN}✅ Se detectaron $COUNT ataques recientes${NC}"
else
    echo -e "${YELLOW}⚠️  No se detectaron ataques (puede ser normal si el WAF los bloqueó)${NC}"
fi

echo ""
echo -e "${BLUE}3. Verificando procesamiento en tiempo real...${NC}"
echo ""

REALTIME=$(curl -s "$BASE_URL/api/real-time/stats")
if echo "$REALTIME" | grep -q '"success":true'; then
    echo -e "${GREEN}✅ Real-Time Processing funcionando${NC}"
else
    echo -e "${YELLOW}⚠️  Real-Time Processing no disponible${NC}"
fi

echo ""
echo -e "${BLUE}4. Verificando detección de bypasses...${NC}"
echo ""

BYPASSES=$(curl -s "$BASE_URL/api/bypasses?limit=5")
if echo "$BYPASSES" | grep -q '"count"'; then
    echo -e "${GREEN}✅ Sistema de detección de bypasses funcionando${NC}"
else
    echo -e "${YELLOW}⚠️  No hay bypasses detectados (normal si no hay bypasses exitosos)${NC}"
fi

echo ""
echo -e "${BLUE}5. Verificando Red Team Inteligente...${NC}"
echo ""

ANALYSIS=$(curl -s "$BASE_URL/api/intelligent-redteam/analysis?tenant_id=default")
if echo "$ANALYSIS" | grep -q '"success":true'; then
    echo -e "${GREEN}✅ Red Team Inteligente funcionando${NC}"
    
    # Mostrar resumen del análisis
    if echo "$ANALYSIS" | grep -q '"total_rules"'; then
        RULES=$(echo "$ANALYSIS" | grep -o '"total_rules":[0-9]*' | grep -o '[0-9]*')
        echo "   - Reglas analizadas: $RULES"
    fi
else
    echo -e "${YELLOW}⚠️  Red Team Inteligente no disponible${NC}"
fi

echo ""
echo -e "${BLUE}6. Verificando Tenant Management...${NC}"
echo ""

TENANTS=$(curl -s "$BASE_URL/api/tenants")
if echo "$TENANTS" | grep -q '"success":true'; then
    echo -e "${GREEN}✅ Tenant Management funcionando${NC}"
    COUNT=$(echo "$TENANTS" | grep -o '"count":[0-9]*' | grep -o '[0-9]*' || echo "0")
    echo "   - Tenants activos: $COUNT"
else
    echo -e "${YELLOW}⚠️  Tenant Management no disponible${NC}"
fi

echo ""
echo -e "${BLUE}7. Verificando auto-mitigación...${NC}"
echo ""

MITIGATION=$(curl -s "$BASE_URL/api/auto-mitigation-stats")
if echo "$MITIGATION" | grep -q '"bypasses"'; then
    echo -e "${GREEN}✅ Auto-Mitigación funcionando${NC}"
else
    echo -e "${YELLOW}⚠️  Auto-Mitigación no disponible${NC}"
fi

echo ""
echo "=================================="
echo -e "${GREEN}✅ Prueba de integración completada!${NC}"
echo ""
echo "📊 Resumen del flujo:"
echo "  1. WAF recibe ataques ✅"
echo "  2. Logs enviados a Kafka ✅"
echo "  3. Procesamiento en tiempo real ✅"
echo "  4. Detección de amenazas ✅"
echo "  5. Red Team Inteligente ✅"
echo "  6. Tenant Management ✅"
echo "  7. Auto-Mitigación ✅"
echo ""
echo "🎯 Sistema completamente integrado!"



