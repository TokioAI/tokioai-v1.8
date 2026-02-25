#!/usr/bin/env python3
"""
Script para probar manualmente el detector de bypasses
"""
import sys
import os
sys.path.insert(0, '/home/osboxes/SOC-AI-LAB')

from adaptive_learning.bypass_detector import BypassDetector

print("🔍 Probando detector de bypasses manualmente...")
print("=" * 60)

detector = BypassDetector()
bypasses = detector.detect_bypasses()

print(f"\n✅ Detectados {len(bypasses)} bypasses\n")

if bypasses:
    for i, bypass in enumerate(bypasses, 1):
        print(f"Bypass {i}:")
        print(f"  IP: {bypass['ip']}")
        print(f"  Tipo: {bypass['attack_type']}")
        print(f"  Método: {bypass['bypass_method']}")
        print(f"  Confianza: {bypass['confidence']}")
        print(f"  Bloqueado: {bypass['blocked_request']['uri']}")
        print(f"  Permitido: {bypass['allowed_request']['uri']}")
        print()
else:
    print("⚠️ No se detectaron bypasses")
    print("\nVerificando logs en BD...")
    import psycopg2
    conn = psycopg2.connect(
        host="localhost",
        port=5432,
        database="soc_ai",
        user="soc_user",
        password="YOUR_POSTGRES_PASSWORD"
    )
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, ip, uri, blocked, threat_type, timestamp
        FROM waf_logs
        WHERE timestamp > NOW() - INTERVAL '60 minutes'
        ORDER BY timestamp
    """)
    logs = cursor.fetchall()
    print(f"Logs encontrados: {len(logs)}")
    for log in logs:
        print(f"  ID {log[0]}: IP={log[1]}, URI={log[2][:50]}, Blocked={log[3]}, Type={log[4]}")
    cursor.close()
    conn.close()

detector.close()


