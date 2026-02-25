#!/bin/bash
# Script para probar las nuevas capacidades de detección avanzada
# Zero-Day, Ofuscación y DDoS

set -e

PROJECT_ID="YOUR_GCP_PROJECT_ID"
REGION="us-central1"
DASHBOARD_URL=$(gcloud run services describe dashboard-api --region=$REGION --project=$PROJECT_ID --format='value(status.url)' 2>/dev/null || echo "")

echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║     🧪 PRUEBA DE DETECCIÓN AVANZADA - Zero-Day, Ofuscación, DDoS   ║"
echo "╚══════════════════════════════════════════════════════════════════════╝"
echo ""
echo "Este script prueba las nuevas capacidades:"
echo "  ✅ Detección de Zero-Day (baseline estadístico)"
echo "  ✅ Detección de Ofuscación (entropía + encoding)"
echo "  ✅ Detección de DDoS Distribuido (correlación)"
echo ""

# Colores
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Función para verificar logs
check_logs() {
    local search_term=$1
    local service=$2
    echo -e "${BLUE}📊 Verificando logs de $service...${NC}"
    
    gcloud run services logs read $service \
        --region=$REGION \
        --project=$PROJECT_ID \
        --limit=50 2>/dev/null | grep -i "$search_term" | head -5 || echo "  (no encontrado aún)"
    echo ""
}

# Función para ver episodios en dashboard
check_episodes() {
    if [ -z "$DASHBOARD_URL" ]; then
        echo -e "${YELLOW}⚠️  Dashboard URL no disponible${NC}"
        return
    fi
    
    echo -e "${BLUE}📊 Verificando episodios en dashboard...${NC}"
    echo "  URL: $DASHBOARD_URL/episodes"
    echo ""
}

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "1️⃣  VERIFICANDO QUE EL SISTEMA ESTÉ FUNCIONANDO"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Verificar que los servicios estén corriendo
echo -e "${BLUE}🔍 Verificando servicios...${NC}"
SERVICES=$(gcloud run services list --region=$REGION --project=$PROJECT_ID --format="value(name)" 2>/dev/null)

if echo "$SERVICES" | grep -q "realtime-processor"; then
    echo -e "${GREEN}✅ realtime-processor está corriendo${NC}"
else
    echo -e "${RED}❌ realtime-processor NO está corriendo${NC}"
    exit 1
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "2️⃣  VERIFICANDO INICIALIZACIÓN DEL ENHANCER"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo -e "${BLUE}🔍 Buscando logs de inicialización...${NC}"
gcloud run services logs read realtime-processor \
    --region=$REGION \
    --project=$PROJECT_ID \
    --limit=100 2>/dev/null | grep -i "EpisodeIntelligenceEnhancer\|enhancement\|zero-day\|ofuscación\|DDoS" | head -10

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✅ Enhancer detectado en logs${NC}"
else
    echo -e "${YELLOW}⚠️  Enhancer no encontrado en logs recientes (puede necesitar tiempo para inicializar)${NC}"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "3️⃣  GENERANDO TRÁFICO DE PRUEBA"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo -e "${YELLOW}⚠️  Para generar tráfico de prueba, puedes:${NC}"
echo ""
echo "  Opción A: Usar el script de ataques existente:"
echo "    ./scripts/test-ataques-rapido.sh"
echo ""
echo "  Opción B: Enviar requests manuales al WAF:"
echo "    # Ataque normal (SQL Injection):"
echo "    curl 'http://TU_WAF/?id=1%20OR%201=1'"
echo ""
echo "    # Ataque ofuscado (encoding múltiple):"
echo "    curl 'http://TU_WAF/?cmd=%2520%252f%252e%252e%252f%252fetc%252fpasswd'"
echo ""
echo "    # Zero-day simulado (comportamiento anómalo sin patrones conocidos):"
echo "    # Necesitas generar tráfico con patrones muy raros"
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "4️⃣  VERIFICANDO DETECCIONES EN LOGS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo -e "${BLUE}📊 Últimos logs del realtime-processor:${NC}"
echo ""

# Buscar logs recientes con detecciones
echo "🔍 Buscando detecciones de Zero-Day:"
check_logs "zero-day\|zero_day\|ZERO-DAY" "realtime-processor"

echo "🔍 Buscando detecciones de Ofuscación:"
check_logs "ofuscaci\|obfuscation\|OFUSCACIÓN" "realtime-processor"

echo "🔍 Buscando detecciones de DDoS:"
check_logs "ddos\|DDoS\|distributed" "realtime-processor"

echo "🔍 Buscando enhancement completado:"
check_logs "enhancement\|Enhanced risk" "realtime-processor"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "5️⃣  VERIFICANDO MÉTRICAS Y ESTADÍSTICAS"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ ! -z "$DASHBOARD_URL" ]; then
    echo -e "${BLUE}📊 Dashboard disponible:${NC}"
    echo "  URL: $DASHBOARD_URL"
    echo ""
    echo "  Puedes verificar:"
    echo "  - Episodios: $DASHBOARD_URL/episodes"
    echo "  - Logs: $DASHBOARD_URL/logs"
    echo "  - Estadísticas: $DASHBOARD_URL/stats"
    echo ""
else
    echo -e "${YELLOW}⚠️  Dashboard URL no disponible${NC}"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "6️⃣  COMANDOS ÚTILES PARA MONITOREAR"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo ""
echo "📋 Ver logs en tiempo real:"
echo "   gcloud run services logs tail realtime-processor --region=$REGION --project=$PROJECT_ID"
echo ""
echo "📊 Ver últimos 100 logs:"
echo "   gcloud run services logs read realtime-processor --region=$REGION --project=$PROJECT_ID --limit=100"
echo ""
echo "🔍 Buscar detecciones específicas:"
echo "   gcloud run services logs read realtime-processor --region=$REGION --project=$PROJECT_ID --limit=200 | grep -i 'zero-day\|ofuscación\|ddos\|enhancement'"
echo ""
echo "📈 Ver episodios procesados:"
echo "   gcloud run services logs read realtime-processor --region=$REGION --project=$PROJECT_ID --limit=200 | grep -i 'procesando episodio\|episodio cerrado'"
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ VERIFICACIÓN COMPLETA"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "💡 Próximos pasos:"
echo "   1. Genera tráfico de prueba (normal y ataques)"
echo "   2. Espera 5-10 minutos para que se procesen episodios"
echo "   3. Verifica los logs buscando las palabras clave mencionadas"
echo "   4. Revisa el dashboard para ver episodios con detecciones avanzadas"
echo ""
echo "⚠️  Nota: El baseline de Zero-Day necesita ~50 episodios normales para activarse"
echo "   (se actualiza cada hora automáticamente)"
echo ""

