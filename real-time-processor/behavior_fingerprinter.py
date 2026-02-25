"""
Behavior Fingerprinter - Genera firmas de comportamiento más allá de IP
Extiende el sistema existente sin romper funcionalidad
"""
import hashlib
import logging
from typing import Dict, Any, List, Optional
from collections import defaultdict

logger = logging.getLogger(__name__)


class BehaviorFingerprinter:
    """Genera firmas de comportamiento basadas en múltiples factores"""
    
    def __init__(self):
        self.signature_cache = {}
        logger.info("✅ BehaviorFingerprinter inicializado")
    
    def generate_fingerprint(self, log: Dict[str, Any]) -> str:
        """
        Genera una firma única de comportamiento basada en:
        - User Agent (ya existe)
        - Headers HTTP
        - Patrones de navegación
        - Cookies
        """
        user_agent = log.get('user_agent', '')
        headers = log.get('headers', {}) or {}
        
        # Extraer componentes clave
        accept_language = headers.get('Accept-Language', '')[:20]
        accept_encoding = headers.get('Accept-Encoding', '')[:20]
        accept = headers.get('Accept', '')[:50]
        
        # Crear firma compuesta
        signature_parts = [
            user_agent[:100],  # Limitar tamaño
            accept_language,
            accept_encoding,
            accept
        ]
        
        signature_string = '|'.join(signature_parts)
        fingerprint = hashlib.sha256(signature_string.encode()).hexdigest()[:16]
        
        return fingerprint
    
    def group_by_fingerprint(self, logs: List[Dict[str, Any]]) -> Dict[str, List[Dict]]:
        """Agrupa logs por fingerprint de comportamiento"""
        groups = defaultdict(list)
        for log in logs:
            fingerprint = self.generate_fingerprint(log)
            groups[fingerprint].append(log)
        return dict(groups)
    
    def detect_behavior_anomaly(self, log: Dict[str, Any], 
                                recent_fingerprints: List[str]) -> bool:
        """
        Detecta si el fingerprint es anormal comparado con fingerprints recientes.
        Útil para detectar cambios de comportamiento sospechosos.
        """
        current_fp = self.generate_fingerprint(log)
        
        if not recent_fingerprints:
            return False
        
        # Si el fingerprint actual es muy diferente a los recientes, es anormal
        # Por ahora, comparación simple (puede mejorarse)
        if current_fp not in recent_fingerprints[-10:]:  # Últimos 10 diferentes
            return True
        
        return False
