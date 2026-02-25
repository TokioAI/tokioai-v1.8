#!/usr/bin/env python3
"""Script para desbloquear una IP"""
import os
import sys
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

ip_to_unblock = sys.argv[1] if len(sys.argv) > 1 else None

if not ip_to_unblock:
    print("❌ Error: Debes proporcionar una IP para desbloquear")
    print("Uso: python unblock_ip.py <IP_ADDRESS>")
    sys.exit(1)

host = os.getenv('POSTGRES_HOST', 'localhost')
port = os.getenv('POSTGRES_PORT', '5432')
database = os.getenv('POSTGRES_DB', 'soc_ai')
user = os.getenv('POSTGRES_USER', 'soc_user')
password = os.getenv('POSTGRES_PASSWORD', '')

print(f"🔓 Desbloqueando IP: {ip_to_unblock}...")

conn = psycopg2.connect(host=host, port=port, database=database, user=user, password=password)
conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
cursor = conn.cursor()

# Verificar si está bloqueada
cursor.execute("SELECT ip, blocked_at, expires_at, active, reason FROM blocked_ips WHERE ip::text = %s ORDER BY blocked_at DESC LIMIT 1", (ip_to_unblock,))
result = cursor.fetchone()

if not result:
    print(f"ℹ️  La IP {ip_to_unblock} no está bloqueada.")
else:
    ip, blocked_at, expires_at, active, reason = result
    print(f"📋 Estado: IP={ip}, Activa={active}, Razón={reason}")
    
    if active:
        cursor.execute("UPDATE blocked_ips SET active = FALSE WHERE ip::text = %s AND active = TRUE", (ip_to_unblock,))
        print(f"✅ IP {ip_to_unblock} desbloqueada exitosamente!")
    else:
        print(f"ℹ️  La IP ya estaba desbloqueada.")

cursor.close()
conn.close()
print("✅ Proceso completado")
