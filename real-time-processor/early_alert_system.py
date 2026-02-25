"""
Early Alert System - Sistema de alertas tempranas para patrones inusuales
Notifica al analista cuando detecta patrones nunca vistos antes
"""
import logging
import json
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from collections import Counter

logger = logging.getLogger(__name__)


class EarlyAlertSystem:
    """
    Sistema de alertas tempranas para patrones inusuales.
    Detecta cuando un episodio tiene características nunca vistas antes.
    """
    
    def __init__(self, postgres_conn, llm_analyzer=None, alert_threshold: float = 0.3):
        """
        Inicializa el sistema de alertas tempranas.
        
        Args:
            postgres_conn: Conexión a PostgreSQL
            llm_analyzer: Instancia de RealtimeLLMAnalyzer para consultar LLM
            alert_threshold: Umbral de "rareza" para alertar (0.0-1.0, más bajo = más sensible)
        """
        self.postgres_conn = postgres_conn
        self.llm_analyzer = llm_analyzer
        self.alert_threshold = alert_threshold
        self.alert_history = []  # Historial de alertas recientes (en memoria)
        self.max_alert_history = 100
        logger.info(f"✅ EarlyAlertSystem inicializado (threshold: {alert_threshold})")
    
    def check_unusual_pattern(self, episode: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Verifica si un episodio tiene patrones inusuales.
        
        Args:
            episode: Episodio a verificar
            
        Returns:
            Dict con alerta si es inusual, None si es normal
        """
        try:
            # 1. Verificar si tiene features nunca vistas antes
            rarity_score = self._calculate_rarity_score(episode)
            
            if rarity_score >= self.alert_threshold:
                # Es inusual, generar alerta
                alert = {
                    'episode_id': episode.get('episode_id'),
                    'src_ip': episode.get('src_ip'),
                    'rarity_score': rarity_score,
                    'unusual_features': self._identify_unusual_features(episode),
                    'timestamp': datetime.now(),
                    'episode_features': {
                        'total_requests': episode.get('total_requests', 0),
                        'unique_uris': episode.get('unique_uris', 0),
                        'request_rate': episode.get('request_rate', 0),
                        'presence_flags': episode.get('presence_flags', {}),
                        'threat_types': episode.get('threat_types', {})
                    }
                }
                
                # Si hay LLM disponible, pedirle análisis adicional
                if self.llm_analyzer and self.llm_analyzer.enabled:
                    alert['llm_analysis'] = self._get_llm_unusual_analysis(episode, alert)
                
                # Guardar alerta en historial
                self._add_to_history(alert)
                
                # Log alerta
                logger.warning(f"🚨 ALERTA TEMPRANA: Patrón inusual detectado - "
                             f"IP={episode.get('src_ip')}, rarity={rarity_score:.2f}, "
                             f"features={alert['unusual_features']}")
                
                return alert
            
            return None
        
        except Exception as e:
            logger.error(f"Error verificando patrón inusual: {e}", exc_info=True)
            return None
    
    def _calculate_rarity_score(self, episode: Dict[str, Any]) -> float:
        """
        Calcula un score de "rareza" del episodio (0.0 = común, 1.0 = muy raro).
        """
        if not self.postgres_conn:
            return 0.0
        
        try:
            rarity = 0.0
            
            # 1. Verificar combinación única de presence_flags
            presence_flags = episode.get('presence_flags', {})
            active_flags = [k for k, v in presence_flags.items() if v]
            flags_combination = tuple(sorted(active_flags))
            
            cursor = self.postgres_conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM episodes
                WHERE presence_flags @> %s::jsonb
                AND created_at > NOW() - INTERVAL '7 days'
            """, (json.dumps(presence_flags),))
            
            count = cursor.fetchone()[0]
            
            # Si esta combinación aparece menos de 5 veces en 7 días, es raro
            if count < 5:
                rarity += 0.3
            
            # 2. Verificar request_rate inusual
            request_rate = episode.get('request_rate', 0)
            if request_rate > 20:  # Muy alto
                rarity += 0.2
            elif request_rate < 0.1:  # Muy bajo (sospechoso en contexto de escaneo)
                rarity += 0.15
            
            # 3. Verificar path_entropy inusual
            entropy = episode.get('path_entropy_avg', 0)
            if entropy < 1.0:  # Muy bajo (patrones muy repetitivos)
                rarity += 0.2
            elif entropy > 6.0:  # Muy alto (muy aleatorio)
                rarity += 0.15
            
            # 4. Verificar combinación única de threat_types
            threat_types = episode.get('threat_types', {})
            if threat_types:
                threat_combination = tuple(sorted(threat_types.keys()))
                cursor.execute("""
                    SELECT COUNT(*) FROM episodes e
                    WHERE EXISTS (
                        SELECT 1 FROM jsonb_each(e.presence_flags) WHERE value = 'true'
                    )
                    AND created_at > NOW() - INTERVAL '7 days'
                    LIMIT 1
                """)
                # Si hay threat_types pero no aparece frecuentemente, es raro
                if len(threat_combination) >= 3:  # Muchos tipos diferentes
                    rarity += 0.2
            
            cursor.close()
            
            return min(rarity, 1.0)  # Cap en 1.0
        
        except Exception as e:
            logger.error(f"Error calculando rarity score: {e}", exc_info=True)
            return 0.0
    
    def _identify_unusual_features(self, episode: Dict[str, Any]) -> List[str]:
        """
        Identifica qué features son inusuales.
        """
        unusual = []
        
        request_rate = episode.get('request_rate', 0)
        if request_rate > 20:
            unusual.append(f"Request rate muy alto ({request_rate:.1f} req/s)")
        elif request_rate < 0.1:
            unusual.append(f"Request rate muy bajo ({request_rate:.1f} req/s)")
        
        entropy = episode.get('path_entropy_avg', 0)
        if entropy < 1.0:
            unusual.append(f"Path entropy muy bajo ({entropy:.2f}) - patrones muy repetitivos")
        elif entropy > 6.0:
            unusual.append(f"Path entropy muy alto ({entropy:.2f}) - muy aleatorio")
        
        presence_flags = episode.get('presence_flags', {})
        active_flags = [k for k, v in presence_flags.items() if v]
        if len(active_flags) >= 4:
            unusual.append(f"Muchos presence flags activos: {', '.join(active_flags)}")
        
        threat_types = episode.get('threat_types', {})
        if len(threat_types) >= 3:
            unusual.append(f"Múltiples tipos de amenazas: {', '.join(threat_types.keys())}")
        
        return unusual if unusual else ["Patrón general inusual"]
    
    def _get_llm_unusual_analysis(self, episode: Dict[str, Any], alert: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Consulta al LLM para análisis adicional de patrones inusuales.
        """
        try:
            import json
            
            prompt = f"""Eres un analista de seguridad SOC experto. Este episodio tiene patrones INUSUALES
que nunca hemos visto antes. Analiza cuidadosamente.

EPISODIO INUSUAL:
- IP: {episode.get('src_ip')}
- Total requests: {episode.get('total_requests', 0)}
- Unique URIs: {episode.get('unique_uris', 0)}
- Request rate: {episode.get('request_rate', 0):.2f} req/s
- Path entropy: {episode.get('path_entropy_avg', 0):.2f}
- Presence flags: {json.dumps(episode.get('presence_flags', {}))}
- Threat types: {json.dumps(episode.get('threat_types', {}))}

CARACTERÍSTICAS INUSUALES:
{chr(10).join('- ' + f for f in alert.get('unusual_features', []))}

ANÁLISIS REQUERIDO:
1. ¿Qué hace este patrón inusual? (¿escaneo avanzado? ¿bypass? ¿nuevo tipo de ataque?)
2. ¿Debería alertarse inmediatamente al analista humano?
3. ¿Qué recomiendas hacer? (BLOQUEAR inmediatamente, MONITOREAR, INVESTIGAR más)

Responde SOLO en formato JSON válido:
{{
    "assessment": "Descripción breve del patrón inusual (máximo 200 caracteres)",
    "severity": "critical|high|medium|low",
    "recommendation": "BLOCK|MONITOR|INVESTIGATE",
    "reasoning": "Explicación de por qué es inusual y qué significa (máximo 300 caracteres)",
    "should_alert_human": true/false
}}
"""
            
            if self.llm_analyzer and self.llm_analyzer.enabled and self.llm_analyzer.model:
                response = self.llm_analyzer.model.generate_content(prompt)
                response_text = response.text if hasattr(response, 'text') else str(response)
                
                # Parsear respuesta
                cleaned_text = response_text.strip()
                if cleaned_text.startswith("```json"):
                    cleaned_text = cleaned_text[7:]
                if cleaned_text.startswith("```"):
                    cleaned_text = cleaned_text[3:]
                if cleaned_text.endswith("```"):
                    cleaned_text = cleaned_text[:-3]
                cleaned_text = cleaned_text.strip()
                
                parsed = json.loads(cleaned_text)
                return parsed
        
        except Exception as e:
            logger.error(f"Error obteniendo análisis LLM de patrón inusual: {e}", exc_info=True)
            return None
    
    def _add_to_history(self, alert: Dict[str, Any]):
        """Agrega alerta al historial"""
        self.alert_history.append(alert)
        if len(self.alert_history) > self.max_alert_history:
            self.alert_history.pop(0)  # Eliminar la más antigua
    
    def get_recent_alerts(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Retorna alertas recientes.
        """
        return self.alert_history[-limit:] if self.alert_history else []




