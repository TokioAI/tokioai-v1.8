#!/usr/bin/env python3
"""
Script completo de prueba para demostrar el sistema de auto-mitigación
Simula un escenario donde un atacante intenta múltiples variaciones hasta encontrar un bypass
"""
import requests
import time
import subprocess
import json
from datetime import datetime

WAF_URL = "http://localhost:8080"
DASHBOARD_API = "http://localhost:9000"

print("🔥 ==========================================")
print("🔥 PRUEBA COMPLETA DEL SISTEMA DE AUTO-MITIGACIÓN")
print("🔥 ==========================================")
print("")

# Paso 1: Generar ataques que serán bloqueados
print("📋 PASO 1: Generando ataques que serán bloqueados...")
print("-" * 60)

attacks_blocked = []
attacks_allowed = []

# Ataque SQLi normal (bloqueado)
print("\n1. Ataque SQLi normal:")
r = requests.get(f"{WAF_URL}/?id=' OR '1'='1", timeout=5)
print(f"   Status: {r.status_code} - {'✅ BLOQUEADO' if r.status_code == 403 else '❌ PERMITIDO'}")
if r.status_code == 403:
    attacks_blocked.append(("SQLi", "/?id=' OR '1'='1"))
time.sleep(1)

# Ataque XSS normal (bloqueado)
print("\n2. Ataque XSS normal:")
r = requests.get(f"{WAF_URL}/?q=<script>alert('XSS')</script>", timeout=5)
print(f"   Status: {r.status_code} - {'✅ BLOQUEADO' if r.status_code == 403 else '❌ PERMITIDO'}")
if r.status_code == 403:
    attacks_blocked.append(("XSS", "/?q=<script>alert('XSS')</script>"))
time.sleep(1)

print("\n⏳ Esperando 10 segundos para que se procesen los logs...")
time.sleep(10)

# Paso 2: Verificar logs en BD
print("\n📋 PASO 2: Verificando logs en base de datos...")
print("-" * 60)
result = subprocess.run([
    "docker", "compose", "exec", "-T", "postgres",
    "psql", "-U", "soc_user", "-d", "soc_ai", "-c",
    """
    SELECT 
        id, ip, uri, blocked, threat_type, timestamp
    FROM waf_logs 
    WHERE timestamp > NOW() - INTERVAL '2 minutes'
    ORDER BY timestamp DESC
    LIMIT 10;
    """
], capture_output=True, text=True)
print(result.stdout)

# Paso 3: Forzar detección de bypasses
print("\n📋 PASO 3: Forzando detección de bypasses...")
print("-" * 60)
print("El servicio threat-detection se ejecuta automáticamente cada 5 minutos.")
print("Para probar inmediatamente, podemos usar el SOC AI Assistant:")

# Paso 4: Probar herramientas desde MCP
print("\n📋 PASO 4: Probando herramientas desde SOC AI Assistant...")
print("-" * 60)

# Consultar logs recientes
print("\n4.1 Consultando logs recientes desde PostgreSQL:")
response = requests.post(
    f"{DASHBOARD_API}/api/mcp/chat",
    json={"prompt": "Muéstrame los últimos 5 logs de ataques desde PostgreSQL"},
    timeout=30
)
if response.status_code == 200:
    data = response.json()
    print(f"   ✅ Respuesta recibida: {len(data.get('response', ''))} caracteres")
    print(f"   Respuesta: {data.get('response', '')[:200]}...")
else:
    print(f"   ❌ Error: {response.status_code}")

# Paso 5: Probar Red Team
print("\n4.2 Ejecutando prueba Red Team:")
response = requests.post(
    f"{DASHBOARD_API}/api/mcp/chat",
    json={"prompt": "Ejecuta una prueba Red Team de tipo XSS en el tenant 1 contra http://localhost:8080"},
    timeout=60
)
if response.status_code == 200:
    data = response.json()
    print(f"   ✅ Respuesta recibida")
    print(f"   Respuesta: {data.get('response', '')[:300]}...")
else:
    print(f"   ❌ Error: {response.status_code}")

# Paso 6: Verificar incidentes
print("\n📋 PASO 5: Verificando incidentes...")
print("-" * 60)
result = subprocess.run([
    "docker", "compose", "exec", "-T", "postgres",
    "psql", "-U", "soc_user", "-d", "soc_ai", "-c",
    """
    SELECT 
        id, title, status, severity, incident_type, detected_at
    FROM incidents 
    ORDER BY detected_at DESC 
    LIMIT 5;
    """
], capture_output=True, text=True)
print(result.stdout)

# Paso 7: Verificar bypasses
print("\n📋 PASO 6: Verificando bypasses detectados...")
print("-" * 60)
result = subprocess.run([
    "docker", "compose", "exec", "-T", "postgres",
    "psql", "-U", "soc_user", "-d", "soc_ai", "-c",
    """
    SELECT 
        id, source_ip, attack_type, bypass_method, mitigated, detected_at
    FROM detected_bypasses 
    ORDER BY detected_at DESC 
    LIMIT 5;
    """
], capture_output=True, text=True)
print(result.stdout)

# Paso 8: Verificar reglas generadas
print("\n📋 PASO 7: Verificando reglas ModSecurity generadas...")
print("-" * 60)
result = subprocess.run([
    "docker", "compose", "exec", "-T", "postgres",
    "psql", "-U", "soc_user", "-d", "soc_ai", "-c",
    """
    SELECT 
        id, rule_name, rule_type, enabled, created_by, created_at
    FROM tenant_rules 
    WHERE created_by = 'auto-mitigation-system'
    ORDER BY created_at DESC 
    LIMIT 5;
    """
], capture_output=True, text=True)
print(result.stdout)

# Verificar archivo de reglas
print("\nVerificando archivo de reglas ModSecurity:")
try:
    with open("modsecurity/rules/auto-mitigation-rules.conf", "r") as f:
        content = f.read()
        rule_count = content.count("SecRule")
        print(f"   ✅ Archivo existe con {rule_count} reglas")
        if rule_count > 0:
            print("   Últimas líneas:")
            print("   " + "\n   ".join(content.split("\n")[-10:]))
except FileNotFoundError:
    print("   ⚠️ Archivo aún no existe (se creará cuando se detecte un bypass)")

print("\n" + "=" * 60)
print("✅ PRUEBA COMPLETA FINALIZADA")
print("=" * 60)
print("\n💡 Para ver el sistema en acción:")
print("   1. Genera más tráfico de ataque")
print("   2. Espera 5 minutos para el próximo ciclo de detección")
print("   3. O usa el SOC AI Assistant para forzar detecciones")
print("\n📊 Monitoreo en tiempo real:")
print("   docker logs -f soc-threat-detection")


