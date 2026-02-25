"""
Local Decision Layer - Calcula risk_score sin consultar LLM
Solo consulta LLM si decision = UNCERTAIN
"""
import logging
import math
from typing import Dict, Any, Optional, List
from collections import Counter

logger = logging.getLogger(__name__)


class LocalDecisionLayer:
    """
    Calcula risk_score basado en reglas heurísticas + modelo local ligero.
    No consulta LLM.
    """
    
    def __init__(self, ml_predictor, block_threshold: float = 0.8, allow_threshold: float = 0.3):
        """
        Inicializa el Local Decision Layer.
        
        Args:
            ml_predictor: Instancia de RealtimeMLPredictor para predicciones ML
            block_threshold: Risk score mínimo para bloquear (default: 0.8)
            allow_threshold: Risk score máximo para permitir (default: 0.3)
        """
        self.ml_predictor = ml_predictor
        self.block_threshold = block_threshold
        self.allow_threshold = allow_threshold
        logger.info(f"✅ LocalDecisionLayer inicializado (block={block_threshold}, allow={allow_threshold})")
    
    def calculate_risk_score(self, episode: Dict[str, Any], 
                            similar_episodes_score: Optional[float] = None) -> Dict[str, Any]:
        """
        Calcula risk_score del episodio usando:
        1. Reglas heurísticas
        2. Modelo ML local
        3. Búsqueda de episodios similares etiquetados (opcional)
        
        Args:
            episode: Episodio con features agregadas
            similar_episodes_score: Score basado en episodios similares etiquetados (0.0-1.0)
            
        Returns:
            Dict con risk_score, decision, confidence, y scores individuales
        """
        # 1. Risk score heurístico
        heuristic_score = self._heuristic_risk_score(episode)
        
        # 2. Risk score de ML (usar el primer log del episodio como muestra)
        ml_score = 0.0
        if episode.get('logs') and len(episode['logs']) > 0:
            sample_log = episode['logs'][0]
            try:
                ml_pred = self.ml_predictor.predict(sample_log)
                if ml_pred and isinstance(ml_pred, dict):
                    ml_score = ml_pred.get('threat_score', 0.0)
                elif isinstance(ml_pred, (int, float)):
                    ml_score = float(ml_pred)
            except Exception as e:
                logger.debug(f"Error en predicción ML: {e}")
                ml_score = 0.0
        
        # 3. Score de episodios similares (si está disponible)
        if similar_episodes_score is None:
            similar_score = 0.5  # Neutral si no hay similares
        else:
            similar_score = similar_episodes_score
        
        # Combinar scores (peso: 40% heurístico, 40% ML, 20% similar)
        risk_score = (0.4 * heuristic_score + 0.4 * ml_score + 0.2 * similar_score)
        risk_score = max(0.0, min(1.0, risk_score))  # Clamp entre 0 y 1
        
        # Decisión
        if risk_score >= self.block_threshold:
            decision = 'BLOCK'
        elif risk_score <= self.allow_threshold:
            decision = 'ALLOW'
        else:
            decision = 'UNCERTAIN'
        
        # Confidence: más lejos de 0.5 = más confianza
        confidence = abs(risk_score - 0.5) * 2
        
        return {
            'risk_score': risk_score,
            'decision': decision,
            'heuristic_score': heuristic_score,
            'ml_score': ml_score,
            'similar_score': similar_score,
            'confidence': confidence
        }
    
    def _heuristic_risk_score(self, episode: Dict[str, Any]) -> float:
        """
        Calcula score heurístico basado en reglas.
        Retorna valor entre 0.0 y 1.0.
        """
        score = 0.0
        
        # 1. Presence flags (indicadores de ataque)
        flags = episode.get('presence_flags', {})
        if flags.get('.env') or flags.get('../'):
            score += 0.3  # Acceso a archivos sensibles
        if flags.get('cgi-bin'):
            score += 0.25  # Path traversal común
        if flags.get('wp-') or flags.get('.git'):
            score += 0.15  # Escaneo de WordPress/Git
        
        # 2. Status code ratio (muchos 4xx = escaneo)
        status_ratio = episode.get('status_code_ratio', {})
        if status_ratio.get('4xx', 0) > 0.5:  # >50% son 4xx
            score += 0.2
        elif status_ratio.get('4xx', 0) > 0.3:  # >30% son 4xx
            score += 0.1
        
        # 3. Request rate (muy alto = bot)
        request_rate = episode.get('request_rate', 0)
        if request_rate > 10:  # > 10 req/s
            score += 0.2
        elif request_rate > 5:  # > 5 req/s
            score += 0.1
        
        # 4. Unique URIs (muchos endpoints = escaneo)
        unique_uris = episode.get('unique_uris', 0)
        if unique_uris >= 15:
            score += 0.2
        elif unique_uris >= 10:
            score += 0.15
        elif unique_uris >= 5:
            score += 0.1
        
        # 5. Path entropy (bajo = patrones repetitivos = bot)
        entropy = episode.get('path_entropy_avg', 0)
        if entropy < 2.0:  # Muy bajo
            score += 0.1
        elif entropy < 3.0:  # Bajo
            score += 0.05
        
        # 6. Threat types detectados en logs
        threat_types = episode.get('threat_types', {})
        if threat_types:
            # Si hay múltiples tipos de amenazas
            if len(threat_types) >= 2:
                score += 0.2
            elif len(threat_types) >= 1:
                score += 0.15
            
            # Amenazas críticas
            critical_threats = ['PATH_TRAVERSAL', 'XSS', 'SQLI', 'CMD_INJECTION']
            for threat in critical_threats:
                if threat in threat_types:
                    score += 0.1
        
        # 7. Total requests (muchos requests en poco tiempo)
        total_requests = episode.get('total_requests', 0)
        if total_requests >= 20:
            score += 0.1
        elif total_requests >= 10:
            score += 0.05
        
        return min(score, 1.0)  # Cap en 1.0
    
    # DEPRECATED: Este método ha sido movido a EpisodeMemory
    # Usar episode_memory.find_similar_episodes() en su lugar
    def find_similar_episodes(self, episode: Dict[str, Any], 
                             postgres_conn, limit: int = 5) -> List[Dict[str, Any]]:
        """
        DEPRECATED: Este método ha sido movido a EpisodeMemory.
        Mantenido por compatibilidad pero ya no se usa.
        """
        logger.warning("LocalDecisionLayer.find_similar_episodes() está deprecated. Usar EpisodeMemory en su lugar.")
        return []

