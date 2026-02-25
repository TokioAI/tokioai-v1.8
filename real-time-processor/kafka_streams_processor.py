"""
Kafka Streams Processor - Procesa logs en tiempo real desde Kafka
Sistema Híbrido Activo: Random Forest + KNN + KMeans + LLM
"""
import os
import json
import asyncio
import time
import threading
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta
from kafka import KafkaConsumer, KafkaProducer
from kafka.errors import KafkaError
import signal
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
import structlog

# Importar componentes
from ml_predictor.realtime_ml_predictor import RealtimeMLPredictor
from llm_analyzer.realtime_llm_analyzer import RealtimeLLMAnalyzer
from pattern_detector.sliding_window_detector import SlidingWindowPatternDetector
from time_window_analyzer import TimeWindowBatchAnalyzer
from owasp_threat_classifier import classify_by_owasp_top10
from episode_intelligence_enhancer import EpisodeIntelligenceEnhancer

# NUEVAS MEJORAS: Sistema inteligente (importación opcional con feature flags)
try:
    from improvements_config import ImprovementsConfig
    from intelligent_blocking_system import IntelligentBlockingSystem, BlockStage
    from rate_limit_manager import RateLimitManager
    from intelligent_cleanup_worker import IntelligentCleanupWorker
    IMPROVEMENTS_AVAILABLE = True
except ImportError as e:
    IMPROVEMENTS_AVAILABLE = False
    # logger se inicializará después de configurar structlog

# NUEVAS MEJORAS FASE 1: Detección Avanzada (Deobfuscation, Threat Intel, Anomaly Detection)
try:
    from deobfuscation_engine import DeobfuscationEngine
    from threat_intelligence.threat_intel_client import ThreatIntelligenceClient
    from anomaly_detection.zero_day_detector import ZeroDayDetector
    from anomaly_detection.baseline_trainer import BaselineTrainer
    ADVANCED_DETECTION_AVAILABLE = True
except ImportError as e:
    ADVANCED_DETECTION_AVAILABLE = False
    # logger se inicializará después de configurar structlog

# Baseline de URLs válidas
try:
    from site_baseline.baseline_manager import BaselineManager
    from site_baseline.persistence import get_valid_paths
    BASELINE_AVAILABLE = True
except ImportError:
    BASELINE_AVAILABLE = False
    # logger se inicializará después de configurar structlog

# PostgreSQL para persistencia
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False
    # logger se inicializará después de configurar structlog

# Configurar structlog
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)


