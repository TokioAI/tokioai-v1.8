#!/usr/bin/env python3
"""
Script para generar ataques de prueba y verificar el sistema completo
"""
import requests
import time
import urllib.parse
from datetime import datetime

WAF_URL = "http://localhost:8080"

print("🔥 Generando ataques de prueba...")
print("=" * 60)

# 1. Ataque SQLi normal (será bloqueado)
print("\n1️⃣ Ataque SQLi normal (debe ser bloqueado):")
payload1 = "?id=' OR '1'='1"
url1 = WAF_URL + payload1
try:
    r = requests.get(url1, timeout=5)
    print(f"   Status: {r.status_code}")
    print(f"   Bloqueado: {'✅ SÍ' if r.status_code == 403 else '❌ NO'}")
except Exception as e:
    print(f"   Error: {e}")
time.sleep(2)

# 2. Ataque XSS normal (será bloqueado)
print("\n2️⃣ Ataque XSS normal (debe ser bloqueado):")
payload2 = "?q=<script>alert('XSS')</script>"
url2 = WAF_URL + payload2
try:
    r = requests.get(url2, timeout=5)
    print(f"   Status: {r.status_code}")
    print(f"   Bloqueado: {'✅ SÍ' if r.status_code == 403 else '❌ NO'}")
except Exception as e:
    print(f"   Error: {e}")
time.sleep(2)

# 3. Bypass con URL encoding (puede pasar)
print("\n3️⃣ Bypass con URL encoding (puede pasar):")
payload3 = "?id=%27%20OR%20%271%27%3D%271"
url3 = WAF_URL + payload3
try:
    r = requests.get(url3, timeout=5)
    print(f"   Status: {r.status_code}")
    print(f"   Bloqueado: {'✅ SÍ' if r.status_code == 403 else '⚠️ PERMITIDO (posible bypass)'}")
except Exception as e:
    print(f"   Error: {e}")
time.sleep(2)

# 4. Bypass con double encoding
print("\n4️⃣ Bypass con double encoding:")
payload4 = "?id=%2527%20OR%20%25271%2527%3D%25271"
url4 = WAF_URL + payload4
try:
    r = requests.get(url4, timeout=5)
    print(f"   Status: {r.status_code}")
    print(f"   Bloqueado: {'✅ SÍ' if r.status_code == 403 else '⚠️ PERMITIDO (posible bypass)'}")
except Exception as e:
    print(f"   Error: {e}")
time.sleep(2)

# 5. Path Traversal
print("\n5️⃣ Path Traversal:")
payload5 = "?file=../../../etc/passwd"
url5 = WAF_URL + payload5
try:
    r = requests.get(url5, timeout=5)
    print(f"   Status: {r.status_code}")
    print(f"   Bloqueado: {'✅ SÍ' if r.status_code == 403 else '❌ NO'}")
except Exception as e:
    print(f"   Error: {e}")
time.sleep(2)

# 6. Command Injection
print("\n6️⃣ Command Injection:")
payload6 = "?cmd=; cat /etc/passwd"
url6 = WAF_URL + payload6
try:
    r = requests.get(url6, timeout=5)
    print(f"   Status: {r.status_code}")
    print(f"   Bloqueado: {'✅ SÍ' if r.status_code == 403 else '❌ NO'}")
except Exception as e:
    print(f"   Error: {e}")

print("\n" + "=" * 60)
print("✅ Ataques generados. Esperando 15 segundos para procesamiento...")
time.sleep(15)

print("\n📊 Verificando logs en base de datos...")
import subprocess
result = subprocess.run([
    "docker", "compose", "exec", "-T", "postgres", 
    "psql", "-U", "soc_user", "-d", "soc_ai", "-c",
    """
    SELECT 
        COUNT(*) as total,
        COUNT(*) FILTER (WHERE blocked = true) as bloqueados,
        COUNT(*) FILTER (WHERE blocked = false) as permitidos,
        COUNT(*) FILTER (WHERE threat_type IS NOT NULL) as con_tipo
    FROM waf_logs 
    WHERE timestamp > NOW() - INTERVAL '10 minutes';
    """
], capture_output=True, text=True)
print(result.stdout)

print("\n✅ Pruebas completadas!")


