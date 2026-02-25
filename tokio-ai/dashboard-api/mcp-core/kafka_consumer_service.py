import os
import json
import logging
import threading
import time
import re
import psycopg2
from kafka import KafkaConsumer
from dotenv import load_dotenv

# Configurar logging con rotación para evitar que los logs crezcan indefinidamente
from logging.handlers import RotatingFileHandler
import os

# Configurar logging básico
log_dir = os.path.dirname(os.path.abspath(__file__))
log_file = os.path.join(log_dir, '..', 'consumer.log')
log_file = os.path.abspath(log_file)

# Crear handler con rotación (máximo 10MB por archivo, mantener 3 archivos de backup)
handler = RotatingFileHandler(
    log_file,
    maxBytes=10*1024*1024,  # 10MB
    backupCount=3,
    encoding='utf-8'
)
handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

# Reducir nivel de logging de Kafka para evitar warnings excesivos de rebalancing
logging.getLogger('kafka').setLevel(logging.ERROR)  # Solo errores, no warnings
logging.getLogger('kafka.coordinator').setLevel(logging.ERROR)  # No warnings de heartbeat
logging.getLogger('kafka.coordinator.heartbeat').setLevel(logging.ERROR)

# Configurar logger principal
logger = logging.getLogger("KafkaConsumerService")
logger.setLevel(logging.INFO)
logger.addHandler(handler)

# También configurar logging básico para otros módulos (sin duplicar handlers)
# Solo agregar handler si no hay otros handlers configurados
root_logger = logging.getLogger()
if not root_logger.handlers:
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)
load_dotenv()

def get_db_connection():
    return psycopg2.connect(
        host=os.getenv('POSTGRES_HOST', 'localhost'),
        port=os.getenv('POSTGRES_PORT', '5432'),
        database=os.getenv('POSTGRES_DB', 'soar_db'),
        user=os.getenv('POSTGRES_USER', 'soar_user'),
        password=os.getenv('POSTGRES_PASSWORD', 'YOUR_POSTGRES_PASSWORD')
    )

def parse_fw_log(raw_text):
    data = {'source_ip': None, 'dest_ip': None, 'source_port': None, 'dest_port': None, 'action': None}
    if 'Deny' in raw_text or 'deny' in raw_text: data['action'] = 'deny'
    elif any(x in raw_text for x in ['Permit', 'permit', 'Accept', 'accept']): data['action'] = 'permit'
    ips = re.findall(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', raw_text)
    if len(ips) >= 1: data['source_ip'] = ips[0]
    if len(ips) >= 2: data['dest_ip'] = ips[1]
    ports = re.findall(r'[/: ](\d{2,5})\b', raw_text)
    if len(ports) >= 1: data['source_port'] = ports[0]
    if len(ports) >= 2: data['dest_port'] = ports[1]
    return data

def fw_consumer():
    logger.info("Iniciando consumidor de FW Postgres (1TB Partition)...")
    brokers = os.getenv('KAFKA_FW_BROKERS', '').split(',')
    topics = ['fw-Perimetrales-logs', 'fw-Internos-logs', 'fortinet']
    group_id = 'CG-CYBORG-SENTINEL-SOC-V5-POSTGRES'
    while True:
        try:
            consumer = KafkaConsumer(*topics, bootstrap_servers=brokers, group_id=group_id, auto_offset_reset='latest',
                                   session_timeout_ms=60000, max_poll_records=100,
                                   value_deserializer=lambda x: x.decode('utf-8', 'ignore') if x else "")
            conn = get_db_connection()
            cursor = conn.cursor()
            for message in consumer:
                raw_log = message.value
                if not raw_log: continue
                p = parse_fw_log(raw_log)
                cursor.execute("INSERT INTO fw_logs (topic, source_ip, dest_ip, source_port, dest_port, action, raw_log) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                             (message.topic, p['source_ip'], p['dest_ip'], p['source_port'], p['dest_port'], p['action'], json.dumps({'raw': raw_log})))
                conn.commit()
        except Exception as e:
            logger.error(f"Error en consumidor FW: {e}")
            time.sleep(10)

def waf_consumer():
    logger.info("Iniciando consumidor de WAF Postgres (1TB Partition)...")
    brokers = os.getenv('KAFKA_WAF_BROKERS', '').split(',')
    group_id = 'CG-CYBORG-SENTINEL-SOC-WAF-V5-POSTGRES'
    while True:
        try:
            consumer = KafkaConsumer('WAF', bootstrap_servers=brokers, group_id=group_id, auto_offset_reset='latest', session_timeout_ms=60000, value_deserializer=lambda x: x.decode('utf-8', 'ignore') if x else "")
            conn = get_db_connection()
            cursor = conn.cursor()
            for message in consumer:
                raw_log = message.value
                if not raw_log: continue
                # Optimización: Solo guardamos alertas o bloqueos para ahorrar espacio
                is_urgent = any(x in raw_log for x in ['blocked', 'alerted', 'Attack signature'])
                if not is_urgent: continue 

                parts = [p.strip('"') for p in re.findall(r'"([^"]*)"', raw_log)]
                if len(parts) >= 10:
                    cursor.execute("INSERT INTO waf_logs (client_ip, host, url, method, status_code, signature_id, action, raw_log) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                                 (parts[0], parts[2], parts[9], parts[6], int(parts[5]) if parts[5].isdigit() else None, parts[11] if len(parts) > 11 else None, parts[7], json.dumps({'raw': raw_log})))
                    conn.commit()
        except Exception as e:
            logger.error(f"Error en consumidor WAF: {e}")
            time.sleep(10)

def cleanup_worker():
    while True:
        try:
            days = int(os.getenv('DB_CLEANUP_DAYS', '7'))
            logger.info(f"🧹 [CYBORG-SENTINEL] Limpieza Postgres (Retención: {days} días)...")
            conn = get_db_connection()
            conn.autocommit = True
            cursor = conn.cursor()
            cursor.execute(f"DELETE FROM fw_logs WHERE event_time < NOW() - INTERVAL '{days} days'")
            cursor.execute(f"DELETE FROM waf_logs WHERE event_time < NOW() - INTERVAL '{days} days'")
            logger.info(f"✅ Limpieza completada. Ejecutando VACUUM...")
            cursor.execute("VACUUM")
            cursor.close(); conn.close()
        except Exception as e:
            logger.error(f"Error en cleanup_worker: {e}")
        time.sleep(3600)

if __name__ == "__main__":
    threading.Thread(target=fw_consumer, daemon=True).start()
    threading.Thread(target=waf_consumer, daemon=True).start()
    threading.Thread(target=cleanup_worker, daemon=True).start()
    while True: time.sleep(1)
