#!/usr/bin/env python3
"""
Script para simular un bypass insertando logs directamente en la BD
Esto permite probar el sistema de auto-mitigación sin esperar el flujo completo
"""
import psycopg2
from datetime import datetime, timedelta
import json

# Conectar a PostgreSQL
conn = psycopg2.connect(
    host="localhost",
    port=5432,
    database="soc_ai",
    user="soc_user",
    password="YOUR_POSTGRES_PASSWORD"
)

cursor = conn.cursor()

print("🔥 Simulando escenario de bypass...")
print("=" * 60)

# Obtener tenant_id por defecto
cursor.execute("SELECT id FROM tenants LIMIT 1")
tenant_result = cursor.fetchone()
tenant_id = tenant_result[0] if tenant_result else 1

print(f"✅ Usando tenant_id: {tenant_id}")

# Simular: Un ataque SQLi que fue bloqueado
print("\n1️⃣ Insertando ataque SQLi BLOQUEADO...")
now = datetime.now()
blocked_time = now - timedelta(minutes=2)

cursor.execute("""
    INSERT INTO waf_logs 
    (tenant_id, timestamp, ip, method, uri, status, size, user_agent, referer, blocked, threat_type, severity, raw_log)
    VALUES 
    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    RETURNING id
""", (
    tenant_id,
    blocked_time,
    "YOUR_IP_ADDRESS",
    "GET",
    "/?id=' OR '1'='1",
    403,
    146,
    "curl/8.5.0",
    "-",
    True,  # BLOQUEADO
    "SQLI",
    "high",
    json.dumps({"raw": "test"})
))
blocked_log_id = cursor.fetchone()[0]
print(f"   ✅ Log bloqueado insertado: ID {blocked_log_id}")

# Simular: El mismo ataque pero con ofuscación que fue PERMITIDO (bypass)
print("\n2️⃣ Insertando el MISMO ataque pero con ofuscación PERMITIDO (bypass)...")
allowed_time = now - timedelta(minutes=1)  # Después del bloqueado

cursor.execute("""
    INSERT INTO waf_logs 
    (tenant_id, timestamp, ip, method, uri, status, size, user_agent, referer, blocked, threat_type, severity, raw_log)
    VALUES 
    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    RETURNING id
""", (
    tenant_id,
    allowed_time,
    "YOUR_IP_ADDRESS",  # Misma IP
    "GET",
    "/?id=%27%20OR%20%271%27%3D%271",  # Mismo ataque pero con URL encoding
    200,  # PERMITIDO (bypass exitoso)
    200,
    "curl/8.5.0",
    "-",
    False,  # PERMITIDO (bypass)
    "SQLI",  # Mismo tipo de ataque
    None,
    json.dumps({"raw": "test"})
))
allowed_log_id = cursor.fetchone()[0]
print(f"   ✅ Log permitido (bypass) insertado: ID {allowed_log_id}")

conn.commit()
print("\n✅ Escenario de bypass simulado correctamente")
print(f"   - Ataque bloqueado: ID {blocked_log_id} (timestamp: {blocked_time})")
print(f"   - Ataque permitido (bypass): ID {allowed_log_id} (timestamp: {allowed_time})")

# Verificar que se insertaron
cursor.execute("""
    SELECT id, ip, uri, blocked, threat_type, timestamp
    FROM waf_logs
    WHERE id IN (%s, %s)
    ORDER BY timestamp
""", (blocked_log_id, allowed_log_id))

print("\n📊 Logs insertados:")
for row in cursor.fetchall():
    print(f"   ID {row[0]}: IP={row[1]}, URI={row[2][:50]}, Blocked={row[3]}, Type={row[4]}, Time={row[5]}")

cursor.close()
conn.close()

print("\n" + "=" * 60)
print("✅ Ahora el detector de bypasses debería detectar este bypass")
print("   El servicio threat-detection se ejecuta cada 5 minutos")
print("   O puedes usar el SOC AI Assistant para forzar la detección")
print("=" * 60)


