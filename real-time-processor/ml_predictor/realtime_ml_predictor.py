"""
ML Predictor en Tiempo Real - Optimizado para predicciones rápidas (< 50ms)
"""
import logging
import os
import time
import json
from typing import Dict, Any, Optional, List
from pathlib import Path
import joblib
import numpy as np
from collections import defaultdict
import threading

# Imports para reentrenamiento
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
from datetime import datetime

logger = logging.getLogger(__name__)

# La función extract_features_from_logs se implementa localmente
# para evitar dependencias circulares


class RealtimeMLPredictor:
    """
    Predictor ML optimizado para tiempo real.
    Mantiene modelos en memoria para predicciones rápidas.
    """
    
    def __init__(self, models_dir: Optional[str] = None, default_model_id: Optional[str] = None):
        """
        Inicializa el predictor en tiempo real.
        
        Args:
            models_dir: Directorio donde están los modelos
            default_model_id: ID del modelo por defecto a usar
        """
        self.models_dir = Path(models_dir or os.getenv('ML_MODELS_DIR', '/app/models'))
        self.default_model_id = default_model_id or os.getenv('DEFAULT_ML_MODEL_ID')
        
        # Cache de modelos en memoria
        self.models_cache = {}
        self.scalers_cache = {}
        self.models_metadata = {}
        self.cache_lock = threading.Lock()
        
        # Métricas
        self.metrics = {
            'total_predictions': 0,
            'total_time_ms': 0.0,
            'avg_time_ms': 0.0,
            'max_time_ms': 0.0,
            'min_time_ms': float('inf'),
            'errors': 0
        }
        self.metrics_lock = threading.Lock()
        
        # Cargar modelo por defecto si existe
        if self.default_model_id:
            self.load_model(self.default_model_id)
        else:
            # Intentar cargar el modelo más reciente
            self._load_latest_model()
    
    def _load_latest_model(self):
        """Carga los modelos más recientes disponibles (Random Forest, KNN, KMeans)"""
        try:
            model_files = list(self.models_dir.glob("*.pkl"))
            # Filtrar scalers
            model_files = [f for f in model_files if not f.name.endswith('_scaler.pkl')]
            
            if model_files:
                # Ordenar por fecha de modificación
                model_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
                
                # Cargar modelos por tipo (prioridad: Random Forest > KNN > KMeans)
                loaded_models = {}
                for model_file in model_files:
                    model_id = model_file.stem
                    model_type = model_id.split('_')[0].lower()
                    
                    if model_type == 'random' and 'random_forest' not in loaded_models:
                        # Buscar random_forest completo
                        if 'random_forest' in model_id.lower():
                            logger.info(f"📦 Cargando Random Forest: {model_id}")
                            if self.load_model(model_id):
                                loaded_models['random_forest'] = model_id
                                self.default_model_id = model_id
                    elif model_type == 'knn' and 'knn' not in loaded_models:
                        logger.info(f"📦 Cargando KNN: {model_id}")
                        if self.load_model(model_id):
                            loaded_models['knn'] = model_id
                    elif model_type == 'kmeans' and 'kmeans' not in loaded_models:
                        logger.info(f"📦 Cargando KMeans: {model_id}")
                        if self.load_model(model_id):
                            loaded_models['kmeans'] = model_id
                
                # Si no se encontró Random Forest, cargar el más reciente
                if not self.default_model_id and model_files:
                    latest_model = model_files[0]
                    model_id = latest_model.stem
                    logger.info(f"📦 Cargando modelo más reciente como default: {model_id}")
                    if self.load_model(model_id):
                        self.default_model_id = model_id
                        
        except Exception as e:
            logger.warning(f"No se pudo cargar modelos: {e}")
    
    def load_model(self, model_id: str) -> bool:
        """
        Carga un modelo en memoria.
        
        Args:
            model_id: ID del modelo a cargar
        
        Returns:
            True si se cargó exitosamente
        """
        try:
            model_path = self.models_dir / f"{model_id}.pkl"
            scaler_path = self.models_dir / f"{model_id}_scaler.pkl"
            
            if not model_path.exists():
                logger.error(f"Modelo no encontrado: {model_path}")
                return False
            
            # Cargar modelo y scaler
            with self.cache_lock:
                self.models_cache[model_id] = joblib.load(model_path)
                if scaler_path.exists():
                    self.scalers_cache[model_id] = joblib.load(scaler_path)
                else:
                    logger.warning(f"Scaler no encontrado para {model_id}, usando sin normalización")
                    self.scalers_cache[model_id] = None
                
                # Guardar metadata
                self.models_metadata[model_id] = {
                    'model_id': model_id,
                    'loaded_at': time.time(),
                    'model_path': str(model_path)
                }
            
            logger.info(f"✅ Modelo {model_id} cargado en memoria")
            return True
            
        except Exception as e:
            logger.error(f"Error cargando modelo {model_id}: {e}", exc_info=True)
            return False
    
    def _extract_features_single(self, log: Dict[str, Any]) -> np.ndarray:
        """Extrae features de un solo log"""
        try:
            # Intentar importar función de mcp-core
            import sys
            from pathlib import Path
            mcp_core_path = Path("/app/mcp-core")
            if mcp_core_path.exists() and str(mcp_core_path) not in sys.path:
                sys.path.insert(0, str(mcp_core_path))
            
            from tools.ml_tools import extract_features_from_logs
            X, _ = extract_features_from_logs([log])
            return X[0] if len(X) > 0 else np.zeros(10)  # 10 features por defecto
        except:
            # Fallback: extracción manual simplificada
            feature_vector = []
            
            # 1. Severidad
            severity = log.get('severity', 'low').lower()
            severity_map = {'low': 0, 'medium': 1, 'high': 2}
            feature_vector.append(severity_map.get(severity, 1))
            
            # 2. Longitud URI
            uri = log.get('uri', '') or (log.get('raw_log', {}) or {}).get('uri', '')
            feature_vector.append(len(str(uri)))
            
            # 3. Longitud query
            query = log.get('query_string', '') or (log.get('raw_log', {}) or {}).get('query_string', '')
            feature_vector.append(len(str(query)))
            
            # 4. Método HTTP
            method = log.get('method', 'GET').upper()
            method_map = {'GET': 0, 'POST': 1, 'PUT': 2, 'DELETE': 3, 'PATCH': 4}
            feature_vector.append(method_map.get(method, 0))
            
            # 5. Status code
            status = log.get('status', 200)
            feature_vector.append(int(status) if status else 200)
            
            # 6-10. Indicadores de ataque (keywords)
            uri_lower = str(uri).lower()
            query_lower = str(query).lower()
            text = f"{uri_lower} {query_lower}"
            
            feature_vector.append(1 if any(kw in text for kw in ['union', 'select', 'drop', "'--"]) else 0)  # SQLi
            feature_vector.append(1 if any(kw in text for kw in ['<script', 'javascript:', 'onerror=']) else 0)  # XSS
            feature_vector.append(1 if any(kw in text for kw in ['../', '/etc/passwd']) else 0)  # Path traversal
            feature_vector.append(1 if any(kw in text for kw in ['cmd=', 'exec=', 'system(']) else 0)  # Command injection
            feature_vector.append(1 if log.get('blocked', False) else 0)  # Blocked
            
            # Rellenar hasta 10 features si es necesario
            while len(feature_vector) < 10:
                feature_vector.append(0)
            
            return np.array(feature_vector[:10])
    
    def predict(self, log: Dict[str, Any], model_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Predice la amenaza de un log en tiempo real (< 50ms objetivo).
        
        Args:
            log: Log normalizado
            model_id: ID del modelo a usar (usa default si no se especifica)
        
        Returns:
            Dict con predicción y métricas
        """
        start_time = time.time()
        
        try:
            # Usar modelo por defecto si no se especifica
            if not model_id:
                model_id = self.default_model_id or list(self.models_cache.keys())[0] if self.models_cache else None
            
            if not model_id or model_id not in self.models_cache:
                # Sin modelo, usar heurística básica
                return self._predict_heuristic(log, start_time)
            
            # Extraer features
            features = self._extract_features_single(log)
            features = features.reshape(1, -1)
            
            # Normalizar si hay scaler
            model = self.models_cache[model_id]
            scaler = self.scalers_cache.get(model_id)
            
            if scaler:
                features = scaler.transform(features)
            
            # Predecir
            prediction = model.predict(features)[0]
            prediction_proba = None
            
            # Obtener probabilidades si el modelo las soporta
            if hasattr(model, 'predict_proba'):
                try:
                    proba = model.predict_proba(features)[0]
                    prediction_proba = float(max(proba))
                except:
                    pass
            
            # Calcular tiempo
            elapsed_ms = (time.time() - start_time) * 1000
            
            # Actualizar métricas
            with self.metrics_lock:
                self.metrics['total_predictions'] += 1
                self.metrics['total_time_ms'] += elapsed_ms
                self.metrics['avg_time_ms'] = self.metrics['total_time_ms'] / self.metrics['total_predictions']
                self.metrics['max_time_ms'] = max(self.metrics['max_time_ms'], elapsed_ms)
                self.metrics['min_time_ms'] = min(self.metrics['min_time_ms'], elapsed_ms)
            
            # Mapear predicción a severidad
            severity_map = {0: 'low', 1: 'medium', 2: 'high'}
            predicted_severity = severity_map.get(int(prediction), 'medium')
            
            # Calcular threat_score
            threat_score = prediction_proba if prediction_proba else (0.5 if predicted_severity == 'medium' else (0.8 if predicted_severity == 'high' else 0.2))
            
            return {
                "success": True,
                "predicted_severity": predicted_severity,
                "threat_score": threat_score,
                "prediction": int(prediction),
                "model_id": model_id,
                "prediction_time_ms": round(elapsed_ms, 2),
                "confidence": prediction_proba
            }
            
        except Exception as e:
            logger.error(f"Error en predicción ML: {e}", exc_info=True)
            with self.metrics_lock:
                self.metrics['errors'] += 1
            
            # Fallback a heurística
            return self._predict_heuristic(log, start_time)
    
    def _predict_heuristic(self, log: Dict[str, Any], start_time: float) -> Dict[str, Any]:
        """Predicción heurística cuando no hay modelo disponible"""
        raw_log = log.get('raw_log')
        if isinstance(raw_log, str):
            try:
                raw_log = json.loads(raw_log)
            except Exception:
                raw_log = {}
        elif not isinstance(raw_log, dict):
            raw_log = {}
        uri = log.get('uri', '') or raw_log.get('uri', '')
        query = log.get('query_string', '') or raw_log.get('query_string', '')
        text = f"{uri} {query}".lower()
        
        # Detectar patrones
        has_sqli = any(kw in text for kw in ['union', 'select', 'drop', "'--", "'1'='1"])
        has_xss = any(kw in text for kw in ['<script', 'javascript:', 'onerror='])
        has_path_traversal = any(kw in text for kw in ['../', '/etc/passwd'])
        has_cmd_injection = any(kw in text for kw in ['cmd=', 'exec=', 'system('])
        
        # Determinar severidad
        if has_sqli or has_xss or has_path_traversal or has_cmd_injection or log.get('blocked'):
            severity = 'high'
            threat_score = 0.8
        elif log.get('status') == 403:
            severity = 'medium'
            threat_score = 0.5
        else:
            severity = 'low'
            threat_score = 0.2
        
        elapsed_ms = (time.time() - start_time) * 1000
        
        return {
            "success": True,
            "predicted_severity": severity,
            "threat_score": threat_score,
            "prediction": 2 if severity == 'high' else (1 if severity == 'medium' else 0),
            "model_id": "heuristic",
            "prediction_time_ms": round(elapsed_ms, 2),
            "confidence": None
        }
    
    def get_metrics(self) -> Dict[str, Any]:
        """Obtiene métricas de rendimiento"""
        with self.metrics_lock:
            return {
                **self.metrics,
                'loaded_models': list(self.models_cache.keys()),
                'default_model': self.default_model_id
            }
    
    def reset_metrics(self):
        """Resetea las métricas"""
        with self.metrics_lock:
            self.metrics = {
                'total_predictions': 0,
                'total_time_ms': 0.0,
                'avg_time_ms': 0.0,
                'max_time_ms': 0.0,
                'min_time_ms': float('inf'),
                'errors': 0
            }
    
    def retrain(self, X: List[List[float]], y: List[int]) -> bool:
        """
        Reentrena un modelo con nuevas etiquetas de analistas.
        
        Este método entrena un nuevo Random Forest usando las features preparadas
        desde episode_features_json y las etiquetas de analyst_labels (ALLOW = 0, ataque = 1).
        
        Args:
            X: Lista de features extraídas de episode_features_json
               Cada elemento es una lista de features numéricas (11 features:
               total_requests, unique_uris, request_rate, path_entropy_avg,
               status_code_ratio['4xx'], y 6 presence_flags binarios)
            y: Lista de etiquetas (0 = ALLOW/normal, 1 = ataque)
        
        Returns:
            True si el reentrenamiento fue exitoso, False en caso contrario
        """
        try:
            logger.info(f"🔄 Iniciando reentrenamiento con {len(X)} muestras...")
            
            # Convertir a numpy arrays
            X = np.array(X)
            y = np.array(y)
            
            # Validar datos
            if len(X) < 10:
                logger.error(f"❌ Muy pocas muestras para entrenar: {len(X)} (mínimo 10)")
                return False
            
            if len(X) != len(y):
                logger.error(f"❌ X e y tienen tamaños diferentes: {len(X)} vs {len(y)}")
                return False
            
            # Verificar que hay al menos algunas muestras de cada clase
            unique_labels = np.unique(y)
            if len(unique_labels) < 2:
                logger.warning(f"⚠️ Solo hay una clase en los datos: {unique_labels}. El modelo podría no generalizar bien.")
            
            # Dividir en train/test (80/20) con stratify para mantener proporción de clases
            try:
                X_train, X_test, y_train, y_test = train_test_split(
                    X, y, test_size=0.2, random_state=42, stratify=y
                )
            except ValueError:
                # Si stratify falla (p. ej., solo una clase), hacer split sin stratify
                logger.warning("⚠️ No se puede hacer stratify, usando split simple")
                X_train, X_test, y_train, y_test = train_test_split(
                    X, y, test_size=0.2, random_state=42
                )
            
            logger.info(f"📊 Datos divididos: train={len(X_train)}, test={len(X_test)}")
            
            # Normalizar features
            scaler = StandardScaler()
            X_train_scaled = scaler.fit_transform(X_train)
            X_test_scaled = scaler.transform(X_test)
            
            # Entrenar Random Forest (buen balance velocidad/precisión para tiempo real)
            logger.info(f"🤖 Entrenando Random Forest con {len(X_train)} muestras...")
            model = RandomForestClassifier(
                n_estimators=100,
                max_depth=15,
                min_samples_split=5,
                min_samples_leaf=2,
                random_state=42,
                n_jobs=-1,
                class_weight='balanced'  # Balancear clases si hay desbalance
            )
            
            model.fit(X_train_scaled, y_train)
            
            # Evaluar modelo
            y_pred = model.predict(X_test_scaled)
            accuracy = accuracy_score(y_test, y_pred)
            precision = precision_score(y_test, y_pred, average='weighted', zero_division=0)
            recall = recall_score(y_test, y_pred, average='weighted', zero_division=0)
            f1 = f1_score(y_test, y_pred, average='weighted', zero_division=0)
            
            logger.info(f"✅ Modelo entrenado - Accuracy: {accuracy:.3f}, F1: {f1:.3f}, "
                       f"Precision: {precision:.3f}, Recall: {recall:.3f}")
            
            # Generar ID del modelo con timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            model_id = f"retrained_rf_{timestamp}"
            
            # Guardar modelo y scaler
            model_path = self.models_dir / f"{model_id}.pkl"
            scaler_path = self.models_dir / f"{model_id}_scaler.pkl"
            
            # Asegurar que el directorio existe
            self.models_dir.mkdir(parents=True, exist_ok=True)
            
            joblib.dump(model, model_path)
            joblib.dump(scaler, scaler_path)
            
            logger.info(f"💾 Modelo guardado: {model_id}")
            
            # Cargar modelo en memoria
            with self.cache_lock:
                self.models_cache[model_id] = model
                self.scalers_cache[model_id] = scaler
                self.models_metadata[model_id] = {
                    'model_id': model_id,
                    'loaded_at': time.time(),
                    'model_path': str(model_path),
                    'accuracy': float(accuracy),
                    'precision': float(precision),
                    'recall': float(recall),
                    'f1_score': float(f1),
                    'training_samples': len(X_train),
                    'test_samples': len(X_test),
                    'created': datetime.now().isoformat()
                }
                
                # Actualizar modelo por defecto al reentrenado
                old_default = self.default_model_id
                self.default_model_id = model_id
                
                logger.info(f"✅ Modelo {model_id} cargado en memoria (reemplazando {old_default})")
            
            logger.info(f"✅ Reentrenamiento completado exitosamente (model_id: {model_id})")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error en reentrenamiento: {e}", exc_info=True)
            return False
    
    def get_accuracy(self) -> Optional[float]:
        """
        Obtiene la accuracy del modelo actual si está disponible.
        
        Returns:
            Accuracy del modelo actual o None si no está disponible
        """
        if not self.default_model_id:
            return None
        
        metadata = self.models_metadata.get(self.default_model_id, {})
        return metadata.get('accuracy')