def _normalize_log_for_episodes(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normaliza un log para que tenga los campos necesarios para EpisodeBuilder.
    Mapea campos de diferentes fuentes (BD, Kafka, etc.) a formato estándar.
    """
    from datetime import datetime
    
    # Normalizar IP (puede venir como 'ip', 'remote_addr', 'src_ip')
    ip = raw.get('ip') or raw.get('remote_addr') or raw.get('src_ip') or 'unknown'
    
    # Normalizar timestamp
    timestamp = raw.get('timestamp') or raw.get('date') or raw.get('created_at')
    if not timestamp:
        timestamp = datetime.now().isoformat()
    elif isinstance(timestamp, datetime):
        timestamp = timestamp.isoformat()
    
    # Normalizar user_agent
    user_agent = raw.get('user_agent') or raw.get('user_agent_header') or raw.get('http_user_agent') or ''
    
    # Normalizar method
    method = raw.get('method') or raw.get('request_method') or 'GET'
    
    # Normalizar URI
    uri = raw.get('uri') or raw.get('request_uri') or raw.get('path') or ''
    
    # Normalizar status
    status = raw.get('status', 200)
    if isinstance(status, str):
        try:
            status = int(status)
        except:
            status = 200
    
    # Crear log normalizado (preservar campos originales)
    normalized = dict(raw)  # Copiar todos los campos originales
    normalized['ip'] = ip
    normalized['timestamp'] = timestamp
    normalized['user_agent'] = user_agent
    normalized['method'] = method
    normalized['uri'] = uri
    normalized['status'] = status
    
    return normalized


class KafkaStreamsProcessor:
    """
    Procesador de streams de Kafka para análisis en tiempo real.
    Integra ML, LLM y detección de patrones.
    """
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Inicializa el procesador de streams.
        
        Args:
            config: Configuración opcional
        """
        self.config = config or {}
        
        # Métricas (inicializar PRIMERO para evitar AttributeError)
        self.metrics = {
            'total_logs_processed': 0,
            'ml_predictions': 0,
            'transformer_predictions': 0,  # FASE 7
            'llm_analyses': 0,
            'patterns_detected': 0,
            'mitigations_sent': 0,
            'fallback_to_transformer': 0,  # FASE 7
            'fallback_to_llm': 0,  # FASE 7
            'blocked_ips_skipped': 0,  # OPTIMIZACIÓN: Logs omitidos por IP bloqueada
            'start_time': time.time(),
            # FASE 7: Métricas de latencia
            'ml_latency_ms': [],
            'transformer_latency_ms': [],
            'llm_latency_ms': [],
            'end_to_end_latency_ms': []
        }
        
        # Configuración de Kafka
        self.kafka_brokers = self.config.get('kafka_brokers') or os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'kafka:9093')
        self.topic_pattern = self.config.get('topic_pattern') or os.getenv('KAFKA_TOPIC_PATTERN', 'waf-logs-*')
        self.consumer_group = self.config.get('consumer_group') or os.getenv('KAFKA_CONSUMER_GROUP', 'realtime-processor-group')
        
        # Inicializar logger structlog
        self.logger = structlog.get_logger(__name__)
        
        # Inicializar componentes
        self.logger.info("inicializando_componentes", message="🔧 Inicializando componentes...")
        
        # ML Predictor (primera capa: RandomForest/clásico)
        models_dir = self.config.get('models_dir') or os.getenv('ML_MODELS_DIR', '/app/models')
        default_model = self.config.get('default_model_id') or os.getenv('DEFAULT_ML_MODEL_ID')
        self.ml_predictor = RealtimeMLPredictor(models_dir=models_dir, default_model_id=default_model)
        self.logger.info("ml_predictor_inicializado", message="✅ ML Predictor inicializado")
        
        # FASE 7: Transformer Predictor (segunda capa: MiniLM/DistilBERT)
        # Inicialización lazy - solo cuando se necesite para evitar bloquear el inicio
        self.transformer_predictor = None
        self.transformer_enabled = self.config.get('enable_transformer', os.getenv('ENABLE_TRANSFORMER', 'true').lower() == 'true')
        self.transformer_initialized = False
        self.transformer_config = {
            'model': self.config.get('transformer_model') or os.getenv('TRANSFORMER_MODEL', 'minilm'),
            'model_path': self.config.get('transformer_model_path') or os.getenv('TRANSFORMER_MODEL_PATH'),
            'models_dir': self.config.get('transformer_models_dir') or os.getenv('TRANSFORMER_MODELS_DIR', '/tmp/models/transformers'),
            'confidence_threshold': float(self.config.get('transformer_confidence_threshold') or os.getenv('TRANSFORMER_CONFIDENCE_THRESHOLD', '0.7')),
            'margin_threshold': float(self.config.get('transformer_margin_threshold') or os.getenv('TRANSFORMER_MARGIN_THRESHOLD', '0.2'))
        }
        
        if self.transformer_enabled:
            self.logger.info("component_enabled", message=f"FASE 7: Transformer habilitado (inicialización lazy cuando se necesite)")
        else:
            self.logger.info("component_enabled", message=f"FASE 7: Transformer deshabilitado")
        
        # LLM Analyzer (tercera capa: teacher)
        gemini_key = self.config.get('gemini_api_key') or os.getenv('GEMINI_API_KEY', '')
        self.llm_analyzer = RealtimeLLMAnalyzer(api_key=gemini_key)
        self.logger.info("llm_analyzer_inicializado", message="✅ LLM Analyzer inicializado")
        
        # Pattern Detector
        window_size = self.config.get('window_size_seconds', 300)
        min_events = self.config.get('min_events', 5)
        self.pattern_detector = SlidingWindowPatternDetector(
            window_size_seconds=window_size,
            min_events=min_events
        )
        self.logger.info("pattern_detector_inicializado", message="✅ Pattern Detector inicializado")
        
        # Kafka Consumer y Producer
        self.consumer = None
        self.producer = None
        self.running = False
        
        # Topic para enviar decisiones de mitigación
        self.threats_topic = self.config.get('threats_topic') or os.getenv('THREATS_TOPIC', 'threats-detected')
        
        # Configuración de procesamiento
        self.ml_threshold = self.config.get('ml_threshold', 0.7)  # Solo LLM si threat_score > 0.7
        self.doubt_threshold = self.config.get('doubt_threshold', 0.35)  # OPTIMIZADO: Umbral de duda más estricto (confianza < 35%) para reducir llamadas LLM
        self.enable_llm = self.config.get('enable_llm', True)
        self.enable_pattern_detection = self.config.get('enable_pattern_detection', True)
        self.send_to_mitigation = self.config.get('send_to_mitigation', True)  # Enviar decisiones a mitigation service
        
        # Configuración de modelos híbridos
        self.use_random_forest = self.config.get('use_random_forest', True)
        self.use_knn = self.config.get('use_knn', True)
        self.use_kmeans = self.config.get('use_kmeans', True)
        
        # PostgreSQL para persistencia y aprendizaje continuo
        self.postgres_enabled = POSTGRES_AVAILABLE and self.config.get('enable_postgres', True)
        self.postgres_conn = None
        if self.postgres_enabled:
            self._init_postgres()
        
        # Buffer para aprendizaje continuo (logs clasificados por LLM)
        self.learning_buffer = []
        self.learning_buffer_lock = threading.Lock()
        self.learning_buffer_size = self.config.get('learning_buffer_size', 100)
        
        # Thread para re-entrenamiento periódico
        self.retrain_interval = self.config.get('retrain_interval_seconds', 3600)  # 1 hora
        self.last_retrain = time.time()
        
        # Thread para leer logs de BD periódicamente (fallback si no llegan a Kafka)
        self.db_poll_interval = self.config.get('db_poll_interval_seconds', 30)  # Leer cada 30 segundos
        self.last_db_poll = 0
        self.last_db_poll_timestamp = None  # Último timestamp procesado desde BD
        
        # NUEVO: Paneo rápido tipo dashboard (analiza logs recientes como un analista humano)
        self.quick_scan_interval = self.config.get('quick_scan_interval_seconds', 120)  # Cada 2 minutos
        self.last_quick_scan = 0
        
        # OPTIMIZACIÓN: Cache de IPs bloqueadas para verificación O(1) sin queries a BD
        self.blocked_ip_cache = None
        if self.postgres_enabled and self.postgres_conn:
            try:
                from blocked_ip_cache import BlockedIPCache
                cache_update_interval = self.config.get('blocked_ip_cache_update_interval', 30)
                self.blocked_ip_cache = BlockedIPCache(
                    postgres_conn=self.postgres_conn,
                    update_interval=cache_update_interval
                )
                self.logger.info("component_enabled", message=f"✅ BlockedIPCache habilitado (update_interval: {cache_update_interval}s)")
            except ImportError as e:
                self.logger.warning("log_event", message=f"BlockedIPCache no disponible: {e}")
                self.blocked_ip_cache = None
        
        # NUEVO: Episode Builder para análisis por episodios (REEMPLAZA lógica antigua)
        try:
            from episode_builder import EpisodeBuilder
            # Ventana configurable: 60s (1min), 300s (5min), 600s (10min)
            episode_window = self.config.get('episode_window_seconds', 
                                            int(os.getenv('EPISODE_WINDOW_SECONDS', '300')))
            max_active_episodes = self.config.get('max_active_episodes', 5000)
            self.episode_builder = EpisodeBuilder(
                episode_window_seconds=episode_window,
                max_active_episodes=max_active_episodes
            )
            self.episode_enabled = True
            self.logger.info("component_enabled", message=f"✅ EpisodeBuilder habilitado (ventana: {episode_window}s = {episode_window/60:.1f}min, max: {max_active_episodes}) - REEMPLAZA lógica antigua")
        except ImportError as e:
            self.logger.warning("log_event", message=f"EpisodeBuilder no disponible: {e}")
            self.episode_builder = None
            self.episode_enabled = False
        
        # NUEVO: Episode Memory - Sistema de memoria persistente para casos similares
        try:
            from episode_memory import EpisodeMemory
            cache_ttl = self.config.get('episode_memory_cache_ttl_hours', 720)  # 30 días
            self.episode_memory = EpisodeMemory(
                postgres_conn=self.postgres_conn if self.postgres_enabled else None,
                cache_ttl_hours=cache_ttl
            )
            self.logger.info("component_enabled", message=f"✅ EpisodeMemory habilitado (TTL: {cache_ttl}h)")
        except ImportError as e:
            self.logger.warning("log_event", message=f"EpisodeMemory no disponible: {e}")
            self.episode_memory = None
        
        # NUEVO: Early Alert System - Alertas tempranas para patrones inusuales
        try:
            from early_alert_system import EarlyAlertSystem
            alert_threshold = self.config.get('early_alert_threshold', 0.3)
            self.early_alert = EarlyAlertSystem(
                postgres_conn=self.postgres_conn if self.postgres_enabled else None,
                llm_analyzer=self.llm_analyzer if self.enable_llm else None,
                alert_threshold=alert_threshold
            )
            self.logger.info("component_enabled", message=f"✅ EarlyAlertSystem habilitado (threshold: {alert_threshold})")
        except ImportError as e:
            self.logger.warning("log_event", message=f"EarlyAlertSystem no disponible: {e}")
            self.early_alert = None
        
        # NUEVO: Episode Intelligence Enhancer - Detección avanzada (zero-day, ofuscación, DDoS)
        try:
            self.episode_enhancer = EpisodeIntelligenceEnhancer()
            self.logger.info("log_event", message="✅ EpisodeIntelligenceEnhancer habilitado (zero-day, ofuscación, DDoS)")
        except Exception as e:
            self.logger.warning("log_event", message=f"EpisodeIntelligenceEnhancer no disponible: {e}")
            self.episode_enhancer = None
        
        # NUEVAS MEJORAS: Sistema de bloqueo inteligente (opcional con feature flags)
        self.intelligent_blocking = None
        self.rate_limit_manager = None
        self.cleanup_worker = None
        if IMPROVEMENTS_AVAILABLE and ImprovementsConfig.ENABLE_INTELLIGENT_BLOCKING:
            try:
                self.intelligent_blocking = IntelligentBlockingSystem(
                    postgres_conn=self.postgres_conn if self.postgres_enabled else None
                )
                self.logger.info("log_event", message="✅ IntelligentBlockingSystem habilitado")
                
                # Rate Limit Manager
                if ImprovementsConfig.ENABLE_RATE_LIMITING:
                    self.rate_limit_manager = RateLimitManager(
                        postgres_conn=self.postgres_conn if self.postgres_enabled else None
                    )
                    self.logger.info("log_event", message="✅ RateLimitManager habilitado")
                
                # Cleanup Worker (iniciar en background)
                if ImprovementsConfig.ENABLE_AUTO_CLEANUP:
                    self.cleanup_worker = IntelligentCleanupWorker(
                        intelligent_blocking=self.intelligent_blocking,
                        postgres_conn=self.postgres_conn if self.postgres_enabled else None
                    )
                    # Se iniciará cuando se inicie el procesador
                    self.logger.info("log_event", message="✅ IntelligentCleanupWorker habilitado (se iniciará en background)")
            except Exception as e:
                self.logger.warning("error_occurred", message=f"Error inicializando mejoras inteligentes: {e}", exc_info=True)
        else:
            if not IMPROVEMENTS_AVAILABLE:
                self.logger.debug("log_event", message="Mejoras inteligentes no disponibles (módulos no encontrados)")
            else:
                self.logger.debug("log_event", message="Mejoras inteligentes deshabilitadas por configuración")
        
        # NUEVAS MEJORAS FASE 1: Detección Avanzada (Deobfuscation, Threat Intel, Anomaly Detection)
        self.deobfuscation_engine = None
        self.threat_intel = None
        self.zero_day_detector = None
        self.baseline_trainer = None
        if ADVANCED_DETECTION_AVAILABLE:
            try:
                # Deobfuscation Engine
                if ImprovementsConfig.ENABLE_DEOBFUSCATION:
                    self.deobfuscation_engine = DeobfuscationEngine(max_depth=5)
                    self.logger.info("log_event", message="✅ DeobfuscationEngine habilitado")
                
                # Threat Intelligence Client
                if ImprovementsConfig.ENABLE_THREAT_INTELLIGENCE:
                    self.threat_intel = ThreatIntelligenceClient()
                    self.logger.info("log_event", message="✅ ThreatIntelligenceClient habilitado")
                
                # Zero-Day Detector (Anomaly Detection)
                if ImprovementsConfig.ENABLE_ANOMALY_DETECTION:
                    contamination = ImprovementsConfig.ANOMALY_CONTAMINATION
                    self.zero_day_detector = ZeroDayDetector(contamination=contamination)
                    self.logger.info("component_enabled", message=f"✅ ZeroDayDetector habilitado (contamination: {contamination})")
                    
                    # Baseline Trainer (iniciar en background)
                    self.baseline_trainer = BaselineTrainer(
                        zero_day_detector=self.zero_day_detector,
                        postgres_conn=self.postgres_conn if self.postgres_enabled else None
                    )
                    self.logger.info("log_event", message="✅ BaselineTrainer habilitado (se iniciará en background)")
            except Exception as e:
                self.logger.warning("error_occurred", message=f"Error inicializando detección avanzada: {e}", exc_info=True)
        else:
            self.logger.debug("log_event", message="Detección avanzada no disponible (módulos no encontrados)")
        
        # NUEVO: Local Decision Layer (sin LLM)
        try:
            from local_decision_layer import LocalDecisionLayer
            block_threshold = self.config.get('episode_block_threshold', 0.8)
            allow_threshold = self.config.get('episode_allow_threshold', 0.3)
            self.local_decision = LocalDecisionLayer(
                ml_predictor=self.ml_predictor,
                block_threshold=block_threshold,
                allow_threshold=allow_threshold
            )
            self.logger.info("component_enabled", message=f"✅ LocalDecisionLayer habilitado (block={block_threshold}, allow={allow_threshold})")
        except ImportError as e:
            self.logger.warning("log_event", message=f"LocalDecisionLayer no disponible: {e}")
            self.local_decision = None
        
        # NUEVO: Learning Loop para reentrenamiento con analyst_labels
        try:
            from learning_loop import LearningLoop
            # Leer desde config o variable de entorno, default 20 (optimizado)
            retrain_threshold = self.config.get('learning_retrain_threshold', 
                                               int(os.getenv('LEARNING_RETRAIN_THRESHOLD', '20')))
            self.learning_loop = LearningLoop(
                ml_predictor=self.ml_predictor,
                postgres_conn=self.postgres_conn if self.postgres_enabled else None,
                retrain_threshold=retrain_threshold
            )
            self.logger.info("component_enabled", message=f"✅ LearningLoop habilitado (threshold: {retrain_threshold} etiquetas)")
        except ImportError as e:
            self.logger.warning("log_event", message=f"LearningLoop no disponible: {e}")
            self.learning_loop = None
        
        # OPTIMIZACIÓN: Buffer por IP para análisis por lotes
        # Agrupa logs sospechosos por IP y analiza cuando se alcanza threshold
        # OPTIMIZADO: Threshold reducido a 3 logs para detección más rápida
        self.ip_suspicious_buffer = {}  # {ip: [logs]}
        self.ip_buffer_lock = threading.Lock()
        self.ip_buffer_threshold = self.config.get('ip_buffer_threshold', 1)  # Analizar cuando hay 1+ log (MUY agresivo para detección inmediata)
        self.scan_probe_block_threshold = self.config.get('scan_probe_block_threshold', 2)  # Bloquear inmediatamente con 2+ SCAN_PROBE (MUY agresivo)
        self.ip_buffer_max_age = self.config.get('ip_buffer_max_age_seconds', 300)  # 5 minutos máximo
        
        # NUEVO: Analizador por ventanas temporales (análisis SOC-level)
        # Analiza tráfico en ventanas temporales para detectar ataques distribuidos, escaneos coordinados, etc.
        time_window_size_logs = self.config.get('time_window_size_logs', int(os.getenv('TIME_WINDOW_SIZE_LOGS', '5')))  # Analizar cada 5 logs (MUY frecuente para detección inmediata)
        time_window_size_seconds = self.config.get('time_window_size_seconds', int(os.getenv('TIME_WINDOW_SIZE_SECONDS', '60')))  # O cada 1 minuto (MUY frecuente para análisis SOC)
        self.time_window_analyzer = TimeWindowBatchAnalyzer(
            window_size_logs=time_window_size_logs,
            window_size_seconds=time_window_size_seconds
        )
        self.window_analysis_lock = threading.Lock()
        self.logger.info("log_event", message=f"✅ TimeWindowBatchAnalyzer inicializado: {time_window_size_logs} logs o {time_window_size_seconds}s")
        
        # NUEVO: Baseline Manager - escanea el sitio para conocer URLs válidas
        if BASELINE_AVAILABLE:
            base_url = self.config.get('waf_target_url') or os.getenv('WAF_TARGET_URL', 'http://modsecurity-nginx:8080')
            tenant_id = self.config.get('tenant_id')
            scan_interval_hours = int(self.config.get('baseline_scan_interval_hours') or os.getenv('BASELINE_SCAN_INTERVAL_HOURS', '24'))
            self.baseline_manager = BaselineManager(
                base_url=base_url,
                tenant_id=tenant_id,
                scan_interval_hours=scan_interval_hours
            )
            # Iniciar escaneo periódico en thread separado
            self.baseline_manager.start_periodic_scanning()
            self.logger.info("log_event", message=f"✅ Baseline Manager inicializado para {base_url}")
        else:
            self.baseline_manager = None
    
    def _ensure_transformer_initialized(self):
        """
        FASE 7: Inicializa el transformer de forma lazy (solo cuando se necesite).
        Evita bloquear el inicio del servicio.
        """
        if self.transformer_initialized:
            return self.transformer_predictor is not None
        
        if not self.transformer_enabled:
            return False
        
        if self.transformer_predictor is not None:
            self.transformer_initialized = True
            return True
        
        try:
            import sys
            from pathlib import Path
            
            # Intentar múltiples rutas (local y GCP)
            transformer_paths = [
                Path(__file__).parent.parent / 'transformer-classifier',
                Path('/app/transformer-classifier'),
                Path(__file__).parent / 'transformer-classifier'
            ]
            transformer_path = None
            
            for path in transformer_paths:
                if path.exists() and (path / 'transformer_predictor.py').exists():
                    transformer_path = path
                    break
            
            if not transformer_path:
                self.logger.warning("log_event", message="FASE 7: Transformer no encontrado en ninguna ruta")
                self.transformer_initialized = True
                return False
            
            if str(transformer_path) not in sys.path:
                sys.path.insert(0, str(transformer_path))
            
            self.logger.info("log_event", message="FASE 7: Importando TransformerPredictor (puede tardar si descarga modelo)...")
            from transformer_predictor import TransformerPredictor
            
            # Actualizar MODELS_DIR
            if self.transformer_config['models_dir']:
                try:
                    import transformer_predictor
                    transformer_predictor.MODELS_DIR = Path(self.transformer_config['models_dir'])
                    transformer_predictor.MODELS_DIR.mkdir(exist_ok=True, parents=True)
                except Exception as e:
                    self.logger.warning("log_event", message=f"FASE 7: No se pudo actualizar MODELS_DIR: {e}")
            
            self.logger.info("log_event", message=f"FASE 7: Inicializando TransformerPredictor con modelo: {self.transformer_config['model']}")
            self.transformer_predictor = TransformerPredictor(
                model_name=self.transformer_config['model'],
                model_path=self.transformer_config['model_path'],
                use_onnx=True,
                confidence_threshold=self.transformer_config['confidence_threshold'],
                margin_threshold=self.transformer_config['margin_threshold']
            )
            self.logger.info("log_event", message=f"✅ Transformer Predictor inicializado: {self.transformer_config['model']}")
            self.transformer_initialized = True
            return True
            
        except Exception as e:
            self.logger.error("error_occurred", message=f"FASE 7: ❌ Error inicializando transformer: {e}", exc_info=True)
            self.transformer_predictor = None
            self.transformer_initialized = True
            return False
    
    def _initialize_consumer(self):
        """Inicializa el consumer de Kafka con reintentos"""
        max_retries = 5
        retry_delay = 5
        
        for attempt in range(max_retries):
            try:
                # Para topic patterns, necesitamos suscribir a múltiples topics
                # Por ahora, suscribirse a todos los topics que coincidan con el patrón
                topics = []
                
                # Si el patrón tiene *, intentar descubrir topics
                if '*' in self.topic_pattern:
                    # Por ahora, usar un topic específico o todos los waf-logs-*
                    # En producción, usar Kafka AdminClient para descubrir topics
                    base_topic = self.topic_pattern.replace('*', '')
                    # Usar el topic base o un topic específico
                    topics = [base_topic] if base_topic else ['waf-logs']
                else:
                    topics = [self.topic_pattern]
                
                self.consumer = KafkaConsumer(
                    *topics,
                    bootstrap_servers=self.kafka_brokers.split(','),
                    group_id=self.consumer_group,
                    value_deserializer=lambda m: json.loads(m.decode('utf-8')),
                    auto_offset_reset='earliest',  # Solo procesar logs nuevos
                    # FASE 2: Deshabilitar auto-commit, hacer commits manuales después de procesar
                    enable_auto_commit=False,
                    max_poll_records=100,  # Procesar en batches
                    consumer_timeout_ms=10000,  # Timeout más largo para polling
                    request_timeout_ms=40000,  # Timeout para requests (debe ser > session_timeout)
                    connections_max_idle_ms=540000,  # Mantener conexiones vivas
                    # FASE 2: Configuración mejorada de consumer
                    session_timeout_ms=30000,  # 30s timeout de sesión
                    heartbeat_interval_ms=10000,  # Heartbeat cada 10s
                    fetch_min_bytes=1,
                    fetch_max_wait_ms=500,
                )
                
                self.logger.info("log_event", message=f"✅ Kafka Consumer inicializado: topics={topics}, group={self.consumer_group}, brokers={self.kafka_brokers}")
                
                # PASO 2: Log de estado inicial (cold start) - verificar offsets
                try:
                    # Esperar un momento para que el consumer se registre con el broker
                    time.sleep(2)
                    partitions = self.consumer.assignment()
                    if partitions:
                        self.logger.info("log_event", message=f"📊 Consumer asignado a {len(partitions)} particiones")
                        for partition in partitions:
                            try:
                                position = self.consumer.position(partition)
                                self.logger.info("log_event", message=f"   Partition {partition}: offset actual = {position}")
                            except Exception as e:
                                self.logger.debug("log_event", message=f"   ⚠️ No se pudo obtener offset de {partition}: {e}")
                    else:
                        self.logger.info("log_event", message="📊 Consumer no tiene particiones asignadas aún (esperando rebalance)")
                except Exception as e:
                    self.logger.debug("log_event", message=f"⚠️ No se pudieron verificar offsets iniciales (normal en cold start): {e}")
                
                # Inicializar Producer para enviar decisiones de mitigación
                if self.send_to_mitigation:
                    self.producer = KafkaProducer(
                        bootstrap_servers=self.kafka_brokers.split(','),
                        value_serializer=lambda v: json.dumps(v).encode('utf-8'),
                        acks=1,
                        compression_type='gzip',  # Cambiado de snappy a gzip (más compatible)
                        request_timeout_ms=40000
                    )
                    self.logger.info("log_event", message=f"✅ Kafka Producer inicializado: topic={self.threats_topic}")
                
                return  # Éxito, salir del loop
                
            except Exception as e:
                if attempt < max_retries - 1:
                    self.logger.warning("log_event", message=f"⚠️ Intento {attempt + 1}/{max_retries} falló al conectar a Kafka: {e}. Reintentando en {retry_delay}s...")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Backoff exponencial
                else:
                    self.logger.error("error_occurred", message=f"❌ Error inicializando Kafka Consumer después de {max_retries} intentos: {e}")
                    raise
    
    def _init_postgres(self):
        """Inicializa conexión a PostgreSQL (soporta Cloud SQL Unix socket) con reintentos"""
        max_retries = 3
        retry_delay = 5
        
        for attempt in range(max_retries):
            try:
                postgres_host = os.getenv('POSTGRES_HOST', 'postgres')
                postgres_port = int(os.getenv('POSTGRES_PORT', '5432'))
                
                # Si POSTGRES_HOST comienza con /cloudsql/PROJECT_ID:REGION:INSTANCE_NAME'dbname': os.getenv('POSTGRES_DB', 'soc_ai'),
                        'user': os.getenv('POSTGRES_USER', 'soc_user'),
                        "password": os.getenv("POSTGRES_PASSWORD", "YOUR_POSTGRES_PASSWORD")),
                        'host': postgres_host,  # Directorio del socket Unix
                        'connect_timeout': 30  # Timeout más largo para Cloud SQL
                    }
                    self.postgres_conn = psycopg2.connect(**connection_params)
                    self.logger.info("log_event", message=f"✅ PostgreSQL conectado vía socket Unix: {postgres_host[:50]}...")
                    
                    # Aplicar migración de learning_history si no existe
                    try:
                        cursor = self.postgres_conn.cursor()
                        cursor.execute("""
                            CREATE TABLE IF NOT EXISTS learning_history (
                                id SERIAL PRIMARY KEY,
                                retrain_timestamp TIMESTAMP DEFAULT NOW(),
                                labels_used INTEGER NOT NULL,
                                labels_since_last INTEGER NOT NULL,
                                retrain_threshold INTEGER NOT NULL,
                                success BOOLEAN DEFAULT FALSE,
                                accuracy_before REAL,
                                accuracy_after REAL,
                                improvement REAL,
                                error_message TEXT,
                                model_version VARCHAR(50),
                                training_duration_seconds REAL
                            )
                        """)
                        cursor.execute("""
                            CREATE INDEX IF NOT EXISTS idx_learning_history_timestamp 
                            ON learning_history(retrain_timestamp DESC)
                        """)
                        cursor.execute("""
                            CREATE INDEX IF NOT EXISTS idx_learning_history_success 
                            ON learning_history(success, retrain_timestamp DESC)
                        """)
                        self.postgres_conn.commit()
                        cursor.close()
                        self.logger.info("log_event", message="✅ Tabla learning_history verificada/creada")
                    except Exception as e:
                        self.logger.warning("error_occurred", message=f"Error creando tabla learning_history: {e}")
                        if self.postgres_conn:
                            self.postgres_conn.rollback()
                    
                    return
                else:
                    # Conexión TCP normal
                    self.postgres_conn = psycopg2.connect(
                        host=postgres_host,
                        port=postgres_port,
                        database=os.getenv('POSTGRES_DB', 'soc_ai'),
                        user=os.getenv('POSTGRES_USER', 'soc_user'),
                        password = os.getenv("POSTGRES_PASSWORD", "YOUR_POSTGRES_PASSWORD")),
                        connect_timeout=30
                    )
                    self.logger.info("log_event", message=f"✅ PostgreSQL conectado vía TCP: {postgres_host}:{postgres_port}")
                    
                    # Aplicar migración de learning_history si no existe
                    try:
                        cursor = self.postgres_conn.cursor()
                        cursor.execute("""
                            CREATE TABLE IF NOT EXISTS learning_history (
                                id SERIAL PRIMARY KEY,
                                retrain_timestamp TIMESTAMP DEFAULT NOW(),
                                labels_used INTEGER NOT NULL,
                                labels_since_last INTEGER NOT NULL,
                                retrain_threshold INTEGER NOT NULL,
                                success BOOLEAN DEFAULT FALSE,
                                accuracy_before REAL,
                                accuracy_after REAL,
                                improvement REAL,
                                error_message TEXT,
                                model_version VARCHAR(50),
                                training_duration_seconds REAL
                            )
                        """)
                        cursor.execute("""
                            CREATE INDEX IF NOT EXISTS idx_learning_history_timestamp 
                            ON learning_history(retrain_timestamp DESC)
                        """)
                        cursor.execute("""
                            CREATE INDEX IF NOT EXISTS idx_learning_history_success 
                            ON learning_history(success, retrain_timestamp DESC)
                        """)
                        self.postgres_conn.commit()
                        cursor.close()
                        self.logger.info("log_event", message="✅ Tabla learning_history verificada/creada")
                    except Exception as e:
                        self.logger.warning("error_occurred", message=f"Error creando tabla learning_history: {e}")
                        if self.postgres_conn:
                            self.postgres_conn.rollback()
                    
                    return
            except Exception as e:
                if attempt < max_retries - 1:
                    self.logger.warning("log_event", message=f"⚠️ Intento {attempt + 1}/{max_retries} falló al conectar a PostgreSQL: {e}. Reintentando en {retry_delay}s...")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Backoff exponencial
                else:
                    self.logger.error("error_occurred", message=f"Error conectando a PostgreSQL después de {max_retries} intentos: {e}")
                    self.logger.warning("log_event", message="PostgreSQL deshabilitado, continuando sin persistencia")
                    self.postgres_enabled = False
                    self.postgres_conn = None
    
    def _process_log(self, log: Dict[str, Any], kafka_metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Procesa un log individual con sistema híbrido activo.
        
        Pipeline Híbrido Activo:
        1. Random Forest Prediction (modelo principal)
        2. Si hay duda (confianza baja): consultar KNN y KMeans
        3. Si sigue habiendo duda: consultar LLM para tipo de ataque
        4. Pattern Detection (ventana deslizante)
        5. Lógica de bloqueo: solo 403 = blocked, ataques no bloqueados → revisar → mitigar
        
        Args:
            log: Log a procesar
            kafka_metadata: Metadata de Kafka (topic, partition, offset) para actualizar el log en PostgreSQL
        """
        # Guardar metadata de Kafka en el log para usarla en _save_to_postgres
        if kafka_metadata:
            log['_kafka_metadata'] = kafka_metadata
        
        # NUEVO: ETAPA 0 - Threat Intelligence Check (PRE-FILTRO rápido)
        ip = log.get('ip') or log.get('remote_addr') or 'unknown'
        if ip != 'unknown' and self.threat_intel and ImprovementsConfig.ENABLE_THREAT_INTELLIGENCE:
            try:
                reputation = self.threat_intel.check_ip_reputation_sync(ip)
                log['_threat_intel'] = reputation
                
                # Si IP es conocidamente maliciosa → bloqueo inmediato
                if reputation.get('recommendation') == 'BLOCK':
                    self.logger.warning("log_event", message=f"🚫 IP maliciosa detectada: {ip} (score: {reputation.get('reputation_score', 0)})")
                    return {
                        'action': 'block_ip',
                        'reason': f"Known malicious IP (reputation score: {reputation.get('reputation_score', 0)})",
                        'threat_type': 'KNOWN_MALICIOUS_IP',
                        'severity': 'high',
                        'classification_source': 'threat_intelligence',
                        'threat_intel': reputation,
                        'log': log
                    }
            except Exception as e:
                self.logger.warning("error_occurred", message=f"Error en threat intelligence para {ip}: {e}")
                # Continuar con pipeline normal si falla
        
        # OPTIMIZACIÓN CRÍTICA: Verificar si IP está bloqueada ANTES de procesar (ahorra CPU/ML/LLM)
        if ip != 'unknown' and self.blocked_ip_cache and self.blocked_ip_cache.is_blocked(ip):
            self.logger.debug("log_event", message=f"⏭️ IP {ip} ya bloqueada, omitiendo procesamiento (ahorro: ML/LLM/EpisodeBuilder)")
            self.metrics['blocked_ips_skipped'] = self.metrics.get('blocked_ips_skipped', 0) + 1
            return {
                'action': 'skip',
                'reason': 'ip_already_blocked',
                'ip': ip,
                'log': log  # Preservar log para logging
            }
        
        # NUEVO: ETAPA 0.5 - Deobfuscation Engine (ANTES de extraer features para ML/LLM)
        if self.deobfuscation_engine and ImprovementsConfig.ENABLE_DEOBFUSCATION:
            try:
                uri = log.get('uri', '') or log.get('request_uri', '')
                query = log.get('query_string', '') or ''
                
                # Desobfuscar URI
                if uri:
                    deobf_result = self.deobfuscation_engine.deobfuscate(uri)
                    if deobf_result.get('is_obfuscated'):
                        log['_original_uri'] = uri
                        log['uri'] = deobf_result.get('max_decoded', uri)
                        log['_deobfuscation_info_uri'] = deobf_result
                        self.logger.warning("log_event", message=f"🔓 Payload ofuscado detectado en URI: {deobf_result.get('techniques_detected', [])}")
                
                # Desobfuscar query
                if query:
                    deobf_result = self.deobfuscation_engine.deobfuscate(query)
                    if deobf_result.get('is_obfuscated'):
                        log['_original_query'] = query
                        log['query_string'] = deobf_result.get('max_decoded', query)
                        if '_deobfuscation_info_query' not in log:
                            log['_deobfuscation_info'] = {}
                        log['_deobfuscation_info_query'] = deobf_result
                        # NUEVO: Si detecta ofuscación, marcar como amenaza para que se bloquee/rate limite
                        log['_obfuscation_detected'] = True
                        log['_obfuscation_severity'] = 'high' if deobf_result.get('obfuscation_layers', 0) >= 3 else 'medium'
                        self.logger.warning("log_event", message=f"🔓 Payload ofuscado detectado en query: {deobf_result.get('techniques_detected', [])} - {deobf_result.get('obfuscation_layers', 0)} capas")
            except Exception as e:
                self.logger.warning("error_occurred", message=f"Error en deobfuscation: {e}")
                # Continuar con pipeline normal si falla
        
        result = {
            'log': log,
            'ml_prediction': None,
            'transformer_prediction': None,  # FASE 7
            'knn_prediction': None,
            'kmeans_prediction': None,
            'llm_analysis': None,
            'patterns': [],
            'action': 'log_only',
            'threat_type': None,
            'classification_source': 'ml',
            'has_doubt': False
        }
        
        try:
            # CRÍTICO: ETAPA 0 - Detectar threat_type PRIMERO (antes de agregar al episodio)
            # Esto asegura que el episodio tenga threat_type cuando se cierre
            heuristic_result = self._detect_suspicious_patterns_heuristic(log)
            if heuristic_result and heuristic_result.get('threat_type'):
                # Patrón obvio detectado - copiar threat_type al log ANTES de agregar al episodio
                threat_type = heuristic_result['threat_type']
                log['threat_type'] = threat_type
                result['threat_type'] = threat_type
                result['classification_source'] = 'heuristic'
                result['severity'] = heuristic_result.get('severity', 'medium')
                result['action'] = heuristic_result.get('action', 'monitor')
                
                # CRÍTICO: Si es un ataque detectado por heurísticas y NO fue bloqueado por WAF (status != 403),
                # establecer needs_mitigation = True para enviarlo inmediatamente a bloqueo
                status = log.get('status', 200)
                if isinstance(status, str):
                    try:
                        status = int(status)
                    except:
                        status = 200
                is_waf_blocked = (status == 403)
                
                # Si es un ataque crítico (PATH_TRAVERSAL, SQLI, XSS, etc.) y NO fue bloqueado por WAF,
                # enviarlo inmediatamente a mitigación para bloquear la IP
                if result['action'] == 'block_ip' and not is_waf_blocked:
                    result['needs_mitigation'] = True
                    result['mitigation_reason'] = f"Ataque {threat_type} detectado por heurísticas (status={status}, no bloqueado por WAF) - bloqueo automático requerido"
                    self.logger.warning("log_event", message=f"🚨 ATAQUE NO BLOQUEADO POR WAF: IP={log.get('ip')}, Threat={threat_type}, Status={status}, "
                                 f"URI={log.get('uri')} - Enviando a mitigación inmediata")
                
                # Clasificar según OWASP Top 10
                from owasp_threat_classifier import classify_by_owasp_top10
                owasp_info = classify_by_owasp_top10(threat_type)
                result['owasp_code'] = owasp_info.get('owasp_code')
                result['owasp_category'] = owasp_info.get('owasp_category')
            
            # NUEVO: Agregar log a episodio DESPUÉS de detectar threat_type (si está disponible)
            # Esto asegura que el episodio tenga threat_type cuando se cierre
            if self.episode_enabled and self.episode_builder:
                closed_episode = self.episode_builder.add_log(log)
                if closed_episode:
                    # Episodio cerrado, procesarlo en thread separado
                    threading.Thread(
                        target=self._process_episode,
                        daemon=True,
                        args=(closed_episode,),
                        name="ProcessEpisode"
                    ).start()
            
            # ETAPA 1: Continuar con procesamiento heurístico (si se detectó threat_type)
            if heuristic_result and heuristic_result.get('threat_type'):
                # Si ya se procesó antes, asegurar que result tenga los datos correctos
                if not result.get('threat_type'):
                    threat_type = heuristic_result['threat_type']
                    log['threat_type'] = threat_type
                    result['threat_type'] = threat_type
                    result['classification_source'] = 'heuristic'
                    result['severity'] = heuristic_result.get('severity', 'medium')
                    result['action'] = heuristic_result.get('action', 'monitor')
                    
                    # CRÍTICO: Si es un ataque detectado por heurísticas y NO fue bloqueado por WAF,
                    # establecer needs_mitigation = True para enviarlo inmediatamente a bloqueo
                    status = log.get('status', 200)
                    if isinstance(status, str):
                        try:
                            status = int(status)
                        except:
                            status = 200
                    is_waf_blocked = (status == 403)
                    
                    if result['action'] == 'block_ip' and not is_waf_blocked:
                        result['needs_mitigation'] = True
                        result['mitigation_reason'] = f"Ataque {threat_type} detectado por heurísticas (status={status}, no bloqueado por WAF) - bloqueo automático requerido"
                        self.logger.warning("log_event", message=f"🚨 ATAQUE NO BLOQUEADO POR WAF: IP={log.get('ip')}, Threat={threat_type}, Status={status}, "
                                     f"URI={log.get('uri')} - Enviando a mitigación inmediata")
                    
                    # Clasificar según OWASP Top 10
                    from owasp_threat_classifier import classify_by_owasp_top10
                    owasp_info = classify_by_owasp_top10(threat_type)
                    result['owasp_code'] = owasp_info.get('owasp_code')
                    result['owasp_category'] = owasp_info.get('owasp_category')
                
                # Verificar status si no se hizo antes
                if 'is_waf_blocked' not in locals():
                    status = log.get('status', 200)
                    if isinstance(status, str):
                        try:
                            status = int(status)
                        except:
                            status = 200
                    is_waf_blocked = (status == 403)
                
                # NUEVO: También analizar logs bloqueados por WAF si muestran patrón de escaneo agresivo
                # Esto permite bloquear IPs permanentemente aunque el WAF ya esté bloqueando requests individuales
                ip = log.get('ip', 'unknown')
                should_track_waf_blocked = False
                
                if is_waf_blocked and ip != 'unknown' and ip:
                    # Si es un escaneo (SCAN_PROBE) bloqueado por WAF, también rastrearlo
                    # para poder bloquear la IP permanentemente después de múltiples intentos
                    threat_type = heuristic_result.get('threat_type', '')
                    uri = (log.get('uri') or log.get('request_uri') or '').lower()
                    
                    # Detectar escaneo basándose en:
                    # 1. Threat type explícito de SCAN_PROBE
                    # 2. Patrones de escaneo en URI (números secuenciales, paths comunes de escaneo)
                    # 3. Múltiples 403s en poco tiempo (se detectará en el buffer)
                    is_scan_pattern = (
                        threat_type in ['SCAN_PROBE', 'MULTIPLE_ATTACKS'] or 
                        'scan' in threat_type.lower() or
                        # Detectar patrones de escaneo: números secuenciales, paths comunes
                        any(pattern in uri for pattern in ['/wp-admin', '/wp-content', '/wp-includes', '/admin', '/phpmyadmin', '/.env', '/config']) or
                        # Detectar escaneo numérico (ej: /2001, /2002, /2003)
                        (uri and uri.replace('/', '').isdigit() and len(uri.replace('/', '')) >= 3)
                    )
                    
                    if is_scan_pattern:
                        should_track_waf_blocked = True
                        self.logger.debug("log_event", message=f"📊 Rastreando log bloqueado por WAF de IP {ip} (patrón: {threat_type}, URI: {uri}) para análisis de bloqueo permanente")
                
                # NUEVO: También agregar logs con SCAN_PROBE aunque no estén bloqueados por WAF
                # Esto permite detectar escaneos incluso cuando el WAF no los bloquea
                original_threat_type = log.get('threat_type', '') or ''
                original_threat_type_upper = str(original_threat_type).upper().strip()
                heuristic_threat_type = heuristic_result.get('threat_type', '') if heuristic_result else ''
                
                is_scan_probe = (
                    original_threat_type_upper == 'SCAN_PROBE' or 
                    heuristic_threat_type == 'SCAN_PROBE' or
                    'SCAN_PROBE' in original_threat_type_upper or
                    'SCAN_PROBE' in str(heuristic_threat_type).upper()
                )
                
                # DEBUG: Log para diagnosticar
                if is_scan_probe:
                    self.logger.info("log_event", message=f"🔍 SCAN_PROBE detectado para IP {ip}: original='{original_threat_type_upper}', heuristic='{heuristic_threat_type}', status={status}")
                
                if not is_waf_blocked or should_track_waf_blocked or is_scan_probe:
                    # Ataque detectado (bloqueado o no) → agregar a buffer por IP para análisis por lotes
                    # O es un SCAN_PROBE (aunque no esté bloqueado por WAF)
                    if ip != 'unknown' and ip:
                        suspicious_entry = {
                            'log': log,
                            'kafka_metadata': kafka_metadata,
                            'heuristic_result': heuristic_result,
                            'timestamp': time.time(),
                            'waf_blocked': is_waf_blocked  # Marcar si fue bloqueado por WAF
                        }
                        
                        with self.ip_buffer_lock:
                            if ip not in self.ip_suspicious_buffer:
                                self.ip_suspicious_buffer[ip] = []
                            self.ip_suspicious_buffer[ip].append(suspicious_entry)
                            
                            # NUEVO: Bloqueo inmediato para escaneos agresivos
                            # Contar SCAN_PROBE en el buffer (incluyendo los bloqueados por WAF)
                            # Contar tanto de heuristic_result como del log original
                            scan_probe_count = 0
                            for e in self.ip_suspicious_buffer[ip]:
                                log_entry = e.get('log', {})
                                heuristic_entry = e.get('heuristic_result', {})
                                log_threat = str(log_entry.get('threat_type', '') or '').upper().strip()
                                heuristic_threat = str(heuristic_entry.get('threat_type', '') or '').upper().strip()
                                if log_threat == 'SCAN_PROBE' or heuristic_threat == 'SCAN_PROBE' or 'SCAN_PROBE' in log_threat or 'SCAN_PROBE' in heuristic_threat:
                                    scan_probe_count += 1
                            
                            # DEBUG: Log el conteo
                            if scan_probe_count > 0:
                                self.logger.info("log_event", message=f"📊 IP {ip}: {scan_probe_count} SCAN_PROBE detectados en buffer (total entries: {len(self.ip_suspicious_buffer[ip])})")
                            
                            # También contar logs bloqueados por WAF que muestren escaneo agresivo
                            # Incluir cualquier log bloqueado por WAF (403) como indicador de escaneo
                            # si hay múltiples en poco tiempo
                            waf_blocked_scan_count = sum(1 for e in self.ip_suspicious_buffer[ip] 
                                                         if e.get('waf_blocked', False))
                            
                            # Si hay muchos 403s bloqueados por WAF en poco tiempo, es un escaneo agresivo
                            waf_blocked_threshold = 3  # 3+ requests bloqueados = escaneo agresivo (MUY agresivo para detección inmediata)
                            if waf_blocked_scan_count >= waf_blocked_threshold:
                                self.logger.warning("log_event", message=f"🚨 IP {ip} tiene {waf_blocked_scan_count} requests bloqueados por WAF, considerando como escaneo agresivo")
                            
                            # NOTA IMPORTANTE: Ya NO bloqueamos automáticamente aquí.
                            # TODAS las decisiones de bloqueo las toma el LLM de forma inteligente
                            # después de analizar el contexto completo en el análisis por lotes.
                            # El bloqueo inmediato por umbrales ha sido eliminado para que el LLM
                            # pueda hacer análisis sofisticado considerando múltiples factores.
                            
                            # DESACTIVADO: La lógica antigua de batch_analysis ha sido REEMPLAZADA por episodios
                            # Los logs se agregan a episodios y las decisiones se toman en _process_episode()
                            # No hacer análisis por lotes aquí, solo agregar a episodios
                            if len(self.ip_suspicious_buffer[ip]) >= self.ip_buffer_threshold:
                                self.logger.debug("log_event", message=f"📊 IP {ip} tiene {len(self.ip_suspicious_buffer[ip])} logs sospechosos (se procesarán en episodios, no batch analysis)")
                            
                            # Limpiar buffers antiguos periódicamente
                            if len(self.ip_suspicious_buffer) > 100:  # Limpiar si hay muchos buffers
                                self._cleanup_old_ip_buffers()
                    
                    # Continuar con procesamiento normal (guardar resultado heurístico)
                    self.logger.info("log_event", message=f"🔍 Patrón heurístico detectado: {heuristic_result['threat_type']} (no bloqueado), agregado a buffer por IP")
                else:
                    # Ya bloqueado por WAF, usar clasificación heurística directamente
                    result['log'] = log
                    result['_log_start_time'] = time.time()
                    if self.postgres_enabled:
                        self._save_to_postgres(log, result, kafka_metadata)
                    return result
                
                # Continuar con guardado del log (incluso si se agregó al buffer)
                result['log'] = log
                result['_log_start_time'] = time.time()
                if self.postgres_enabled:
                    self._save_to_postgres(log, result, kafka_metadata)
                return result
            
            # Verificar si ya fue bloqueado por WAF (SOLO 403 = blocked)
            status = log.get('status', 200)
            if isinstance(status, str):
                try:
                    status = int(status)
                except:
                    status = 200
            # Solo 403 significa que el WAF bloqueó
            is_waf_blocked = (status == 403)
            
            # FASE 7: Tracking de latencia end-to-end
            log_start_time = time.time()
            
            # 1. Random Forest Prediction (modelo principal)
            ml_start = time.time()
            ml_pred = self.ml_predictor.predict(log, model_id=None)  # Usa default (Random Forest si está disponible)
            ml_latency = (time.time() - ml_start) * 1000
            result['ml_prediction'] = ml_pred
            self.metrics['ml_predictions'] += 1
            self.metrics['ml_latency_ms'].append(ml_latency)
            
            threat_score = ml_pred.get('threat_score', 0) or 0
            confidence = ml_pred.get('confidence', 0.5) or 0.5
            predicted_severity = ml_pred.get('predicted_severity', 'low') or 'low'
            
            # Asegurar que son números
            try:
                threat_score = float(threat_score) if threat_score is not None else 0.0
                confidence = float(confidence) if confidence is not None else 0.5
            except (ValueError, TypeError):
                threat_score = 0.0
                confidence = 0.5
            
            # Detectar duda: confianza baja del ML
            # O si es un ataque no bloqueado por WAF (necesita clasificación LLM)
            has_doubt = (confidence < self.doubt_threshold)
            is_unblocked_attack = ((threat_score or 0) > 0.6 and not is_waf_blocked)
            result['has_doubt'] = has_doubt
            result['is_unblocked_attack'] = is_unblocked_attack
            
            # PASO 3 - COLAPSO COGNITIVO: NO ejecutar Transformer/LLM aquí
            # Se ejecutarán SOLO en episodios cuando sea necesario (decision=UNCERTAIN)
            # Esto evita ejecuciones innecesarias y reduce costos
            transformer_pred = None
            # REMOVIDO: Ejecución de Transformer en log individual
            # Se ejecutará en episodio si es necesario
            if False:  # Deshabilitado - se ejecutará en episodio si necesario
                # Inicializar transformer de forma lazy si no está inicializado
                if self._ensure_transformer_initialized() and self.transformer_predictor:
                    try:
                        transformer_start = time.time()
                        transformer_pred = self.transformer_predictor.predict(log)
                        transformer_latency = (time.time() - transformer_start) * 1000
                        result['transformer_prediction'] = transformer_pred
                        self.metrics['transformer_predictions'] += 1
                        self.metrics['fallback_to_transformer'] += 1
                        self.metrics['transformer_latency_ms'].append(transformer_latency)
                        
                        if transformer_pred and transformer_pred.get('success'):
                            # Usar predicción del transformer si es confiable
                            transformer_confidence = transformer_pred.get('confidence', 0.0)
                            transformer_is_threat = transformer_pred.get('is_threat', False)
                            transformer_is_uncertain = transformer_pred.get('is_uncertain', False)
                            
                            # Si transformer tiene alta confianza, usarlo
                            if transformer_confidence > confidence and not transformer_is_uncertain:
                                threat_score = 0.9 if transformer_is_threat else 0.1
                                confidence = transformer_confidence
                                predicted_severity = transformer_pred.get('prediction', 'low')
                                result['classification_source'] = 'transformer'
                                
                                # Obtener threat_type del transformer si está disponible
                                if transformer_pred.get('threat_type'):
                                    threat_type = transformer_pred['threat_type']
                                    result['threat_type'] = threat_type
                                    # Copiar threat_type al log (puede haber episodios activos)
                                    log['threat_type'] = threat_type
                                    # Clasificar según OWASP Top 10
                                    owasp_info = classify_by_owasp_top10(threat_type)
                                    result['owasp_code'] = owasp_info.get('owasp_code')
                                    result['owasp_category'] = owasp_info.get('owasp_category')
                                
                                has_doubt = False  # Transformer resolvió la duda
                                self.logger.debug("log_event", message=f"Transformer resolvió duda: confianza={transformer_confidence:.3f}")
                            elif transformer_is_uncertain:
                                # Transformer también tiene duda, mantener has_doubt=True para LLM
                                has_doubt = True
                                self.logger.debug("log_event", message=f"Transformer también tiene duda, consultando LLM")
                    except Exception as e:
                        self.logger.warning("error_occurred", message=f"Error en predicción transformer: {e}")
                        transformer_pred = None
            
            # 3. Si aún hay duda, consultar modelos de respaldo (KNN, KMeans)
            if has_doubt and (self.use_knn or self.use_kmeans):
                backup_predictions = []
                
                if self.use_knn:
                    try:
                        knn_pred = self.ml_predictor.predict(log, model_id='knn')
                        if knn_pred and knn_pred.get('model_id', '').startswith('knn'):
                            result['knn_prediction'] = knn_pred
                            backup_predictions.append(knn_pred)
                    except Exception as e:
                        self.logger.debug("log_event", message=f"KNN no disponible: {e}")
                
                if self.use_kmeans:
                    try:
                        kmeans_pred = self.ml_predictor.predict(log, model_id='kmeans')
                        if kmeans_pred and kmeans_pred.get('model_id', '').startswith('kmeans'):
                            result['kmeans_prediction'] = kmeans_pred
                            backup_predictions.append(kmeans_pred)
                    except Exception as e:
                        self.logger.debug("log_event", message=f"KMeans no disponible: {e}")
                
                # Si hay predicciones de respaldo, promediar
                if backup_predictions:
                    avg_threat_score = sum((p.get('threat_score', 0) or 0) for p in backup_predictions) / len(backup_predictions)
                    try:
                        avg_threat_score = float(avg_threat_score) if avg_threat_score is not None else 0.0
                    except (ValueError, TypeError):
                        avg_threat_score = 0.0
                    if avg_threat_score > threat_score:
                        threat_score = avg_threat_score
                        result['classification_source'] = 'hybrid_ml'
            
            # NUEVO: Si detectamos ofuscación, aumentar threat_score ANTES de anomaly detection
            if log.get('_obfuscation_detected'):
                obfuscation_severity = log.get('_obfuscation_severity', 'medium')
                if obfuscation_severity == 'high':
                    threat_score = max(threat_score, 0.85)  # Alta ofuscación = alto riesgo
                else:
                    threat_score = max(threat_score, 0.70)  # Ofuscación media = riesgo moderado-alto
                self.logger.debug("log_event", message=f"🔓 Ofuscación detectada, threat_score aumentado a {threat_score:.2f}")
            
            # NUEVO: Anomaly Detection (Zero-Day Detection) - después de ML, antes de LLM
            anomaly_result = None
            if self.zero_day_detector and ImprovementsConfig.ENABLE_ANOMALY_DETECTION:
                try:
                    # Contexto para anomaly detection
                    context = {
                        'request_rate': threat_score * 10  # Aproximación
                    }
                    anomaly_result = self.zero_day_detector.detect_anomaly(log, context=context)
                    result['anomaly_detection'] = anomaly_result
                    
                    # Si es zero-day candidate, incrementar threat_score
                    if anomaly_result.get('is_zero_day_candidate'):
                        anomaly_confidence = anomaly_result.get('confidence', 0.0)
                        threat_score = max(threat_score, anomaly_confidence * 0.9)  # Ajustar threat_score
                        self.logger.warning("log_event", message=f"🔍 Zero-day candidate detectado: IP={ip}, confidence={anomaly_confidence:.2f}")
                        result['threat_type'] = result.get('threat_type') or 'ZERO_DAY_CANDIDATE'
                        result['classification_source'] = 'anomaly_detection'
                except Exception as e:
                    self.logger.warning("error_occurred", message=f"Error en anomaly detection: {e}")
                    anomaly_result = None
            
            # PASO 3 - COLAPSO COGNITIVO: NO ejecutar LLM aquí en logs individuales
            # Se ejecutará SOLO en episodios cuando decision=UNCERTAIN
            # Esto reduce dramáticamente las llamadas a LLM y reduce costos
            # Exception: Zero-day candidates aún se pueden consultar aquí si es crítico
            should_consult_llm = False
            llm_analysis = None
            
            # SOLO consultar LLM individual si es zero-day candidate (crítico)
            if anomaly_result and anomaly_result.get('is_zero_day_candidate'):
                # Zero-day es crítico, mantener consulta inmediata
                should_consult_llm = True
                self.logger.warning("log_event", message=f"🚨 Zero-day candidate detectado, consultando LLM inmediatamente")
            
            if should_consult_llm and self.enable_llm:
                self.metrics['fallback_to_llm'] += 1
                llm_start = time.time()
                llm_analysis = self.llm_analyzer.analyze(log, ml_pred)
                llm_latency = (time.time() - llm_start) * 1000
                result['llm_analysis'] = llm_analysis
                self.metrics['llm_analyses'] += 1
                self.metrics['llm_latency_ms'].append(llm_latency)
                
                if llm_analysis.get('analyzed'):
                    # LLM proporciona tipo de ataque y clasificación
                    llm_threat_type = llm_analysis.get('threat_type')
                    llm_severity = llm_analysis.get('severity', predicted_severity)
                    llm_action = llm_analysis.get('action', 'monitor')
                    
                    # Solo usar LLM si proporcionó un threat_type válido (no NONE)
                    if llm_threat_type and llm_threat_type != 'NONE':
                        result['threat_type'] = llm_threat_type
                        # Copiar threat_type al log (puede haber episodios activos)
                        log['threat_type'] = llm_threat_type
                        result['severity'] = llm_severity
                        result['action'] = llm_action
                        result['classification_source'] = 'llm'
                        
                        # OWASP code puede venir directamente del LLM o clasificarlo
                        if llm_analysis.get('owasp_code'):
                            result['owasp_code'] = llm_analysis.get('owasp_code')
                            result['owasp_category'] = llm_analysis.get('owasp_category')
                        else:
                            # Clasificar según OWASP Top 10 si no viene del LLM
                            owasp_info = classify_by_owasp_top10(llm_threat_type)
                            result['owasp_code'] = owasp_info.get('owasp_code')
                            result['owasp_category'] = owasp_info.get('owasp_category')
                        
                        # Guardar en buffer de aprendizaje continuo para re-entrenar modelo
                        self._add_to_learning_buffer(log, llm_analysis)
                    else:
                        # LLM dice que no es ataque, usar predicción ML
                        result['threat_type'] = None
                        result['severity'] = predicted_severity
                        result['classification_source'] = 'ml'
            else:
                # PASO 3: Sin LLM consultado, usar predicción ML directamente
                # Marcar para análisis en episodio si es necesario
                result['_needs_episode_analysis'] = (has_doubt and threat_score > 0.3) or is_unblocked_attack
                
                # Sin duda o sin LLM consultado, usar predicción ML directamente
                result['severity'] = predicted_severity
                if (threat_score or 0) > 0.8:
                    result['action'] = 'block_ip'
                    result['severity'] = 'high'
                elif (threat_score or 0) > 0.6:
                    result['action'] = 'monitor'
                    result['severity'] = 'medium'
                else:
                    result['action'] = 'log_only'
                    result['severity'] = 'low'
            
            # 4. Pattern Detection
            if self.enable_pattern_detection:
                patterns = self.pattern_detector.add_event(log)
                result['patterns'] = patterns
                self.metrics['patterns_detected'] += len(patterns)
                
                # Si se detecta un patrón crítico, actualizar acción
                for pattern in patterns:
                    if pattern.get('severity') == 'high':
                        if result['action'] == 'log_only':
                            result['action'] = 'monitor'
                        elif result['action'] == 'monitor':
                            result['action'] = 'block_ip'
                        result['severity'] = 'high'
                        break
            
            # 5. Lógica de bloqueo: solo 403 = blocked
            # Si es ataque y no fue bloqueado por WAF, aplicar mitigación
            if result['action'] == 'block_ip' and not is_waf_blocked:
                # Este log será enviado a mitigation service para aplicar bloqueo
                result['needs_mitigation'] = True
                result['mitigation_reason'] = f"Ataque detectado ({result.get('threat_type', 'UNKNOWN')}) no bloqueado por WAF"
            
            # Guardar tiempo de inicio en el result para latencia end-to-end
            result['_log_start_time'] = log_start_time
            result['log'] = log  # Asegurar que el log esté en el result
            
            # Asegurar clasificación OWASP si hay threat_type pero no owasp_code
            if result.get('threat_type') and not result.get('owasp_code'):
                owasp_info = classify_by_owasp_top10(result['threat_type'])
                result['owasp_code'] = owasp_info.get('owasp_code')
                result['owasp_category'] = owasp_info.get('owasp_category')
            
            # NUEVO: Agregar log a ventana temporal para análisis SOC-level
            if self.time_window_analyzer.add_log(log, result):
                # Analizar ventana en thread separado (no bloquea pipeline principal)
                threading.Thread(
                    target=self._analyze_time_window_async,
                    daemon=True,
                    name="TimeWindowAnalysis"
                ).start()
            
            # Guardar en PostgreSQL
            if self.postgres_enabled:
                # Extraer metadata de Kafka si está disponible
                kafka_metadata = log.get('_kafka_metadata')
                self._save_to_postgres(log, result, kafka_metadata)
            
            return result
            
        except Exception as e:
            self.logger.error("error_procesando_log", error=str(e), exc_info=True)
            result['error'] = str(e)
            return result
    
    def _add_to_learning_buffer(self, log: Dict[str, Any], llm_analysis: Dict[str, Any]):
        """Agrega log clasificado por LLM al buffer de aprendizaje"""
        with self.learning_buffer_lock:
            learning_entry = {
                'log': log,
                'threat_type': llm_analysis.get('threat_type'),
                'severity': llm_analysis.get('severity', 'low'),
                'action': llm_analysis.get('action', 'log_only'),
                'timestamp': datetime.now().isoformat(),
                'source': 'llm'
            }
            self.learning_buffer.append(learning_entry)
            
            # Si el buffer está lleno, intentar re-entrenar
            if len(self.learning_buffer) >= self.learning_buffer_size:
                self.logger.info("component_starting", message=f"Buffer de aprendizaje lleno ({len(self.learning_buffer)}), iniciando re-entrenamiento...")
                threading.Thread(target=self._trigger_retrain, daemon=True).start()
    
    def _save_to_postgres(self, log: Dict[str, Any], result: Dict[str, Any], kafka_metadata: Optional[Dict[str, Any]] = None):
        """
        Actualiza el log en PostgreSQL con las clasificaciones ML/Transformer/LLM.
        Usa kafka_topic, kafka_partition, kafka_offset para identificar el log único.
        """
        if not self.postgres_conn:
            return
        
        try:
            cursor = self.postgres_conn.cursor()
            
            # Extraer datos del log
            raw_log = log.get('raw_log')
            if isinstance(raw_log, str):
                try:
                    raw_log = json.loads(raw_log)
                except Exception:
                    raw_log = {}
            elif not isinstance(raw_log, dict):
                raw_log = {}
            ip = log.get('ip', '')
            uri = log.get('uri', '') or raw_log.get('uri', '')
            method = log.get('method', 'GET') or raw_log.get('method', 'GET')
            status = log.get('status', 200) or raw_log.get('status', 200)
            user_agent = log.get('user_agent', '') or raw_log.get('user_agent', '')
            referer = log.get('referer', '') or raw_log.get('referer', '')
            
            # Determinar si está bloqueado (SOLO 403 = blocked por WAF)
            if isinstance(status, str):
                try:
                    status = int(status)
                except:
                    status = 200
            blocked = (status == 403)
            
            # Tipo de amenaza
            threat_type = result.get('threat_type') or log.get('threat_type')
            if not threat_type and result.get('llm_analysis'):
                threat_type = result['llm_analysis'].get('threat_type')
            
            # Severidad
            severity = result.get('severity', 'low').upper()
            
            # Fuente de clasificación
            classification_source = result.get('classification_source', 'ml')
            
            # Obtener información OWASP
            owasp_code = result.get('owasp_code')
            owasp_category = result.get('owasp_category')
            
            # Resolver tenant_id si no viene en el log
            tenant_id = log.get('tenant_id')
            if tenant_id is None:
                host = log.get('host') or raw_log.get('host')
                tenant_id = self._resolve_tenant_id(host)
            
            # Extraer metadata de Kafka para identificar el log único
            kafka_topic = None
            kafka_partition = None
            kafka_offset = None
            if kafka_metadata:
                kafka_topic = kafka_metadata.get('topic')
                kafka_partition = kafka_metadata.get('partition')
                kafka_offset = kafka_metadata.get('offset')
            else:
                # Intentar extraer del log si no viene en metadata
                kafka_topic = log.get('kafka_topic')
                kafka_partition = log.get('kafka_partition')
                kafka_offset = log.get('kafka_offset')
            
            # Si tenemos metadata de Kafka, hacer UPDATE usando ON CONFLICT
            # Esto actualiza el log que ya fue insertado por persistence-worker
            if kafka_topic is not None and kafka_partition is not None and kafka_offset is not None:
                try:
                    # UPDATE usando kafka_topic, kafka_partition, kafka_offset como clave única
                    # Intentar actualizar incluyendo columnas OWASP si existen
                    try:
                        cursor.execute("""
                            UPDATE waf_logs SET
                                threat_type = %s,
                                severity = %s,
                                classification_source = %s,
                                blocked = %s,
                                raw_log = %s,
                                owasp_code = %s,
                                owasp_category = %s,
                                tenant_id = COALESCE(%s, tenant_id)
                            WHERE kafka_topic = %s AND kafka_partition = %s AND kafka_offset = %s
                        """, (
                            (threat_type or '')[:50] if threat_type else None,
                            (severity or 'low')[:20].upper() if severity else 'LOW',
                            (classification_source or 'ml')[:50],
                            blocked,
                            json.dumps({**log, 'owasp_code': owasp_code, 'owasp_category': owasp_category})[:10000] if log else '{}',
                            (owasp_code or '')[:20] if owasp_code else None,
                            (owasp_category or '')[:100] if owasp_category else None,
                            tenant_id,
                            kafka_topic,
                            kafka_partition,
                            kafka_offset
                        ))
                    except Exception as e:
                        # Si las columnas OWASP no existen, actualizar sin ellas
                        if 'column "owasp_code" does not exist' in str(e).lower() or 'column "owasp_category" does not exist' in str(e).lower():
                            self.logger.debug("log_event", message="Columnas OWASP no existen aún, actualizando sin ellas...")
                            cursor.execute("""
                                UPDATE waf_logs SET
                                    threat_type = %s,
                                    severity = %s,
                                    classification_source = %s,
                                    blocked = %s,
                                    raw_log = %s,
                                    tenant_id = COALESCE(%s, tenant_id)
                                WHERE kafka_topic = %s AND kafka_partition = %s AND kafka_offset = %s
                            """, (
                                (threat_type or '')[:50] if threat_type else None,
                                (severity or 'low')[:20].upper() if severity else 'LOW',
                                (classification_source or 'ml')[:50],
                                blocked,
                                json.dumps({**log, 'owasp_code': owasp_code, 'owasp_category': owasp_category})[:10000] if log else '{}',
                                tenant_id,
                                kafka_topic,
                                kafka_partition,
                                kafka_offset
                            ))
                        else:
                            raise
                    
                    # Si no se actualizó ninguna fila, el log no existe aún (raro, pero posible)
                    if cursor.rowcount == 0:
                        self.logger.debug("log_event", message=f"Log no encontrado para actualizar (topic={kafka_topic}, partition={kafka_partition}, offset={kafka_offset}), insertando nuevo...")
                        # Insertar nuevo log (fallback)
                        cursor.execute("""
                            INSERT INTO waf_logs (
                                timestamp, ip, method, uri, status, size, user_agent, referer,
                                blocked, threat_type, severity, raw_log, classification_source,
                                kafka_topic, kafka_partition, kafka_offset, tenant_id, created_at
                            ) VALUES (
                                %s, %s, %s, %s, %s, %s, %s, %s,
                                %s, %s, %s, %s, %s,
                                %s, %s, %s, %s, NOW()
                            )
                            ON CONFLICT (kafka_topic, kafka_partition, kafka_offset) DO UPDATE SET
                                threat_type = EXCLUDED.threat_type,
                                severity = EXCLUDED.severity,
                                classification_source = EXCLUDED.classification_source,
                                blocked = EXCLUDED.blocked,
                                raw_log = EXCLUDED.raw_log,
                                tenant_id = COALESCE(EXCLUDED.tenant_id, waf_logs.tenant_id)
                        """, (
                            datetime.now(),
                            (ip or '')[:45],
                            (method or 'GET')[:10],
                            (uri or '')[:500],
                            int(status) if status else 200,
                            0,
                            (user_agent or '')[:500],
                            (referer or '')[:500],
                            blocked,
                            (threat_type or '')[:50] if threat_type else None,
                            (severity or 'low')[:20].upper() if severity else 'LOW',
                            json.dumps({**log, 'owasp_code': owasp_code, 'owasp_category': owasp_category})[:10000] if log else '{}',
                            (classification_source or 'ml')[:50],
                            kafka_topic,
                            kafka_partition,
                            kafka_offset,
                            tenant_id
                        ))
                    else:
                        self.logger.debug("log_event", message=f"✅ Log actualizado (topic={kafka_topic}, partition={kafka_partition}, offset={kafka_offset})")
                except Exception as e:
                    # Si hay error de transacción, hacer rollback primero
                    if 'InFailedSqlTransaction' in str(e) or 'current transaction is aborted' in str(e).lower():
                        self.logger.warning("error_occurred", message=f"Error de transacción SQL, haciendo rollback: {e}")
                        self.postgres_conn.rollback()
                        cursor = self.postgres_conn.cursor()  # Crear nuevo cursor después del rollback
                    else:
                        # Asegurar rollback antes de intentar INSERT alternativo
                        try:
                            self.postgres_conn.rollback()
                            cursor = self.postgres_conn.cursor()
                        except Exception:
                            pass
                    
                    # Si falla el UPDATE (puede ser que las columnas kafka_* no existan), hacer INSERT simple
                    self.logger.warning("error_occurred", message=f"Error en UPDATE, intentando INSERT: {e}")
                    try:
                        cursor.execute("""
                        INSERT INTO waf_logs (
                            timestamp, ip, method, uri, status, size, user_agent, referer,
                            blocked, threat_type, severity, raw_log, classification_source, tenant_id, created_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, NOW()
                        )
                    """, (
                        datetime.now(),
                        (ip or '')[:45],
                        (method or 'GET')[:10],
                        (uri or '')[:500],
                        int(status) if status else 200,
                        0,
                        (user_agent or '')[:500],
                        (referer or '')[:500],
                        blocked,
                        (threat_type or '')[:50] if threat_type else None,
                        (severity or 'low')[:20].upper() if severity else 'LOW',
                        json.dumps({**log, 'owasp_code': owasp_code, 'owasp_category': owasp_category})[:10000] if log else '{}',
                        (classification_source or 'ml')[:50],
                        tenant_id
                    ))
                    except Exception as e2:
                        self.logger.error("error_occurred", message=f"Error también en INSERT después de UPDATE fallido: {e2}")
                        if self.postgres_conn:
                            self.postgres_conn.rollback()
            else:
                # No hay metadata de Kafka, hacer INSERT simple (fallback)
                self.logger.debug("log_event", message="No hay metadata de Kafka, insertando log nuevo...")
                cursor.execute("""
                    INSERT INTO waf_logs (
                        timestamp, ip, method, uri, status, size, user_agent, referer,
                        blocked, threat_type, severity, raw_log, classification_source, tenant_id, created_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, NOW()
                    )
                """, (
                    datetime.now(),
                    (ip or '')[:45],
                    (method or 'GET')[:10],
                    (uri or '')[:500],
                    int(status) if status else 200,
                    0,
                    (user_agent or '')[:500],
                    (referer or '')[:500],
                    blocked,
                    (threat_type or '')[:50] if threat_type else None,
                    (severity or 'low')[:20].upper() if severity else 'LOW',
                    json.dumps({**log, 'owasp_code': owasp_code, 'owasp_category': owasp_category})[:10000] if log else '{}',
                    (classification_source or 'ml')[:50],
                    tenant_id
                ))
            
            self.postgres_conn.commit()
            cursor.close()
            
        except Exception as e:
            # Si hay error de transacción, hacer rollback
            if 'InFailedSqlTransaction' in str(e) or 'current transaction is aborted' in str(e).lower():
                self.logger.warning("error_occurred", message=f"Error de transacción SQL, haciendo rollback: {e}")
                if self.postgres_conn:
                    self.postgres_conn.rollback()
            self.logger.error("error_occurred", message=f"Error guardando en PostgreSQL: {e}", exc_info=True)
            try:
                self.postgres_conn.rollback()
            except:
                pass

    def _resolve_tenant_id(self, host: Optional[str]) -> Optional[int]:
        """Resolver tenant_id por host con cache simple."""
        try:
            if not host or not self.postgres_conn:
                return None
            host = str(host).split(":")[0].lower()
            if host.startswith("www."):
                host = host[4:]
            if not hasattr(self, "_tenant_cache"):
                self._tenant_cache = {}
                self._tenant_cache_ts = {}
                self._tenant_cache_ttl = int(os.getenv("TENANT_CACHE_TTL", "300"))
            now = time.time()
            if host in self._tenant_cache and (now - self._tenant_cache_ts.get(host, 0) < self._tenant_cache_ttl):
                return self._tenant_cache.get(host)
            cursor = self.postgres_conn.cursor()
            cursor.execute(
                "SELECT id FROM tenants WHERE domain = %s OR domain LIKE %s LIMIT 1",
                (host, f"%{host}%")
            )
            result = cursor.fetchone()
            cursor.close()
            tenant_id = result[0] if result else None
            self._tenant_cache[host] = tenant_id
            self._tenant_cache_ts[host] = now
            return tenant_id
        except Exception as e:
            self.logger.debug("log_event", message=f"No se pudo resolver tenant_id para host {host}: {e}")
            return None
    
    def _trigger_retrain(self):
        """Dispara re-entrenamiento de modelos con datos del buffer de LLM"""
        try:
            # Importar funciones de entrenamiento
            import sys
            from pathlib import Path
            mcp_core_path = Path("/app/mcp-core")
            if mcp_core_path.exists():
                sys.path.insert(0, str(mcp_core_path))
                from tools.ml_tools import train_ml_model, extract_features_from_logs
                
                with self.learning_buffer_lock:
                    if len(self.learning_buffer) < 10:  # Mínimo para entrenar
                        self.logger.warning("log_event", message=f"Buffer insuficiente para re-entrenar: {len(self.learning_buffer)}/10")
                        return
                    
                    # Preparar datos de entrenamiento con etiquetas LLM
                    training_logs = []
                    for entry in self.learning_buffer:
                        log = entry['log'].copy()
                        # Agregar threat_type y severity del LLM al log para entrenamiento
                        log['threat_type'] = entry['threat_type']
                        log['severity'] = entry['severity']
                        log['labeled_by'] = 'llm'
                        training_logs.append(log)
                    
                    self.logger.info("log_event", message=f"🔄 Re-entrenando Random Forest con {len(training_logs)} logs etiquetados por LLM...")
                    
                    # Re-entrenar Random Forest
                    if self.use_random_forest:
                        result = asyncio.run(train_ml_model(
                            model_type='random_forest',
                            logs_data=training_logs,
                            n_estimators=100
                        ))
                        if result.get('success'):
                            model_id = result.get('model_id')
                            self.logger.info("log_event", message=f"✅ Random Forest re-entrenado exitosamente: {model_id}")
                            # Recargar el modelo en el predictor
                            try:
                                self.ml_predictor.load_model(model_id)
                                self.logger.info("log_event", message=f"✅ Modelo {model_id} cargado en predictor")
                            except Exception as e:
                                self.logger.warning("log_event", message=f"No se pudo cargar modelo {model_id}: {e}")
                        else:
                            self.logger.error("error_occurred", message=f"Error re-entrenando modelo: {result.get('error')}")
                    
                    # Limpiar buffer después de entrenar
                    self.learning_buffer = []
                    self.last_retrain = time.time()
                    self.logger.info("log_event", message="✅ Buffer de aprendizaje limpiado después de re-entrenamiento")
                    
        except Exception as e:
            self.logger.error("error_occurred", message=f"Error en re-entrenamiento: {e}", exc_info=True)
    
    def _is_suspicious_unblocked_request(self, log: Dict[str, Any]) -> bool:
        """
        Detecta si un request no bloqueado (status != 403) contiene patrones sospechosos.
        Usa heurísticas mejoradas para detectar ataques que pasaron el WAF.
        
        Args:
            log: Log normalizado
        
        Returns:
            True si detecta patrones sospechosos que indican ataque no bloqueado
        """
        status = log.get('status', 200)
        if isinstance(status, str):
            try:
                status = int(status)
            except:
                status = 200
        
        # Solo analizar requests no bloqueados
        if status == 403:
            return False
        
        uri = (log.get('uri') or log.get('request_uri') or '').lower()
        query = (log.get('query_string') or log.get('query') or '').lower()
        text = f"{uri} {query}"
        
        # Patrones de SQL Injection
        sqli_patterns = ["' or '1'='1", "' or 1=1", " union ", " select ", "%27", "'; drop", 
                        "'; delete", "sleep(", "waitfor", "benchmark(", "pg_sleep", "xp_cmdshell"]
        if any(pattern in text for pattern in sqli_patterns):
            return True
        
        # Patrones de XSS
        xss_patterns = ["<script", "javascript:", "onerror=", "onload=", "eval(", "alert(",
                       "document.cookie", "document.write", "innerhtml"]
        if any(pattern in text for pattern in xss_patterns):
            return True
        
        # Patrones de Path Traversal
        path_traversal_patterns = ["../", "/etc/passwd", "/etc/shadow", "..\\", "windows\\system32",
                                  "boot.ini", "web.config", ".env", "....//", "....\\\\"]
        if any(pattern in text for pattern in path_traversal_patterns):
            return True
        
        # Patrones de Command Injection
        cmd_injection_patterns = ["cmd=", "command=", "exec=", "&&", "||", "| cat ", "| ls ",
                                 "| id ", "| whoami ", "`id`", "$(", "exec(", "system("]
        # Evitar falsos positivos en archivos JS normales
        is_js_file = uri.endswith(('.js', '.min.js')) or '/js/' in uri or '/javascript/' in uri
        if not is_js_file and any(pattern in text for pattern in cmd_injection_patterns):
            return True
        
        # Patrones de SSRF
        ssrf_patterns = ["http://YOUR_IP_ADDRESS", "http://localhost", "file://", "gopher://",
                        "dict://", "ftp://internal"]
        if any(pattern in text for pattern in ssrf_patterns):
            return True
        
        return False
    
    def _detect_suspicious_patterns_heuristic(self, log: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Detecta patrones sospechosos MUY OBVIOS usando heurísticas antes de ML.
        CAMBIO: Heurística más conservadora - solo detecta patrones críticos y obvios.
        Patrones ambiguos o variantes ofuscadas se dejan para ML/Transformer/LLM.
        
        Args:
            log: Log normalizado
        
        Returns:
            Dict con threat_type, severity, action si detecta patrón MUY OBVIO, None si no
        """
        uri = (log.get('uri') or log.get('request_uri') or '').lower()
        query = (log.get('query_string') or log.get('query') or '').lower()
        user_agent = (log.get('user_agent') or '').lower()
        method = (log.get('method') or log.get('request_method') or 'GET').upper()
        text = f"{uri} {query} {user_agent}"
        
        # SQL Injection - Solo patrones MUY obvios (dejar variantes ofuscadas para ML)
        # Patrones críticos que son 99% ataques reales
        critical_sqli_patterns = ["' or '1'='1", "' or 1=1", " union select ", "'; drop table", 
                                  "'; delete from", "1' union select"]
        if any(x in text for x in critical_sqli_patterns):
            return {
                'threat_type': 'SQLI',
                'severity': 'high',
                'action': 'block_ip'
            }
        
        # XSS - Solo patrones MUY obvios con <script> explícito (dejar variantes ofuscadas para ML/Transformer)
        # Solo detectar XSS clásico, no ofuscado
        critical_xss_patterns = ["<script>", "<script ", "javascript:alert(", "onerror=alert("]
        if any(x in text for x in critical_xss_patterns):
            return {
                'threat_type': 'XSS',
                'severity': 'high',
                'action': 'block_ip'
            }
        
        # Path Traversal - Detectar patrones críticos y variantes encoded
        # Incluir .env, .git/config como PATH_TRAVERSAL (son intentos de acceso a archivos sensibles)
        # También detectar path traversal encoded (..%2F, ..%5C, etc.)
        import urllib.parse
        text_decoded = urllib.parse.unquote(text) if '%' in text else text
        critical_path_patterns = [
            "/etc/passwd", "/etc/shadow", "windows\\system32\\", "boot.ini",
            "/.env", "/.git/config", "/.git/", "web.config"
        ]
        path_traversal_indicators = [
            "../", "..\\", "....//", "....\\\\", "%2e%2e/", "%2e%2e\\",
            "..%2f", "..%5c", "%2e%2e%2f", "%2e%2e%5c",
            ".%2e/", ".%2e\\", "%2e%2e", ".%2e"  # Detectar .%2e (.. encoded)
        ]
        # Detectar patrones críticos en texto original o decodificado
        if any(x in text for x in critical_path_patterns) or any(x in text_decoded for x in critical_path_patterns):
            return {
                'threat_type': 'PATH_TRAVERSAL',
                'severity': 'high',
                'action': 'block_ip'
            }
        # Detectar path traversal encoded (incluyendo .%2e que es .. encoded)
        # Si hay patrones de path traversal encoded (incluso sin /etc/passwd explícito)
        if any(x in text.lower() for x in path_traversal_indicators):
            # Si hay múltiples niveles encoded (ej: /cgi-bin/.%2e/.%2e/.%2e) o patrones obvios
            if text.lower().count('%2e') >= 3 or '/cgi-bin/' in uri.lower() or '/etc/' in text_decoded or '/passwd' in text_decoded or '.env' in uri or '.git' in uri:
                return {
                    'threat_type': 'PATH_TRAVERSAL',
                    'severity': 'high',
                    'action': 'block_ip'
                }
        
        # Command Injection - Solo comandos críticos explícitos (evitar falsos positivos)
        # Solo detectar comandos shell obvios, no patrones ambiguos
        critical_cmd_patterns = ["&& rm -rf", "|| cat /etc/passwd", "| cat /etc/passwd", 
                                 "`cat /etc/passwd`", "$(cat /etc/passwd)"]
        is_js_file = uri.endswith(('.js', '.min.js')) or '/js/' in uri or '/javascript/' in uri
        if not is_js_file and any(x in text for x in critical_cmd_patterns):
            return {
                'threat_type': 'CMD_INJECTION',
                'severity': 'high',
                'action': 'block_ip'
            }
        
        # SSRF - Solo URLs locales explícitas con parámetros sospechosos
        # Requiere combinación de URL local + parámetro que indica SSRF
        if any(x in text for x in ["http://YOUR_IP_ADDRESS", "file:///etc/passwd"]) and \
           ("url=" in query or "link=" in query or "target=" in query or "proxy=" in query):
            return {
                'threat_type': 'SSRF',
                'severity': 'high',
                'action': 'block_ip'
            }
        
        # Scanning Patterns - Detectar múltiples patrones de escaneo comunes
        # WordPress Scanning
        wp_scan_patterns = [
            "/wp-includes/", "/wp-admin/", "/wp-content/", "wlwmanifest.xml",
            "xmlrpc.php", "wp-login.php", "wp-config.php", "/wp-includes/",
            "/wp-admin/includes/", "/wp-includes/css/", "/wp-includes/js/",
            "/wp-includes/PHPMailer/", "/wp-includes/html-api/", "/wp-includes/Text/",
            "/wp-includes/ID3/", "/wp-includes/theme-compat/"
        ]
        # Otros patrones de escaneo comunes
        common_scan_patterns = [
            "/.env", "/.git/config", "/.well-known/", "/.well-known/acme-challenge/",
            "/admin/", "/phpmyadmin/", "/config", "/geoserver/", "/SDK/",
            "/robots.txt", "/sitemap.xml", "/ads.txt", "/favicon.ico",
            "/webui/", "/actuator/", "/backend/", "/dev/"
        ]
        # Detectar si el log original ya tiene SCAN_PROBE (viene del WAF o clasificación previa)
        # CAMBIO: SCAN_PROBE ahora genera bloqueos (no solo monitor) para que los episodios puedan bloquear IPs
        original_threat_type = (log.get('threat_type') or '').upper()
        if original_threat_type == 'SCAN_PROBE':
            return {
                'threat_type': 'SCAN_PROBE',
                'severity': 'medium',
                'action': 'block_ip'  # CAMBIO: block_ip en lugar de monitor para que genere bloqueos
            }
        # Detectar patrones de escaneo en URI
        # CAMBIO: SCAN_PROBE ahora genera bloqueos para que los episodios puedan bloquear IPs
        if any(pattern in uri for pattern in wp_scan_patterns + common_scan_patterns):
            return {
                'threat_type': 'SCAN_PROBE',
                'severity': 'medium',
                'action': 'block_ip'  # CAMBIO: block_ip en lugar de monitor
            }
        # Detectar múltiples 404s seguidos (indicador de escaneo)
        status = log.get('status', 200)
        if isinstance(status, str):
            try:
                status = int(status)
            except:
                status = 200
        if status == 404 and any(pattern in uri for pattern in ['/wp-', '/admin', '/.env', '/.git', '/config', '/phpmyadmin']):
            return {
                'threat_type': 'SCAN_PROBE',
                'severity': 'medium',
                'action': 'block_ip'  # CAMBIO: block_ip en lugar de monitor
            }
        
        # CONNECT method abuse - Este puede quedarse (muy específico)
        if method and method.upper() == "CONNECT" and ":" in uri:
            return {
                'threat_type': 'UNAUTHORIZED_ACCESS',
                'severity': 'medium',
                'action': 'monitor'
            }
        
        # NO detectar: variantes ofuscadas, patrones ambiguos, encoding, etc.
        # Estos se dejan para ML/Transformer/LLM que pueden analizar mejor el contexto
        return None
    
    def _analyze_ip_batch(self, ip: str) -> Optional[Dict[str, Any]]:
        """
        Analiza un lote de logs sospechosos de una IP usando DataFrame.
        Decide si la IP es maliciosa basándose en patrones agregados.
        
        Args:
            ip: IP a analizar
            
        Returns:
            Dict con is_malicious, threat_types, severity, etc. o None
        """
        if ip not in self.ip_suspicious_buffer:
            return None
        
        batch = self.ip_suspicious_buffer[ip]
        if len(batch) < self.ip_buffer_threshold:
            return None
        
        try:
            import pandas as pd
            
            # Crear DataFrame con los logs del batch
            logs_data = []
            for entry in batch:
                log = entry['log']
                heuristic = entry.get('heuristic_result', {})
                
                logs_data.append({
                    'timestamp': entry.get('timestamp', time.time()),
                    'ip': log.get('ip', ip),
                    'uri': log.get('uri', ''),
                    'method': log.get('method', 'GET'),
                    'status': log.get('status', 200),
                    'threat_type': heuristic.get('threat_type', 'UNKNOWN'),
                    'severity': heuristic.get('severity', 'low'),
                    'user_agent': log.get('user_agent', ''),
                    'uri_length': len(log.get('uri', '')),
                    'query_string': log.get('query_string', '')
                })
            
            df = pd.DataFrame(logs_data)
            
            # Análisis agregado para decidir si es malicioso
            threat_types = df['threat_type'].value_counts()
            unique_threats = len(threat_types)
            total_logs = len(df)
            
            # Criterios para considerar IP maliciosa:
            # 1. Múltiples tipos de amenazas diferentes
            # 2. Alta frecuencia de amenazas (>= 50% de logs son sospechosos)
            # 3. Severidades altas predominan
            high_severity_count = len(df[df['severity'] == 'high'])
            severity_ratio = high_severity_count / total_logs if total_logs > 0 else 0
            
            # Criterios MUY AGRESIVOS para detección rápida de escaneos
            scan_probe_count = threat_types.get('SCAN_PROBE', 0) if isinstance(threat_types, dict) else 0
            if not isinstance(threat_types, dict):
                # Si threat_types es una Series de pandas, convertir a dict
                scan_probe_count = threat_types.get('SCAN_PROBE', 0) if hasattr(threat_types, 'get') else 0
                if not scan_probe_count:
                    # Contar desde el DataFrame
                    scan_probe_count = len(df[df['threat_type'] == 'SCAN_PROBE'])
            
            is_malicious = (
                scan_probe_count >= 1 or  # 1+ SCAN_PROBE = escaneo obvio (MUY agresivo)
                total_logs >= 1 or  # Cualquier log sospechoso (MUY agresivo)
                unique_threats >= 1 or  # Cualquier tipo de ataque (no NONE)
                (total_logs >= 1 and severity_ratio >= 0.2) or  # 1 log y 20%+ con severidad alta (MUY agresivo)
                severity_ratio >= 0.3  # 30%+ con severidad alta (MUY agresivo)
            )
            
            # Determinar threat_type principal
            primary_threat = threat_types.index[0] if len(threat_types) > 0 else 'MULTIPLE_ATTACKS'
            if unique_threats > 2:
                primary_threat = 'MULTIPLE_ATTACKS'
            
            # Severidad agregada
            max_severity = df['severity'].max() if 'severity' in df.columns else 'medium'
            if severity_ratio >= 0.5:
                max_severity = 'high'
            elif severity_ratio >= 0.3:
                max_severity = 'medium'
            
            self.logger.info(f"🔍 Análisis batch IP {ip}: {total_logs} logs, {unique_threats} tipos amenazas, "
                       f"severidad_ratio={severity_ratio:.2f}, is_malicious={is_malicious}")
            
            return {
                'is_malicious': is_malicious,
                'ip': ip,
                'total_logs': total_logs,
                'unique_threat_types': unique_threats,
                'threat_types': threat_types.to_dict(),
                'primary_threat_type': primary_threat,
                'severity': max_severity,
                'severity_ratio': severity_ratio,
                'high_severity_count': high_severity_count
            }
            
        except ImportError:
            self.logger.warning("log_event", message="pandas no disponible, usando análisis simple sin DataFrame")
            # Fallback: análisis simple sin pandas (criterios mejorados)
            unique_threats = len(set(entry.get('heuristic_result', {}).get('threat_type', 'UNKNOWN') 
                                   for entry in batch))
            total_logs = len(batch)
            # Criterios mejorados: 3+ logs O 2+ tipos diferentes
            is_malicious = (unique_threats >= 2 or total_logs >= 3)
            return {
                'is_malicious': is_malicious,
                'ip': ip,
                'total_logs': len(batch),
                'primary_threat_type': 'MULTIPLE_ATTACKS' if unique_threats > 1 else 'UNKNOWN',
                'severity': 'high' if is_malicious else 'medium'
            }
        except Exception as e:
            self.logger.error("error_occurred", message=f"Error analizando batch de IP {ip}: {e}", exc_info=True)
            return None
    
    def _mark_ip_batch_as_blocked(self, ip: str, batch_result: Dict[str, Any]):
        """
        Marca todos los logs de un batch de IP como bloqueados (403) y los guarda en PostgreSQL.
        NUEVO: Consulta LLM como agente de decisión antes de bloquear.
        """
        if ip not in self.ip_suspicious_buffer:
            return
        
        batch = self.ip_suspicious_buffer[ip]
        total_logs = len(batch)
        self.logger.info("log_event", message=f"🔍 Analizando batch de IP {ip} con {total_logs} logs sospechosos...")
        
        # Preparar resumen del batch para LLM
        threat_types = {}
        sample_logs = []
        high_severity_count = 0
        time_span = 0
        
        for entry in batch:
            heuristic = entry.get('heuristic_result', {})
            threat_type = heuristic.get('threat_type', 'UNKNOWN')
            threat_types[threat_type] = threat_types.get(threat_type, 0) + 1
            
            if heuristic.get('severity') == 'high':
                high_severity_count += 1
            
            # Agregar a muestra (máximo 5, los más recientes)
            if len(sample_logs) < 5:
                log = entry['log']
                sample_logs.append({
                    'uri': log.get('uri', ''),
                    'method': log.get('method', 'GET'),
                    'threat_type': threat_type
                })
            
            # Calcular span temporal
            entry_time = entry.get('timestamp', time.time())
            if time_span == 0:
                time_span = time.time() - entry_time
        
        severity_ratio = high_severity_count / total_logs if total_logs > 0 else 0
        unique_threats = len(threat_types)
        
        # Contar cuántos logs fueron bloqueados por WAF vs no bloqueados
        waf_blocked_count = sum(1 for entry in batch if entry.get('waf_blocked', False))
        not_blocked_count = total_logs - waf_blocked_count
        
        batch_summary = {
            'ip': ip,
            'total_logs': total_logs,
            'threat_types': threat_types,
            'time_span_seconds': time_span,
            'sample_logs': sample_logs,
            'severity_ratio': severity_ratio,
            'unique_threat_types': unique_threats,
            'waf_blocked_count': waf_blocked_count,  # Cuántos fueron bloqueados por WAF
            'not_blocked_count': not_blocked_count,  # Cuántos NO fueron bloqueados por WAF
            'waf_blocked_ratio': waf_blocked_count / total_logs if total_logs > 0 else 0  # Ratio de bloqueos WAF
        }
        
        # CONSULTAR LLM COMO AGENTE DE DECISIÓN
        llm_batch_analysis = None
        if self.enable_llm and self.llm_analyzer:
            try:
                self.logger.info("log_event", message=f"🤖 Consultando LLM para decisión de bloqueo de IP {ip}...")
                llm_batch_analysis = self.llm_analyzer.analyze_batch(batch_summary)
                
                if llm_batch_analysis.get('analyzed') and llm_batch_analysis.get('decision') == 'block_ip':
                    self.logger.warning("log_event", message=f"✅ LLM DECIDIÓ BLOQUEAR IP {ip}: {llm_batch_analysis.get('reason', 'Patrón malicioso detectado')}")
                elif llm_batch_analysis.get('decision') == 'monitor':
                    self.logger.info("log_event", message=f"⚠️ LLM decidió MONITOREAR IP {ip} (no bloquear aún): {llm_batch_analysis.get('reason', '')}")
            except Exception as e:
                self.logger.error("error_occurred", message=f"Error consultando LLM para batch: {e}", exc_info=True)
        
        # Decisión final: usar LLM si está disponible, sino usar análisis estadístico
        if llm_batch_analysis and llm_batch_analysis.get('analyzed'):
            should_block = llm_batch_analysis.get('decision') == 'block_ip'
            primary_threat = llm_batch_analysis.get('threat_type', batch_result.get('primary_threat_type', 'MULTIPLE_ATTACKS'))
            severity = llm_batch_analysis.get('severity', batch_result.get('severity', 'high'))
            reason = llm_batch_analysis.get('reason', 'Decisión del LLM basada en patrón de comportamiento')
            confidence = llm_batch_analysis.get('confidence', 0.8)
            block_duration_seconds = llm_batch_analysis.get('block_duration_seconds', 3600)  # Duración decidida por LLM
            classification_source = 'batch_analysis_llm'
        else:
            # Fallback a análisis estadístico (no debería llegar aquí si LLM está habilitado, pero por si acaso)
            should_block = batch_result.get('is_malicious', False)
            primary_threat = batch_result.get('primary_threat_type', 'MULTIPLE_ATTACKS')
            severity = batch_result.get('severity', 'high')
            reason = f"Análisis estadístico: {unique_threats} tipos de amenazas, {total_logs} logs, ratio severidad={severity_ratio:.1%}"
            confidence = 0.7
            block_duration_seconds = 3600  # Default: 1 hora para fallback
            classification_source = 'batch_analysis'
        
        if not should_block:
            self.logger.info("log_event", message=f"ℹ️ IP {ip} no será bloqueada (monitoreo): {reason}")
            # Limpiar buffer pero no bloquear
            with self.ip_buffer_lock:
                if ip in self.ip_suspicious_buffer:
                    del self.ip_suspicious_buffer[ip]
            return
        
        self.logger.warning("log_event", message=f"🚨 BLOQUEANDO IP {ip}: {total_logs} logs, {unique_threats} tipos amenazas - {reason}")
        
        # Clasificar OWASP
        owasp_info = classify_by_owasp_top10(primary_threat)
        owasp_code = owasp_info.get('owasp_code')
        owasp_category = owasp_info.get('owasp_category')
        
        # Procesar cada log del batch como bloqueado
        for entry in batch:
            log = entry['log']
            kafka_metadata = entry.get('kafka_metadata')
            
            # Marcar como bloqueado
            log['status'] = 403
            log['blocked'] = True
            
            # Crear resultado con clasificación
            result = {
                'log': log,
                'threat_type': primary_threat,
                'classification_source': classification_source,
                'severity': severity,
                'action': 'block_ip',
                'owasp_code': owasp_code,
                'owasp_category': owasp_category,
                '_log_start_time': entry.get('timestamp', time.time()),
                'mitigation_reason': reason,
                'batch_confidence': confidence
            }
            
            # Guardar en PostgreSQL
            if self.postgres_enabled:
                try:
                    self._save_to_postgres(log, result, kafka_metadata)
                except Exception as e:
                    self.logger.error("error_occurred", message=f"Error guardando log bloqueado del batch: {e}")
            
            # ENVIAR A MITIGACIÓN PARA BLOQUEO REAL EN NGINX
            if self.send_to_mitigation and self.producer:
                try:
                    mitigation_message = {
                        'log': log,
                        'action': 'block_ip',
                        'severity': severity,
                        'threat_type': primary_threat,
                        'tenant_id': log.get('tenant_id', 'default'),
                        'timestamp': datetime.now().isoformat(),
                        'reason': f"Batch analysis - {reason}",
                        'classification_source': classification_source,
                        'waf_blocked': False,  # No bloqueado por WAF, sino por análisis inteligente
                        'needs_mitigation': True,
                        'ip': ip,
                        'duration': block_duration_seconds,  # Duración decidida por el LLM
                        'batch_total_logs': total_logs,
                        'batch_unique_threats': unique_threats,
                        'batch_confidence': confidence
                    }
                    
                    self.producer.send(self.threats_topic, value=mitigation_message)
                    self.producer.flush()  # Asegurar envío inmediato
                    self.metrics['mitigations_sent'] += 1
                    
                    self.logger.warning("log_event", message=f"🛡️ MITIGACIÓN AUTOMÁTICA ENVIADA (BATCH): IP={ip}, Threat={primary_threat}, Source={classification_source}")
                except Exception as e:
                    self.logger.error("error_occurred", message=f"Error enviando decisión de mitigación de batch: {e}", exc_info=True)
        
        # NUEVO: Guardar IP bloqueada en tabla blocked_ips para que aparezca en el dashboard
        if self.postgres_enabled:
            try:
                cursor = self.postgres_conn.cursor()
                # Calcular expires_at usando la duración decidida por el LLM
                expires_at = datetime.now() + timedelta(seconds=block_duration_seconds)
                
                cursor.execute("""
                    INSERT INTO blocked_ips (
                        ip, blocked_at, expires_at, reason, blocked_by,
                        threat_type, severity, classification_source, active
                    )
                    VALUES (%s, NOW(), %s, %s, %s, %s, %s, %s, TRUE)
                    ON CONFLICT (ip) WHERE active = TRUE
                    DO UPDATE SET
                        blocked_at = NOW(),
                        expires_at = EXCLUDED.expires_at,
                        reason = EXCLUDED.reason,
                        threat_type = EXCLUDED.threat_type,
                        severity = EXCLUDED.severity,
                        classification_source = EXCLUDED.classification_source,
                        active = TRUE,
                        updated_at = NOW()
                """, (
                    ip,
                    expires_at,
                    reason[:500],  # Limitar longitud del reason
                    classification_source,
                    primary_threat,
                    severity,
                    classification_source
                ))
                self.postgres_conn.commit()
                self.logger.info("log_event", message=f"✅ IP {ip} guardada en tabla blocked_ips (classification_source: {classification_source})")
                cursor.close()
            except Exception as e:
                self.logger.error("error_occurred", message=f"Error guardando IP bloqueada en blocked_ips: {e}", exc_info=True)
                if self.postgres_conn:
                    self.postgres_conn.rollback()
        
        # Limpiar buffer de esta IP
        with self.ip_buffer_lock:
            if ip in self.ip_suspicious_buffer:
                del self.ip_suspicious_buffer[ip]
    
    def _cleanup_old_ip_buffers(self):
        """Limpia buffers de IP que son demasiado antiguos"""
        current_time = time.time()
        ips_to_remove = []
        
        with self.ip_buffer_lock:
            for ip, batch in self.ip_suspicious_buffer.items():
                if not batch:
                    ips_to_remove.append(ip)
                    continue
                
                # Verificar edad del buffer más antiguo
                oldest_timestamp = min(entry.get('timestamp', current_time) for entry in batch)
                age = current_time - oldest_timestamp
                
                if age > self.ip_buffer_max_age:
                    self.logger.debug("log_event", message=f"Limpiando buffer antiguo de IP {ip} (edad: {age:.0f}s)")
                    ips_to_remove.append(ip)
            
            for ip in ips_to_remove:
                del self.ip_suspicious_buffer[ip]
    
    def _analyze_time_window_async(self):
        """
        Analiza ventana temporal en thread separado (no bloquea pipeline principal).
        Detecta ataques distribuidos, escaneos coordinados, etc.
        """
        try:
            # Obtener ventana para análisis
            window = self.time_window_analyzer.get_window_for_analysis()
            if not window:
                return
            
            self.logger.info("component_starting", message=f"🧠 Iniciando análisis SOC de ventana temporal: {len(window)} logs")
            
            # Construir resumen de la ventana
            window_summary = self.time_window_analyzer.build_window_summary(window)
            
            # Analizar con LLM como analista SOC
            if self.enable_llm and self.llm_analyzer:
                # Obtener baseline de paths válidos para el análisis
                baseline_paths = None
                if BASELINE_AVAILABLE and self.baseline_manager:
                    tenant_id = self.config.get('tenant_id')
                    try:
                        baseline_paths = get_valid_paths(tenant_id=tenant_id)
                        if baseline_paths:
                            self.logger.debug("log_event", message=f"📋 Usando baseline con {len(baseline_paths)} paths válidos para análisis")
                    except Exception as e:
                        self.logger.warning("error_occurred", message=f"Error obteniendo baseline: {e}")
                
                analysis_result = self.llm_analyzer.analyze_time_window_batch(
                    window_summary,
                    baseline_paths=baseline_paths
                )
                
                if analysis_result.get('analyzed') and analysis_result.get('success'):
                    # Procesar decisiones: bloquear IPs detectadas
                    ips_to_block = analysis_result.get('ips_to_block', [])
                    ips_to_monitor = analysis_result.get('ips_to_monitor', [])
                    reasoning = analysis_result.get('reasoning', '')
                    confidence = analysis_result.get('confidence', 0.8)
                    attack_patterns = analysis_result.get('attack_patterns_detected', [])
                    
                    self.logger.warning("log_event", message=f"🧠 Análisis SOC completado: {len(ips_to_block)} IPs a bloquear, "
                                 f"{len(ips_to_monitor)} IPs a monitorear. Patrones: {attack_patterns}")
                    
                    # Bloquear cada IP detectada
                    for ip_to_block in ips_to_block:
                        self._block_ip_from_window_analysis(ip_to_block, window_summary, reasoning, 
                                                           confidence, attack_patterns)
                    
                    # Monitorear IPs sospechosas (log pero no bloquear aún)
                    for ip_to_monitor in ips_to_monitor:
                        self.logger.info("log_event", message=f"👁️ IP {ip_to_monitor} marcada para monitoreo: {reasoning[:100]}")
                else:
                    # Si el LLM falló o no está disponible, usar fallback heurístico
                    self.logger.warning("log_event", message=f"⚠️ Análisis SOC con LLM no disponible, usando fallback heurístico")
                    fallback_result = self.llm_analyzer._fallback_window_analysis(window_summary)
                    
                    ips_to_block = fallback_result.get('ips_to_block', [])
                    ips_to_monitor = fallback_result.get('ips_to_monitor', [])
                    reasoning = fallback_result.get('reasoning', 'Análisis heurístico de fallback')
                    confidence = fallback_result.get('confidence', 0.7)
                    attack_patterns = fallback_result.get('attack_patterns_detected', [])
                    
                    self.logger.warning("log_event", message=f"🔧 Fallback heurístico: {len(ips_to_block)} IPs a bloquear, "
                                 f"{len(ips_to_monitor)} IPs a monitorear")
                    
                    # Bloquear cada IP detectada por fallback
                    for ip_to_block in ips_to_block:
                        self._block_ip_from_window_analysis(ip_to_block, window_summary, reasoning, 
                                                           confidence, attack_patterns)
                    
                    # Monitorear IPs sospechosas
                    for ip_to_monitor in ips_to_monitor:
                        self.logger.info("log_event", message=f"👁️ IP {ip_to_monitor} marcada para monitoreo (fallback): {reasoning[:100]}")
            else:
                self.logger.debug("log_event", message="LLM no habilitado, omitiendo análisis de ventana temporal")
                
        except Exception as e:
            self.logger.error("error_occurred", message=f"❌ Error analizando ventana temporal: {e}", exc_info=True)
    
    def _block_ip_from_window_analysis(self, ip: str, window_summary: Dict[str, Any], 
                                       reasoning: str, confidence: float, 
                                       attack_patterns: List[str]):
        """
        Bloquea una IP detectada por análisis de ventana temporal.
        Envía mensaje a mitigation service para bloqueo en nginx.
        
        Args:
            ip: IP a bloquear
            window_summary: Resumen de la ventana temporal
            reasoning: Razón del bloqueo
            confidence: Confianza de la decisión
            attack_patterns: Patrones de ataque detectados
        """
        try:
            self.logger.warning("log_event", message=f"🚨 BLOQUEANDO IP {ip} desde análisis SOC de ventana temporal: {reasoning[:150]}")
            
            # Buscar logs de esta IP en la ventana para obtener contexto
            ip_logs = None
            suspicious_ips = window_summary.get('suspicious_ips', [])
            for ip_data in suspicious_ips:
                if ip_data['ip'] == ip:
                    ip_logs = ip_data
                    break
            
            # Determinar threat_type principal
            threat_types = ip_logs.get('threat_types', {}) if ip_logs else {}
            primary_threat = 'MULTIPLE_ATTACKS'
            if threat_types:
                # Obtener el threat_type más común
                sorted_threats = sorted(threat_types.items(), key=lambda x: x[1], reverse=True)
                primary_threat = sorted_threats[0][0] if sorted_threats[0][0] != 'NONE' else 'MULTIPLE_ATTACKS'
            
            # Clasificar OWASP
            owasp_info = classify_by_owasp_top10(primary_threat)
            owasp_code = owasp_info.get('owasp_code')
            owasp_category = owasp_info.get('owasp_category')
            
            # Crear mensaje de mitigación
            mitigation_message = {
                'action': 'block_ip',
                'ip': ip,
                'threat_type': primary_threat,
                'severity': 'high',
                'classification_source': 'time_window_soc_analysis',
                'reason': f"Análisis SOC de ventana temporal: {reasoning[:200]}",
                'timestamp': datetime.now().isoformat(),
                'duration': 3600,  # 1 hora
                'needs_mitigation': True,
                'waf_blocked': False,
                'confidence': confidence,
                'attack_patterns': attack_patterns,
                'owasp_code': owasp_code,
                'owasp_category': owasp_category,
                'window_analysis': {
                    'total_logs_in_window': window_summary.get('total_logs', 0),
                    'unique_ips_in_window': window_summary.get('unique_ips', 0),
                    'time_span': window_summary.get('time_span_seconds', 0)
                },
                'tenant_id': 'default'
            }
            
            # Enviar a mitigation service
            if self.send_to_mitigation and self.producer:
                try:
                    self.producer.send(self.threats_topic, value=mitigation_message)
                    self.producer.flush()
                    self.metrics['mitigations_sent'] += 1
                    
                    self.logger.warning("log_event", message=f"✅ IP {ip} enviada a mitigation service para bloqueo (SOC analysis)")
                except Exception as e:
                    self.logger.error("error_occurred", message=f"❌ Error enviando IP {ip} a mitigation service: {e}")
            else:
                self.logger.warning("log_event", message=f"⚠️ Mitigation service no disponible, IP {ip} no será bloqueada")
            
            # También actualizar en PostgreSQL si tenemos conexión
            if self.postgres_enabled and self.postgres_conn:
                try:
                    cursor = self.postgres_conn.cursor()
                    
                    # 1. Marcar logs de esta IP como bloqueados
                    cursor.execute("""
                        UPDATE waf_logs 
                        SET blocked = TRUE, 
                            threat_type = %s,
                            classification_source = 'time_window_soc_analysis',
                            severity = 'high'
                        WHERE ip = %s 
                        AND timestamp > NOW() - INTERVAL '5 minutes'
                        AND blocked = FALSE
                    """, (primary_threat, ip))
                    
                    # 2. Guardar IP en tabla blocked_ips (para sync script)
                    expires_at = datetime.now() + timedelta(hours=1)  # Bloqueo por 1 hora
                    try:
                        cursor.execute("""
                            INSERT INTO blocked_ips (
                                ip, blocked_at, expires_at, reason, blocked_by,
                                threat_type, severity, classification_source, active
                            )
                            VALUES (%s, NOW(), %s, %s, 'time_window_soc_analysis', %s, %s, %s, TRUE)
                            ON CONFLICT (ip) WHERE active = TRUE
                            DO UPDATE SET
                                blocked_at = NOW(),
                                expires_at = EXCLUDED.expires_at,
                                reason = EXCLUDED.reason,
                                threat_type = EXCLUDED.threat_type,
                                severity = EXCLUDED.severity,
                                classification_source = EXCLUDED.classification_source,
                                active = TRUE,
                                updated_at = NOW()
                        """, (
                            ip,
                            expires_at,
                            f"Análisis SOC: {reasoning[:200]}",
                            primary_threat,
                            'high',
                            'time_window_soc_analysis'
                        ))
                        self.logger.info("log_event", message=f"✅ IP {ip} guardada en tabla blocked_ips")
                    except Exception as e:
                        # Si la tabla no existe, intentar crearla
                        if 'does not exist' in str(e) or 'relation' in str(e).lower():
                            self.logger.warning("log_event", message=f"⚠️ Tabla blocked_ips no existe, intentando crearla...")
                            try:
                                # Crear tabla si no existe
                                cursor.execute("""
                                    CREATE TABLE IF NOT EXISTS blocked_ips (
                                        id BIGSERIAL PRIMARY KEY,
                                        ip INET NOT NULL,
                                        blocked_at TIMESTAMP NOT NULL DEFAULT NOW(),
                                        expires_at TIMESTAMP,
                                        reason TEXT,
                                        blocked_by VARCHAR(50) DEFAULT 'auto-mitigation',
                                        threat_type VARCHAR(50),
                                        severity VARCHAR(20),
                                        classification_source VARCHAR(50),
                                        active BOOLEAN NOT NULL DEFAULT TRUE,
                                        unblocked_at TIMESTAMP,
                                        unblock_reason TEXT,
                                        created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                                        updated_at TIMESTAMP NOT NULL DEFAULT NOW()
                                    )
                                """)
                                # Crear índice único
                                cursor.execute("""
                                    CREATE UNIQUE INDEX IF NOT EXISTS idx_blocked_ips_ip_active 
                                    ON blocked_ips(ip) WHERE active = TRUE
                                """)
                                self.postgres_conn.commit()
                                self.logger.info("log_event", message=f"✅ Tabla blocked_ips creada exitosamente")
                                
                                # Reintentar insertar
                                cursor.execute("""
                                    INSERT INTO blocked_ips (
                                        ip, blocked_at, expires_at, reason, blocked_by,
                                        threat_type, severity, classification_source, active
                                    )
                                    VALUES (%s, NOW(), %s, %s, 'time_window_soc_analysis', %s, %s, %s, TRUE)
                                    ON CONFLICT (ip) WHERE active = TRUE
                                    DO UPDATE SET
                                        blocked_at = NOW(),
                                        expires_at = EXCLUDED.expires_at,
                                        reason = EXCLUDED.reason,
                                        threat_type = EXCLUDED.threat_type,
                                        severity = EXCLUDED.severity,
                                        classification_source = EXCLUDED.classification_source,
                                        active = TRUE,
                                        updated_at = NOW()
                                """, (
                                    ip,
                                    expires_at,
                                    f"Análisis SOC: {reasoning[:200]}",
                                    primary_threat,
                                    'high',
                                    'time_window_soc_analysis'
                                ))
                                self.logger.info("log_event", message=f"✅ IP {ip} guardada en tabla blocked_ips (después de crear tabla)")
                            except Exception as e2:
                                self.logger.error("error_occurred", message=f"❌ Error creando tabla blocked_ips: {e2}")
                                self.postgres_conn.rollback()
                        else:
                            self.logger.warning("log_event", message=f"⚠️ No se pudo guardar en blocked_ips: {e}")
                    
                    self.postgres_conn.commit()
                    cursor.close()
                    self.logger.debug("log_event", message=f"📊 Logs de IP {ip} marcados como bloqueados en PostgreSQL")
                except Exception as e:
                    self.logger.error("error_occurred", message=f"Error actualizando logs de IP {ip} en PostgreSQL: {e}")
                    if self.postgres_conn:
                        self.postgres_conn.rollback()
        except Exception as e:
            self.logger.error("error_occurred", message=f"❌ Error bloqueando IP {ip} desde análisis de ventana: {e}", exc_info=True)
    
    def _handle_result(self, result: Dict[str, Any]):
        """Maneja el resultado del procesamiento con lógica de bloqueo correcta"""
        action = result.get('action')
        severity = result.get('severity', 'low')
        patterns = result.get('patterns', [])
        log = result.get('log', {})
        threat_type = result.get('threat_type')
        needs_mitigation = result.get('needs_mitigation', False)
        
        # Verificar si ya fue bloqueado por WAF (403)
        status = log.get('status', 200)
        is_waf_blocked = (status == 403) or log.get('blocked', False)
        
        # Log de amenazas críticas
        if severity == 'high' or action == 'block_ip':
            self.logger.warning("log_event", message=f"🚨 AMENAZA CRÍTICA: IP={log.get('ip')}, "
                         f"Action={action}, Severity={severity}, Type={threat_type}, "
                         f"WAF Blocked={is_waf_blocked}, Needs Mitigation={needs_mitigation}")
        
        # Log de patrones detectados
        if patterns:
            for pattern in patterns:
                self.logger.info("log_event", message=f"📊 PATRÓN DETECTADO: {pattern.get('pattern_type')} - "
                          f"IP={pattern.get('ip')}, Severity={pattern.get('severity')}")
        
        # Lógica de bloqueo: solo 403 = blocked
        # Si es ataque y NO fue bloqueado por WAF, enviar a mitigación
        if needs_mitigation or (action == 'block_ip' and not is_waf_blocked):
            # Enviar decisión de mitigación al mitigation service
            if self.send_to_mitigation and self.producer:
                try:
                    # Preparar mensaje para mitigation service
                    mitigation_message = {
                        'log': log,
                        'action': 'block_ip',  # Aplicar bloqueo
                        'severity': severity,
                        'threat_type': threat_type,
                        'ml_prediction': result.get('ml_prediction'),
                        'knn_prediction': result.get('knn_prediction'),
                        'kmeans_prediction': result.get('kmeans_prediction'),
                        'llm_analysis': result.get('llm_analysis'),
                        'patterns': patterns,
                        'tenant_id': log.get('tenant_id', 'default'),
                        'timestamp': datetime.now().isoformat(),
                        'reason': result.get('mitigation_reason', f"Threat detected: {severity} severity, type: {threat_type}"),
                        'classification_source': result.get('classification_source', 'ml'),
                        'waf_blocked': is_waf_blocked,
                        'needs_mitigation': True
                    }
                    
                    # Agregar información adicional
                    # Para ataques críticos detectados por heurísticas, usar duración más larga
                    if result.get('classification_source') == 'heuristic' and severity == 'high':
                        mitigation_message['duration'] = 86400  # 24 horas para ataques críticos
                    else:
                        mitigation_message['duration'] = 3600  # 1 hora por defecto
                    mitigation_message['ip'] = log.get('ip')
                    mitigation_message['return_403'] = True  # CRÍTICO: Devolver 403 en lugar del status original
                    
                    # Enviar a Kafka
                    self.producer.send(self.threats_topic, value=mitigation_message)
                    self.metrics['mitigations_sent'] += 1
                    
                    self.logger.warning("log_event", message=f"🛡️ MITIGACIÓN AUTOMÁTICA: IP={log.get('ip')}, "
                                 f"Threat={threat_type}, Action=block_ip, Status={status}, "
                                 f"Return403=True, Duration={mitigation_message['duration']}s")
                
                except Exception as e:
                    self.logger.error("error_occurred", message=f"Error enviando decisión de mitigación: {e}", exc_info=True)
        
        # Si solo necesita monitoreo (no bloqueo inmediato)
        elif action == 'monitor' and self.send_to_mitigation and self.producer:
            try:
                mitigation_message = {
                    'log': log,
                    'action': 'monitor',
                    'severity': severity,
                    'threat_type': threat_type,
                    'ml_prediction': result.get('ml_prediction'),
                    'llm_analysis': result.get('llm_analysis'),
                    'patterns': patterns,
                    'tenant_id': log.get('tenant_id', 'default'),
                    'timestamp': datetime.now().isoformat(),
                    'reason': f"Threat detected: {severity} severity - monitoring",
                    'classification_source': result.get('classification_source', 'ml'),
                    'waf_blocked': is_waf_blocked
                }
                
                self.producer.send(self.threats_topic, value=mitigation_message)
                self.logger.debug("log_event", message=f"Monitoreo enviado: IP={log.get('ip')}, Threat={threat_type}")
            
            except Exception as e:
                self.logger.error("error_occurred", message=f"Error enviando monitoreo: {e}", exc_info=True)
        
        # FASE 7: Calcular latencia end-to-end al final del procesamiento
        log_start_time = result.get('_log_start_time') or log.get('_start_time') or time.time()
        end_to_end_latency = (time.time() - log_start_time) * 1000
        self.metrics['end_to_end_latency_ms'].append(end_to_end_latency)
        
        return result
    
    def start(self):
        """Inicia el procesamiento de streams"""
        self.logger.info("log_event", message="🚀 Iniciando Kafka Streams Processor...")
        
        # Inicializar consumer
        self._initialize_consumer()
        
        # Manejar señales para shutdown graceful
        def signal_handler(sig, frame):
            self.logger.info("log_event", message="Señal de interrupción recibida, cerrando...")
            self.stop()
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Iniciar cleanup worker si está habilitado
        if self.cleanup_worker:
            try:
                self.cleanup_worker.start()
                self.logger.info("log_event", message="✅ IntelligentCleanupWorker iniciado en background")
            except Exception as e:
                self.logger.warning("error_occurred", message=f"Error iniciando cleanup worker: {e}")
        
        # Iniciar baseline trainer si está habilitado
        if self.baseline_trainer and ADVANCED_DETECTION_AVAILABLE and ImprovementsConfig.ENABLE_ANOMALY_DETECTION:
            try:
                self.baseline_trainer.start()
                self.logger.info("log_event", message="✅ BaselineTrainer iniciado en background")
            except Exception as e:
                self.logger.warning("error_occurred", message=f"Error iniciando baseline trainer: {e}")
        
        self.running = True
        self.logger.info("log_event", message="✅ Procesador iniciado, esperando logs...")
        
        # Contador de errores consecutivos para reinicio automático
        consecutive_errors = 0
        max_consecutive_errors = 10
        cycle_count = 0
        last_health_log = time.time()
        
        try:
            while self.running:
                try:
                    cycle_count += 1
                    current_time = time.time()
                    
                    # Poll de mensajes (batch)
                    message_pack = self.consumer.poll(timeout_ms=1000)
                    if message_pack:
                        self.logger.info("log_event", message=f"📦 Poll recibió {sum(len(msgs) for msgs in message_pack.values())} mensajes de {len(message_pack)} particiones")
                        consecutive_errors = 0  # Resetear contador si hay mensajes
                    
                    # FALLBACK: Leer logs de BD periódicamente (cada 30 segundos)
                    # Esto asegura que aunque los logs no lleguen a Kafka, el procesador los procese
                    # Se ejecuta independientemente de si hay mensajes en Kafka
                    if self.postgres_enabled:
                        if current_time - self.last_db_poll >= self.db_poll_interval:
                            try:
                                logs_processed = self._process_logs_from_db()
                                if logs_processed and logs_processed > 0:
                                    self.logger.info("log_event", message=f"📥 Procesados {logs_processed} logs desde BD (fallback)")
                                self.last_db_poll = current_time
                            except Exception as e:
                                self.logger.error("error_occurred", message=f"Error en _process_logs_from_db: {e}", exc_info=True)
                                # No detener el procesador, continuar
                        
                        # DESACTIVADO: _quick_dashboard_scan ha sido REEMPLAZADO por análisis por episodios
                        # Las decisiones ahora se toman exclusivamente en _process_episode()
                        # No ejecutar paneo rápido, solo procesar episodios
                        
                        # NUEVO: Flush episodios antiguos (cada 5 minutos)
                        # Cierra episodios que no han recibido logs recientes
                        if self.episode_enabled and self.episode_builder:
                            if not hasattr(self, 'last_episode_flush'):
                                self.last_episode_flush = current_time
                            
                            if current_time - self.last_episode_flush >= 300:  # Cada 5 minutos
                                closed_episodes = self.episode_builder.flush_old_episodes(max_age_seconds=600)
                                for closed_episode in closed_episodes:
                                    threading.Thread(
                                        target=self._process_episode,
                                        daemon=True,
                                        args=(closed_episode,),
                                        name="ProcessFlushedEpisode"
                                    ).start()
                                self.last_episode_flush = current_time
                        
                        # NUEVO: Learning Loop - verificar si hay suficientes etiquetas para reentrenar
                        if self.learning_loop and current_time - self.last_retrain >= self.retrain_interval:
                            threading.Thread(
                                target=self.learning_loop.check_and_retrain,
                                daemon=True,
                                name="LearningLoop"
                            ).start()
                            self.last_retrain = current_time
                        
                        # NUEVO: Actualizar baseline de episodios normales (cada hora)
                        if self.episode_enhancer:
                            if not hasattr(self, 'last_baseline_update'):
                                self.last_baseline_update = current_time
                            
                            if current_time - self.last_baseline_update >= 3600:  # Cada hora
                                threading.Thread(
                                    target=self._update_baseline_background,
                                    daemon=True,
                                    name="UpdateBaseline"
                                ).start()
                                self.last_baseline_update = current_time
                    
                    # Health check logging cada 60 segundos
                    if current_time - last_health_log >= 60:
                        active_episodes = len(self.episode_builder.active_episodes) if (self.episode_enabled and self.episode_builder) else 0
                        self.logger.info(f"💚 Health check: {self.metrics['total_logs_processed']} logs procesados, "
                                  f"{active_episodes} episodios activos, ciclo #{cycle_count}")
                        last_health_log = current_time
                    
                    if not message_pack:
                        continue
                    
                    # Procesar cada mensaje
                    for topic_partition, messages in message_pack.items():
                        for message in messages:
                            try:
                                self.logger.debug("log_event", message=f"📥 Mensaje recibido de {topic_partition.topic}:{topic_partition.partition}")
                                log = message.value
                                
                                # CRÍTICO: Normalizar log antes de procesar (igual que dashboard)
                                log = _normalize_log_for_episodes(log)
                                
                                # Guardar tiempo de inicio para calcular latencia end-to-end
                                log_start_time = time.time()
                                log['_start_time'] = log_start_time
                                
                                # Extraer metadata de Kafka para actualizar el log en PostgreSQL
                                kafka_metadata = {
                                    'topic': message.topic,
                                    'partition': message.partition,
                                    'offset': message.offset
                                }
                                
                                # Procesar log
                                result = self._process_log(log, kafka_metadata=kafka_metadata)
                                result['log'] = log  # Asegurar que el log esté en el result
                                result['_log_start_time'] = log_start_time  # Guardar tiempo de inicio para latencia
                                
                                # Manejar resultado
                                self._handle_result(result)
                                
                                # Actualizar métricas
                                self.metrics['total_logs_processed'] += 1
                                
                                # Log cada 100 logs
                                if self.metrics['total_logs_processed'] % 100 == 0:
                                    elapsed = time.time() - self.metrics['start_time']
                                    rate = self.metrics['total_logs_processed'] / elapsed if elapsed > 0 else 0
                                    self.logger.info(f"📊 Procesados {self.metrics['total_logs_processed']} logs "
                                              f"({rate:.1f} logs/seg)")
                            
                            except Exception as e:
                                self.logger.error("error_occurred", message=f"Error procesando mensaje: {e}", exc_info=True)
                                consecutive_errors += 1
                                # Si hay muchos errores consecutivos, esperar un poco antes de continuar
                                if consecutive_errors >= max_consecutive_errors:
                                    self.logger.warning("error_occurred", message=f"⚠️ {consecutive_errors} errores consecutivos, esperando 5s antes de continuar...")
                                    time.sleep(5)
                                    consecutive_errors = 0  # Resetear después de esperar
                    
                        # Commit de offsets (solo si no hay errores críticos)
                        try:
                            self.consumer.commit()
                        except Exception as e:
                            self.logger.error("error_occurred", message=f"Error haciendo commit de offsets: {e}", exc_info=True)
                            # No detener el procesador por errores de commit
                    
                    # Health check: verificar que los componentes estén funcionando
                    if self.episode_enabled and self.episode_builder:
                        try:
                            active_episodes_count = len(self.episode_builder.active_episodes)
                            if active_episodes_count > 0:
                                self.logger.debug("log_event", message=f"💚 Health check: {active_episodes_count} episodios activos")
                        except Exception as e:
                            self.logger.warning("error_occurred", message=f"⚠️ Error en health check de episodios: {e}")
                    
                    # Resetear contador de errores si pasó suficiente tiempo
                    if consecutive_errors > 0:
                        time.sleep(0.1)  # Pequeña pausa para no saturar
                
                except Exception as e:
                    consecutive_errors += 1
                    self.logger.error("error_occurred", message=f"Error en loop principal: {e}", exc_info=True)
                    # No detener el procesador, continuar intentando
                    if consecutive_errors >= max_consecutive_errors:
                        self.logger.warning("error_occurred", message=f"⚠️ {consecutive_errors} errores consecutivos en loop principal, esperando 10s...")
                        time.sleep(10)
                        consecutive_errors = 0
                    else:
                        time.sleep(1)  # Esperar 1 segundo antes de reintentar
                
                except Exception as e:
                    consecutive_errors += 1
                    self.logger.error("error_occurred", message=f"Error en loop principal: {e}", exc_info=True)
                    # No detener el procesador, continuar intentando
                    if consecutive_errors >= max_consecutive_errors:
                        self.logger.warning("error_occurred", message=f"⚠️ {consecutive_errors} errores consecutivos en loop principal, esperando 10s...")
                        time.sleep(10)
                        consecutive_errors = 0
                    else:
                        time.sleep(1)  # Esperar 1 segundo antes de reintentar
        
        except KeyboardInterrupt:
            self.logger.info("log_event", message="Interrupción recibida")
        except Exception as e:
            self.logger.error("error_occurred", message=f"Error crítico en procesamiento: {e}", exc_info=True)
            # Intentar reiniciar componentes críticos en lugar de detenerse
            try:
                self.logger.info("log_event", message="🔄 Intentando reiniciar componentes...")
                if hasattr(self, 'consumer') and self.consumer:
                    try:
                        self.consumer.close()
                    except:
                        pass
                self._initialize_consumer()
                self.logger.info("log_event", message="✅ Componentes reiniciados, continuando...")
                # Continuar el loop en lugar de detenerse
                self.running = True
            except Exception as restart_error:
                self.logger.error("error_occurred", message=f"❌ Error crítico al reiniciar: {restart_error}", exc_info=True)
        finally:
            if not self.running:
                self.stop()
    
    def _process_logs_from_db(self) -> int:
        """
        FALLBACK: Lee logs nuevos de la base de datos y los procesa como si vinieran de Kafka.
        Esto asegura que aunque los logs no lleguen a Kafka, el procesador los procese.
        
        Returns:
            int: Número de logs procesados
        """
        if not self.postgres_enabled:
            return 0
        
        # CRÍTICO: Verificar y reconectar si la conexión está cerrada
        try:
            if not self.postgres_conn or self.postgres_conn.closed != 0:
                self.logger.warning("log_event", message="⚠️ Conexión PostgreSQL cerrada, reconectando...")
                self._init_postgres()
                if not self.postgres_conn or self.postgres_conn.closed != 0:
                    self.logger.error("log_event", message="❌ No se pudo reconectar a PostgreSQL")
                    return 0
        except Exception as e:
            self.logger.warning("error_occurred", message=f"⚠️ Error verificando conexión PostgreSQL: {e}, reconectando...")
            try:
                self._init_postgres()
                if not self.postgres_conn or self.postgres_conn.closed != 0:
                    self.logger.error("error_occurred", message="❌ No se pudo reconectar a PostgreSQL después del error")
                    return 0
            except Exception as reconnect_error:
                self.logger.error("error_occurred", message=f"❌ Error reconectando a PostgreSQL: {reconnect_error}")
                return 0
        
        try:
            from psycopg2.extras import RealDictCursor
            cursor = self.postgres_conn.cursor(cursor_factory=RealDictCursor)
            
            # Leer logs nuevos desde la última vez que leímos
            # Leer TODOS los logs nuevos basándose solo en timestamp (no importa si tienen kafka_topic)
            # Esto asegura que procesemos logs aunque no hayan pasado por Kafka
            # OPTIMIZACIÓN: Límite dinámico basado en tiempo disponible
            # Objetivo: usar máximo 25s de los 30s disponibles (dejar 5s de margen)
            time_budget = 25  # segundos
            estimated_time_per_log = 0.01  # 10ms por log (estimación conservadora)
            max_logs = int(time_budget / estimated_time_per_log)  # ~2,500 logs
            
            # Límite mínimo y máximo para evitar extremos
            max_logs = max(500, min(max_logs, 2000))  # Entre 500 y 2000 logs
            
            if self.last_db_poll_timestamp:
                cursor.execute("""
                    SELECT * FROM waf_logs
                    WHERE timestamp > %s
                    ORDER BY timestamp ASC
                    LIMIT %s
                """, (self.last_db_poll_timestamp, max_logs))
            else:
                # Primera vez: leer logs de los últimos 10 minutos para no perder actividad reciente
                cursor.execute("""
                    SELECT * FROM waf_logs
                    WHERE timestamp > NOW() - INTERVAL '10 minutes'
                    ORDER BY timestamp ASC
                    LIMIT %s
                """, (max_logs,))
            
            logs = cursor.fetchall()
            cursor.close()
            
            if logs:
                self.logger.info("log_event", message=f"📥 Leyendo {len(logs)} logs nuevos de la base de datos (fallback)")
                
                for row in logs:
                    try:
                        # Convertir row a dict
                        log = dict(row)
                        
                        # Convertir objetos datetime a strings ISO para serialización JSON
                        from datetime import datetime, date
                        for key, value in log.items():
                            if isinstance(value, (datetime, date)):
                                log[key] = value.isoformat()
                        
                        # CRÍTICO: Normalizar log antes de procesar (igual que dashboard)
                        # Esto asegura que EpisodeBuilder reciba los campos correctos
                        log = _normalize_log_for_episodes(log)
                        
                        # Actualizar último timestamp procesado
                        if log.get('timestamp'):
                            if isinstance(log['timestamp'], str):
                                try:
                                    log_timestamp = datetime.fromisoformat(log['timestamp'].replace('Z', '+00:00'))
                                except:
                                    log_timestamp = datetime.now()
                            else:
                                log_timestamp = log['timestamp']
                            
                            if self.last_db_poll_timestamp is None or log_timestamp > self.last_db_poll_timestamp:
                                self.last_db_poll_timestamp = log_timestamp
                        
                        # Procesar log como si viniera de Kafka (sin kafka_metadata)
                        log_start_time = time.time()
                        log['_start_time'] = log_start_time
                        
                        # Procesar log
                        result = self._process_log(log, kafka_metadata=None)
                        result['log'] = log
                        result['_log_start_time'] = log_start_time
                        
                        # Manejar resultado
                        self._handle_result(result)
                        
                        # Actualizar métricas
                        self.metrics['total_logs_processed'] += 1
                        
                    except Exception as e:
                        self.logger.error("error_occurred", message=f"Error procesando log de BD: {e}", exc_info=True)
                        # Continuar con el siguiente log en lugar de detenerse
                        continue
                
                return len(logs)  # Retornar cantidad procesada
        except Exception as e:
            self.logger.warning("error_occurred", message=f"Error leyendo logs de BD (fallback): {e}", exc_info=True)
            # No detener el procesador, solo loguear el error
            # El siguiente ciclo intentará de nuevo
            return 0
    
    def _quick_dashboard_scan(self):
        """
        Paneo rápido tipo dashboard: Lee logs recientes de BD y los analiza visualmente
        como un analista humano mirando el dashboard. Detecta:
        - Escaneos repetidos (misma IP o diferentes IPs)
        - Bypasses de WAF (ataques que pasaron pero deberían estar bloqueados)
        - Patrones sospechosos obvios
        """
        if not self.postgres_enabled or not self.postgres_conn:
            return
        
        try:
            from psycopg2.extras import RealDictCursor
            from datetime import datetime, timedelta
            cursor = self.postgres_conn.cursor(cursor_factory=RealDictCursor)
            
            # Leer logs de los últimos 3 minutos (paneo rápido)
            cursor.execute("""
                SELECT ip, method, uri, status, threat_type, classification_source, timestamp, user_agent
                FROM waf_logs
                WHERE timestamp > NOW() - INTERVAL '3 minutes'
                ORDER BY timestamp DESC
                LIMIT 500
            """)
            
            logs = cursor.fetchall()
            cursor.close()
            
            if not logs or len(logs) < 5:
                return  # No hay suficientes logs para analizar
            
            self.logger.info("log_event", message=f"👁️ PANEO RÁPIDO: Analizando {len(logs)} logs recientes (últimos 3 minutos) como dashboard visual...")
            
            # Agrupar por IP para análisis visual
            ip_summary = {}
            for row in logs:
                ip = row.get('ip', 'unknown')
                if ip == 'unknown' or not ip:
                    continue
                
                if ip not in ip_summary:
                    ip_summary[ip] = {
                        'ip': ip,
                        'total_requests': 0,
                        'unique_endpoints': set(),
                        'threat_types': {},
                        'waf_blocked': 0,  # status 403
                        'bypass_detected': 0,  # Ataques que NO fueron bloqueados por WAF pero deberían
                        'scan_patterns': set(),
                        'recent_logs': []
                    }
                
                summary = ip_summary[ip]
                summary['total_requests'] += 1
                summary['unique_endpoints'].add(row.get('uri', ''))
                
                status = row.get('status', 200)
                if isinstance(status, str):
                    try:
                        status = int(status)
                    except:
                        status = 200
                
                if status == 403:
                    summary['waf_blocked'] += 1
                
                threat_type = row.get('threat_type', '') or ''
                if threat_type:
                    summary['threat_types'][threat_type] = summary['threat_types'].get(threat_type, 0) + 1
                
                # Detectar bypass: amenaza detectada pero status != 403
                uri = (row.get('uri') or '').lower()
                if threat_type and threat_type != 'NONE' and status != 403:
                    # Es un ataque que pasó el WAF (bypass)
                    summary['bypass_detected'] += 1
                    
                    # Detectar patrones de escaneo
                    scan_patterns = ['.env', '.git', '/wp-', '/admin', '/phpmyadmin', '/config', 'passwd', '.%2e', '%2e%2e', '/cgi-bin/']
                    if any(pattern in uri for pattern in scan_patterns):
                        summary['scan_patterns'].add(uri)
                
                # Guardar muestra de logs recientes (últimos 10 por IP)
                if len(summary['recent_logs']) < 10:
                    summary['recent_logs'].append({
                        'timestamp': row.get('timestamp'),
                        'uri': row.get('uri'),
                        'status': status,
                        'threat_type': threat_type,
                        'method': row.get('method', 'GET')
                    })
            
            # Preparar resumen para LLM (formato tipo dashboard)
            suspicious_ips = []
            for ip, summary in ip_summary.items():
                unique_endpoints = len(summary['unique_endpoints'])
                
                # Criterios para considerar IP sospechosa:
                # 1. Muchos bypasses (ataques que pasaron WAF)
                # 2. Escaneo repetido (muchos endpoints únicos)
                # 3. Múltiples amenazas
                # 4. Muchos bloqueos WAF (escaneo agresivo)
                
                is_suspicious = (
                    summary['bypass_detected'] >= 1 or  # 1+ ataques que pasaron WAF (MUY crítico)
                    unique_endpoints >= 3 or  # 3+ endpoints diferentes (escaneo)
                    len(summary['threat_types']) >= 1 or  # Cualquier tipo de amenaza
                    summary['waf_blocked'] >= 2 or  # 2+ bloqueos WAF
                    summary['total_requests'] >= 5  # Muchas requests en poco tiempo
                )
                
                if is_suspicious:
                    suspicious_ips.append({
                        'ip': ip,
                        'total_requests': summary['total_requests'],
                        'unique_endpoints': unique_endpoints,
                        'threat_types': dict(summary['threat_types']),
                        'waf_blocked': summary['waf_blocked'],
                        'bypass_detected': summary['bypass_detected'],
                        'scan_patterns': list(summary['scan_patterns'])[:5],  # Primeros 5
                        'sample_logs': summary['recent_logs']
                    })
            
            if not suspicious_ips:
                self.logger.debug("log_event", message="👁️ PANEO RÁPIDO: No se detectaron IPs sospechosas en logs recientes")
                return
            
            self.logger.info("log_event", message=f"👁️ PANEO RÁPIDO: Detectadas {len(suspicious_ips)} IPs sospechosas para análisis")
            
            # Analizar con LLM como si fuera un analista mirando el dashboard
            if self.enable_llm and self.llm_analyzer:
                analysis_result = self.llm_analyzer.analyze_dashboard_scan(suspicious_ips)
                
                if analysis_result.get('analyzed') and analysis_result.get('success'):
                    ips_to_block = analysis_result.get('ips_to_block', [])
                    reasoning = analysis_result.get('reasoning', '')
                    
                    if ips_to_block:
                        self.logger.warning("log_event", message=f"🚨 PANEO RÁPIDO: {len(ips_to_block)} IPs deben ser bloqueadas: {reasoning[:150]}")
                        
                        for ip_data in ips_to_block:
                            ip = ip_data.get('ip') if isinstance(ip_data, dict) else ip_data
                            duration = ip_data.get('block_duration_seconds', 3600) if isinstance(ip_data, dict) else 3600
                            
                            # Bloquear IP
                            self._block_ip_from_dashboard_scan(ip, ip_summary.get(ip, {}), duration, reasoning)
        
        except Exception as e:
            self.logger.error("error_occurred", message=f"❌ Error en paneo rápido tipo dashboard: {e}", exc_info=True)
    
    def _block_ip_from_dashboard_scan(self, ip: str, ip_summary: Dict[str, Any], 
                                       duration_seconds: int, reasoning: str):
        """
        Bloquea una IP detectada por paneo rápido tipo dashboard.
        """
        try:
            from datetime import datetime, timedelta
            
            self.logger.warning("log_event", message=f"🚨 BLOQUEANDO IP {ip} desde paneo rápido: {reasoning[:150]}")
            
            # Determinar threat_type y severity basándose en el resumen
            threat_types = ip_summary.get('threat_types', {})
            primary_threat = max(threat_types.items(), key=lambda x: x[1])[0] if threat_types else 'SCAN_PROBE'
            
            # Severity basado en bypass_detected y waf_blocked
            bypass_count = ip_summary.get('bypass_detected', 0)
            waf_blocked = ip_summary.get('waf_blocked', 0)
            
            if bypass_count >= 2 or waf_blocked >= 5:
                severity = 'high'
            elif bypass_count >= 1 or waf_blocked >= 2:
                severity = 'medium'
            else:
                severity = 'low'
            
            expires_at = datetime.now() + timedelta(seconds=duration_seconds)
            
            # Guardar en blocked_ips
            if self.postgres_enabled and self.postgres_conn:
                try:
                    cursor = self.postgres_conn.cursor()
                    cursor.execute("""
                        INSERT INTO blocked_ips (ip, blocked_at, expires_at, reason, classification_source, threat_type, severity)
                        VALUES (%s, NOW(), %s, %s, 'dashboard_quick_scan', %s, %s)
                        ON CONFLICT (ip) DO UPDATE SET
                            blocked_at = NOW(),
                            expires_at = EXCLUDED.expires_at,
                            reason = EXCLUDED.reason,
                            classification_source = EXCLUDED.classification_source,
                            threat_type = EXCLUDED.threat_type,
                            severity = EXCLUDED.severity
                    """, (ip, expires_at, reasoning[:500], primary_threat, severity))
                    self.postgres_conn.commit()
                    cursor.close()
                    self.logger.info("log_event", message=f"✅ IP {ip} bloqueada desde paneo rápido (duración: {duration_seconds}s)")
                except Exception as e:
                    self.logger.error("error_occurred", message=f"Error guardando IP bloqueada desde paneo rápido: {e}", exc_info=True)
                    if self.postgres_conn:
                        self.postgres_conn.rollback()
            
            # Enviar a mitigation service
            if self.producer and self.send_to_mitigation:
                try:
                    mitigation_message = {
                        'action': 'block_ip',
                        'ip': ip,
                        'reason': reasoning[:200],
                        'threat_type': primary_threat,
                        'severity': severity,
                        'duration_seconds': duration_seconds,
                        'expires_at': expires_at.isoformat(),
                        'source': 'dashboard_quick_scan',
                        'timestamp': datetime.now().isoformat()
                    }
                    self.producer.send(self.threats_topic, value=mitigation_message)
                    self.logger.info("log_event", message=f"✅ Mensaje de mitigación enviado para IP {ip}")
                except Exception as e:
                    self.logger.error("error_occurred", message=f"Error enviando mensaje de mitigación: {e}", exc_info=True)
        
        except Exception as e:
            self.logger.error("error_occurred", message=f"❌ Error bloqueando IP desde paneo rápido: {e}", exc_info=True)
    
    def _should_allow_common_paths(self, episode: Dict[str, Any]) -> bool:
        """
        Verifica si las URLs son paths comunes que NO deberían bloquearse.
        Retorna True si debe permitirse (no bloquear).
        """
        sample_uris = episode.get('sample_uris', [])
        if not sample_uris:
            return False
        
        # CRÍTICO: Paths comunes que SIEMPRE deben estar permitidos
        common_paths = ['/', '/robots.txt', '/favicon.ico', '/sitemap.xml', '/health', '/status', '/index.html', '/logo-tokio-removebg-preview.png']
        total_requests = episode.get('total_requests', 0)
        threat_types = episode.get('threat_types', {}) or {}
        
        # CRÍTICO: Si hay threat crítico confirmado, NO permitir aunque sea path común
        critical_threats = {'PATH_TRAVERSAL', 'XSS', 'SQLI', 'CMD_INJECTION', 'SSRF'}
        has_critical = any(threat in critical_threats for threat in threat_types.keys()) if threat_types else False
        
        if has_critical:
            return False  # No permitir paths comunes si hay ataque crítico
        
        # Verificar si todas las URLs son paths comunes
        from urllib.parse import urlparse
        all_common = True
        for uri in sample_uris[:5]:  # Verificar primeros 5
            parsed = urlparse(uri)
            path = parsed.path
            
            if path not in common_paths:
                all_common = False
                break
        
        # Si todas son comunes Y solo hay 1-3 requests, probablemente es legítimo
        if all_common and total_requests <= 3:
            return True
        
        return False
    
    def _process_episode(self, episode: Dict[str, Any]):
        """
        Procesa un episodio completo:
        1. Calcula risk_score local (sin LLM)
        2. Si UNCERTAIN → consulta LLM
        3. Guarda en BD
        4. Si BLOCK → bloquea IP
        
        Args:
            episode: Episodio con features agregadas
        """
        try:
            src_ip = episode.get('src_ip', 'unknown')
            if src_ip == 'unknown' or not src_ip:
                return
            
            self.logger.info("log_event", message=f"📊 Procesando episodio: IP={src_ip}, requests={episode.get('total_requests', 0)}, "
                       f"unique_uris={episode.get('unique_uris', 0)}")
            
            # 1. Buscar episodios similares usando EpisodeMemory (memoria persistente)
            similar_episodes = []
            similar_score = None
            if self.episode_memory:
                # Preparar features para búsqueda
                episode_features = {
                    'total_requests': episode.get('total_requests', 0),
                    'unique_uris': episode.get('unique_uris', 0),
                    'request_rate': episode.get('request_rate', 0),
                    'status_code_ratio': episode.get('status_code_ratio', {}),
                    'presence_flags': episode.get('presence_flags', {}),
                    'path_entropy_avg': episode.get('path_entropy_avg', 0),
                    'threat_types': episode.get('threat_types', {})
                }
                
                similar_episodes = self.episode_memory.find_similar_episodes(
                    episode_features, limit=5, min_similarity=0.6
                )
                
                if similar_episodes:
                    # Usar el más similar como referencia
                    top_similar = similar_episodes[0]
                    similarity = top_similar['similarity_score']
                    label = top_similar['analyst_label']
                    
                    self.logger.info("log_event", message=f"💾 Memoria: Encontrado episodio similar (similarity={similarity:.2f}, label={label})")
                    
                    # Si el label es un ataque, usar similarity como score
                    if label != 'ALLOW':
                        similar_score = similarity * 0.8  # Ponderar un poco menos
                    else:
                        similar_score = (1 - similarity) * 0.3  # Si es ALLOW, reducir score
            
            # 2. Decisión local (sin LLM)
            if not self.local_decision:
                self.logger.warning("log_event", message="LocalDecisionLayer no disponible, saltando análisis de episodio")
                return
            
            decision_result = self.local_decision.calculate_risk_score(episode, similar_score)
            decision = decision_result['decision']
            risk_score = decision_result['risk_score']
            
            self.logger.info(f"📊 Episodio IP={src_ip}: risk_score={risk_score:.2f}, decision={decision}, "
                       f"heuristic={decision_result.get('heuristic_score', 0):.2f}, "
                       f"ml={decision_result.get('ml_score', 0):.2f}")
            
            # 2.5. NUEVO: Verificar contra baseline de URLs válidas ANTES de enhancement
            # CRÍTICO: NO verificar baseline si hay threat_types críticos confirmados
            baseline_check = None
            threat_types_pre = episode.get('threat_types', {}) or {}
            critical_threats_pre = {'PATH_TRAVERSAL', 'XSS', 'SQLI', 'CMD_INJECTION', 'SSRF'}
            has_critical_threat_pre = any(threat in critical_threats_pre for threat in threat_types_pre.keys()) if threat_types_pre else False
            
            if has_critical_threat_pre:
                # CRÍTICO: Si hay threat crítico, NO verificar baseline (ahorra tiempo y evita falsos negativos)
                self.logger.warning("log_event", message=f"⚠️ Threat crítico detectado ({', '.join(threat_types_pre.keys())}), saltando verificación de baseline")
                baseline_check = None  # Asegurar que baseline_check es None
            elif BASELINE_AVAILABLE and self.baseline_manager:
                # Solo verificar baseline si NO hay threats críticos confirmados
                baseline_check = self._check_episode_against_baseline(episode)
                
                # Si todas las URLs son válidas, reducir riesgo significativamente
                if baseline_check and baseline_check.get('all_urls_valid'):
                    # Reducir risk_score
                    original_risk = decision_result.get('risk_score', 0.5)
                    adjusted_risk = max(0.0, original_risk + baseline_check.get('baseline_adjustment', 0.0))
                    decision_result['risk_score'] = adjusted_risk
                    risk_score = adjusted_risk
                    
                    # Si el riesgo ajustado es muy bajo, cambiar decisión a ALLOW
                    if adjusted_risk < 0.3:
                        decision = 'ALLOW'
                        decision_result['decision'] = 'ALLOW'
                        self.logger.info(f"✅ Episodio con URLs válidas conocidas, NO bloqueando "
                                   f"(risk ajustado: {original_risk:.2f} → {adjusted_risk:.2f})")
                    else:
                        self.logger.info(f"⚠️ Episodio con URLs válidas pero riesgo aún alto "
                                  f"(risk ajustado: {original_risk:.2f} → {adjusted_risk:.2f})")
                
                # Si mayoría de URLs son válidas, reducir riesgo moderadamente
                elif baseline_check and baseline_check.get('valid_urls_count', 0) > baseline_check.get('invalid_urls_count', 0):
                    original_risk = decision_result.get('risk_score', 0.5)
                    adjusted_risk = max(0.0, original_risk + baseline_check.get('baseline_adjustment', 0.0))
                    decision_result['risk_score'] = adjusted_risk
                    risk_score = adjusted_risk
                    
                    self.logger.debug(f"📋 Mayoría de URLs válidas, risk ajustado: "
                                f"{original_risk:.2f} → {adjusted_risk:.2f}")
            
            # 2.6. NUEVO: Mejorar análisis con detección avanzada (zero-day, ofuscación, DDoS)
            enhancement = None
            if self.episode_enhancer:
                try:
                    enhancement = self.episode_enhancer.enhance_episode_analysis(
                        episode, decision_result
                    )
                    
                    # Actualizar decision_result con enhanced_risk_score
                    if enhancement['enhanced_risk_score'] > risk_score:
                        decision_result['risk_score'] = enhancement['enhanced_risk_score']
                        risk_score = enhancement['enhanced_risk_score']
                        
                        # Si enhanced_risk es alto, cambiar decision a UNCERTAIN para forzar LLM
                        if enhancement['enhanced_risk_score'] > 0.7 and decision == 'ALLOW':
                            decision = 'UNCERTAIN'
                            decision_result['decision'] = 'UNCERTAIN'
                            self.logger.info("log_event", message=f"⚠️ Enhanced risk alto ({enhancement['enhanced_risk_score']:.2f}), "
                                      f"forzando UNCERTAIN para consultar LLM")
                    
                    # Log de detecciones avanzadas
                    if enhancement['zero_day_risk']:
                        self.logger.warning(f"🚨 ZERO-DAY RISK detectado en episodio IP={src_ip} "
                                     f"(score={enhancement['analysis_details']['zero_day']['score']:.2f})")
                    if enhancement['obfuscation_detected']:
                        self.logger.warning(f"🔍 OFUSCACIÓN detectada en episodio IP={src_ip} "
                                     f"(score={enhancement['analysis_details']['obfuscation']['score']:.2f})")
                    if enhancement['ddos_risk']:
                        ddos_details = enhancement['analysis_details']['ddos']
                        # NUEVO: Guardar IPs coordinadas en el episodio para bloquearlas todas
                        coordinated_ips = []
                        for attack_detail in ddos_details.get('details', []):
                            if 'ips' in attack_detail:
                                coordinated_ips.extend(attack_detail['ips'])
                        
                        # Guardar IPs coordinadas en intelligence_analysis para uso posterior
                        if coordinated_ips:
                            if not episode.get('intelligence_analysis'):
                                episode['intelligence_analysis'] = {}
                            episode['intelligence_analysis']['coordinated_attack_ips'] = list(set(coordinated_ips))
                            self.logger.warning(f"🌐 DDoS RISK detectado: {ddos_details['coordinated_attacks']} ataques coordinados, "
                                         f"{ddos_details['total_suspicious_episodes']} episodios sospechosos, "
                                         f"{len(set(coordinated_ips))} IPs involucradas")
                    
                    # Guardar información de baseline en intelligence_analysis
                    if baseline_check:
                        if not episode.get('intelligence_analysis'):
                            episode['intelligence_analysis'] = {}
                        episode['intelligence_analysis']['baseline_check'] = {
                            'all_urls_valid': baseline_check.get('all_urls_valid', False),
                            'valid_urls_count': baseline_check.get('valid_urls_count', 0),
                            'invalid_urls_count': baseline_check.get('invalid_urls_count', 0),
                            'baseline_adjustment': baseline_check.get('baseline_adjustment', 0.0)
                        }
                    
                except Exception as e:
                    self.logger.error("error_occurred", message=f"Error en enhancement de episodio: {e}", exc_info=True)
                    enhancement = None
            
            # 3. PASO 3 - COLAPSO COGNITIVO: Si UNCERTAIN → intentar Transformer primero, luego LLM
            llm_analysis = None
            llm_consulted = False
            transformer_used = False
            
            if decision == 'UNCERTAIN' and (0.3 <= risk_score <= 0.8):
                # SOLO si episodio es incierto, intentar resolver con Transformer primero (más rápido/barato)
                # Luego, si Transformer no resuelve, consultar LLM
                
                # 3.1. Intentar Transformer primero (más rápido que LLM)
                if self._ensure_transformer_initialized() and self.transformer_predictor:
                    try:
                        # Usar el primer log del episodio para análisis
                        sample_log = episode.get('logs', [None])[0] if episode.get('logs') else None
                        if sample_log:
                            self.logger.info("log_event", message=f"🔍 Episodio UNCERTAIN, intentando resolver con Transformer primero: IP={src_ip}")
                            transformer_start = time.time()
                            transformer_pred = self.transformer_predictor.predict(sample_log)
                            transformer_latency = (time.time() - transformer_start) * 1000
                            self.metrics['transformer_predictions'] += 1
                            self.metrics['fallback_to_transformer'] += 1
                            self.metrics['transformer_latency_ms'].append(transformer_latency)
                            transformer_used = True
                            
                            if transformer_pred and transformer_pred.get('success'):
                                transformer_confidence = transformer_pred.get('confidence', 0.0)
                                transformer_is_threat = transformer_pred.get('is_threat', False)
                                transformer_is_uncertain = transformer_pred.get('is_uncertain', False)
                                
                                # Si Transformer tiene alta confianza, usarlo y actualizar decision
                                if transformer_confidence > 0.7 and not transformer_is_uncertain:
                                    if transformer_is_threat:
                                        decision = 'BLOCK'
                                        risk_score = 0.9
                                        decision_result['decision'] = 'BLOCK'
                                        decision_result['risk_score'] = 0.9
                                        self.logger.info("log_event", message=f"✅ Transformer resolvió: BLOCK (confidence={transformer_confidence:.2f})")
                                    else:
                                        decision = 'ALLOW'
                                        risk_score = 0.2
                                        decision_result['decision'] = 'ALLOW'
                                        decision_result['risk_score'] = 0.2
                                        self.logger.info("log_event", message=f"✅ Transformer resolvió: ALLOW (confidence={transformer_confidence:.2f})")
                                elif transformer_is_uncertain:
                                    self.logger.debug("log_event", message=f"⚠️ Transformer también tiene duda, consultando LLM")
                    except Exception as e:
                        self.logger.warning("error_occurred", message=f"Error en predicción transformer para episodio: {e}")
                
                # 3.2. Si sigue UNCERTAIN después de Transformer, consultar LLM
                if decision == 'UNCERTAIN' and self.enable_llm and self.llm_analyzer:
                    self.logger.info("log_event", message=f"🤖 Episodio sigue UNCERTAIN, consultando LLM: IP={src_ip}")
                    try:
                        llm_analysis = self.llm_analyzer.analyze_episode(episode)
                        llm_consulted = True
                        # Asegurar que llm_analysis es un diccionario
                        if not isinstance(llm_analysis, dict):
                            self.logger.error("log_event", message=f"❌ LLM retornó tipo inesperado: {type(llm_analysis)}, valor: {llm_analysis}")
                            llm_analysis = {'success': False, 'analyzed': False, 'label': 'ALLOW', 'confidence': 0.5}
                    except Exception as e:
                        self.logger.error("error_occurred", message=f"❌ Error en análisis de episodio: {e}", exc_info=True)
                        llm_analysis = {'success': False, 'analyzed': False, 'label': 'ALLOW', 'confidence': 0.5}
                
                # Verificar que llm_analysis sea un diccionario antes de usar .get()
                if llm_analysis and isinstance(llm_analysis, dict) and llm_analysis.get('analyzed'):
                    llm_label = llm_analysis.get('label', 'ALLOW')
                    llm_confidence = llm_analysis.get('confidence', 0.5)
                    
                    # Actualizar decisión basándose en LLM
                    if llm_label != 'ALLOW':
                        decision = 'BLOCK'
                        self.logger.info("log_event", message=f"🤖 LLM decidió BLOQUEAR: {llm_label} (confidence={llm_confidence:.2f})")
                    else:
                        decision = 'ALLOW'
                        self.logger.info("log_event", message=f"🤖 LLM decidió PERMITIR (confidence={llm_confidence:.2f})")
            
            # 4. NUEVO: Verificar si es un patrón inusual (Early Alert System)
            alert = None
            if self.early_alert:
                episode['episode_id'] = None  # Aún no tiene ID
                alert = self.early_alert.check_unusual_pattern(episode)
                if alert:
                    self.logger.warning(f"🚨 ALERTA TEMPRANA: Patrón inusual detectado - "
                                 f"IP={episode.get('src_ip')}, rarity={alert.get('rarity_score', 0):.2f}")
                    llm_info = alert.get('llm_analysis') or {}
                    if isinstance(llm_info, dict) and llm_info.get('should_alert_human'):
                        self.logger.warning("log_event", message=f"⚠️ LLM recomienda alertar al analista humano: {llm_info.get('assessment', '')}")
            
            # 5. CRÍTICO: Verificar y aplicar bloqueos ANTES de guardar en BD
            # Esto asegura que el episodio se guarde con la decisión correcta (BLOCK si debe bloquearse)
            #    a) Decisión es BLOCK, O
            #    b) Hay threat_types confirmados (PATH_TRAVERSAL, XSS, SQLI, etc.) incluso si decision es ALLOW/UNCERTAIN
            # NUEVO: NO bloquear si todas las URLs son válidas según baseline
            should_block = False
            block_reason = ""
            
            # Verificar baseline: si todas las URLs son válidas, NO bloquear
            # PERO: Si hay threat_types críticos confirmados (PATH_TRAVERSAL, XSS, SQLI, etc.), 
            # IGNORAR el baseline y bloquear de todas formas (el baseline puede tener falsos positivos)
            threat_types = episode.get('threat_types', {}) or {}
            critical_threats = {'PATH_TRAVERSAL', 'XSS', 'SQLI', 'CMD_INJECTION', 'SSRF'}
            has_critical_threat = any(threat in critical_threats for threat in threat_types.keys()) if threat_types else False
            
            if baseline_check and baseline_check.get('all_urls_valid') and not has_critical_threat:
                # Solo permitir si NO hay threats críticos confirmados
                should_block = False
                block_reason = "URLs válidas conocidas según baseline"
                decision = 'ALLOW'
                decision_result['decision'] = 'ALLOW'
                self.logger.info("log_event", message=f"✅ NO bloqueando: Todas las URLs son válidas según baseline (sin threats críticos)")
                
                # CRÍTICO: Si todas las URLs están en baseline, eliminar SCAN_PROBE de threat_types
                threat_types = episode.get('threat_types', {}) or {}
                if 'SCAN_PROBE' in threat_types and baseline_check.get('all_urls_valid'):
                    self.logger.info("log_event", message=f"✅ URLs en baseline detectadas, removiendo SCAN_PROBE de threat_types")
                    del threat_types['SCAN_PROBE']
                    episode['threat_types'] = threat_types
            elif has_critical_threat:
                # CRÍTICO: Si hay threat crítico confirmado, BLOQUEAR independientemente del baseline
                should_block = True
                block_reason = f"Threat crítico confirmado ({', '.join(threat_types.keys())}) - ignorando baseline"
                decision = 'BLOCK'
                decision_result['decision'] = 'BLOCK'
                if decision_result.get('risk_score', 0) < 0.8:
                    decision_result['risk_score'] = 0.9
                self.logger.warning("log_event", message=f"🚨 BLOQUEANDO por threat crítico confirmado (baseline ignorado): {', '.join(threat_types.keys())}")
            elif decision == 'BLOCK':
                should_block = True
                block_reason = "decision=BLOCK"
            else:
                # Verificar si hay threat_types confirmados que requieren bloqueo inmediato
                threat_types = episode.get('threat_types', {}) or {}
                critical_threats = {'PATH_TRAVERSAL', 'XSS', 'SQLI', 'CMD_INJECTION', 'SSRF'}
                
                # NUEVO: Si no hay threat_types, inferir SCAN_PROBE desde:
                # 1. Presence flags fuertes (wp-, .git, cgi-bin)
                # 2. Patrones de comportamiento (muchos URIs únicos, muchos 4xx, etc.)
                if not threat_types:
                    presence_flags = episode.get('presence_flags', {}) or {}
                    total_requests = episode.get('total_requests', 0)
                    unique_uris = episode.get('unique_uris', 0)
                    status_ratio = episode.get('status_code_ratio', {}) or {}
                    fourxx_ratio = status_ratio.get('4xx', 0)
                    
                    self.logger.debug("log_event", message=f"🔍 Verificando patrones de escaneo: presence_flags={presence_flags}, requests={total_requests}, unique_uris={unique_uris}, 4xx_ratio={fourxx_ratio:.2%}")
                    
                    # 1. Inferir SCAN_PROBE desde presence flags sospechosos
                    scan_flags = ['wp-', '.git', 'cgi-bin']
                    has_scan_flags = any(presence_flags.get(flag, False) for flag in scan_flags)
                    
                    # 2. Inferir SCAN_PROBE desde patrones de comportamiento
                    # - Muchos URIs únicos (>= 10) en muchos requests (>= 10) = escaneo claro
                    # - Muchos 4xx (>= 40%) + muchos URIs únicos (>= 8) = escaneo
                    # - Request rate moderado-alto (> 1 req/s) + muchos URIs únicos (>= 8) = escaneo
                    has_scan_pattern = (
                        (unique_uris >= 10 and total_requests >= 10) or  # Muchos endpoints diferentes
                        (fourxx_ratio >= 0.4 and unique_uris >= 8 and total_requests >= 8) or  # Muchos 4xx + muchos endpoints
                        (episode.get('request_rate', 0) > 1.0 and unique_uris >= 8 and total_requests >= 8)  # Rate alto + muchos endpoints
                    )
                    
                    if has_scan_flags or has_scan_pattern:
                        # Inferir SCAN_PROBE
                        threat_types = {'SCAN_PROBE': total_requests}
                        detected_flags = [flag for flag in scan_flags if presence_flags.get(flag, False)]
                        pattern_reason = []
                        if has_scan_flags:
                            pattern_reason.append(f"flags={detected_flags}")
                        if has_scan_pattern:
                            pattern_reason.append(f"pattern(uris={unique_uris}, requests={total_requests}, 4xx={fourxx_ratio:.1%})")
                        self.logger.warning("log_event", message=f"🔍 Infiriendo SCAN_PROBE: {', '.join(pattern_reason)}")
                
                # Si hay threat_types confirmados, bloquear inmediatamente
                if threat_types:
                    detected_threats = set(threat_types.keys())
                    critical_detected = detected_threats.intersection(critical_threats)
                    
                    if critical_detected:
                        should_block = True
                        block_reason = f"confirmed_attack ({', '.join(critical_detected)})"
                        # Forzar decisión a BLOCK para consistencia
                        decision = 'BLOCK'
                        decision_result['decision'] = 'BLOCK'
                        # Aumentar risk_score si es bajo
                        if decision_result.get('risk_score', 0) < 0.8:
                            decision_result['risk_score'] = 0.9
                        self.logger.warning("log_event", message=f"🚨 Ataque confirmado detectado, forzando BLOCK: {', '.join(critical_detected)}")
                    elif 'SCAN_PROBE' in detected_threats:
                        # SCAN_PROBE: bloquear si:
                        # 1. Presence flags fuertes (wp-, .git, cgi-bin, .env) con 5+ requests (aumentado de 3)
                        # 2. Patrón de escaneo detectado (muchos URIs únicos, muchos 4xx, etc.) con 15+ requests (aumentado de 8)
                        # 3. 20+ requests (aumentado de 10) - escaneo extenso
                        # IMPORTANTE: Verificar primero si hay etiquetas ALLOW para esta IP
                        
                        src_ip = episode.get('src_ip')
                        has_allow_label = False
                        
                        # Verificar si hay etiquetas ALLOW recientes para esta IP
                        if self.postgres_enabled and self.postgres_conn and src_ip:
                            try:
                                cursor = self.postgres_conn.cursor()
                                cursor.execute("""
                                    SELECT COUNT(*) 
                                    FROM analyst_labels al
                                    INNER JOIN episodes e ON al.episode_id = e.episode_id
                                    WHERE e.src_ip = %s::inet 
                                    AND al.analyst_label = 'ALLOW'
                                    AND al.timestamp > NOW() - INTERVAL '30 days'
                                    LIMIT 1
                                """, (src_ip,))
                                allow_count = cursor.fetchone()[0]
                                cursor.close()
                                
                                if allow_count > 0:
                                    has_allow_label = True
                                    self.logger.info("log_event", message=f"✅ IP {src_ip} tiene {allow_count} etiqueta(s) ALLOW reciente(s), siendo más permisivo con SCAN_PROBE")
                            except Exception as e:
                                self.logger.debug("error_occurred", message=f"Error verificando etiquetas ALLOW para {src_ip}: {e}")
                        
                        presence_flags = episode.get('presence_flags', {}) or {}
                        scan_flags = ['wp-', '.git', 'cgi-bin', '.env']
                        has_strong_scan_flags = any(presence_flags.get(flag, False) for flag in scan_flags)
                        total_requests = episode.get('total_requests', 0)
                        unique_uris = episode.get('unique_uris', 0)
                        status_ratio = episode.get('status_code_ratio', {}) or {}
                        fourxx_ratio = status_ratio.get('4xx', 0)
                        
                        # Si hay etiquetas ALLOW, aumentar umbrales significativamente
                        scan_threshold_multiplier = 2.0 if has_allow_label else 1.0
                        
                        # Detectar si es un patrón de escaneo claro (ya usado para inferir SCAN_PROBE)
                        # Aumentar umbrales para ser menos agresivo
                        min_unique_uris_scan = int(10 * scan_threshold_multiplier)
                        min_requests_scan = int(10 * scan_threshold_multiplier)
                        min_requests_pattern = int(8 * scan_threshold_multiplier)
                        
                        is_scan_pattern = (
                            (unique_uris >= min_unique_uris_scan and total_requests >= min_requests_scan) or
                            (fourxx_ratio >= 0.5 and unique_uris >= min_requests_pattern and total_requests >= min_requests_pattern) or  # Aumentado de 0.4 a 0.5
                            (episode.get('request_rate', 0) > 2.0 and unique_uris >= min_requests_pattern and total_requests >= min_requests_pattern)  # Aumentado de 1.0 a 2.0
                        )
                        
                        # Umbrales aumentados para ser menos agresivo
                        min_requests_flags = int(5 * scan_threshold_multiplier)  # Aumentado de 3 a 5
                        min_requests_pattern_block = int(15 * scan_threshold_multiplier)  # Aumentado de 8 a 15
                        min_requests_extensive = int(20 * scan_threshold_multiplier)  # Aumentado de 10 a 20
                        
                        # Solo bloquear si NO hay etiquetas ALLOW y cumple umbrales
                        if not has_allow_label:
                            if has_strong_scan_flags and total_requests >= min_requests_flags:
                                # Presence flags fuertes + umbral aumentado = escaneo claro
                                should_block = True
                                block_reason = f"scan_probe_with_flags (requests={total_requests}, flags={[flag for flag in scan_flags if presence_flags.get(flag, False)]})"
                                decision = 'BLOCK'
                                decision_result['decision'] = 'BLOCK'
                                if decision_result.get('risk_score', 0) < 0.7:
                                    decision_result['risk_score'] = 0.8
                                self.logger.warning("log_event", message=f"🚨 SCAN_PROBE con presence flags fuertes detectado, forzando BLOCK: {block_reason}")
                            elif is_scan_pattern and total_requests >= min_requests_pattern_block:
                                # Patrón de escaneo claro detectado (muchos URIs únicos, muchos 4xx, etc.) = escaneo
                                should_block = True
                                block_reason = f"scan_probe_pattern (requests={total_requests}, unique_uris={unique_uris}, 4xx_ratio={fourxx_ratio:.1%})"
                                decision = 'BLOCK'
                                decision_result['decision'] = 'BLOCK'
                                if decision_result.get('risk_score', 0) < 0.7:
                                    decision_result['risk_score'] = 0.8
                                self.logger.warning("log_event", message=f"🚨 SCAN_PROBE con patrón de escaneo detectado, forzando BLOCK: {block_reason}")
                            elif total_requests >= min_requests_extensive:
                                # 20+ requests sin patrones claros = escaneo extenso
                                should_block = True
                                block_reason = f"scan_probe_extensive (requests={total_requests})"
                                decision = 'BLOCK'
                                decision_result['decision'] = 'BLOCK'
                                if decision_result.get('risk_score', 0) < 0.7:
                                    decision_result['risk_score'] = 0.8
                        else:
                            self.logger.info("log_event", message=f"ℹ️ IP {src_ip} tiene etiquetas ALLOW, NO bloqueando por SCAN_PROBE (requests={total_requests}, unique_uris={unique_uris})")
            
            # CRÍTICO: Verificar paths comunes SOLO si NO hay threats críticos
            # Si hay PATH_TRAVERSAL, XSS, SQLI, etc., SIEMPRE bloquear (ignorar paths comunes)
            threat_types_final = episode.get('threat_types', {}) or {}
            critical_threats_final = {'PATH_TRAVERSAL', 'XSS', 'SQLI', 'CMD_INJECTION', 'SSRF'}
            has_critical_final = any(threat in critical_threats_final for threat in threat_types_final.keys()) if threat_types_final else False
            
            # Solo verificar paths comunes si NO hay threats críticos y aún no se decidió bloquear
            if not should_block and decision != 'BLOCK' and not has_critical_final:
                if self._should_allow_common_paths(episode):
                    self.logger.info("log_event", message=f"✅ Paths comunes detectados, NO bloqueando: {episode.get('sample_uris', [])[:3]}")
                    should_block = False
                    decision = 'ALLOW'
                    decision_result['decision'] = 'ALLOW'
                    # Continuar guardando pero como ALLOW (no rompe flujo existente)
            elif has_critical_final:
                # CRÍTICO: Si hay threat crítico, SIEMPRE bloquear (incluso si es path común)
                should_block = True
                decision = 'BLOCK'
                decision_result['decision'] = 'BLOCK'
                self.logger.warning("log_event", message=f"🚨 Threat crítico detectado ({', '.join(threat_types_final.keys())}), bloqueando a pesar de paths comunes")
            
            # 6. Guardar episodio en BD (ahora con la decisión correcta si debe bloquearse)
            episode_id = self._save_episode_to_db(episode, decision_result, llm_analysis, llm_consulted, alert)
            
            # 7. Actualizar episode_id en alert si existe
            if alert and episode_id:
                alert['episode_id'] = episode_id
            
            # 8. Ejecutar bloqueo de IP si corresponde (ahora con episode_id)
            if should_block:
                self.logger.warning("log_event", message=f"🚨 BLOQUEANDO IP {episode.get('src_ip')} - Razón: {block_reason}")
                self._block_ip_from_episode(episode, decision_result, llm_analysis, episode_id, alert)
            
            # 8.5. NUEVO: Si hay ataque coordinado con SCAN_PROBE, bloquear TODAS las IPs involucradas
            threat_types_final_block = episode.get('threat_types', {}) or {}
            intelligence_analysis_final = episode.get('intelligence_analysis', {}) or {}
            coordinated_ips = intelligence_analysis_final.get('coordinated_attack_ips', [])
            src_ip_final = episode.get('src_ip')
            
            # Si hay SCAN_PROBE Y hay IPs coordinadas (ataque distribuido), bloquear TODAS
            if 'SCAN_PROBE' in threat_types_final_block and coordinated_ips:
                self.logger.warning("log_event", message=f"🌐 ATAQUE DISTRIBUIDO SCAN_PROBE detectado: bloqueando {len(coordinated_ips)} IPs coordinadas")
                for coord_ip in coordinated_ips:
                    if coord_ip and coord_ip != src_ip_final:  # No bloquear la IP actual dos veces
                        try:
                            # Crear un episodio mínimo para bloquear esta IP
                            coord_episode = {
                                'src_ip': coord_ip,
                                'threat_types': {'SCAN_PROBE': 1},
                                'total_requests': 1,
                                'intelligence_analysis': {
                                    'coordinated_attack': True,
                                    'coordinated_attack_ips': coordinated_ips
                                }
                            }
                            coord_decision_result = {
                                'decision': 'BLOCK',
                                'risk_score': 0.85,  # Alto riesgo para ataques coordinados
                                'threat_type': 'SCAN_PROBE',
                                'severity': 'high',
                                'confidence': 0.9
                            }
                            coord_block_reason = f"SCAN_PROBE distribuido coordinado ({len(coordinated_ips)} IPs)"
                            self.logger.warning("log_event", message=f"🚨 BLOQUEANDO IP coordinada {coord_ip} - Razón: {coord_block_reason}")
                            self._block_ip_from_episode(coord_episode, coord_decision_result, None, None, None)
                        except Exception as e:
                            self.logger.error("error_occurred", message=f"Error bloqueando IP coordinada {coord_ip}: {e}", exc_info=True)
            
            # 9. Si hay episodios similares, actualizar cache de similitud
            if similar_episodes and episode_id:
                self._update_similarity_cache(episode_id, similar_episodes)
            
            # 10. NUEVO: Actualizar baseline si episodio es normal
            if self.episode_enhancer and decision == 'ALLOW' and not episode.get('threat_types'):
                # Agregar a cola para actualizar baseline (se procesa en background)
                try:
                    self.episode_enhancer.recent_normal_episodes.append(episode)
                except Exception as e:
                    self.logger.debug("error_occurred", message=f"Error agregando episodio normal al baseline: {e}")
        
        except Exception as e:
            self.logger.error("error_occurred", message=f"❌ Error procesando episodio: {e}", exc_info=True)
    
    def _save_episode_to_db(self, episode: Dict[str, Any], decision_result: Dict[str, Any],
                            llm_analysis: Optional[Dict[str, Any]], llm_consulted: bool,
                            alert: Optional[Dict[str, Any]] = None) -> Optional[int]:
        """
        Guarda episodio en tabla episodes de BD.
        
        Returns:
            episode_id si se guardó exitosamente, None si no
        """
        if not self.postgres_enabled or not self.postgres_conn:
            return None
        
        try:
            import json
            from datetime import datetime
            
            cursor = self.postgres_conn.cursor()
            
            # Preparar datos
            tenant_id = episode.get('tenant_id')
            if isinstance(tenant_id, str):
                tenant_id = int(tenant_id) if tenant_id.isdigit() else None
            src_ip = episode.get('src_ip')
            ua_hash = episode.get('user_agent_hash')
            episode_start = episode.get('episode_start')
            episode_end = episode.get('episode_end')
            
            if isinstance(episode_start, str):
                episode_start = datetime.fromisoformat(episode_start.replace('Z', '+00:00'))
            if isinstance(episode_end, str):
                episode_end = datetime.fromisoformat(episode_end.replace('Z', '+00:00'))
            
            # Guardar episodio
            sample_uris = episode.get('sample_uris', [])[:10]  # Máximo 10 URIs
            
            # NUEVO: Obtener intelligence_analysis si existe
            intelligence_analysis = episode.get('intelligence_analysis')
            intelligence_analysis_json = json.dumps(intelligence_analysis) if intelligence_analysis else None
            
            # Intentar con sample_uris e intelligence_analysis primero
            try:
                cursor.execute("""
                    INSERT INTO episodes (
                        tenant_id, src_ip, user_agent_hash, episode_start, episode_end,
                        total_requests, unique_uris, methods_count, status_code_ratio,
                        presence_flags, path_entropy_avg, request_rate, risk_score,
                        decision, llm_consulted, llm_label, llm_confidence, sample_uris,
                        intelligence_analysis
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    ) RETURNING episode_id
                """, (
                    tenant_id,
                    src_ip,
                    ua_hash,
                    episode_start,
                    episode_end,
                    episode.get('total_requests', 0),
                    episode.get('unique_uris', 0),
                    json.dumps(episode.get('methods_count', {})),
                    json.dumps(episode.get('status_code_ratio', {})),
                    json.dumps(episode.get('presence_flags', {})),
                    episode.get('path_entropy_avg', 0),
                    episode.get('request_rate', 0),
                    decision_result.get('risk_score', 0),
                    decision_result.get('decision', 'UNCERTAIN'),
                    llm_consulted,
                    llm_analysis.get('label') if llm_analysis else None,
                    llm_analysis.get('confidence') if llm_analysis else None,
                    json.dumps(sample_uris),
                    intelligence_analysis_json
                ))
            except Exception as col_error:
                # Si falla porque sample_uris no existe, hacer rollback y intentar sin sample_uris
                if 'sample_uris' in str(col_error).lower() or 'column' in str(col_error).lower():
                    self.logger.warning("log_event", message=f"⚠️ Columna sample_uris no existe, haciendo rollback y guardando episodio sin sample_uris")
                    self.postgres_conn.rollback()
                    # Necesitamos un nuevo cursor después del rollback
                    cursor.close()
                    cursor = self.postgres_conn.cursor()
                    
                    # Intentar con intelligence_analysis pero sin sample_uris
                    try:
                        cursor.execute("""
                            INSERT INTO episodes (
                                tenant_id, src_ip, user_agent_hash, episode_start, episode_end,
                                total_requests, unique_uris, methods_count, status_code_ratio,
                                presence_flags, path_entropy_avg, request_rate, risk_score,
                                decision, llm_consulted, llm_label, llm_confidence,
                                intelligence_analysis
                            ) VALUES (
                                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                            ) RETURNING episode_id
                        """, (
                            tenant_id,
                            src_ip,
                            ua_hash,
                            episode_start,
                            episode_end,
                            episode.get('total_requests', 0),
                            episode.get('unique_uris', 0),
                            json.dumps(episode.get('methods_count', {})),
                            json.dumps(episode.get('status_code_ratio', {})),
                            json.dumps(episode.get('presence_flags', {})),
                            episode.get('path_entropy_avg', 0),
                            episode.get('request_rate', 0),
                            decision_result.get('risk_score', 0),
                            decision_result.get('decision', 'UNCERTAIN'),
                            llm_consulted,
                            llm_analysis.get('label') if llm_analysis else None,
                            llm_analysis.get('confidence') if llm_analysis else None,
                            intelligence_analysis_json
                        ))
                    except Exception as intel_error:
                        # Si intelligence_analysis tampoco existe, guardar sin ese campo
                        if 'intelligence_analysis' in str(intel_error).lower() or 'column' in str(intel_error).lower():
                            self.logger.warning("log_event", message=f"⚠️ Columna intelligence_analysis no existe, guardando episodio sin intelligence_analysis")
                            self.postgres_conn.rollback()
                            cursor.close()
                            cursor = self.postgres_conn.cursor()
                            cursor.execute("""
                                INSERT INTO episodes (
                                    tenant_id, src_ip, user_agent_hash, episode_start, episode_end,
                                    total_requests, unique_uris, methods_count, status_code_ratio,
                                    presence_flags, path_entropy_avg, request_rate, risk_score,
                                    decision, llm_consulted, llm_label, llm_confidence
                                ) VALUES (
                                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                                ) RETURNING episode_id
                            """, (
                                tenant_id,
                                src_ip,
                                ua_hash,
                                episode_start,
                                episode_end,
                                episode.get('total_requests', 0),
                                episode.get('unique_uris', 0),
                                json.dumps(episode.get('methods_count', {})),
                                json.dumps(episode.get('status_code_ratio', {})),
                                json.dumps(episode.get('presence_flags', {})),
                                episode.get('path_entropy_avg', 0),
                                episode.get('request_rate', 0),
                                decision_result.get('risk_score', 0),
                                decision_result.get('decision', 'UNCERTAIN'),
                                llm_consulted,
                                llm_analysis.get('label') if llm_analysis else None,
                                llm_analysis.get('confidence') if llm_analysis else None
                            ))
                        else:
                            raise
                else:
                    raise  # Re-lanzar si es otro error
            
            episode_id = cursor.fetchone()[0]
            self.postgres_conn.commit()
            cursor.close()
            
            self.logger.info("log_event", message=f"✅ Episodio guardado en BD: episode_id={episode_id}, decision={decision_result.get('decision')}")
            return episode_id
        
        except Exception as e:
            self.logger.error("error_occurred", message=f"Error guardando episodio en BD: {e}", exc_info=True)
            if self.postgres_conn:
                self.postgres_conn.rollback()
            return None
    
    def _check_episode_against_baseline(self, episode: Dict[str, Any]) -> Dict[str, Any]:
        """
        Verifica si las URLs del episodio están en el baseline de URLs válidas.
        Si todas las URLs son válidas, reduce el risk_score significativamente.
        
        Returns:
            Dict con:
            - all_urls_valid: bool
            - valid_urls_count: int
            - invalid_urls_count: int
            - baseline_adjustment: float (ajuste al risk_score)
        """
        if not BASELINE_AVAILABLE or not self.baseline_manager:
            return {
                'all_urls_valid': False,
                'valid_urls_count': 0,
                'invalid_urls_count': 0,
                'baseline_adjustment': 0.0
            }
        
        try:
            from site_baseline.persistence import is_path_valid, get_valid_paths
            from urllib.parse import urlparse
            
            # Obtener paths del episodio
            sample_uris = episode.get('sample_uris', [])
            if not sample_uris:
                return {
                    'all_urls_valid': False,
                    'valid_urls_count': 0,
                    'invalid_urls_count': 0,
                    'baseline_adjustment': 0.0
                }
            
            # Obtener baseline de paths válidos
            tenant_id = self.config.get('tenant_id')
            valid_paths = get_valid_paths(tenant_id=tenant_id)
            
            if not valid_paths:
                # Baseline no está listo aún
                self.logger.debug("log_event", message="Baseline no disponible aún, no se puede verificar URLs")
                return {
                    'all_urls_valid': False,
                    'valid_urls_count': 0,
                    'invalid_urls_count': 0,
                    'baseline_adjustment': 0.0
                }
            
            # CRÍTICO: Paths comunes que SIEMPRE deben estar permitidos
            always_allowed_paths = {
                '/', '/favicon.ico', '/robots.txt', '/sitemap.xml',
                '/logo-tokio-removebg-preview.png', '/logo-tokio-removebg-preview.png?',
                '/health', '/status', '/index.html', '/index.php'
            }
            
            # Verificar cada URI del episodio
            valid_count = 0
            invalid_count = 0
            valid_paths_found = []
            invalid_paths_found = []
            
            for uri in sample_uris[:10]:  # Verificar hasta 10 URIs
                # Extraer path de la URI
                parsed = urlparse(uri)
                path = parsed.path
                
                # Normalizar path (remover trailing slash para comparación)
                path_normalized = path.rstrip('/') or '/'
                
                # CRÍTICO: Verificar si está en paths siempre permitidos PRIMERO
                if path_normalized in always_allowed_paths or any(
                    allowed_path.rstrip('/') == path_normalized 
                    for allowed_path in always_allowed_paths
                ):
                    valid_count += 1
                    valid_paths_found.append(path)
                    continue
                
                # Luego verificar si el path está en el baseline de la BD
                if is_path_valid(path, tenant_id=tenant_id):
                    valid_count += 1
                    valid_paths_found.append(path)
                else:
                    invalid_count += 1
                    invalid_paths_found.append(path)
            
            # Calcular ajuste al risk_score
            total_checked = valid_count + invalid_count
            if total_checked == 0:
                baseline_adjustment = 0.0
            else:
                valid_ratio = valid_count / total_checked
                
                # Si todas las URLs son válidas → reducir riesgo significativamente
                if valid_ratio == 1.0:
                    baseline_adjustment = -0.4  # Reducir riesgo en 0.4
                    all_urls_valid = True
                elif valid_ratio >= 0.8:
                    baseline_adjustment = -0.2  # Reducir riesgo en 0.2
                    all_urls_valid = False
                elif valid_ratio >= 0.5:
                    baseline_adjustment = -0.1  # Reducir riesgo en 0.1
                    all_urls_valid = False
                else:
                    baseline_adjustment = 0.0  # No ajustar
                    all_urls_valid = False
            
            self.logger.debug(f"📋 Baseline check: {valid_count}/{total_checked} URLs válidas, "
                        f"ajuste: {baseline_adjustment:.2f}")
            
            return {
                'all_urls_valid': all_urls_valid,
                'valid_urls_count': valid_count,
                'invalid_urls_count': invalid_count,
                'baseline_adjustment': baseline_adjustment,
                'valid_paths': valid_paths_found,
                'invalid_paths': invalid_paths_found
            }
            
        except Exception as e:
            self.logger.error("error_occurred", message=f"Error verificando baseline: {e}", exc_info=True)
            return {
                'all_urls_valid': False,
                'valid_urls_count': 0,
                'invalid_urls_count': 0,
                'baseline_adjustment': 0.0
            }
    
    def _calculate_intelligent_block_duration(
        self,
        risk_score: float,
        threat_types: Dict[str, Any],
        zero_day_risk: bool,
        ddos_risk: bool,
        obfuscation_detected: bool,
        detected_critical: bool,
        total_requests: int,
        unique_uris: int,
        llm_analysis: Optional[Dict[str, Any]]
    ) -> int:
        """
        Calcula duración inteligente adaptativa del bloqueo basándose en:
        - Enhanced risk score
        - Detecciones avanzadas (zero-day, DDoS, ofuscación)
        - Tipo y severidad de amenaza
        - Volumen de ataque
        
        Retorna duración en segundos.
        """
        
        # CRÍTICO: Verificar threat_types correctamente (puede ser {} o None)
        has_known_threats = bool(threat_types and len(threat_types) > 0)
        
        # PRIORIDAD 1: SCAN_PROBE - MOVER PRIMERO (antes de zero-day/DDoS)
        # Si hay SCAN_PROBE conocido, ignorar zero-day/DDoS (son falsos positivos)
        if has_known_threats and 'SCAN_PROBE' in threat_types:
            # CRÍTICO: Para SCAN_PROBE, usar bloqueo MUY corto según volumen
            if total_requests >= 20:
                return 21600  # 6 horas (escaneo extenso)
            elif total_requests >= 10:
                return 3600  # 1 hora (escaneo moderado)
            elif total_requests >= 5:
                return 1800  # 30 minutos (escaneo básico)
            elif total_requests >= 3:
                return 900  # 15 minutos (escaneo mínimo)
            elif total_requests >= 2:
                return 600  # 10 minutos (muy básico)
            else:
                # CRÍTICO: 1 request de SCAN_PROBE = bloqueo MUY corto (NO 24h)
                return 300  # 5 minutos (NO 24 horas!)
        
        # PRIORIDAD 2: DDoS → Bloqueo largo PERO solo si hay evidencia real Y NO hay threats conocidos
        # CRÍTICO: Si tiene threat_types conocidos, NO es DDoS coordinado real
        if ddos_risk and not has_known_threats:
            # Solo considerar DDoS si NO hay threat_types conocidos
            if total_requests >= 10 and risk_score >= 0.7:
                return 86400  # 24 horas (DDoS real con muchos requests)
            elif total_requests >= 5:
                return 21600  # 6 horas (DDoS moderado)
            else:
                return 3600  # 1 hora (falso positivo de DDoS con pocos requests)
        
        # PRIORIDAD 3: Zero-Day → Bloqueo largo PERO solo si no hay threat_types conocidos
        # CRÍTICO: Si tiene threat_types conocidos, NO es zero-day real (es ataque conocido)
        # Ignorar zero_day_risk completamente si hay threat_types conocidos
        if zero_day_risk and not has_known_threats:
            # Solo considerar zero-day si NO hay threat_types conocidos
            if total_requests >= 5 and risk_score >= 0.7:
                return 43200  # 12 horas (zero-day real con evidencia)
            else:
                return 1800  # 30 minutos (posible falso positivo)
        
        # PRIORIDAD 4: LLM confirmó ataque → Bloqueo medio-largo según confianza Y volumen
        # IMPORTANTE: Ajustar según volumen de requests para evitar bloqueos excesivos
        if llm_analysis and llm_analysis.get('label') != 'ALLOW':
            confidence = llm_analysis.get('confidence', 0.5)
            
            # Si hay solo 1 request, usar bloqueo corto incluso con alta confianza
            if total_requests == 1:
                if confidence > 0.8:
                    return 900  # 15 minutos (alta confianza pero solo 1 request)
                elif confidence > 0.6:
                    return 600  # 10 minutos (confianza media pero solo 1 request)
                else:
                    return 300  # 5 minutos (confianza baja, solo 1 request)
            
            # Con múltiples requests, usar confianza para determinar duración
            if confidence > 0.8:
                if total_requests >= 20:
                    return 86400  # 24 horas (alta confianza + muchos requests)
                elif total_requests >= 10:
                    return 21600  # 6 horas (alta confianza + requests moderados)
                elif total_requests >= 5:
                    return 3600  # 1 hora (alta confianza + pocos requests)
                else:
                    return 900  # 15 minutos (alta confianza + muy pocos requests)
            elif confidence > 0.6:
                if total_requests >= 10:
                    return 21600  # 6 horas (confianza media + requests moderados)
                else:
                    return 1800  # 30 minutos (confianza media + pocos requests)
            else:
                return 600  # 10 minutos (confianza baja)
        
        # PRIORIDAD 5: Ataques críticos confirmados (PATH_TRAVERSAL, XSS, SQLI, etc.)
        # IMPORTANTE: Ajustar según volumen para evitar bloqueos excesivos
        if detected_critical:
            if total_requests >= 20:
                return 86400  # 24 horas (muchos requests - ataque masivo)
            elif total_requests >= 10:
                return 21600  # 6 horas (requests moderados - ataque sostenido)
            elif total_requests >= 5:
                return 3600  # 1 hora (requests moderados-bajos)
            elif total_requests >= 3:
                return 900  # 15 minutos (pocos requests - posible escaneo)
            else:
                # Un solo request con threat crítico → bloqueo muy corto (puede ser falso positivo o intento aislado)
                # CRÍTICO: 1 request no justifica bloqueo largo
                return 300  # 5 minutos (bloqueo mínimo para un solo request)
        
        # PRIORIDAD 6: Ofuscación detectada
        if obfuscation_detected:
            if risk_score >= 0.8:
                return 21600  # 6 horas (alto riesgo + ofuscación)
            else:
                return 3600  # 1 hora (riesgo medio + ofuscación)
        
        # PRIORIDAD 7: Basado en enhanced_risk_score Y volumen
        # Ajustar duración según risk_score Y cantidad de requests
        if risk_score >= 0.9:
            # Riesgo muy alto
            if total_requests >= 20:
                return 86400  # 24 horas (riesgo muy alto + muchos requests)
            elif total_requests >= 5:
                return 21600  # 6 horas (riesgo muy alto + requests moderados)
            else:
                return 3600  # 1 hora (riesgo muy alto pero pocos requests)
        elif risk_score >= 0.8:
            # Riesgo alto
            if total_requests >= 10:
                return 21600  # 6 horas (riesgo alto + requests moderados)
            elif total_requests >= 3:
                return 3600  # 1 hora (riesgo alto + pocos requests)
            else:
                return 900  # 15 minutos (riesgo alto pero solo 1-2 requests)
        elif risk_score >= 0.7:
            # Riesgo medio-alto
            if total_requests >= 5:
                return 3600  # 1 hora
            else:
                return 900  # 15 minutos (riesgo medio-alto pero pocos requests)
        elif risk_score >= 0.6:
            # Riesgo medio
            return 900  # 15 minutos (riesgo medio, bloqueo corto)
        elif risk_score >= 0.4:
            # Riesgo bajo-medio
            return 600  # 10 minutos (riesgo bajo-medio, bloqueo muy corto)
        else:
            # Riesgo bajo → bloqueo muy corto (auto-desbloqueo temprano)
            return 300  # 5 minutos (riesgo bajo, bloqueo mínimo)
    
    def _block_ip_from_episode(self, episode: Dict[str, Any], decision_result: Dict[str, Any],
                               llm_analysis: Optional[Dict[str, Any]], episode_id: Optional[int],
                               alert: Optional[Dict[str, Any]] = None):
        """
        Bloquea una IP detectada por análisis de episodio con duración inteligente adaptativa.
        Usa enhanced_risk_score e intelligence_analysis para calcular duración óptima.
        
        NUEVO: Integra sistema inteligente de bloqueo si está habilitado (bloqueo progresivo).
        """
        try:
            from datetime import datetime, timedelta
            
            src_ip = episode.get('src_ip')
            
            # NUEVO: Usar sistema inteligente si está habilitado (modo shadow o activo)
            intelligent_action = None
            if self.intelligent_blocking and ImprovementsConfig.ENABLE_INTELLIGENT_BLOCKING:
                try:
                    # Construir classification_result para el sistema inteligente
                    classification_result = {
                        'threat_type': decision_result.get('threat_type', 'NONE'),
                        'severity': decision_result.get('severity', 'medium'),
                        'confidence': decision_result.get('confidence', 0.7)
                    }
                    
                    # Analizar con sistema inteligente
                    intelligent_action = self.intelligent_blocking.analyze_and_decide(
                        episode, classification_result
                    )
                    
                    # Si está en modo shadow, solo loggear
                    if ImprovementsConfig.ENABLE_INTELLIGENT_BLOCKING_SHADOW:
                        self.logger.info(f"🔮 [SHADOW MODE] Sistema inteligente sugiere: {intelligent_action['action']} "
                                  f"(stage: {intelligent_action['stage'].value}, risk: {intelligent_action['risk_score']:.2f})")
                    else:
                        # Modo activo: usar decisión del sistema inteligente
                        self.logger.info(f"🧠 Sistema inteligente: {intelligent_action['action']} "
                                  f"(stage: {intelligent_action['stage'].value}, risk: {intelligent_action['risk_score']:.2f})")
                except Exception as e:
                    self.logger.warning("error_occurred", message=f"Error en sistema inteligente, usando lógica tradicional: {e}")
                    intelligent_action = None
            
            # NUEVO: Usar enhanced_risk_score si está disponible (más preciso)
            intelligence_analysis = episode.get('intelligence_analysis', {}) or {}
            enhanced_risk = intelligence_analysis.get('enhanced_risk_score')
            
            # Si sistema inteligente está activo y tiene risk_score, usarlo
            if intelligent_action and intelligent_action.get('risk_score') is not None:
                risk_score = intelligent_action['risk_score']
            else:
                risk_score = enhanced_risk if enhanced_risk is not None else decision_result.get('risk_score', 0.8)
            
            # Obtener block_stage si está disponible
            block_stage = None
            if intelligent_action and intelligent_action.get('stage'):
                block_stage = intelligent_action['stage'].value if hasattr(intelligent_action['stage'], 'value') else str(intelligent_action['stage'])
            
            # CRÍTICO: Leer valores de intelligence_analysis Y verificar threat_types
            zero_day_risk_raw = intelligence_analysis.get('zero_day_risk', False)
            ddos_risk_raw = intelligence_analysis.get('ddos_risk', False)
            
            threat_types = episode.get('threat_types', {}) or {}
            has_known_threats = bool(threat_types and len(threat_types) > 0)
            
            # CRÍTICO: Si hay threat_types conocidos, FORZAR zero-day/DDoS a False
            # (Por si el enhancement no se ejecutó correctamente)
            zero_day_risk = zero_day_risk_raw if not has_known_threats else False
            ddos_risk = ddos_risk_raw if not has_known_threats else False
            
            obfuscation_detected = intelligence_analysis.get('obfuscation_detected', False)
            
            critical_threats = {'PATH_TRAVERSAL', 'XSS', 'SQLI', 'CMD_INJECTION', 'SSRF'}
            detected_critical = any(threat in critical_threats for threat in threat_types.keys()) if threat_types else False
            
            total_requests = episode.get('total_requests', 0)
            unique_uris = episode.get('unique_uris', 0)
            
            # CRÍTICO: Asegurar que SCAN_PROBE con 1 request siempre use bloqueo corto
            # ANTES de calcular duración normal
            if has_known_threats and 'SCAN_PROBE' in threat_types and total_requests == 1:
                # FORZAR bloqueo corto para 1 request SCAN_PROBE
                duration_seconds = 300  # 5 minutos
                self.logger.info("log_event", message=f"🔒 SCAN_PROBE con 1 request detectado, usando bloqueo corto: 5 minutos (IP={episode.get('src_ip')})")
            else:
                # Calcular duración normal (pero NO usar llm_analysis si hay SCAN_PROBE conocido)
                llm_for_duration = None if (has_known_threats and 'SCAN_PROBE' in threat_types) else llm_analysis
                
                duration_seconds = self._calculate_intelligent_block_duration(
                    risk_score=risk_score,
                    threat_types=threat_types,
                    zero_day_risk=zero_day_risk,  # Usar valores corregidos
                    ddos_risk=ddos_risk,  # Usar valores corregidos
                    obfuscation_detected=obfuscation_detected,
                    detected_critical=detected_critical,
                    total_requests=total_requests,
                    unique_uris=unique_uris,
                    llm_analysis=llm_for_duration  # No usar LLM si hay SCAN_PROBE conocido
                )
            
            # Determinar threat_type y severity
            if llm_analysis and llm_analysis.get('label') != 'ALLOW':
                threat_type = llm_analysis.get('label', 'MULTIPLE_ATTACKS')
                severity = 'high' if llm_analysis.get('confidence', 0) > 0.7 else 'medium'
                reason = llm_analysis.get('reasoning', f'Episodio malicioso detectado (risk_score={risk_score:.2f})')
            elif threat_types:
                threat_type = max(threat_types.items(), key=lambda x: x[1])[0]
                severity = 'high' if detected_critical or risk_score >= 0.8 else 'medium'
                
                # Construir razón con detecciones avanzadas
                # CRÍTICO: Solo mostrar zero-day/DDoS si NO hay threat_types conocidos (ya corregido arriba)
                reason_parts = [f'{threat_type} detectado']
                if zero_day_risk:  # Ya está corregido (False si hay threat_types)
                    reason_parts.append('⚠️ ZERO-DAY')
                if ddos_risk:  # Ya está corregido (False si hay threat_types)
                    reason_parts.append('🌐 DDoS')
                if obfuscation_detected:
                    reason_parts.append('🔒 OFUSCADO')
                
                reason = f"{', '.join(reason_parts)} - {total_requests} requests, {unique_uris} URIs únicos, risk_score={risk_score:.2f}"
            else:
                threat_type = 'SCAN_PROBE' if unique_uris >= 3 else 'MULTIPLE_ATTACKS'
                severity = 'medium' if risk_score < 0.7 else 'high'
                reason = f'Episodio malicioso detectado: {total_requests} requests, {unique_uris} URIs únicos, risk_score={risk_score:.2f}'
            
            expires_at = datetime.now() + timedelta(seconds=duration_seconds)
            
            # Formatear duración para log
            duration_hours = duration_seconds / 3600
            if duration_hours < 1:
                duration_str = f"{duration_seconds/60:.0f}min"
            elif duration_hours < 24:
                duration_str = f"{duration_hours:.1f}h"
            else:
                duration_str = f"{duration_hours/24:.1f}d"
            
            # NUEVO: Si el sistema inteligente decidió rate_limit, aplicar rate limiting en lugar de bloquear
            if intelligent_action and intelligent_action.get('action') == 'rate_limit' and self.rate_limit_manager:
                try:
                    rate_limit_result = self.rate_limit_manager.apply_rate_limit(
                        ip=src_ip,
                        risk_score=risk_score,
                        reason=f"Sistema inteligente: {intelligent_action.get('reason', reason[:100])}",
                        duration_hours=24  # Default 24 horas para rate limits
                    )
                    level_str = rate_limit_result['level'].value if hasattr(rate_limit_result['level'], 'value') else str(rate_limit_result['level'])
                    self.logger.info(f"⏱️ Rate limiting aplicado a IP {src_ip}: {level_str} "
                               f"({rate_limit_result['requests_per_minute']} req/min) - NO se bloquea")
                    # NO continuar con el bloqueo si es rate_limit
                    return
                except Exception as e:
                    self.logger.error("error_occurred", message=f"Error aplicando rate limiting: {e}", exc_info=True)
                    # Si falla rate limiting, continuar con bloqueo normal
            
            self.logger.warning(f"🚨 BLOQUEANDO IP {src_ip} desde episodio: {threat_type}, "
                          f"severity={severity}, duration={duration_str}, "
                          f"risk={risk_score:.2f}, reason={reason[:100]}")
            
            # Guardar en blocked_ips
            if self.postgres_enabled and self.postgres_conn:
                try:
                    cursor = self.postgres_conn.cursor()
                    # Estrategia UPDATE/INSERT manual (más compatible que ON CONFLICT con índices parciales)
                    # Primero intentar UPDATE de registro activo existente
                    cursor.execute("""
                        UPDATE blocked_ips 
                            SET blocked_at = NOW(),
                            expires_at = %s,
                            reason = %s,
                            classification_source = 'episode_analysis',
                            threat_type = %s,
                            severity = %s,
                            active = TRUE,
                            updated_at = NOW()
                        WHERE ip = %s AND active = TRUE
                    """, (
                        expires_at, 
                        reason[:500], 
                        threat_type, 
                        severity, 
                        src_ip
                    ))
                    
                    # NUEVO: Actualizar block_stage y risk_score si están disponibles
                    if block_stage and cursor.rowcount > 0:
                        cursor.execute("""
                            UPDATE blocked_ips 
                            SET block_stage = %s, risk_score = %s
                            WHERE ip = %s AND active = TRUE
                        """, (
                            block_stage,
                            intelligent_action['risk_score'] if intelligent_action else risk_score,
                            src_ip
                        ))
                    
                    # Si no se actualizó ningún registro, hacer INSERT
                    if cursor.rowcount == 0:
                        # NUEVO: Incluir block_stage y risk_score si están disponibles
                        if block_stage:
                            cursor.execute("""
                                INSERT INTO blocked_ips (ip, blocked_at, expires_at, reason, classification_source, threat_type, severity, active, block_stage, risk_score)
                                VALUES (%s, NOW(), %s, %s, 'episode_analysis', %s, %s, TRUE, %s, %s)
                            """, (src_ip, expires_at, reason[:500], threat_type, severity, block_stage, intelligent_action['risk_score'] if intelligent_action else risk_score))
                        else:
                            cursor.execute("""
                                INSERT INTO blocked_ips (ip, blocked_at, expires_at, reason, classification_source, threat_type, severity, active)
                                VALUES (%s, NOW(), %s, %s, 'episode_analysis', %s, %s, TRUE)
                            """, (src_ip, expires_at, reason[:500], threat_type, severity))
                    self.postgres_conn.commit()
                    cursor.close()
                    self.logger.info("log_event", message=f"✅ IP {src_ip} bloqueada desde episodio (episode_id={episode_id})")
                    
                    # OPTIMIZACIÓN: Actualizar cache inmediatamente (sin esperar actualización periódica)
                    if self.blocked_ip_cache:
                        self.blocked_ip_cache.add_blocked_ip(src_ip, expires_at)
                except Exception as e:
                    self.logger.error("error_occurred", message=f"Error guardando IP bloqueada desde episodio: {e}", exc_info=True)
                    if self.postgres_conn:
                        self.postgres_conn.rollback()
            
            # Enviar a mitigation service
            if self.producer and self.send_to_mitigation:
                try:
                    mitigation_message = {
                        'action': 'block_ip',
                        'ip': src_ip,
                        'reason': reason[:200],
                        'threat_type': threat_type,
                        'severity': severity,
                        'duration_seconds': duration_seconds,
                        'expires_at': expires_at.isoformat(),
                        'source': 'episode_analysis',
                        'episode_id': episode_id,
                        'risk_score': risk_score,
                        'timestamp': datetime.now().isoformat()
                    }
                    self.producer.send(self.threats_topic, value=mitigation_message)
                    self.logger.info("log_event", message=f"✅ Mensaje de mitigación enviado para IP {src_ip}")
                except Exception as e:
                    self.logger.error("error_occurred", message=f"Error enviando mensaje de mitigación: {e}", exc_info=True)
        
        except Exception as e:
            self.logger.error("error_occurred", message=f"❌ Error bloqueando IP desde episodio: {e}", exc_info=True)
    
    def _update_baseline_background(self):
        """
        Actualiza baseline de episodios normales en background.
        Se ejecuta cada hora para mantener baseline actualizado.
        """
        if not self.episode_enhancer:
            return
        
        try:
            normal_episodes = list(self.episode_enhancer.recent_normal_episodes)
            if len(normal_episodes) >= 50:
                self.logger.info("log_event", message=f"🔄 Actualizando baseline estadístico con {len(normal_episodes)} episodios normales...")
                self.episode_enhancer.update_baseline(normal_episodes)
                self.logger.info("log_event", message=f"✅ Baseline actualizado: {self.episode_enhancer.normal_baseline['episode_count']} episodios")
            else:
                self.logger.debug("log_event", message=f"Baseline no actualizado: {len(normal_episodes)}/<50 episodios normales")
        except Exception as e:
            self.logger.error("error_occurred", message=f"Error actualizando baseline en background: {e}", exc_info=True)
    
    def _update_similarity_cache(self, episode_id: int, similar_episodes: List[Dict[str, Any]]):
        """
        Actualiza cache de similitud entre episodios.
        """
        if not self.postgres_enabled or not self.postgres_conn:
            return
        
        try:
            cursor = self.postgres_conn.cursor()
            
            for similar in similar_episodes:
                similar_episode_id = similar['episode_id']
                similarity_score = similar['similarity_score']
                
                cursor.execute("""
                    INSERT INTO episode_similarity_cache (episode_id, similar_episode_id, similarity_score)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (episode_id, similar_episode_id) DO UPDATE SET
                        similarity_score = EXCLUDED.similarity_score,
                        cached_at = NOW()
                """, (episode_id, similar_episode_id, similarity_score))
            
            self.postgres_conn.commit()
            cursor.close()
        
        except Exception as e:
            self.logger.debug("error_occurred", message=f"Error actualizando cache de similitud: {e}")
            if self.postgres_conn:
                self.postgres_conn.rollback()
    
    def stop(self):
        """Detiene el procesador"""
        self.logger.info("log_event", message="🛑 Deteniendo procesador...")
        self.running = False
        
        # Detener cleanup worker si está corriendo
        if self.cleanup_worker:
            try:
                self.cleanup_worker.stop()
                self.logger.info("log_event", message="✅ IntelligentCleanupWorker detenido")
            except Exception as e:
                self.logger.warning("error_occurred", message=f"Error deteniendo cleanup worker: {e}")
        
        # Detener baseline trainer si está corriendo
        if self.baseline_trainer:
            try:
                self.baseline_trainer.stop()
                self.logger.info("log_event", message="✅ BaselineTrainer detenido")
            except Exception as e:
                self.logger.warning("error_occurred", message=f"Error deteniendo baseline trainer: {e}")
        
        if self.producer:
            self.producer.flush()
            self.producer.close()
            self.logger.info("log_event", message="✅ Kafka Producer cerrado")
        
        if self.consumer:
            self.consumer.close()
            self.logger.info("log_event", message="✅ Kafka Consumer cerrado")
        
        # FASE 7: Calcular métricas agregadas
        computed_metrics = self._compute_metrics()
        
        # Mostrar métricas finales
        elapsed = time.time() - self.metrics['start_time']
        self.logger.info("log_event", message="=" * 60)
        self.logger.info("log_event", message="📊 MÉTRICAS FINALES")
        self.logger.info("log_event", message="=" * 60)
        self.logger.info("log_event", message=f"Total logs procesados: {self.metrics['total_logs_processed']}")
        self.logger.info("log_event", message=f"ML Predictions: {self.metrics['ml_predictions']}")
        self.logger.info("log_event", message=f"Transformer Predictions: {self.metrics.get('transformer_predictions', 0)}")
        self.logger.info("log_event", message=f"LLM Analyses: {self.metrics['llm_analyses']}")
        self.logger.info("log_event", message=f"Patterns detectados: {self.metrics['patterns_detected']}")
        self.logger.info("log_event", message=f"Mitigaciones enviadas: {self.metrics['mitigations_sent']}")
        self.logger.info("log_event", message=f"Fallback a Transformer: {self.metrics.get('fallback_to_transformer', 0)}")
        self.logger.info("log_event", message=f"Fallback a LLM: {self.metrics.get('fallback_to_llm', 0)}")
        self.logger.info("log_event", message=f"Tiempo total: {elapsed:.1f}s")
        if elapsed > 0:
            self.logger.info("log_event", message=f"Throughput: {self.metrics['total_logs_processed'] / elapsed:.1f} logs/seg")
        if computed_metrics:
            self.logger.info("log_event", message=f"Latencia P95 end-to-end: {computed_metrics.get('latency_p95_ms', 0):.1f}ms")
            self.logger.info("log_event", message=f"Latencia promedio ML: {computed_metrics.get('avg_ml_latency_ms', 0):.1f}ms")
            self.logger.info("log_event", message=f"Latencia promedio Transformer: {computed_metrics.get('avg_transformer_latency_ms', 0):.1f}ms")
        self.logger.info("log_event", message="=" * 60)
    
    def _compute_metrics(self) -> Dict[str, Any]:
        """
        FASE 7: Calcula métricas agregadas (P95, promedios, etc.)
        """
        metrics = {}
        
        # Latencia end-to-end P95
        if self.metrics.get('end_to_end_latency_ms'):
            latencies = self.metrics['end_to_end_latency_ms']
            if latencies:
                sorted_latencies = sorted(latencies)
                p95_idx = int(len(sorted_latencies) * 0.95)
                metrics['latency_p95_ms'] = sorted_latencies[p95_idx] if p95_idx < len(sorted_latencies) else sorted_latencies[-1]
                metrics['latency_p50_ms'] = sorted_latencies[len(sorted_latencies) // 2]
                metrics['latency_p99_ms'] = sorted_latencies[int(len(sorted_latencies) * 0.99)] if len(sorted_latencies) > 1 else sorted_latencies[-1]
        
        # Latencia promedio ML
        if self.metrics.get('ml_latency_ms'):
            ml_latencies = self.metrics['ml_latency_ms']
            if ml_latencies:
                metrics['avg_ml_latency_ms'] = sum(ml_latencies) / len(ml_latencies)
        
        # Latencia promedio Transformer
        if self.metrics.get('transformer_latency_ms'):
            transformer_latencies = self.metrics['transformer_latency_ms']
            if transformer_latencies:
                metrics['avg_transformer_latency_ms'] = sum(transformer_latencies) / len(transformer_latencies)
        
        # Latencia promedio LLM
        if self.metrics.get('llm_latency_ms'):
            llm_latencies = self.metrics['llm_latency_ms']
            if llm_latencies:
                metrics['avg_llm_latency_ms'] = sum(llm_latencies) / len(llm_latencies)
        
        # Tasa de fallback
        total_processed = self.metrics.get('total_logs_processed', 0)
        if total_processed > 0:
            metrics['fallback_to_transformer_rate'] = self.metrics.get('fallback_to_transformer', 0) / total_processed
            metrics['fallback_to_llm_rate'] = self.metrics.get('fallback_to_llm', 0) / total_processed
        
        # Throughput
        elapsed = time.time() - self.metrics.get('start_time', time.time())
        if elapsed > 0:
            metrics['throughput_logs_per_sec'] = self.metrics.get('total_logs_processed', 0) / elapsed
        
        return metrics
    
    def get_metrics(self) -> Dict[str, Any]:
        """
        FASE 7: Retorna métricas completas incluyendo agregadas
        """
        computed_metrics = self._compute_metrics()
        
        # Construir respuesta sin listas grandes (solo métricas agregadas)
        response = {
            'total_logs_processed': self.metrics.get('total_logs_processed', 0),
            'ml_predictions': self.metrics.get('ml_predictions', 0),
            'transformer_predictions': self.metrics.get('transformer_predictions', 0),
            'llm_analyses': self.metrics.get('llm_analyses', 0),
            'patterns_detected': self.metrics.get('patterns_detected', 0),
            'mitigations_sent': self.metrics.get('mitigations_sent', 0),
            'fallback_to_transformer': self.metrics.get('fallback_to_transformer', 0),
            'fallback_to_llm': self.metrics.get('fallback_to_llm', 0),
            'start_time': self.metrics.get('start_time', time.time())
        }
        
        # Agregar métricas calculadas
        response.update(computed_metrics)
        
        # Agregar métricas del transformer si está disponible
        if self.transformer_predictor:
            transformer_metrics = self.transformer_predictor.get_metrics()
            response['transformer_metrics'] = transformer_metrics
        
        return response


def main():
    """Función principal"""
    config = {
        'kafka_brokers': os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'kafka:9093'),
        'topic_pattern': os.getenv('KAFKA_TOPIC_PATTERN', 'waf-logs'),
        'consumer_group': os.getenv('KAFKA_CONSUMER_GROUP', 'realtime-processor-group'),
        'models_dir': os.getenv('ML_MODELS_DIR', '/app/models'),
        'default_model_id': os.getenv('DEFAULT_ML_MODEL_ID'),
        'gemini_api_key': os.getenv('GEMINI_API_KEY', ''),
        'window_size_seconds': int(os.getenv('PATTERN_WINDOW_SIZE', '300')),
        'min_events': int(os.getenv('PATTERN_MIN_EVENTS', '5')),
        'ml_threshold': float(os.getenv('ML_THRESHOLD', '0.7')),
        'enable_llm': os.getenv('ENABLE_LLM', 'true').lower() == 'true',
        'enable_pattern_detection': os.getenv('ENABLE_PATTERN_DETECTION', 'true').lower() == 'true',
        'threats_topic': os.getenv('THREATS_TOPIC', 'threats-detected'),
        'send_to_mitigation': os.getenv('SEND_TO_MITIGATION', 'true').lower() == 'true',
        # Configuración de análisis SOC de ventanas temporales
        'time_window_size_logs': int(os.getenv('TIME_WINDOW_SIZE_LOGS', '20')),  # Analizar cada 20 logs (reducido de 100)
        'time_window_size_seconds': int(os.getenv('TIME_WINDOW_SIZE_SECONDS', '300'))  # Analizar cada 5 minutos (aumentado de 60s)
    }
    
    # Global status for health check
    worker_status = {"running": False, "metrics": {}}

    class HealthCheckHandler(BaseHTTPRequestHandler):
        def _set_headers(self, status_code=200, content_type='application/json'):
            self.send_response(status_code)
            self.send_header('Content-type', content_type)
            self.end_headers()

        def do_GET(self):
            if self.path == '/health' or self.path == '/healthz':
                status_code = 200
                metrics = worker_status.get("metrics", {})
                
                # NUEVO: Agregar métricas de Detección Avanzada Fase 1
                advanced_detection_metrics = {}
                processor = worker_status.get("processor")
                if processor:
                    # Deobfuscation Engine stats
                    if hasattr(processor, 'deobfuscation_engine') and processor.deobfuscation_engine:
                        advanced_detection_metrics['deobfuscation'] = processor.deobfuscation_engine.get_stats()
                    
                    # Threat Intelligence stats
                    if hasattr(processor, 'threat_intel') and processor.threat_intel:
                        advanced_detection_metrics['threat_intelligence'] = processor.threat_intel.get_stats()
                    
                    # Anomaly Detection stats
                    if hasattr(processor, 'zero_day_detector') and processor.zero_day_detector:
                        advanced_detection_metrics['anomaly_detection'] = processor.zero_day_detector.get_stats()
                
                response_data = {
                    "status": "ok" if worker_status["running"] else "degraded",
                    "worker_running": worker_status["running"],
                    "metrics": metrics,
                    "advanced_detection": advanced_detection_metrics  # NUEVO
                }
                self._set_headers(status_code)
                self.wfile.write(json.dumps(response_data).encode('utf-8'))
            else:
                self._set_headers(404, 'text/plain')
                self.wfile.write(b"Not Found")

        def log_message(self, format, *args):
            pass

    def run_http_server():
        port = int(os.getenv("PORT", 8080))
        server_address = ('YOUR_IP_ADDRESS', port)
        httpd = HTTPServer(server_address, HealthCheckHandler)
        self.logger.info("log_event", message=f"HTTP Health Check server running on port {port}")
        httpd.serve_forever()

    # Start HTTP server in a separate thread
    http_thread = threading.Thread(target=run_http_server, daemon=True)
    http_thread.start()

    processor = KafkaStreamsProcessor(config)
    worker_status["processor"] = processor  # Guardar referencia para HealthCheckHandler
    worker_status["running"] = True
    
    # Update metrics periodically
    def update_metrics():
        while worker_status["running"]:
            worker_status["metrics"] = processor.metrics
            time.sleep(10)
    
    metrics_thread = threading.Thread(target=update_metrics, daemon=True)
    metrics_thread.start()
    
    processor.start()


if __name__ == "__main__":
    main()

