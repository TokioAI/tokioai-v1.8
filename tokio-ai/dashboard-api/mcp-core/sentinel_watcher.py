import os
import time
import psycopg2
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO, format='%(asctime)s - [SENTINEL-WATCHER] - %(message)s')
logger = logging.getLogger("SentinelWatcher")

TARGET_IP = 'YOUR_IP_ADDRESS'

def get_db_connection():
    return psycopg2.connect(host=os.getenv('POSTGRES_HOST'), database=os.getenv('POSTGRES_DB'), user=os.getenv('POSTGRES_USER'), password=os.getenv('POSTGRES_PASSWORD'))

def audit_server():
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 1. Buscar nuevos logs en FW para esta IP en los últimos 5 minutos
    cur.execute("""
        SELECT count(*) FROM fw_logs 
        WHERE (source_ip = %s OR dest_ip = %s) AND event_time > NOW() - INTERVAL '5 minutes'
    """, (TARGET_IP, TARGET_IP))
    recent_fw = cur.fetchone()[0]
    
    # 2. Buscar ataques en WAF
    cur.execute("""
        SELECT count(*) FROM waf_logs 
        WHERE client_ip = %s AND action = 'blocked' AND event_time > NOW() - INTERVAL '5 minutes'
    """, (TARGET_IP,))
    recent_waf = cur.fetchone()[0]
    
    status = 'SAFE'
    details = f'Actividad FW (5m): {recent_fw}, Bloqueos WAF: {recent_waf}'
    
    if recent_waf > 0 or recent_fw > 100:
        status = 'ALERT'
        logger.warning(f"⚠️ Alerta detectada para {TARGET_IP}! {details}")
    
    # 3. Persistir estado del guardia
    cur.execute("""
        INSERT INTO silent_watch_status (ip, status, alert_count, details)
        VALUES (%s, %s, %s, %s)
    """, (TARGET_IP, status, recent_waf, details))
    
    conn.commit()
    cur.close(); conn.close()
    logger.info(f"Vigilancia completada para {TARGET_IP}: {status}")

if __name__ == "__main__":
    logger.info(f"Iniciando monitoreo silencioso sobre {TARGET_IP}...")
    while True:
        try:
            audit_server()
        except Exception as e:
            logger.error(f"Error en el guardia: {e}")
        time.sleep(300) # Auditar cada 5 minutos
