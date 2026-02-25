#!/bin/bash
# Script para generar tráfico de prueba específico para probar las nuevas detecciones
# Zero-Day, Ofuscación y DDoS

set -e

WAF_URL="${WAF_URL:-http://localhost:8080}"  # Cambiar según tu WAF

echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║     🧪 GENERANDO TRÁFICO DE PRUEBA PARA DETECCIÓN AVANZADA         ║"
echo "╚══════════════════════════════════════════════════════════════════════╝"
echo ""
echo "WAF URL: $WAF_URL"
echo ""

# Función para generar tráfico normal (para baseline)
generate_normal_traffic() {
    echo "📊 Generando tráfico NORMAL (para baseline)..."
    for i in {1..20}; do
        curl -s "$WAF_URL/" > /dev/null 2>&1 &
        curl -s "$WAF_URL/about" > /dev/null 2>&1 &
        curl -s "$WAF_URL/products" > /dev/null 2>&1 &
        sleep 0.1
    done
    echo "✅ Tráfico normal generado"
    echo ""
}

# Función para generar ataques ofuscados
generate_obfuscated_attacks() {
    echo "🔍 Generando ataques OFUSCADOS (encoding múltiple)..."
    
    # Ataques con encoding múltiple (doble/triple encoding)
    attacks=(
        # Double encoding
        "%2520%252f%252e%252e%252f%252fetc%252fpasswd"
        "%252e%252e%252f%252e%252e%252f%252e%252e%252fetc%252fpasswd"
        
        # Unicode encoding
        "%u002e%u002e%u002fetc%u002fpasswd"
        "%u003c%u0073%u0063%u0072%u0069%u0070%u0074%u003e"
        
        # Hex encoding
        "%2e%2e%2f%2e%2e%2fetc%2fpasswd"
        "%3c%73%63%72%69%70%74%3e%61%6c%65%72%74%28%31%29%3c%2f%73%63%72%69%70%74%3e"
        
        # Mixed encoding
        "%252e%2e%2f%252e%252e%2fetc%252fpasswd"
    )
    
    for attack in "${attacks[@]}"; do
        echo "  Enviando: ?cmd=$attack"
        curl -s "$WAF_URL/?cmd=$attack" > /dev/null 2>&1 &
        sleep 0.2
    done
    
    echo "✅ Ataques ofuscados generados"
    echo ""
}

# Función para generar ataques zero-day simulados (comportamiento anómalo)
generate_zero_day_simulation() {
    echo "🚨 Generando comportamiento ANÓMALO (simulando Zero-Day)..."
    
    # Crear URIs con patrones muy raros y únicos (no vistos antes)
    # Alta entropía, comportamientos extraños
    anomalous_patterns=(
        "/a7x9k2m1p5q8r3s6t4v1w9y2z7"
        "/m9x3k7p2q6r1s5t9v3w7y1z5"
        "/x4k8p1q5r9s3t7v2w6y0z4"
        "/?a1=z9&b2=y8&c3=x7&d4=w6&e5=v5"
        "/api/v9.YOUR_IP_ADDRESS.9/data?format=xyz123&compress=abc789"
    )
    
    for pattern in "${anomalous_patterns[@]}"; do
        echo "  Enviando: $pattern"
        curl -s "$WAF_URL$pattern" > /dev/null 2>&1 &
        curl -s -X POST "$WAF_URL$pattern" -d "data=random_$(date +%s)" > /dev/null 2>&1 &
        sleep 0.3
    done
    
    echo "✅ Comportamiento anómalo generado"
    echo ""
}

# Función para simular DDoS (múltiples IPs con mismo comportamiento)
simulate_ddos() {
    echo "🌐 Simulando DDoS DISTRIBUIDO (múltiples IPs, mismo comportamiento)..."
    
    # Simular múltiples IPs haciendo el mismo ataque coordinado
    # En un entorno real, esto vendría de diferentes IPs
    # Aquí simulamos cambiando user-agent pero manteniendo el mismo patrón
    
    ddos_pattern="/wp-admin/admin-ajax.php?action=test"
    
    for i in {1..10}; do
        # Simular diferentes user-agents (en realidad serían diferentes IPs)
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.$i"
        echo "  Request $i con UA: $user_agent"
        curl -s "$WAF_URL$ddos_pattern" \
            -H "User-Agent: $user_agent" \
            -H "X-Forwarded-For: 203.0.113.$i" > /dev/null 2>&1 &
        sleep 0.1
    done
    
    echo "✅ DDoS simulado generado"
    echo ""
}

# Main
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Generando tráfico de prueba..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# 1. Tráfico normal (para baseline - necesita ~50 episodios)
echo "1️⃣ Tráfico NORMAL (para construir baseline)"
generate_normal_traffic
sleep 2

# 2. Ataques ofuscados
echo "2️⃣ Ataques OFUSCADOS (encoding múltiple)"
generate_obfuscated_attacks
sleep 2

# 3. Zero-day simulado
echo "3️⃣ Comportamiento ANÓMALO (Zero-Day simulado)"
generate_zero_day_simulation
sleep 2

# 4. DDoS simulado
echo "4️⃣ DDoS DISTRIBUIDO (ataques coordinados)"
simulate_ddos

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ TRÁFICO DE PRUEBA GENERADO"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "⏳ Espera 5-10 minutos para que:"
echo "   1. Los logs lleguen a Kafka"
echo "   2. Se procesen y agreguen en episodios"
echo "   3. Se ejecuten las detecciones avanzadas"
echo ""
echo "📊 Luego verifica los logs con:"
echo "   ./scripts/test-deteccion-avanzada.sh"
echo ""
echo "🔍 O ver logs en tiempo real:"
echo "   gcloud run services logs tail realtime-processor --region=us-central1 --project=YOUR_GCP_PROJECT_ID"
echo ""

