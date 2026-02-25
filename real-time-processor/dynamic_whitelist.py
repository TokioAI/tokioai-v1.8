"""
Dynamic Whitelist/Blacklist - Aprende IPs legítimas y maneja falsos positivos
"""
import logging
import time
from typing import Dict, Any, List, Set, Optional
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class DynamicWhitelist:
    """Gestiona whitelist y blacklist dinámicas"""
    
    def __init__(self, learning_period: int = 3600):
        """
        Args:
            learning_period: Período de aprendizaje en segundos (default: 1 hora)
        """
        from improvements_config import ImprovementsConfig
        
        self.learning_period = learning_period
        self.min_good_requests = ImprovementsConfig.MIN_GOOD_REQUESTS_FOR_WHITELIST
        
        # Whitelist: IPs que han sido legítimas consistentemente
        self.whitelist = set()
        self.whitelist_candidates = {}  # ip -> {'first_seen': timestamp, 'good_requests': count}
        
        # Blacklist: IPs bloqueadas permanentemente
        self.blacklist = set()
        
        # Auto-unblock: IPs bloqueadas temporalmente
        self.blocked_ips = {}  # ip -> {'blocked_at': timestamp, 'expires_at': timestamp, 'reason': str}
        
        logger.info(f"✅ DynamicWhitelist inicializado (learning_period: {learning_period}s)")
    
    def should_whitelist_ip(self, ip: str) -> bool:
        """Verifica si una IP está en whitelist"""
        return ip in self.whitelist
    
    def should_block_ip(self, ip: str) -> bool:
        """Verifica si una IP debe ser bloqueada (blacklist)"""
        return ip in self.blacklist
    
    def learn_from_good_behavior(self, ip: str, log: Dict[str, Any]):
        """
        Aprende de comportamiento legítimo.
        Si una IP tiene comportamiento normal durante learning_period, se agrega a whitelist.
        """
        current_time = time.time()
        
        # Solo aprender si no está en whitelist ya
        if ip in self.whitelist:
            return
        
        # Verificar si es comportamiento legítimo
        if self._is_legitimate_behavior(log):
            if ip not in self.whitelist_candidates:
                self.whitelist_candidates[ip] = {
                    'first_seen': current_time,
                    'good_requests': 0,
                    'last_seen': current_time
                }
            
            candidate = self.whitelist_candidates[ip]
            candidate['good_requests'] += 1
            candidate['last_seen'] = current_time
            
            # Si ha tenido comportamiento legítimo durante learning_period
            if (current_time - candidate['first_seen'] >= self.learning_period and
                candidate['good_requests'] >= self.min_good_requests):
                
                # Agregar a whitelist
                self.whitelist.add(ip)
                del self.whitelist_candidates[ip]
                logger.info(f"✅ IP {ip} agregada a whitelist (aprendizaje automático)")
    
    def _is_legitimate_behavior(self, log: Dict[str, Any]) -> bool:
        """Determina si un log representa comportamiento legítimo"""
        # No tiene threat_type o es NONE
        threat_type = log.get('threat_type') or log.get('classification', {}).get('threat_type')
        if threat_type and threat_type != 'NONE':
            return False
        
        # Status code es exitoso (200, 301, etc., no 403)
        status = log.get('status', 200)
        if status == 403:  # Bloqueado por WAF
            return False
        
        # No es patrón de escaneo
        uri = log.get('uri', '').lower()
        scan_patterns = ['wp-admin', 'wp-content', '/.env', '/actuator', 'admin', 'config']
        if any(pattern in uri for pattern in scan_patterns):
            return False
        
        return True
    
    def auto_unblock_after_period(self, ip: str, block_duration: int = 3600):
        """
        Programa auto-desbloqueo después de un período.
        
        Args:
            ip: IP bloqueada
            block_duration: Duración del bloqueo en segundos (default: 1 hora)
        """
        current_time = time.time()
        self.blocked_ips[ip] = {
            'blocked_at': current_time,
            'expires_at': current_time + block_duration,
            'reason': 'auto_temporary_block'
        }
    
    def get_expired_blocks(self) -> List[str]:
        """Retorna IPs cuyo bloqueo temporal ha expirado"""
        current_time = time.time()
        expired = []
        
        for ip, block_info in list(self.blocked_ips.items()):
            if current_time >= block_info['expires_at']:
                expired.append(ip)
                del self.blocked_ips[ip]
        
        return expired
    
    def manual_whitelist(self, ip: str, reason: str = "manual"):
        """Agrega IP manualmente a whitelist"""
        self.whitelist.add(ip)
        if ip in self.blocked_ips:
            del self.blocked_ips[ip]
        logger.info(f"✅ IP {ip} agregada manualmente a whitelist: {reason}")
    
    def manual_blacklist(self, ip: str, reason: str = "manual"):
        """Agrega IP manualmente a blacklist permanente"""
        self.blacklist.add(ip)
        logger.info(f"⚠️ IP {ip} agregada a blacklist permanente: {reason}")
