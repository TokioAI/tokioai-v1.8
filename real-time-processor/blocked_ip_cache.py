"""
BlockedIPCache - Cache en memoria de IPs bloqueadas para verificación O(1)
Actualización periódica desde PostgreSQL (sin costo adicional de queries por log).
"""
import logging
import time
import threading
from typing import Optional, Set, Dict
from datetime import datetime

logger = logging.getLogger(__name__)


class BlockedIPCache:
    """
    Cache en memoria de IPs bloqueadas para verificación O(1) sin queries a BD.
    Actualización periódica desde PostgreSQL (una query cada 30s, no por log).
    """
    
    def __init__(self, postgres_conn, update_interval: int = 30):
        """
        Inicializa el cache de IPs bloqueadas.
        
        Args:
            postgres_conn: Conexión a PostgreSQL
            update_interval: Intervalo de actualización en segundos (default: 30s)
        """
        self.postgres_conn = postgres_conn
        self.update_interval = update_interval
        self.blocked_ips: Set[str] = set()  # Set para búsqueda O(1)
        self.blocked_ips_expiry: Dict[str, datetime] = {}  # {ip: expires_at} para limpieza
        self.last_update = 0
        self.lock = threading.Lock()
        self.update_thread = None
        self.running = True
        
        # Inicializar cache inmediatamente
        if self.postgres_conn:
            self._update_cache()
            logger.info(f"✅ BlockedIPCache inicializado (update_interval: {update_interval}s)")
        else:
            logger.warning("⚠️ BlockedIPCache inicializado sin conexión PostgreSQL")
    
    def is_blocked(self, ip: str) -> bool:
        """
        Verifica si IP está bloqueada - O(1) lookup.
        
        Args:
            ip: Dirección IP a verificar
            
        Returns:
            True si la IP está bloqueada y no expirada, False en caso contrario
        """
        if not ip or ip == 'unknown':
            return False
        
        current_time = time.time()
        
        # Auto-actualizar si es necesario (sin bloqueo si no es crítico)
        if current_time - self.last_update > self.update_interval:
            # Actualizar en background (no bloquear)
            if not self.update_thread or not self.update_thread.is_alive():
                self.update_thread = threading.Thread(
                    target=self._update_cache,
                    daemon=True,
                    name="BlockedIPCacheUpdate"
                )
                self.update_thread.start()
        
        with self.lock:
            # Verificar si está bloqueada y no expirada
            if ip in self.blocked_ips:
                expires_at = self.blocked_ips_expiry.get(ip)
                if expires_at and expires_at < datetime.now():
                    # Expirado, remover
                    self.blocked_ips.discard(ip)
                    self.blocked_ips_expiry.pop(ip, None)
                    return False
                return True
            return False
    
    def _update_cache(self):
        """
        Actualiza cache desde PostgreSQL (una query cada 30s, no por log).
        """
        if not self.postgres_conn:
            return
        
        try:
            cursor = self.postgres_conn.cursor()
            cursor.execute("""
                SELECT ip, expires_at
                FROM blocked_ips
                WHERE active = TRUE
                AND (expires_at IS NULL OR expires_at > NOW())
            """)
            rows = cursor.fetchall()
            cursor.close()
            
            new_blocked = set()
            new_expiry = {}
            for row in rows:
                ip = str(row[0])  # Convertir INET a string
                expires_at = row[1]
                new_blocked.add(ip)
                if expires_at:
                    new_expiry[ip] = expires_at
            
            with self.lock:
                old_count = len(self.blocked_ips)
                self.blocked_ips = new_blocked
                self.blocked_ips_expiry = new_expiry
                self.last_update = time.time()
            
            logger.debug(f"✅ Cache actualizado: {len(new_blocked)} IPs bloqueadas (antes: {old_count})")
        except Exception as e:
            logger.error(f"Error actualizando cache de IPs bloqueadas: {e}", exc_info=True)
    
    def add_blocked_ip(self, ip: str, expires_at: Optional[datetime] = None):
        """
        Agrega IP al cache inmediatamente (sin esperar actualización).
        Útil cuando se bloquea una IP y queremos que el cache se actualice de inmediato.
        
        Args:
            ip: Dirección IP a agregar
            expires_at: Fecha de expiración del bloqueo (opcional)
        """
        if not ip or ip == 'unknown':
            return
        
        with self.lock:
            self.blocked_ips.add(ip)
            if expires_at:
                self.blocked_ips_expiry[ip] = expires_at
            logger.debug(f"✅ IP {ip} agregada al cache (expires: {expires_at})")
    
    def remove_blocked_ip(self, ip: str):
        """
        Remueve IP del cache.
        Útil cuando se desbloquea una IP manualmente.
        
        Args:
            ip: Dirección IP a remover
        """
        with self.lock:
            self.blocked_ips.discard(ip)
            self.blocked_ips_expiry.pop(ip, None)
            logger.debug(f"✅ IP {ip} removida del cache")
    
    def get_stats(self) -> Dict[str, any]:
        """
        Obtiene estadísticas del cache.
        
        Returns:
            Dict con estadísticas (count, last_update, etc.)
        """
        with self.lock:
            return {
                'blocked_ips_count': len(self.blocked_ips),
                'last_update': self.last_update,
                'update_interval': self.update_interval,
                'expired_count': len([ip for ip, exp in self.blocked_ips_expiry.items() if exp < datetime.now()])
            }


