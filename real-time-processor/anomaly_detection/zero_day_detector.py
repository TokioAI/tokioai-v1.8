"""
Zero-Day Detector - Detección de anomalías no supervisada
Usa Isolation Forest + Behavioral Baselining
"""
import os
import logging
import numpy as np
from typing import Dict, Any, List, Optional
from collections import defaultdict, deque
from datetime import datetime, timedelta
import threading

try:
    from sklearn.ensemble import IsolationForest
    from sklearn.preprocessing import StandardScaler
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

logger = logging.getLogger(__name__)


class ZeroDayDetector:
    """
    Detector de zero-days usando múltiples técnicas de anomaly detection.
    """
    
    def __init__(self, contamination: float = 0.01):
        """
        Args:
            contamination: Proporción esperada de anomalías (1% = 0.01)
        """
        if not SKLEARN_AVAILABLE:
            logger.warning("scikit-learn no disponible, anomaly detection deshabilitado")
            self.enabled = False
            return
        
        self.enabled = True
        self.contamination = contamination
        
        # Isolation Forest
        self.isolation_forest = IsolationForest(
            contamination=contamination,
            n_estimators=200,
            max_samples='auto',
            random_state=42,
            n_jobs=-1
        )
        
        # Scaler para normalizar features
        self.scaler = StandardScaler()
        
        # Behavioral baselines por IP
        self.baselines = defaultdict(dict)  # {ip: {features: distribution}}
        self.baseline_window_days = 7
        
        # Training data buffer
        self.training_buffer = deque(maxlen=10000)  # Últimos 10k logs normales
        
        # Stats
        self.stats = {
            'total_analyses': 0,
            'anomalies_detected': 0,
            'zero_day_candidates': 0,
            'isolation_forest_trained': False
        }
        
        self.lock = threading.Lock()
    
    def extract_features(self, log: Dict[str, Any]) -> np.ndarray:
        """
        Extrae features numéricas del log para anomaly detection.
        
        Features:
        1. URI length
        2. Query length
        3. User-agent length
        4. Request rate (rpm)
        5. Status code
        6. Method encoding
        7. Path depth
        8. Query parameter count
        9. Special characters in URI
        10. Entropy de URI
        11. Entropy de query
        12. Encoding indicators
        13. Numeric ratio in URI
        14. Upper/lower case ratio
        15. User-agent uniqueness
        """
        uri = str(log.get('uri', '') or '')
        query = str(log.get('query_string', '') or '')
        user_agent = str(log.get('user_agent', '') or '')
        method = log.get('method', 'GET')
        status = log.get('status', 200)
        
        features = np.zeros(15)
        
        # 1. URI length
        features[0] = len(uri)
        
        # 2. Query length
        features[1] = len(query)
        
        # 3. User-agent length
        features[2] = len(user_agent)
        
        # 4. Request rate (debe calcularse en contexto, usar placeholder)
        features[3] = 1.0  # Se actualizará con contexto real
        
        # 5. Status code
        features[4] = int(status) if isinstance(status, (int, str)) else 200
        
        # 6. Method encoding (GET=0, POST=1, etc.)
        method_map = {'GET': 0, 'POST': 1, 'PUT': 2, 'DELETE': 3, 'PATCH': 4, 'HEAD': 5, 'OPTIONS': 6}
        features[5] = method_map.get(method.upper(), 0)
        
        # 7. Path depth (número de /)
        features[6] = uri.count('/')
        
        # 8. Query parameter count
        features[7] = query.count('&') + (1 if '=' in query else 0)
        
        # 9. Special characters in URI
        special_chars = sum(1 for c in uri if c in '&?=<>[]{}()|\\')
        features[8] = special_chars
        
        # 10. Entropy de URI (medida de aleatoriedad)
        features[9] = self._calculate_entropy(uri)
        
        # 11. Entropy de query
        features[10] = self._calculate_entropy(query)
        
        # 12. Encoding indicators (detecta si hay encoding)
        has_encoding = '%' in uri or '%' in query
        features[11] = 1.0 if has_encoding else 0.0
        
        # 13. Numeric ratio in URI (muchos números = sospechoso)
        if len(uri) > 0:
            numeric_ratio = sum(1 for c in uri if c.isdigit()) / len(uri)
            features[12] = numeric_ratio
        else:
            features[12] = 0.0
        
        # 14. Upper/lower case ratio
        if len(uri) > 0:
            upper_ratio = sum(1 for c in uri if c.isupper()) / len(uri)
            features[13] = upper_ratio
        else:
            features[13] = 0.0
        
        # 15. User-agent uniqueness (0=común, 1=raro)
        # Simplificado por ahora
        features[14] = 0.5
        
        return features
    
    def _calculate_entropy(self, text: str) -> float:
        """Calcula entropía de Shannon"""
        if not text:
            return 0.0
        
        from collections import Counter
        counter = Counter(text)
        length = len(text)
        
        entropy = 0.0
        for count in counter.values():
            probability = count / length
            if probability > 0:
                entropy -= probability * np.log2(probability)
        
        return entropy
    
    def train_on_legitimate_traffic(self, logs: List[Dict[str, Any]]):
        """
        Entrena el modelo con tráfico legítimo conocido.
        Debe ejecutarse periódicamente en background.
        """
        if not self.enabled:
            return
        
        if len(logs) < 100:
            logger.warning("Necesitas al menos 100 logs para entrenar")
            return
        
        try:
            # Extraer features
            X = []
            for log in logs:
                features = self.extract_features(log)
                X.append(features)
            
            X = np.array(X)
            
            # Normalizar
            X_scaled = self.scaler.fit_transform(X)
            
            # Entrenar Isolation Forest
            self.isolation_forest.fit(X_scaled)
            
            with self.lock:
                self.stats['isolation_forest_trained'] = True
            
            logger.info(f"✅ Isolation Forest entrenado con {len(logs)} muestras legítimas")
        
        except Exception as e:
            logger.error(f"Error entrenando Isolation Forest: {e}", exc_info=True)
    
    def detect_anomaly(self, log: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Detecta si un log es una anomalía (potencial zero-day).
        
        Args:
            log: Log a analizar
            context: Contexto adicional (request rate, etc.)
            
        Returns:
            Dict con:
            - is_zero_day_candidate: Boolean
            - confidence: 0.0-1.0
            - iso_score: Isolation Forest score
            - behavioral_score: Behavioral deviation score
            - anomaly_reasons: Lista de razones
        """
        if not self.enabled:
            return {
                'is_zero_day_candidate': False,
                'confidence': 0.0,
                'reason': 'anomaly_detection_disabled'
            }
        
        with self.lock:
            if not self.stats['isolation_forest_trained']:
                # Si no está entrenado, no podemos detectar
                return {
                    'is_zero_day_candidate': False,
                    'confidence': 0.0,
                    'reason': 'model_not_trained'
                }
        
        self.stats['total_analyses'] += 1
        
        # Extraer features
        features = self.extract_features(log)
        
        # Actualizar features con contexto si está disponible
        if context:
            if 'request_rate' in context:
                features[3] = context['request_rate']
        
        # Normalizar
        try:
            features_scaled = self.scaler.transform([features])[0]
        except:
            # Si el scaler no está entrenado, usar features raw
            features_scaled = features
        
        # 1. Isolation Forest score
        iso_score = self.isolation_forest.score_samples([features_scaled])[0]
        # Score negativo = anomalía, más negativo = más anómalo
        is_iso_anomaly = iso_score < -0.5
        
        # 2. Behavioral deviation (por IP)
        ip = log.get('ip') or log.get('remote_addr') or 'unknown'
        behavioral_score = self._check_behavioral_deviation(ip, log, features)
        is_behavioral_anomaly = behavioral_score > 0.7
        
        # 3. Contar votos de anomalía
        anomaly_votes = sum([
            is_iso_anomaly,  # Isolation Forest
            is_behavioral_anomaly,  # Behavioral
        ])
        
        is_zero_day = anomaly_votes >= 2  # Si 2 de 2 indican anomalía
        
        # Calcular confianza
        confidence = anomaly_votes / 2.0  # Máximo 2 votos
        
        # Razones
        anomaly_reasons = []
        if is_iso_anomaly:
            anomaly_reasons.append(f"Isolation Forest anomaly (score: {iso_score:.2f})")
        if is_behavioral_anomaly:
            anomaly_reasons.append(f"Behavioral deviation (score: {behavioral_score:.2f})")
        
        if is_zero_day:
            self.stats['zero_day_candidates'] += 1
            self.stats['anomalies_detected'] += 1
        
        return {
            'is_zero_day_candidate': is_zero_day,
            'confidence': confidence,
            'iso_score': float(iso_score),
            'behavioral_score': behavioral_score,
            'anomaly_reasons': anomaly_reasons,
            'features_used': len(features)
        }
    
    def _check_behavioral_deviation(self, ip: str, log: Dict[str, Any], features: np.ndarray) -> float:
        """
        Verifica desviación del comportamiento normal de la IP.
        """
        if ip == 'unknown' or ip not in self.baselines:
            return 0.0  # Sin baseline, no podemos juzgar
        
        baseline = self.baselines[ip]
        deviation_score = 0.0
        
        uri = str(log.get('uri', '') or '')
        user_agent = str(log.get('user_agent', '') or '')
        
        # 1. URI nunca vista antes por esta IP
        known_uris = baseline.get('known_uris', set())
        if uri not in known_uris and len(known_uris) > 10:  # Solo si hay suficiente baseline
            deviation_score += 0.3
        
        # 2. User-agent cambió
        known_user_agents = baseline.get('user_agents', set())
        if user_agent and user_agent not in known_user_agents and len(known_user_agents) > 0:
            deviation_score += 0.2
        
        # 3. Request rate spike
        avg_rpm = baseline.get('avg_rpm', 1.0)
        current_rpm = features[3] if features[3] > 0 else 1.0
        if current_rpm > avg_rpm * 10:  # 10x el promedio
            deviation_score += 0.4
        
        # 4. Horario inusual (si tenemos datos)
        hour = datetime.now().hour
        active_hours = baseline.get('active_hours', set())
        if active_hours and hour not in active_hours:
            deviation_score += 0.1
        
        return min(deviation_score, 1.0)
    
    def update_baseline(self, ip: str, log: Dict[str, Any]):
        """
        Actualiza el baseline de comportamiento para una IP.
        Se debe llamar periódicamente con logs legítimos.
        """
        if ip == 'unknown':
            return
        
        if ip not in self.baselines:
            self.baselines[ip] = {
                'known_uris': set(),
                'user_agents': set(),
                'rpm_samples': deque(maxlen=1000),
                'active_hours': set(),
                'first_seen': datetime.now(),
                'last_updated': datetime.now()
            }
        
        baseline = self.baselines[ip]
        uri = str(log.get('uri', '') or '')
        user_agent = str(log.get('user_agent', '') or '')
        
        # Actualizar conocidos
        if uri:
            baseline['known_uris'].add(uri)
        if user_agent:
            baseline['user_agents'].add(user_agent)
        
        # Actualizar hora activa
        baseline['active_hours'].add(datetime.now().hour)
        
        # Actualizar timestamp
        baseline['last_updated'] = datetime.now()
        
        # Limpiar baselines antiguos (más de 7 días sin actualizar)
        if (datetime.now() - baseline['last_updated']).days > self.baseline_window_days:
            if ip in self.baselines:
                del self.baselines[ip]
    
    def get_stats(self) -> Dict[str, Any]:
        """Retorna estadísticas"""
        with self.lock:
            return {
                **self.stats,
                'baselines_count': len(self.baselines),
                'training_buffer_size': len(self.training_buffer)
            }
