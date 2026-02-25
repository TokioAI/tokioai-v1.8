"""
Configuración centralizada para las mejoras implementadas
Permite activar/desactivar features sin romper código
"""
import os
from typing import Dict, Any

class ImprovementsConfig:
    """Configuración de mejoras incrementales"""
    
    # Feature flags (activar/desactivar sin código)
    ENABLE_BEHAVIOR_FINGERPRINTING = os.getenv('ENABLE_BEHAVIOR_FINGERPRINTING', 'false').lower() == 'true'
    ENABLE_ENDPOINT_RATE_LIMITING = os.getenv('ENABLE_ENDPOINT_RATE_LIMITING', 'false').lower() == 'true'
    ENABLE_DISTRIBUTED_CORRELATION = os.getenv('ENABLE_DISTRIBUTED_CORRELATION', 'false').lower() == 'true'
    ENABLE_DYNAMIC_WHITELIST = os.getenv('ENABLE_DYNAMIC_WHITELIST', 'false').lower() == 'true'
    ENABLE_INTELLIGENT_BLOCKING = os.getenv('INTELLIGENT_BLOCKING_ENABLED', 'false').lower() == 'true'
    ENABLE_INTELLIGENT_BLOCKING_SHADOW = os.getenv('INTELLIGENT_BLOCKING_SHADOW_MODE', 'true').lower() == 'true'
    ENABLE_RATE_LIMITING = os.getenv('RATE_LIMITING_ENABLED', 'false').lower() == 'true'
    ENABLE_EARLY_PREDICTION = os.getenv('EARLY_PREDICTION_ENABLED', 'false').lower() == 'true'
    ENABLE_AUTO_CLEANUP = os.getenv('AUTO_CLEANUP_ENABLED', 'false').lower() == 'true'
    
    # NUEVAS MEJORAS: Detección Avanzada (Fase 1)
    # NOTA: Threat Intelligence DESHABILITADO por defecto (usuario NO quiere APIs externas)
    ENABLE_DEOBFUSCATION = os.getenv('ENABLE_DEOBFUSCATION', 'true').lower() == 'true'  # Habilitado por defecto
    ENABLE_THREAT_INTELLIGENCE = os.getenv('ENABLE_THREAT_INTELLIGENCE', 'false').lower() == 'true'  # DESHABILITADO (APIs externas)
    ENABLE_ANOMALY_DETECTION = os.getenv('ENABLE_ANOMALY_DETECTION', 'true').lower() == 'true'  # Habilitado por defecto
    
    # Configuración de Threat Intelligence
    THREAT_INTEL_CACHE_TTL = int(os.getenv('THREAT_INTEL_CACHE_TTL', '3600'))  # 1 hora
    THREAT_INTEL_BLOCK_THRESHOLD = int(os.getenv('THREAT_INTEL_BLOCK_THRESHOLD', '80'))  # Score >= 80
    
    # Configuración de Anomaly Detection
    ANOMALY_CONTAMINATION = float(os.getenv('ANOMALY_CONTAMINATION', '0.01'))  # 1%
    ANOMALY_TRAINING_INTERVAL = int(os.getenv('ANOMALY_TRAINING_INTERVAL', '3600'))  # 1 hora
    
    # Configuración de Behavior Fingerprinting
    BEHAVIOR_FINGERPRINT_WINDOW = int(os.getenv('BEHAVIOR_FINGERPRINT_WINDOW', '300'))  # 5 minutos
    
    # Configuración de Rate Limiting
    DEFAULT_RATE_LIMIT = int(os.getenv('DEFAULT_RATE_LIMIT', '100'))  # requests/min
    RATE_LIMIT_WINDOW = int(os.getenv('RATE_LIMIT_WINDOW', '60'))  # segundos
    
    # Configuración de Correlación Distribuida
    CORRELATION_WINDOW = int(os.getenv('CORRELATION_WINDOW', '60'))  # segundos
    MIN_IPS_FOR_DDOS = int(os.getenv('MIN_IPS_FOR_DDOS', '5'))  # IPs mínimas
    
    # Configuración de Whitelist
    WHITELIST_LEARNING_PERIOD = int(os.getenv('WHITELIST_LEARNING_PERIOD', '3600'))  # 1 hora
    MIN_GOOD_REQUESTS_FOR_WHITELIST = int(os.getenv('MIN_GOOD_REQUESTS_FOR_WHITELIST', '50'))
    
    # Configuración de Bloqueo Inteligente
    INTELLIGENT_BLOCKING_BLOCK_THRESHOLD = float(os.getenv('INTELLIGENT_BLOCKING_BLOCK_THRESHOLD', '0.85'))
    INTELLIGENT_BLOCKING_ALLOW_THRESHOLD = float(os.getenv('INTELLIGENT_BLOCKING_ALLOW_THRESHOLD', '0.3'))
    
    # Configuración de Sincronización Optimizada
    MAX_IPS_TOTAL = int(os.getenv('MAX_IPS_TOTAL', '5000'))  # Límite máximo de IPs
    EMERGENCY_MODE_THRESHOLD = int(os.getenv('EMERGENCY_MODE_THRESHOLD', '3000'))  # Umbral de emergencia
    CLEANUP_AGE_HOURS = int(os.getenv('CLEANUP_AGE_HOURS', '168'))  # 7 días
    NGINX_RELOAD_MIN_INTERVAL = int(os.getenv('NGINX_RELOAD_MIN_INTERVAL', '10'))  # 10 segundos
    
    @classmethod
    def get_config_dict(cls) -> Dict[str, Any]:
        """Retorna configuración como dict para logging"""
        return {
            'behavior_fingerprinting': cls.ENABLE_BEHAVIOR_FINGERPRINTING,
            'endpoint_rate_limiting': cls.ENABLE_ENDPOINT_RATE_LIMITING,
            'distributed_correlation': cls.ENABLE_DISTRIBUTED_CORRELATION,
            'dynamic_whitelist': cls.ENABLE_DYNAMIC_WHITELIST,
            'intelligent_blocking': cls.ENABLE_INTELLIGENT_BLOCKING,
            'intelligent_blocking_shadow': cls.ENABLE_INTELLIGENT_BLOCKING_SHADOW,
            'rate_limiting': cls.ENABLE_RATE_LIMITING,
            'early_prediction': cls.ENABLE_EARLY_PREDICTION,
            'auto_cleanup': cls.ENABLE_AUTO_CLEANUP,
            'deobfuscation': cls.ENABLE_DEOBFUSCATION,
            'threat_intelligence': cls.ENABLE_THREAT_INTELLIGENCE,
            'anomaly_detection': cls.ENABLE_ANOMALY_DETECTION
        }
    
    @classmethod
    def log_config(cls, logger):
        """Loggea la configuración actual"""
        config = cls.get_config_dict()
        enabled = [k for k, v in config.items() if v]
        disabled = [k for k, v in config.items() if not v]
        
        if enabled:
            logger.info(f"✅ Mejoras ACTIVADAS: {', '.join(enabled)}")
        if disabled:
            logger.debug(f"⚪ Mejoras DESACTIVADAS: {', '.join(disabled)}")
