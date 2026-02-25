"""
Rate Limit Manager - Gestiona rate limiting dinámico por IP
Sincroniza con Nginx y ModSecurity
"""
import logging
import time
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from enum import Enum

logger = logging.getLogger(__name__)


class RateLimitLevel(Enum):
    """Niveles de rate limiting (progresivos)"""
    NONE = "none"              # Sin límite
    LENIENT = "lenient"        # 100 req/min (advertencia suave)
    MODERATE = "moderate"      # 30 req/min (prevención)
    STRICT = "strict"          # 10 req/min (ataque moderado)
    VERY_STRICT = "very_strict"  # 3 req/min (ataque agresivo)


class RateLimitManager:
    """
    Gestiona rate limiting inteligente por IP.
    Determina límites basado en risk_score y comportamiento.
    """
    
    def __init__(self, config: Optional[Dict] = None, postgres_conn=None):
        self.config = config or {}
        self.postgres_conn = postgres_conn
        
        # Configuración de límites por nivel
        self.rate_limit_config = {
            RateLimitLevel.NONE: {'requests': 999999, 'window': 60},  # Sin límite práctico
            RateLimitLevel.LENIENT: {'requests': 100, 'window': 60},   # 100 req/min
            RateLimitLevel.MODERATE: {'requests': 30, 'window': 60},   # 30 req/min
            RateLimitLevel.STRICT: {'requests': 10, 'window': 60},     # 10 req/min
            RateLimitLevel.VERY_STRICT: {'requests': 3, 'window': 60}  # 3 req/min
        }
        
        # Estado de IPs con rate limiting
        self.ip_rate_limits = {}  # {ip: {'level': RateLimitLevel, 'applied_at': timestamp, 'risk_score': float}}
        
        logger.info("✅ RateLimitManager inicializado")
    
    def determine_rate_limit_level(self, risk_score: float, ip: str) -> RateLimitLevel:
        """
        Determina nivel de rate limiting basado en risk_score.
        PROGRESIVO: Más riesgo = límite más estricto.
        """
        # Umbrales progresivos
        if risk_score >= 0.85:
            return RateLimitLevel.VERY_STRICT  # 3 req/min
        elif risk_score >= 0.70:
            return RateLimitLevel.STRICT       # 10 req/min
        elif risk_score >= 0.55:
            return RateLimitLevel.MODERATE     # 30 req/min
        elif risk_score >= 0.40:
            return RateLimitLevel.LENIENT      # 100 req/min
        else:
            return RateLimitLevel.NONE         # Sin límite
    
    def get_rate_limit_config(self, level: RateLimitLevel) -> Dict[str, int]:
        """Obtiene configuración de límite para un nivel"""
        return self.rate_limit_config.get(level, self.rate_limit_config[RateLimitLevel.MODERATE])
    
    def apply_rate_limit(self, ip: str, risk_score: float, 
                        reason: str = "Sistema inteligente", duration_hours: int = 24) -> Dict[str, Any]:
        """
        Aplica rate limiting a una IP y guarda en PostgreSQL.
        
        Args:
            ip: IP a rate limitear
            risk_score: Score de riesgo (0.0-1.0)
            reason: Razón del rate limiting
            duration_hours: Duración en horas (default: 24h)
        
        Returns:
            {
                'ip': str,
                'level': RateLimitLevel,
                'requests_per_minute': int,
                'window_seconds': int,
                'reason': str,
                'risk_score': float
            }
        """
        level = self.determine_rate_limit_level(risk_score, ip)
        config = self.get_rate_limit_config(level)
        
        # Si es NONE, no aplicar rate limiting
        if level == RateLimitLevel.NONE:
            return {
                'ip': ip,
                'level': level,
                'requests_per_minute': config['requests'],
                'window_seconds': config['window'],
                'reason': reason,
                'risk_score': risk_score
            }
        
        # Actualizar estado en memoria
        self.ip_rate_limits[ip] = {
            'level': level,
            'applied_at': time.time(),
            'risk_score': risk_score,
            'reason': reason,
            'requests': config['requests'],
            'window': config['window']
        }
        
        # Guardar en PostgreSQL
        self.save_to_postgres(ip, level, config['requests'], config['window'], risk_score, reason, duration_hours)
        
        logger.info(f"⏱️ Rate limiting aplicado a IP {ip}: {level.value} "
                   f"({config['requests']} req/{config['window']}s) - Risk: {risk_score:.1%}")
        
        return {
            'ip': ip,
            'level': level,
            'requests_per_minute': config['requests'],
            'window_seconds': config['window'],
            'reason': reason,
            'risk_score': risk_score
        }
    
    def save_to_postgres(self, ip: str, level: RateLimitLevel, requests: int, 
                        window: int, risk_score: float, reason: str, duration_hours: int = 24):
        """Guarda rate limiting en PostgreSQL (tabla rate_limited_ips)"""
        if not self.postgres_conn:
            return
        
        try:
            expires_at = datetime.now() + timedelta(hours=duration_hours)
            cursor = self.postgres_conn.cursor()
            
            cursor.execute("""
                INSERT INTO rate_limited_ips (
                    ip, rate_limit_level, rate_limit_requests, rate_limit_window,
                    applied_at, expires_at, risk_score, reason, active
                )
                VALUES (%s, %s, %s, %s, NOW(), %s, %s, %s, TRUE)
                ON CONFLICT (ip) WHERE active = TRUE
                DO UPDATE SET
                    rate_limit_level = EXCLUDED.rate_limit_level,
                    rate_limit_requests = EXCLUDED.rate_limit_requests,
                    rate_limit_window = EXCLUDED.rate_limit_window,
                    applied_at = NOW(),
                    expires_at = EXCLUDED.expires_at,
                    risk_score = EXCLUDED.risk_score,
                    reason = EXCLUDED.reason,
                    updated_at = NOW()
            """, (ip, level.value, requests, window, expires_at, risk_score, reason[:500]))
            
            self.postgres_conn.commit()
            cursor.close()
            logger.debug(f"✅ Rate limiting guardado en PostgreSQL para IP {ip}")
        except Exception as e:
            logger.error(f"Error guardando rate limiting en PostgreSQL: {e}", exc_info=True)
            if self.postgres_conn:
                self.postgres_conn.rollback()
    
    def remove_rate_limit(self, ip: str) -> bool:
        """Remueve rate limiting de una IP (memoria y PostgreSQL)"""
        removed = False
        if ip in self.ip_rate_limits:
            del self.ip_rate_limits[ip]
            removed = True
        
        # Desactivar en PostgreSQL
        if self.postgres_conn:
            try:
                cursor = self.postgres_conn.cursor()
                cursor.execute("""
                    UPDATE rate_limited_ips
                    SET active = FALSE,
                        updated_at = NOW()
                    WHERE ip = %s::inet AND active = TRUE
                """, (ip,))
                self.postgres_conn.commit()
                cursor.close()
                if cursor.rowcount > 0:
                    logger.debug(f"✅ Rate limiting desactivado en PostgreSQL para IP {ip}")
            except Exception as e:
                logger.error(f"Error desactivando rate limiting en PostgreSQL: {e}", exc_info=True)
                if self.postgres_conn:
                    self.postgres_conn.rollback()
        
        if removed:
            logger.info(f"✅ Rate limiting removido de IP {ip}")
            return True
        return False
    
    def get_ips_needing_rate_limit(self) -> List[Dict[str, Any]]:
        """Obtiene todas las IPs que necesitan rate limiting"""
        return [
            {
                'ip': ip,
                'level': state['level'].value,
                'requests': state['requests'],
                'window': state['window'],
                'reason': state['reason']
            }
            for ip, state in self.ip_rate_limits.items()
        ]
