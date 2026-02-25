"""
Worker que entrena modelos de anomaly detection en background
con tráfico legítimo conocido.
"""
import logging
import time
import threading
from typing import List, Dict, Any
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class BaselineTrainer:
    """
    Entrena modelos de anomaly detection periódicamente con tráfico legítimo.
    """
    
    def __init__(self, zero_day_detector, postgres_conn=None):
        self.zero_day_detector = zero_day_detector
        self.postgres_conn = postgres_conn
        self.running = False
        self.thread = None
        self.training_interval = 3600  # 1 hora
    
    def start(self):
        """Inicia el worker de entrenamiento"""
        if self.running:
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._training_loop, daemon=True)
        self.thread.start()
        logger.info("✅ Baseline Trainer iniciado")
    
    def stop(self):
        """Detiene el worker"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
    
    def _training_loop(self):
        """Loop de entrenamiento"""
        while self.running:
            try:
                # Obtener logs legítimos de los últimos 7 días
                legitimate_logs = self._get_legitimate_traffic()
                
                if len(legitimate_logs) >= 100:
                    logger.info(f"🔄 Entrenando anomaly detection con {len(legitimate_logs)} logs legítimos")
                    self.zero_day_detector.train_on_legitimate_traffic(legitimate_logs)
                else:
                    logger.warning(f"No hay suficientes logs legítimos para entrenar ({len(legitimate_logs)})")
                
                # Esperar antes de siguiente entrenamiento
                time.sleep(self.training_interval)
            
            except Exception as e:
                logger.error(f"Error en training loop: {e}", exc_info=True)
                time.sleep(60)  # Esperar 1 minuto antes de reintentar
    
    def _get_legitimate_traffic(self) -> List[Dict[str, Any]]:
        """
        Obtiene tráfico legítimo conocido desde PostgreSQL.
        Logs que fueron etiquetados como ALLOW o que no tienen threat_type.
        """
        if not self.postgres_conn:
            return []
        
        try:
            cursor = self.postgres_conn.cursor()
            
            # Obtener logs legítimos de los últimos 7 días
            cursor.execute("""
                SELECT 
                    ip, uri, query_string, user_agent, method, status,
                    timestamp, created_at
                FROM waf_logs
                WHERE created_at > NOW() - INTERVAL '7 days'
                AND (threat_type IS NULL OR threat_type = 'NONE')
                AND status IN (200, 301, 302, 304)
                AND blocked = FALSE
                ORDER BY created_at DESC
                LIMIT 10000
            """)
            
            rows = cursor.fetchall()
            cursor.close()
            
            # Convertir a dicts
            logs = []
            for row in rows:
                logs.append({
                    'ip': row[0],
                    'uri': row[1],
                    'query_string': row[2],
                    'user_agent': row[3],
                    'method': row[4],
                    'status': row[5],
                    'timestamp': row[6].isoformat() if row[6] else None,
                    'created_at': row[7].isoformat() if row[7] else None
                })
            
            return logs
        
        except Exception as e:
            logger.error(f"Error obteniendo tráfico legítimo: {e}", exc_info=True)
            return []
