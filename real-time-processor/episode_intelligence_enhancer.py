"""
Episode Intelligence Enhancer - Mejora episodios con detección avanzada
Detección de zero-day, ofuscación y DDoS distribuido SIN costo adicional

Se integra en _process_episode ANTES del LLM para mejorar la decisión local
MUY RÁPIDO: <10ms por episodio
SIN COSTO: No usa LLM, solo análisis estadístico local
"""
import numpy as np
from collections import deque, defaultdict, Counter
from typing import Dict, Any, List, Optional
import math
import logging
import time
from datetime import datetime

logger = logging.getLogger(__name__)


class EpisodeIntelligenceEnhancer:
    """
    Mejora episodios con detección inteligente de:
    1. Zero-day (anomalías estadísticas comparadas con baseline)
    2. Ofuscación (análisis de URIs y payloads)
    3. DDoS potencial (correlación entre episodios)
    
    Se ejecuta ANTES del LLM para mejorar la decisión local.
    MUY RÁPIDO: <10ms por episodio
    SIN COSTO: No usa LLM, solo análisis estadístico local
    """
    
    def __init__(self):
        # Baseline de episodios normales (se construye dinámicamente)
        self.normal_baseline = {
            'features_mean': {},
            'features_std': {},
            'episode_count': 0,
            'last_updated': None
        }
        
        # Cola circular de episodios normales recientes
        self.recent_normal_episodes = deque(maxlen=500)  # Últimos 500 episodios normales
        
        # Cache de episodios sospechosos (para correlación DDoS)
        self.recent_suspicious_episodes = deque(maxlen=100)  # Últimos 100 sospechosos
        
        logger.info("✅ EpisodeIntelligenceEnhancer inicializado")
    
    def enhance_episode_analysis(self, episode: Dict[str, Any], 
                                  decision_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Mejora el análisis del episodio con detección avanzada.
        
        Args:
            episode: Episodio a analizar
            decision_result: Resultado de decisión local existente
            
        Returns:
            Dict con:
            - zero_day_risk: bool
            - obfuscation_detected: bool
            - ddos_risk: bool
            - enhanced_risk_score: float (risk_score mejorado)
            - should_consult_llm: bool (recomendación)
        """
        start_time = time.time()
        
        # 1. Detectar ofuscación (MUY RÁPIDO: <2ms)
        obfuscation = self._detect_obfuscation(episode)
        
        # CRÍTICO: Verificar si hay threat_types conocidos ANTES de marcar zero-day/DDoS
        threat_types = episode.get('threat_types', {}) or {}
        has_known_threats = bool(threat_types and len(threat_types) > 0)
        
        # 2. Detectar zero-day/anomalía (RÁPIDO: <5ms)
        zero_day_risk = self._detect_zero_day_risk(episode)
        
        # 3. Detectar DDoS potencial (RÁPIDO: <3ms)
        ddos_risk = self._detect_ddos_risk(episode)
        
        # CRÍTICO: Solo considerar zero-day/DDoS si NO hay threat_types conocidos
        # Si hay SCAN_PROBE, PATH_TRAVERSAL, etc., NO es zero-day/DDoS real
        zero_day_is_real = zero_day_risk['is_zero_day'] and not has_known_threats
        ddos_is_real = ddos_risk['is_ddos'] and not has_known_threats
        
        # 4. Ajustar risk_score basándose en detecciones
        original_risk = decision_result.get('risk_score', 0.5)
        enhanced_risk = original_risk
        
        # Si hay ofuscación → aumentar riesgo
        if obfuscation['is_obfuscated']:
            risk_increase = 0.15 * obfuscation['score']
            enhanced_risk += risk_increase
            logger.debug(f"🔍 Ofuscación detectada: +{risk_increase:.2f} al risk_score")
        
        # Si hay zero-day risk REAL (sin threats conocidos) → aumentar riesgo significativamente
        if zero_day_is_real:
            risk_increase = 0.25 * zero_day_risk['score']
            enhanced_risk += risk_increase
            logger.warning(f"🚨 Zero-day risk detectado: +{risk_increase:.2f} al risk_score")
        
        # Si hay DDoS risk REAL (sin threats conocidos) → aumentar riesgo
        if ddos_is_real:
            enhanced_risk += 0.20
            logger.warning(f"🌐 DDoS risk detectado: +0.20 al risk_score")
        
        # Normalizar a 0-1
        enhanced_risk = min(enhanced_risk, 1.0)
        
        # 5. Recomendar LLM si:
        # - Decision original es UNCERTAIN Y hay señales de riesgo
        # - Hay ofuscación Y no hay threat_types conocidos (posible ataque nuevo)
        # - Hay zero-day risk (definitivamente consultar LLM)
        # - Enhanced risk es alto (>0.7)
        decision = decision_result.get('decision', 'ALLOW')
        
        should_consult_llm = (
            decision == 'UNCERTAIN' or
            (obfuscation['is_obfuscated'] and not has_known_threats) or
            zero_day_is_real or  # Usar valor corregido (solo True si NO hay threats conocidos)
            (enhanced_risk > 0.7)
        )
        
        # Guardar detecciones en episodio para que LLM las vea
        # IMPORTANTE: Guardar solo valores booleanos y numéricos, no objetos completos
        # CRÍTICO: Usar valores corregidos (solo True si NO hay threats conocidos)
        episode['intelligence_analysis'] = {
            'zero_day_risk': zero_day_is_real,  # Solo True si NO hay threats conocidos
            'ddos_risk': ddos_is_real,  # Solo True si NO hay threats conocidos
            'obfuscation_detected': obfuscation['is_obfuscated'],  # Solo booleano
            'enhanced_risk_score': enhanced_risk,
            'original_risk_score': original_risk,
            # Guardar detalles completos solo si son relevantes (para debugging)
            'analysis_details': {
                'obfuscation': obfuscation,
                'zero_day': zero_day_risk,
                'ddos': ddos_risk
            }
        }
        
        elapsed_ms = (time.time() - start_time) * 1000
        
        logger.debug(f"⚡ Enhancement completado en {elapsed_ms:.1f}ms: "
                    f"zero_day={zero_day_is_real}, "
                    f"obfuscation={obfuscation['is_obfuscated']}, "
                    f"ddos={ddos_is_real}, "
                    f"enhanced_risk={enhanced_risk:.2f}")
        
        return {
            'zero_day_risk': zero_day_is_real,  # Usar valor corregido
            'obfuscation_detected': obfuscation['is_obfuscated'],
            'ddos_risk': ddos_is_real,  # Usar valor corregido
            'enhanced_risk_score': enhanced_risk,
            'should_consult_llm': should_consult_llm,
            'analysis_details': {
                'obfuscation': obfuscation,
                'zero_day': zero_day_risk,
                'ddos': ddos_risk
            }
        }
    
    def _detect_obfuscation(self, episode: Dict[str, Any]) -> Dict[str, Any]:
        """
        Detecta ofuscación en URIs del episodio.
        MUY RÁPIDO: <2ms
        """
        sample_uris = episode.get('sample_uris', [])
        if not sample_uris:
            return {
                'is_obfuscated': False, 
                'score': 0.0,
                'avg_entropy': 0.0,
                'avg_encoded_ratio': 0.0,
                'rare_patterns': 0.0
            }
        
        total_entropy = 0.0
        total_encoded = 0.0
        total_rare_patterns = 0
        
        # Analizar máximo 10 URIs para mantener velocidad
        uris_to_analyze = sample_uris[:10]
        
        for uri in uris_to_analyze:
            # Entropía de Shannon (medida de aleatoriedad)
            entropy = self._shannon_entropy(uri)
            total_entropy += entropy
            
            # Ratio de encoding (%XX)
            encoded_ratio = uri.count('%') / len(uri) if uri else 0.0
            total_encoded += encoded_ratio
            
            # Patrones raros de ofuscación
            uri_lower = uri.lower()
            rare_patterns = (
                uri_lower.count('%25') +      # Double encoding (%)
                uri_lower.count('%u00') +     # Unicode encoding
                uri_lower.count('\\x') +      # Hex escape
                uri_lower.count('%252e') +    # Double encoded path traversal
                uri_lower.count('\\u')        # Unicode escape
            )
            total_rare_patterns += rare_patterns
        
        # Calcular promedios
        uri_count = len(uris_to_analyze)
        avg_entropy = total_entropy / uri_count if uri_count > 0 else 0.0
        avg_encoded = total_encoded / uri_count if uri_count > 0 else 0.0
        avg_rare = total_rare_patterns / uri_count if uri_count > 0 else 0.0
        
        # Score combinado (pesos optimizados)
        # Entropía alta (>5 bits) = muy aleatorio/ofuscado
        # Encoding ratio alto (>0.2) = mucho URL encoding
        # Rare patterns > 0 = técnicas avanzadas de ofuscación
        obfuscation_score = (
            min(avg_entropy / 6.0, 1.0) * 0.4 +      # Normalizar entropía (máx ~6-8 bits)
            min(avg_encoded * 5.0, 1.0) * 0.3 +      # Normalizar encoding ratio
            min(avg_rare / 3.0, 1.0) * 0.3           # Normalizar rare patterns
        )
        
        is_obfuscated = obfuscation_score > 0.5  # Umbral ajustable
        
        return {
            'is_obfuscated': is_obfuscated,
            'score': float(obfuscation_score),
            'avg_entropy': float(avg_entropy),
            'avg_encoded_ratio': float(avg_encoded),
            'rare_patterns': float(avg_rare)
        }
    
    def _detect_zero_day_risk(self, episode: Dict[str, Any]) -> Dict[str, Any]:
        """
        Detecta riesgo de zero-day comparando con baseline normal.
        RÁPIDO: <5ms (solo comparaciones estadísticas)
        """
        if self.normal_baseline['episode_count'] < 50:
            # Baseline no listo, no podemos detectar zero-day
            return {
                'is_zero_day': False, 
                'score': 0.0, 
                'reason': 'baseline_not_ready',
                'deviations': 0,
                'avg_deviation': 0.0,
                'has_known_threats': bool(episode.get('threat_types', {}))
            }
        
        # Extraer features del episodio
        features = self._extract_episode_features(episode)
        
        # Comparar con baseline
        deviations = 0
        total_deviation = 0.0
        
        for feature_name, value in features.items():
            mean = self.normal_baseline['features_mean'].get(feature_name, 0)
            std = self.normal_baseline['features_std'].get(feature_name, 1.0)
            
            # Evitar división por cero
            if std == 0:
                std = 1.0
            
            # Z-score (desviación estándar desde la media)
            z_score = abs((value - mean) / std)
            
            if z_score > 2.0:  # Más de 2 desviaciones estándar = anómalo
                deviations += 1
                total_deviation += z_score
        
        # Calcular desviación promedio
        feature_count = len(features) if features else 1
        avg_deviation = total_deviation / feature_count
        
        # Es zero-day si:
        # 1. Tiene 3+ features con desviación significativa (Z > 2.0)
        # 2. NO tiene threat_types conocidos (no es ataque conocido)
        # 3. Desviación promedio alta (>2.5 desviaciones estándar)
        # 4. Tiene suficiente evidencia (requests >= 2, no solo un request aislado)
        has_known_threats = bool(episode.get('threat_types', {}))
        total_requests = episode.get('total_requests', 0)
        
        # CRÍTICO: Si tiene threat_types conocidos, NO puede ser zero-day
        # Si tiene solo 1 request, probablemente es un falso positivo
        is_zero_day = (
            deviations >= 3 and
            not has_known_threats and  # NO debe tener threat_types conocidos
            avg_deviation > 2.5 and
            total_requests >= 2  # Mínimo 2 requests para considerar zero-day
        )
        
        # Score de zero-day (0-1)
        zero_day_score = min(avg_deviation / 5.0, 1.0) if is_zero_day else 0.0
        
        return {
            'is_zero_day': is_zero_day,
            'score': float(zero_day_score),
            'deviations': deviations,
            'avg_deviation': float(avg_deviation),
            'has_known_threats': has_known_threats,
            'baseline_episodes': self.normal_baseline['episode_count']
        }
    
    def _detect_ddos_risk(self, episode: Dict[str, Any]) -> Dict[str, Any]:
        """
        Detecta riesgo de DDoS buscando patrones coordinados entre episodios.
        RÁPIDO: <3ms (solo verificar patrones recientes)
        """
        # Agregar episodio sospechoso a cache si corresponde
        threat_types = episode.get('threat_types', {})
        risk_score = episode.get('risk_score', 0.0)
        
        if threat_types or risk_score > 0.6:
            current_time = time.time()
            self.recent_suspicious_episodes.append({
                'episode': episode,
                'timestamp': current_time
            })
        
        # Buscar patrones coordinados en últimos 60 segundos
        current_time = time.time()
        # Convertir a lista primero para evitar "deque mutated during iteration"
        recent_suspicious_list = list(self.recent_suspicious_episodes)
        recent_suspicious = [
            e for e in recent_suspicious_list
            if current_time - e['timestamp'] < 60
        ]
        
        if len(recent_suspicious) < 5:
            return {
                'is_ddos': False, 
                'coordinated_attacks': 0,
                'total_suspicious_episodes': len(recent_suspicious),
                'details': []
            }
        
        # Agrupar por "comportamiento" (no por IP) para detectar coordinación
        behavior_groups = defaultdict(list)
        
        for entry in recent_suspicious:
            ep = entry['episode']
            # Crear firma de comportamiento (no basada en IP)
            behavior = self._create_behavior_signature(ep)
            behavior_groups[behavior].append(entry)  # Guardar entry completo (incluye timestamp)
        
        # Buscar grupos con múltiples IPs diferentes (coordinación)
        coordinated_attacks = []
        for behavior, entries in behavior_groups.items():
            # Extraer episodios y crear set de IPs
            episodes = [e['episode'] for e in entries]
            unique_ips = set(ep.get('src_ip') for ep in episodes if ep.get('src_ip'))
            
            # CRÍTICO: DDoS requiere múltiples IPs (>=5) Y coordinación temporal
        # Además, debe haber suficiente volumen de requests para ser significativo
        if len(unique_ips) >= 5:  # 5+ IPs diferentes con mismo comportamiento
                # Verificar coordinación temporal (usar timestamps de entries directamente)
                timestamps = [e['timestamp'] for e in entries]
                
                if timestamps:
                    time_span = max(timestamps) - min(timestamps)
                    
                    # Verificar que haya suficiente volumen total de requests
                    total_requests_across_episodes = sum(ep.get('total_requests', 0) for ep in episodes)
                    
                    # DDoS real: múltiples IPs, coordinación temporal Y volumen significativo
                    if time_span < 30 and total_requests_across_episodes >= 10:  # En menos de 30s Y >=10 requests totales
                        # CRÍTICO: Guardar las IPs reales para poder bloquearlas todas
                        coordinated_attacks.append({
                            'ips_count': len(unique_ips),
                            'ips': list(unique_ips),  # NUEVO: Guardar IPs reales
                            'behavior': behavior,
                            'time_span': time_span,
                            'episode_count': len(episodes),
                            'total_requests': total_requests_across_episodes
                        })
        
        # CRÍTICO: Solo marcar como DDoS si hay ataques coordinados confirmados
        is_ddos = len(coordinated_attacks) > 0
        
        return {
            'is_ddos': is_ddos,
            'coordinated_attacks': len(coordinated_attacks),
            'total_suspicious_episodes': len(recent_suspicious),
            'details': coordinated_attacks[:3]  # Top 3 para logging
        }
    
    def _extract_episode_features(self, episode: Dict[str, Any]) -> Dict[str, float]:
        """
        Extrae features numéricas del episodio para comparación estadística.
        """
        total_requests = episode.get('total_requests', 0)
        
        # Calcular time span
        episode_start = episode.get('episode_start')
        episode_end = episode.get('episode_end')
        
        if isinstance(episode_start, str):
            try:
                episode_start = datetime.fromisoformat(episode_start.replace('Z', '+00:00'))
            except:
                episode_start = datetime.now()
        
        if isinstance(episode_end, str):
            try:
                episode_end = datetime.fromisoformat(episode_end.replace('Z', '+00:00'))
            except:
                episode_end = datetime.now()
        
        if not isinstance(episode_start, datetime):
            episode_start = datetime.now()
        if not isinstance(episode_end, datetime):
            episode_end = datetime.now()
        
        time_span = (episode_end - episode_start).total_seconds()
        time_span = max(time_span, 1.0)  # Evitar división por cero
        
        # Extraer features
        request_rate = total_requests / time_span
        unique_uris = float(episode.get('unique_uris', 0))
        path_entropy = float(episode.get('path_entropy_avg', 0))
        
        status_ratio = episode.get('status_code_ratio', {}) or {}
        ratio_4xx = float(status_ratio.get('4xx', 0))
        
        methods_count = episode.get('methods_count', {}) or {}
        methods_diversity = float(len(methods_count))
        
        presence_flags = episode.get('presence_flags', {}) or {}
        presence_flags_count = float(sum(1 for v in presence_flags.values() if v))
        
        return {
            'request_rate': request_rate,
            'unique_uris': unique_uris,
            'path_entropy': path_entropy,
            'ratio_4xx': ratio_4xx,
            'methods_diversity': methods_diversity,
            'presence_flags_count': presence_flags_count
        }
    
    def _create_behavior_signature(self, episode: Dict[str, Any]) -> str:
        """
        Crea firma única de comportamiento (no basada en IP).
        Útil para detectar coordinación entre múltiples IPs.
        """
        # Normalizar URIs (remover parámetros específicos, mantener patrones)
        sample_uris = episode.get('sample_uris', [])[:5]
        normalized_uris = []
        
        for uri in sample_uris:
            # Remover query strings y fragmentos
            if '?' in uri:
                uri = uri.split('?')[0]
            if '#' in uri:
                uri = uri.split('#')[0]
            # Limitar longitud
            normalized_uris.append(uri[:50])
        
        methods = set((episode.get('methods_count', {}) or {}).keys())
        status_ratio = episode.get('status_code_ratio', {}) or {}
        
        # Crear firma hash
        signature_data = {
            'uri_patterns': sorted(normalized_uris),
            'methods': sorted(methods),
            'status_pattern': tuple(sorted(status_ratio.items()))
        }
        
        import hashlib
        return hashlib.md5(str(signature_data).encode()).hexdigest()
    
    def _shannon_entropy(self, text: str) -> float:
        """
        Calcula entropía de Shannon (medida de aleatoriedad).
        Textos ofuscados tienen alta entropía (más aleatorios).
        """
        if not text:
            return 0.0
        
        from collections import Counter
        counter = Counter(text)
        length = len(text)
        entropy = 0.0
        
        for count in counter.values():
            p = count / length
            if p > 0:
                entropy -= p * math.log2(p)
        
        return entropy
    
    def update_baseline(self, normal_episodes: List[Dict[str, Any]]):
        """
        Actualiza baseline estadístico con episodios normales.
        Se llama periódicamente en background.
        
        Args:
            normal_episodes: Lista de episodios clasificados como normales
        """
        if len(normal_episodes) < 50:
            logger.debug(f"Baseline no actualizado: {len(normal_episodes)}/<50 episodios normales")
            return
        
        # Agregar a cola circular
        for ep in normal_episodes:
            if len(self.recent_normal_episodes) >= 500:
                self.recent_normal_episodes.popleft()
            self.recent_normal_episodes.append(ep)
        
        # Extraer features de todos los episodios normales
        all_features = []
        for ep in list(self.recent_normal_episodes):
            try:
                features = self._extract_episode_features(ep)
                all_features.append(features)
            except Exception as e:
                logger.debug(f"Error extrayendo features de episodio: {e}")
                continue
        
        if not all_features:
            logger.warning("No se pudieron extraer features para baseline")
            return
        
        # Calcular estadísticas (media y desviación estándar)
        feature_names = all_features[0].keys()
        means = {}
        stds = {}
        
        for feature_name in feature_names:
            values = [f[feature_name] for f in all_features]
            means[feature_name] = float(np.mean(values))
            std = float(np.std(values))
            stds[feature_name] = std if std > 0 else 1.0  # Evitar std=0
        
        # Actualizar baseline
        self.normal_baseline = {
            'features_mean': means,
            'features_std': stds,
            'episode_count': len(all_features),
            'last_updated': datetime.now()
        }
        
        logger.info(f"✅ Baseline actualizado: {len(all_features)} episodios normales, "
                   f"{len(feature_names)} features, ready=True")

