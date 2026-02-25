"""
Learning Loop - Reentrena modelo local cada N episodios etiquetados
Permite aprendizaje incremental supervisado
"""
import logging
import time
import threading
from typing import Dict, Any, List, Optional
from collections import Counter

logger = logging.getLogger(__name__)


class LearningLoop:
    """
    Reentrena modelo local cada N episodios etiquetados.
    Reduce dependencia del LLM con el tiempo.
    """
    
    def __init__(self, ml_predictor, postgres_conn, retrain_threshold: int = 100):
        """
        Inicializa el Learning Loop.
        
        Args:
            ml_predictor: Instancia de RealtimeMLPredictor para reentrenar
            postgres_conn: Conexión a PostgreSQL para leer analyst_labels
            retrain_threshold: Número de etiquetas nuevas necesarias para reentrenar
        """
        self.ml_predictor = ml_predictor
        self.postgres_conn = postgres_conn
        self.retrain_threshold = retrain_threshold
        self.last_retrain_count = 0
        self.last_retrain_time = time.time()
        self.retrain_interval_seconds = 1800  # Reentrenar máximo cada 30 minutos (aprendizaje más rápido)
        logger.info(f"✅ LearningLoop inicializado (threshold: {retrain_threshold} etiquetas)")
    
    def check_and_retrain(self):
        """
        Verifica si hay suficientes etiquetas nuevas y reentrena si es necesario.
        Debe llamarse periódicamente (ej: cada hora).
        """
        if not self.postgres_conn:
            return
        
        try:
            # Contar etiquetas nuevas desde último reentrenamiento
            new_labels_count = self._count_new_labels()
            
            if new_labels_count >= self.retrain_threshold:
                # Verificar que no reentrenamos muy frecuentemente
                time_since_last = time.time() - self.last_retrain_time
                if time_since_last < self.retrain_interval_seconds:
                    logger.debug(f"⏳ Reentrenamiento reciente, esperando... ({time_since_last:.0f}s < {self.retrain_interval_seconds}s)")
                    return
                
                logger.info(f"🔄 Reentrenando modelo con {new_labels_count} nuevas etiquetas...")
                success = self._retrain_model()
                
                if success:
                    self.last_retrain_count = new_labels_count
                    self.last_retrain_time = time.time()
                    logger.info(f"✅ Modelo reentrenado exitosamente")
                else:
                    logger.warning(f"⚠️ Reentrenamiento falló, se reintentará más tarde")
            else:
                logger.debug(f"📊 Etiquetas nuevas: {new_labels_count}/{self.retrain_threshold} (faltan {self.retrain_threshold - new_labels_count})")
        
        except Exception as e:
            logger.error(f"❌ Error en check_and_retrain: {e}", exc_info=True)
    
    def _count_new_labels(self) -> int:
        """Cuenta etiquetas nuevas desde último reentrenamiento"""
        try:
            cursor = self.postgres_conn.cursor()
            
            # Contar etiquetas creadas después del último reentrenamiento
            cursor.execute("""
                SELECT COUNT(*) FROM analyst_labels
                WHERE timestamp > NOW() - INTERVAL '24 hours'
            """)
            
            count = cursor.fetchone()[0]
            cursor.close()
            return count
        
        except Exception as e:
            logger.error(f"Error contando etiquetas nuevas: {e}", exc_info=True)
            return 0
    
    def _get_analyst_labels(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Obtiene etiquetas de analistas desde BD.
        
        Args:
            limit: Número máximo de etiquetas a obtener (None = todas)
            
        Returns:
            Lista de dicts con episode_features_json y analyst_label
        """
        try:
            from psycopg2.extras import RealDictCursor
            cursor = self.postgres_conn.cursor(cursor_factory=RealDictCursor)
            
            query = """
                SELECT 
                    al.episode_features_json,
                    al.analyst_label,
                    al.confidence,
                    e.total_requests,
                    e.unique_uris,
                    e.request_rate,
                    e.presence_flags,
                    e.status_code_ratio
                FROM analyst_labels al
                JOIN episodes e ON al.episode_id = e.episode_id
                ORDER BY al.timestamp DESC
            """
            
            if limit:
                query += f" LIMIT {limit}"
            
            cursor.execute(query)
            labels = cursor.fetchall()
            cursor.close()
            
            return [dict(row) for row in labels]
        
        except Exception as e:
            logger.error(f"Error obteniendo analyst_labels: {e}", exc_info=True)
            return []
    
    def _prepare_training_data(self, labels: List[Dict[str, Any]]) -> tuple:
        """
        Prepara datos de entrenamiento desde analyst_labels.
        
        Args:
            labels: Lista de etiquetas de analistas
            
        Returns:
            Tuple (X, y) donde X son features y y son labels
        """
        X = []
        y = []
        
        for label_data in labels:
            features_json = label_data.get('episode_features_json', {})
            if isinstance(features_json, str):
                import json
                features_json = json.loads(features_json)
            
            # Extraer features numéricas
            features = [
                features_json.get('total_requests', 0),
                features_json.get('unique_uris', 0),
                features_json.get('request_rate', 0),
                features_json.get('path_entropy_avg', 0),
                features_json.get('status_code_ratio', {}).get('4xx', 0),
            ]
            
            # Agregar presence flags como features binarias
            presence_flags = features_json.get('presence_flags', {})
            features.extend([
                1 if presence_flags.get('.env') else 0,
                1 if presence_flags.get('../') else 0,
                1 if presence_flags.get('wp-') else 0,
                1 if presence_flags.get('cgi-bin') else 0,
                1 if presence_flags.get('.git') else 0,
            ])
            
            X.append(features)
            
            # Label: 1 si es ataque, 0 si es ALLOW
            analyst_label = label_data.get('analyst_label', 'ALLOW')
            y.append(1 if analyst_label != 'ALLOW' else 0)
        
        return X, y
    
    def _retrain_model(self) -> bool:
        """
        Reentrena modelo con analyst_labels y guarda historial.
        
        Returns:
            True si reentrenamiento exitoso, False si falló
        """
        retrain_start = time.time()
        labels_used = 0
        accuracy_before = None
        accuracy_after = None
        
        try:
            # Contar etiquetas nuevas desde último reentrenamiento
            labels_since_last = self._count_new_labels()
            
            # 1. Obtener etiquetas de BD
            labels = self._get_analyst_labels(limit=1000)  # Limitar para no sobrecargar
            
            if len(labels) < 10:
                logger.warning(f"⚠️ Muy pocas etiquetas para reentrenar: {len(labels)}")
                self._save_retrain_history(
                    labels_used=len(labels),
                    labels_since_last=labels_since_last,
                    success=False,
                    error_message=f"Muy pocas etiquetas: {len(labels)}"
                )
                return False
            
            labels_used = len(labels)
            
            # 2. Obtener accuracy actual (si es posible)
            if hasattr(self.ml_predictor, 'get_accuracy'):
                try:
                    accuracy_before = self.ml_predictor.get_accuracy()
                except:
                    pass
            
            logger.info(f"📊 Preparando datos de entrenamiento desde {len(labels)} etiquetas...")
            
            # 3. Preparar datos de entrenamiento
            X, y = self._prepare_training_data(labels)
            
            if len(X) < 10:
                logger.warning(f"⚠️ Muy pocos datos preparados: {len(X)}")
                self._save_retrain_history(
                    labels_used=labels_used,
                    labels_since_last=labels_since_last,
                    success=False,
                    error_message=f"Muy pocos datos preparados: {len(X)}"
                )
                return False
            
            # 4. Reentrenar modelo
            logger.info(f"🔄 Reentrenando modelo con {len(X)} muestras...")
            
            if hasattr(self.ml_predictor, 'retrain'):
                success = self.ml_predictor.retrain(X, y)
                
                # 5. Obtener accuracy después (si es posible)
                if success and hasattr(self.ml_predictor, 'get_accuracy'):
                    try:
                        accuracy_after = self.ml_predictor.get_accuracy()
                    except:
                        pass
                
                # 6. Calcular mejora
                improvement = None
                if accuracy_before is not None and accuracy_after is not None:
                    improvement = accuracy_after - accuracy_before
                
                # 7. Guardar historial
                training_duration = time.time() - retrain_start
                self._save_retrain_history(
                    labels_used=labels_used,
                    labels_since_last=labels_since_last,
                    success=success,
                    accuracy_before=accuracy_before,
                    accuracy_after=accuracy_after,
                    improvement=improvement,
                    training_duration_seconds=training_duration
                )
                
                return success
            else:
                logger.warning("⚠️ ml_predictor no tiene método retrain(), saltando reentrenamiento")
                self._save_retrain_history(
                    labels_used=labels_used,
                    labels_since_last=labels_since_last,
                    success=False,
                    error_message="ml_predictor no tiene método retrain()"
                )
                return False
        
        except Exception as e:
            logger.error(f"❌ Error en reentrenamiento: {e}", exc_info=True)
            self._save_retrain_history(
                labels_used=labels_used,
                labels_since_last=self._count_new_labels() if hasattr(self, 'postgres_conn') and self.postgres_conn else 0,
                success=False,
                error_message=str(e)
            )
            return False
    
    def _save_retrain_history(self, labels_used: int, labels_since_last: int, 
                              success: bool, accuracy_before: Optional[float] = None,
                              accuracy_after: Optional[float] = None, 
                              improvement: Optional[float] = None,
                              training_duration_seconds: Optional[float] = None,
                              error_message: Optional[str] = None):
        """Guarda historial de reentrenamiento en BD."""
        if not self.postgres_conn:
            return
        
        try:
            cursor = self.postgres_conn.cursor()
            cursor.execute("""
                INSERT INTO learning_history (
                    retrain_timestamp, labels_used, labels_since_last, retrain_threshold,
                    success, accuracy_before, accuracy_after, improvement,
                    training_duration_seconds, error_message
                ) VALUES (NOW(), %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                labels_used, labels_since_last, self.retrain_threshold,
                success, accuracy_before, accuracy_after, improvement,
                training_duration_seconds, error_message
            ))
            self.postgres_conn.commit()
            cursor.close()
            logger.info(f"✅ Historial de reentrenamiento guardado")
        except Exception as e:
            logger.error(f"Error guardando historial de reentrenamiento: {e}", exc_info=True)
            if self.postgres_conn:
                self.postgres_conn.rollback()



