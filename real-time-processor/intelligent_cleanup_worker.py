"""
Worker que ejecuta limpieza inteligente periódicamente.
Se ejecuta cada 5 minutos y:
- Auto-desbloquea IPs con comportamiento mejorado
- Aprende de falsos positivos
- Limpia estados antiguos
"""
import logging
import time
import threading
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class IntelligentCleanupWorker:
    """Worker de limpieza inteligente que se ejecuta periódicamente"""
    
    def __init__(self, intelligent_blocking, postgres_conn=None, cleanup_interval: int = 300):
        """
        Args:
            intelligent_blocking: Instancia de IntelligentBlockingSystem
            postgres_conn: Conexión a PostgreSQL (opcional)
            cleanup_interval: Intervalo de limpieza en segundos (default: 5 minutos)
        """
        self.intelligent_blocking = intelligent_blocking
        self.postgres_conn = postgres_conn
        self.cleanup_interval = cleanup_interval
        self.running = False
        self.cleanup_thread = None
        
        logger.info(f"✅ IntelligentCleanupWorker inicializado (intervalo: {cleanup_interval}s)")
    
    def start(self):
        """Inicia el worker de limpieza en background"""
        if self.running:
            logger.warning("⚠️ Cleanup worker ya está corriendo")
            return
        
        self.running = True
        self.cleanup_thread = threading.Thread(
            target=self._cleanup_cycle,
            daemon=True,
            name="IntelligentCleanupWorker"
        )
        self.cleanup_thread.start()
        logger.info("✅ IntelligentCleanupWorker iniciado")
    
    def stop(self):
        """Detiene el worker de limpieza"""
        self.running = False
        if self.cleanup_thread:
            self.cleanup_thread.join(timeout=10)
        logger.info("🛑 IntelligentCleanupWorker detenido")
    
    def _cleanup_cycle(self):
        """Ciclo de limpieza que se ejecuta periódicamente"""
        logger.info("🔄 Iniciando ciclo de limpieza inteligente...")
        
        while self.running:
            try:
                # 0. CRÍTICO: Desactivar IPs expiradas por tiempo en PostgreSQL
                expired_unblocked = 0
                if self.postgres_conn:
                    try:
                        cursor = self.postgres_conn.cursor()
                        # Desactivar IPs que expiraron pero siguen activas
                        cursor.execute("""
                            UPDATE blocked_ips 
                            SET active = FALSE,
                                unblocked_at = NOW(),
                                unblock_reason = 'Auto-desbloqueo: Bloqueo expirado por tiempo'
                            WHERE active = TRUE
                            AND expires_at < NOW()
                            AND (expires_at IS NOT NULL)
                        """)
                        expired_unblocked = cursor.rowcount
                        self.postgres_conn.commit()
                        cursor.close()
                        if expired_unblocked > 0:
                            logger.info(f"🧹 Auto-limpieza: {expired_unblocked} IPs expiradas desactivadas automáticamente")
                    except Exception as e:
                        logger.error(f"Error desactivando IPs expiradas: {e}", exc_info=True)
                        if self.postgres_conn:
                            self.postgres_conn.rollback()
                
                # 1. Verificar IPs bloqueadas para auto-desbloqueo (basado en comportamiento)
                blocked_ips = [
                    ip for ip, state in self.intelligent_blocking.ip_states.items() 
                    if state['current_stage'].value in ['soft_block', 'hard_block']
                ]
                
                unblocked_count = 0
                for ip in blocked_ips:
                    if self.intelligent_blocking.execute_auto_unblock(ip):
                        unblocked_count += 1
                        # Persistir desbloqueo en BD si está disponible
                        if self.postgres_conn:
                            self._unblock_ip_in_db(ip, reason="Auto-limpieza inteligente: Comportamiento mejorado")
                
                if unblocked_count > 0:
                    logger.info(f"🧹 Auto-limpieza: {unblocked_count} IPs desbloqueadas por comportamiento mejorado")
                
                # 2. Limpiar estados antiguos (más de 24h sin actividad)
                current_time = time.time()
                stale_ips = [
                    ip for ip, state in list(self.intelligent_blocking.ip_states.items())
                    if current_time - state['last_activity'] > 86400  # 24h
                ]
                
                for ip in stale_ips:
                    with self.intelligent_blocking.lock:
                        if ip in self.intelligent_blocking.ip_states:
                            del self.intelligent_blocking.ip_states[ip]
                        if ip in self.intelligent_blocking.reputation_cache:
                            # Mantener reputación pero marcar como antiguo
                            self.intelligent_blocking.reputation_cache[ip]['last_updated'] = current_time - 86400
                
                if stale_ips:
                    logger.info(f"🧹 Limpieza: {len(stale_ips)} estados antiguos removidos")
                
                # 3. Limpiar reputación cache antiguo (más de 7 días sin actualizar)
                old_reputation_ips = [
                    ip for ip, rep in list(self.intelligent_blocking.reputation_cache.items())
                    if current_time - rep['last_updated'] > 604800  # 7 días
                ]
                
                for ip in old_reputation_ips:
                    if ip in self.intelligent_blocking.reputation_cache:
                        del self.intelligent_blocking.reputation_cache[ip]
                
                if old_reputation_ips:
                    logger.debug(f"🧹 Limpieza: {len(old_reputation_ips)} reputaciones antiguas removidas")
                
            except Exception as e:
                logger.error(f"Error en cleanup cycle: {e}", exc_info=True)
            
            # Esperar antes de siguiente ciclo
            for _ in range(self.cleanup_interval):
                if not self.running:
                    break
                time.sleep(1)
    
    def _unblock_ip_in_db(self, ip: str, reason: str):
        """Persiste desbloqueo en PostgreSQL"""
        if not self.postgres_conn:
            return
        
        try:
            cursor = self.postgres_conn.cursor()
            cursor.execute("""
                UPDATE blocked_ips 
                SET active = FALSE,
                    unblocked_at = NOW(),
                    unblock_reason = %s
                WHERE ip = %s::inet
                AND active = TRUE
            """, (reason, ip))
            self.postgres_conn.commit()
            cursor.close()
            logger.debug(f"✅ IP {ip} marcada como desbloqueada en BD")
        except Exception as e:
            logger.error(f"Error desbloqueando IP {ip} en BD: {e}", exc_info=True)
            if self.postgres_conn:
                self.postgres_conn.rollback()
