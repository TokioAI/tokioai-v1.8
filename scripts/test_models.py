#!/usr/bin/env python3
"""Script para probar el flujo de modelos ML → Transformer → LLM"""

import json
import time
import sys
import os
from datetime import datetime
import random

try:
    from kafka import KafkaProducer
except ImportError:
    print("❌ Error: kafka-python no está instalado")
    print("   Instalando...")
    os.system("pip install -q kafka-python")
    from kafka import KafkaProducer

# Diferentes tipos de ataques para probar los modelos
ATTACKS = [
    {
        'uri': "/?id=1' OR '1'='1",
        'threat': 'SQLI',
        'status': 403,
        'desc': 'SQL Injection clara (bloqueada por WAF)'
    },
    {
        'uri': '/?q=<script>alert(1)</script>',
        'threat': 'XSS',
        'status': 403,
        'desc': 'XSS clara (bloqueada por WAF)'
    },
    {
        'uri': '/?file=../../etc/passwd',
        'threat': 'PATH_TRAVERSAL',
        'status': 200,
        'desc': 'Path Traversal NO bloqueada (debería activar LLM)'
    },
    {
        'uri': '/admin/login?user=admin&pass=test123',
        'threat': 'BRUTE_FORCE',
        'status': 401,
        'desc': 'Brute Force NO bloqueada (debería activar LLM)'
    },
    {
        'uri': '/api/users?filter=complex_query_with_suspicious_pattern',
        'threat': 'API_ABUSE',
        'status': 200,
        'desc': 'API abuse ambiguo (debería activar Transformer si ML duda)'
    },
    {
        'uri': '/normal/page?param=value',
        'threat': 'NONE',
        'status': 200,
        'desc': 'Tráfico normal'
    },
]

def main():
    kafka_bootstrap = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'YOUR_IP_ADDRESS:9093')
    kafka_topic = os.getenv('KAFKA_TOPIC_WAF_LOGS', 'waf-logs')
    
    print("=== PRUEBA DEL SISTEMA DE MODELOS ===")
    print(f"Kafka: {kafka_bootstrap}, Topic: {kafka_topic}")
    print("")
    
    producer = KafkaProducer(
        bootstrap_servers=kafka_bootstrap.split(','),
        value_serializer=lambda v: json.dumps(v).encode('utf-8'),
        acks='all',
        max_in_flight_requests_per_connection=1,
        enable_idempotence=True,
        request_timeout_ms=10000,
        delivery_timeout_ms=30000
    )
    
    print("Enviando logs de prueba con diferentes tipos de ataques...")
    print("")
    
    # Enviar cada tipo de ataque 2 veces
    for i, attack in enumerate(ATTACKS * 2, 1):
        log = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'ip': f'192.168.1.{random.randint(1, 255)}',
            'method': 'GET',
            'uri': attack['uri'],
            'status': attack['status'],
            'size': random.randint(100, 5000),
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'blocked': attack['status'] == 403,
            'tenant_id': 1
        }
        
        try:
            producer.send(kafka_topic, log)
            print(f"  ✅ {i:2d}. {attack['threat']:15s} - {attack['desc']}")
            time.sleep(0.3)
        except Exception as e:
            print(f"  ❌ Error enviando log {i}: {e}")
    
    producer.flush()
    producer.close()
    
    print("")
    print("✅ 12 logs de prueba enviados a Kafka")
    print("   Espera 15-20 segundos y verifica las métricas del procesador")

if __name__ == '__main__':
    main()









