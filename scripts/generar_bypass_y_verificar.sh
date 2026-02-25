#!/bin/bash
# Script para generar un bypass de prueba y verificar que se cree el incidente

echo "🔥 =========================================="
echo "🔥 GENERANDO BYPASS DE PRUEBA"
echo "🔥 =========================================="
echo ""

# Colores
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}📋 PASO 1: Insertando logs de bypass en la BD...${NC}"
echo "----------------------------------------"

docker compose exec -T postgres psql -U soc_user -d soc_ai << 'EOF'
-- Limpiar datos de prueba anteriores (opcional)
-- DELETE FROM incidents WHERE title LIKE '%Bypass Test%';
-- DELETE FROM detected_bypasses WHERE source_ip = 'YOUR_IP_ADDRESS';

-- Insertar ataque SQLi bloqueado
INSERT INTO waf_logs (tenant_id, timestamp, ip, method, uri, status, blocked, threat_type, raw_log)
VALUES (
    1,
    NOW() - INTERVAL '3 minutes',
    'YOUR_IP_ADDRESS',
    'GET',
    '/?id='' OR ''1''=''1',
    403,
    true,
    'SQLI',
    '{"raw": "test bypass"}'
) ON CONFLICT DO NOTHING;

-- Insertar el mismo ataque pero con URL encoding (bypass exitoso)
INSERT INTO waf_logs (tenant_id, timestamp, ip, method, uri, status, blocked, threat_type, raw_log)
VALUES (
    1,
    NOW() - INTERVAL '2 minutes',
    'YOUR_IP_ADDRESS',
    'GET',
    '/?id=%27%20OR%20%271%27%3D%271',
    200,
    false,
    'SQLI',
    '{"raw": "test bypass"}'
) ON CONFLICT DO NOTHING;

-- Verificar que se insertaron
SELECT 
    id, ip, uri, blocked, threat_type, timestamp 
FROM waf_logs 
WHERE ip = 'YOUR_IP_ADDRESS' 
ORDER BY timestamp;
EOF

echo ""
echo -e "${GREEN}✅ Logs insertados${NC}"
echo ""
echo -e "${BLUE}📋 PASO 2: Forzando detección de bypasses...${NC}"
echo "----------------------------------------"

# Ejecutar detección desde el contenedor threat-detection
docker compose exec -T threat-detection-service python3 << 'PYEOF'
import sys
import os
sys.path.insert(0, '/app')

from adaptive_learning.bypass_detector import BypassDetector
from adaptive_learning.auto_mitigation import AutoMitigationSystem
from incident_management.incident_manager import IncidentManager

print("🔍 Detectando bypasses...")

detector = BypassDetector()
bypasses = detector.detect_bypasses()

print(f"✅ Detectados {len(bypasses)} bypasses\n")

if bypasses:
    mitigation = AutoMitigationSystem()
    incident_mgr = IncidentManager()
    
    for bypass in bypasses:
        print(f"📋 Procesando bypass: IP={bypass['ip']}, Tipo={bypass['attack_type']}")
        
        # Guardar bypass
        bypass_id = detector.save_bypass(bypass)
        print(f"   ✅ Bypass guardado: ID {bypass_id}")
        
        # Crear incidente
        incident_id = incident_mgr.create_incident_for_bypass(bypass_id)
        print(f"   ✅ Incidente creado: ID {incident_id}")
        
        # Aplicar auto-mitigación
        result = mitigation.analyze_bypass_and_mitigate(bypass_id)
        if result.get("success"):
            print(f"   ✅ Auto-mitigación exitosa: Regla {result.get('rule_id')} aplicada")
        else:
            print(f"   ⚠️ Error en mitigación: {result.get('error', 'Desconocido')}")
    
    detector.close()
    mitigation.close()
    incident_mgr.close()
else:
    print("⚠️ No se detectaron bypasses")
    print("   Verificando logs en BD...")
    import psycopg2
    conn = psycopg2.connect(
        host="postgres",
        database="soc_ai",
        user="soc_user",
        password="YOUR_POSTGRES_PASSWORD"
    )
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, ip, uri, blocked, threat_type, timestamp
        FROM waf_logs
        WHERE timestamp > NOW() - INTERVAL '10 minutes'
        ORDER BY timestamp
    """)
    logs = cursor.fetchall()
    print(f"   Logs encontrados: {len(logs)}")
    for log in logs:
        print(f"     ID {log[0]}: IP={log[1]}, URI={log[2][:50]}, Blocked={log[3]}, Type={log[4]}")
    cursor.close()
    conn.close()
    detector.close()

print("\n✅ Proceso completado")
PYEOF

echo ""
echo -e "${BLUE}📋 PASO 3: Verificando resultados...${NC}"
echo "----------------------------------------"

echo ""
echo -e "${YELLOW}Bypasses detectados:${NC}"
docker compose exec -T postgres psql -U soc_user -d soc_ai -c "
SELECT 
    id, source_ip, attack_type, bypass_method, mitigated, detected_at 
FROM detected_bypasses 
ORDER BY detected_at DESC 
LIMIT 3;
"

echo ""
echo -e "${YELLOW}Incidentes creados:${NC}"
docker compose exec -T postgres psql -U soc_user -d soc_ai -c "
SELECT 
    id, title, status, severity, incident_type, detected_at 
FROM incidents 
ORDER BY detected_at DESC 
LIMIT 3;
"

echo ""
echo -e "${YELLOW}Reglas ModSecurity generadas:${NC}"
docker compose exec -T postgres psql -U soc_user -d soc_ai -c "
SELECT 
    id, rule_name, enabled, created_by, created_at 
FROM tenant_rules 
WHERE created_by = 'auto-mitigation-system'
ORDER BY created_at DESC 
LIMIT 3;
"

echo ""
echo -e "${GREEN}✅ =========================================="
echo -e "${GREEN}✅ PROCESO COMPLETADO"
echo -e "${GREEN}✅ ==========================================${NC}"
echo ""
echo "🌐 Ahora puedes ver los resultados en el dashboard:"
echo "   http://localhost:9000"
echo ""
echo "   - Tab 'Incidents': Verás el incidente creado"
echo "   - Tab 'Bypasses': Verás el bypass detectado"
echo "   - Tab 'Auto-Mitigations': Verás la regla generada"
echo ""


