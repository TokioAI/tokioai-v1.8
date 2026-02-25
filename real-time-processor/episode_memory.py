"""
Episode Memory - Sistema de memoria persistente para casos similares
Guarda decisiones y permite búsqueda rápida de episodios similares
"""
import logging
import json
import hashlib
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from collections import defaultdict

logger = logging.getLogger(__name__)


class EpisodeMemory:
    """
    Sistema de memoria persistente para episodios.
    Guarda decisiones del analista y permite búsqueda rápida de casos similares.
    """
    
    def __init__(self, postgres_conn, cache_ttl_hours: int = 720):  # 30 días por defecto
        """
        Inicializa el sistema de memoria.
        
        Args:
            postgres_conn: Conexión a PostgreSQL
            cache_ttl_hours: Tiempo de vida del cache en horas
        """
        self.postgres_conn = postgres_conn
        self.cache_ttl_hours = cache_ttl_hours
        self.in_memory_cache = {}  # Cache en memoria para acceso rápido
        self.cache_max_size = 1000  # Máximo de entradas en cache
        logger.info(f"✅ EpisodeMemory inicializado (TTL: {cache_ttl_hours}h)")
    
    def save_analyst_decision(self, episode_id: int, episode_features: Dict[str, Any],
                              analyst_label: str, analyst_notes: str = None,
                              analyst_id: str = None, confidence: float = 1.0) -> bool:
        """
        Guarda una decisión del analista para un episodio.
        Esto se usa cuando el analista corrige o etiqueta un episodio.
        
        Args:
            episode_id: ID del episodio
            episode_features: Features del episodio (JSON)
            analyst_label: Etiqueta del analista (ALLOW, PATH_TRAVERSAL, etc.)
            analyst_notes: Notas del analista
            analyst_id: ID del analista
            confidence: Confianza de la etiqueta (0.0-1.0)
            
        Returns:
            True si se guardó exitosamente
        """
        if not self.postgres_conn:
            return False
        
        try:
            cursor = self.postgres_conn.cursor()
            
            # Guardar en analyst_labels
            cursor.execute("""
                INSERT INTO analyst_labels (
                    episode_id, episode_features_json, analyst_label,
                    analyst_notes, analyst_id, confidence
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (episode_id) DO UPDATE SET
                    analyst_label = EXCLUDED.analyst_label,
                    analyst_notes = EXCLUDED.analyst_notes,
                    analyst_id = EXCLUDED.analyst_id,
                    confidence = EXCLUDED.confidence,
                    timestamp = NOW()
            """, (
                episode_id,
                json.dumps(episode_features),
                analyst_label,
                analyst_notes,
                analyst_id,
                confidence
            ))
            
            self.postgres_conn.commit()
            cursor.close()
            
            # Invalidar cache en memoria
            cache_key = self._generate_cache_key(episode_features)
            if cache_key in self.in_memory_cache:
                del self.in_memory_cache[cache_key]
            
            logger.info(f"💾 Decisión del analista guardada: episode_id={episode_id}, label={analyst_label}")
            return True
        
        except Exception as e:
            logger.error(f"Error guardando decisión del analista: {e}", exc_info=True)
            if self.postgres_conn:
                self.postgres_conn.rollback()
            return False
    
    def find_similar_episodes(self, episode_features: Dict[str, Any], 
                             limit: int = 5, min_similarity: float = 0.6) -> List[Dict[str, Any]]:
        """
        Encuentra episodios similares que fueron etiquetados por el analista.
        Usa cosine similarity en features y busca en BD.
        
        Args:
            episode_features: Features del episodio actual
            limit: Número máximo de similares a retornar
            min_similarity: Similitud mínima requerida (0.0-1.0)
            
        Returns:
            Lista de episodios similares con sus etiquetas
        """
        if not self.postgres_conn:
            return []
        
        try:
            # Verificar cache en memoria primero
            cache_key = self._generate_cache_key(episode_features)
            if cache_key in self.in_memory_cache:
                cached_result = self.in_memory_cache[cache_key]
                if self._is_cache_valid(cached_result):
                    logger.debug(f"💾 Cache hit para features similares")
                    return cached_result['similar_episodes']
            
            # Buscar en BD
            from psycopg2.extras import RealDictCursor
            cursor = self.postgres_conn.cursor(cursor_factory=RealDictCursor)
            
            # Obtener todos los episodios etiquetados recientes
            cursor.execute("""
                SELECT 
                    al.episode_id,
                    al.episode_features_json,
                    al.analyst_label,
                    al.confidence,
                    al.timestamp,
                    e.total_requests,
                    e.unique_uris,
                    e.request_rate,
                    e.presence_flags
                FROM analyst_labels al
                JOIN episodes e ON al.episode_id = e.episode_id
                WHERE al.timestamp > NOW() - INTERVAL '%s hours'
                ORDER BY al.timestamp DESC
                LIMIT 500
            """, (self.cache_ttl_hours,))
            
            labeled_episodes = cursor.fetchall()
            cursor.close()
            
            # Calcular similitud con cada uno
            similar_episodes = []
            current_vector = self._features_to_vector(episode_features)
            
            for labeled in labeled_episodes:
                labeled_features = labeled['episode_features_json']
                if isinstance(labeled_features, str):
                    labeled_features = json.loads(labeled_features)
                elif not isinstance(labeled_features, dict):
                    continue
                
                labeled_vector = self._features_to_vector(labeled_features)
                similarity = self._cosine_similarity(current_vector, labeled_vector)
                
                if similarity >= min_similarity:
                    similar_episodes.append({
                        'episode_id': labeled['episode_id'],
                        'similarity_score': similarity,
                        'analyst_label': labeled['analyst_label'],
                        'confidence': labeled.get('confidence', 1.0),
                        'timestamp': labeled['timestamp']
                    })
            
            # Ordenar por similitud y retornar top N
            similar_episodes.sort(key=lambda x: x['similarity_score'], reverse=True)
            result = similar_episodes[:limit]
            
            # Guardar en cache en memoria
            if len(self.in_memory_cache) >= self.cache_max_size:
                # Eliminar entrada más antigua
                oldest_key = min(self.in_memory_cache.keys(), 
                               key=lambda k: self.in_memory_cache[k]['timestamp'])
                del self.in_memory_cache[oldest_key]
            
            self.in_memory_cache[cache_key] = {
                'similar_episodes': result,
                'timestamp': datetime.now()
            }
            
            return result
        
        except Exception as e:
            logger.error(f"Error buscando episodios similares: {e}", exc_info=True)
            return []
    
    def _features_to_vector(self, features: Dict[str, Any]) -> List[float]:
        """
        Convierte features de episodio a vector numérico para calcular similitud.
        """
        vector = []
        
        # Features numéricas
        vector.append(float(features.get('total_requests', 0)))
        vector.append(float(features.get('unique_uris', 0)))
        vector.append(float(features.get('request_rate', 0)))
        vector.append(float(features.get('path_entropy_avg', 0)))
        
        # Status code ratios
        status_ratio = features.get('status_code_ratio', {})
        vector.append(float(status_ratio.get('2xx', 0)))
        vector.append(float(status_ratio.get('3xx', 0)))
        vector.append(float(status_ratio.get('4xx', 0)))
        vector.append(float(status_ratio.get('5xx', 0)))
        
        # Presence flags (binario)
        presence_flags = features.get('presence_flags', {})
        vector.append(1.0 if presence_flags.get('.env') else 0.0)
        vector.append(1.0 if presence_flags.get('../') else 0.0)
        vector.append(1.0 if presence_flags.get('wp-') else 0.0)
        vector.append(1.0 if presence_flags.get('cgi-bin') else 0.0)
        vector.append(1.0 if presence_flags.get('.git') else 0.0)
        
        return vector
    
    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """
        Calcula cosine similarity entre dos vectores.
        """
        if len(vec1) != len(vec2):
            return 0.0
        
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        magnitude1 = sum(a * a for a in vec1) ** 0.5
        magnitude2 = sum(b * b for b in vec2) ** 0.5
        
        if magnitude1 == 0 or magnitude2 == 0:
            return 0.0
        
        return dot_product / (magnitude1 * magnitude2)
    
    def _generate_cache_key(self, features: Dict[str, Any]) -> str:
        """Genera clave de cache basada en features"""
        key_data = {
            'unique_uris': features.get('unique_uris', 0),
            'request_rate': round(features.get('request_rate', 0), 1),
            'presence_flags': features.get('presence_flags', {})
        }
        key_str = json.dumps(key_data, sort_keys=True)
        return hashlib.md5(key_str.encode()).hexdigest()
    
    def _is_cache_valid(self, cache_entry: Dict[str, Any]) -> bool:
        """Verifica si una entrada de cache es válida"""
        if 'timestamp' not in cache_entry:
            return False
        age = (datetime.now() - cache_entry['timestamp']).total_seconds() / 3600
        return age < (self.cache_ttl_hours / 24)  # Cache válido por 1/24 del TTL
    
    def get_learning_stats(self) -> Dict[str, Any]:
        """
        Retorna estadísticas de aprendizaje (cuántos casos se han aprendido).
        """
        if not self.postgres_conn:
            return {}
        
        try:
            cursor = self.postgres_conn.cursor()
            
            cursor.execute("""
                SELECT 
                    COUNT(*) as total_labels,
                    COUNT(DISTINCT analyst_label) as unique_labels,
                    COUNT(*) FILTER (WHERE analyst_label != 'ALLOW') as attack_labels,
                    COUNT(*) FILTER (WHERE analyst_label = 'ALLOW') as allow_labels,
                    MAX(timestamp) as last_label_time
                FROM analyst_labels
                WHERE timestamp > NOW() - INTERVAL '%s hours'
            """, (self.cache_ttl_hours,))
            
            row = cursor.fetchone()
            cursor.close()
            
            return {
                'total_labels': row[0] or 0,
                'unique_labels': row[1] or 0,
                'attack_labels': row[2] or 0,
                'allow_labels': row[3] or 0,
                'last_label_time': row[4].isoformat() if row[4] else None
            }
        
        except Exception as e:
            logger.error(f"Error obteniendo estadísticas de aprendizaje: {e}", exc_info=True)
            return {}




