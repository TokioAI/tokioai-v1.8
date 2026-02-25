#!/usr/bin/env python3
"""
Script simple para enviar logs de prueba a Kafka
"""
import json
import time
import random
from kafka import KafkaProducer
from datetime import datetime

# Configuración
KAFKA_BROKERS = "YOUR_IP_ADDRESS:9093"
TOPIC = "waf-logs"

# Patrones de ataques
ATTACKS = [
    {"uri": "/?id=1' OR '1'='1", "threat": "SQLI", "status": 403},
    {"uri": "/?q=<script>alert(1)</script>", "threat": "XSS", "status": 403},
    {"uri": "/?file=../../etc/passwd", "threat": "PATH_TRAVERSAL", "status": 403},
    {"uri": "/?cmd=;ls", "threat": "CMD_INJECTION", "status": 403},
    {"uri": "/api/users", "threat": "SCAN_PROBE", "status": 404},
    {"uri": "/admin/login", "threat": "BRUTE_FORCE", "status": 401},
]

def create_log(attack):
    return {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "ip": f"192.168.1.{random.randint(1, 255)}",
        "method": "GET",
        "uri": attack["uri"],
        "status": attack["status"],
        "size": random.randint(100, 5000),
        "user_agent": "Mozilla/5.0",
        "referer": "",
        "blocked": attack["status"] == 403,
        "tenant_id": 1
    }

def main():
    print(f"Conectando a Kafka: {KAFKA_BROKERS}")
    producer = KafkaProducer(
        bootstrap_servers=KAFKA_BROKERS.split(','),
        value_serializer=lambda v: json.dumps(v).encode('utf-8'),
        acks=1,
        retries=3
    )
    
    print(f"Enviando logs al topic: {TOPIC}")
    sent = 0
    for i in range(50):  # Enviar 50 logs
        attack = random.choice(ATTACKS)
        log = create_log(attack)
        
        try:
            future = producer.send(TOPIC, log)
            future.get(timeout=5)
            sent += 1
            if (i + 1) % 10 == 0:
                print(f"  ✅ Enviados {i + 1} logs...")
            time.sleep(0.1)
        except Exception as e:
            print(f"  ❌ Error enviando log {i+1}: {e}")
    
    producer.flush()
    producer.close()
    print(f"\n✅ Total enviados: {sent} logs")

if __name__ == "__main__":
    main()









