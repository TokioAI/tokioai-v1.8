#!/bin/bash
# Script para probar el sistema de batch analysis + LLM agente

DOMAIN="${1:-airesiliencehub.space}"
echo "🧪 PROBANDO BATCH ANALYSIS + LLM AGENTE"
echo "========================================"
echo ""
echo "🎯 Objetivo: https://${DOMAIN}"
echo ""
echo "Este script generará 5 ataques diferentes desde la misma IP"
echo "El sistema debería:"
echo "  1. Detectar 3+ ataques sospechosos (heurística)"
echo "  2. Agrupar en batch buffer"
echo "  3. Consultar LLM como agente de decisión"
echo "  4. LLM decide si bloquear la IP"
echo ""

# Función para hacer request
make_attack() {
    local url=$1
    local desc=$2
    echo "📤 ${desc}"
    curl -s -k -w "\nStatus: %{http_code}\n" -X GET "https://${DOMAIN}${url}" > /dev/null 2>&1
    echo "✅ Enviado"
    sleep 2  # Esperar 2 segundos entre ataques
}

echo "🚀 Generando ataques de prueba..."
echo ""

# Ataque 1: Path Traversal
make_attack "/cgi-bin/../../../etc/passwd" "1️⃣ PATH_TRAVERSAL"

# Ataque 2: XSS
make_attack "/%3Cscript%3Ealert('XSS')%3C/script%3E" "2️⃣ XSS"

# Ataque 3: SQL Injection
make_attack "/test?id=1' OR '1'='1" "3️⃣ SQLI"

# Ataque 4: Path Traversal (variante)
make_attack "/cgi-bin/.%2e/.%2e/.%2e/.%2e/etc/passwd" "4️⃣ PATH_TRAVERSAL (variante)"

# Ataque 5: Command Injection
make_attack "/test?cmd=cat /etc/passwd" "5️⃣ CMD_INJECTION"

echo ""
echo "✅ Ataques generados"
echo ""
echo "📊 VERIFICACIÓN:"
echo ""
echo "1. Ver logs en tiempo real (buscar 'LLM' o 'batch'):"
echo "   gcloud run services logs read realtime-processor --region=us-central1 --project=YOUR_GCP_PROJECT_ID --limit=100 | grep -i 'llm\|batch\|BLOQUEAR'"
echo ""
echo "2. Ver en el dashboard (espera 10-15 segundos):"
echo "   https://YOUR_DASHBOARD_API_URL"
echo "   Busca logs con:"
echo "     - Source: 'Batch+LLM' o 'Batch Analysis'"
echo "     - Status: 403"
echo "     - Decision: 'Blocked' (rojo)"
echo ""
echo "3. Buscar en logs específicamente:"
echo "   - '🤖 Consultando LLM para decisión'"
echo "   - '✅ LLM DECIDIÓ BLOQUEAR IP'"
echo "   - '🛡️ MITIGACIÓN AUTOMÁTICA ENVIADA (BATCH)'"
echo ""
