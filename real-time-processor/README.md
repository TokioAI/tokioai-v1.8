# Real-Time Processor - Fase 2

## 🎯 Descripción

Sistema de procesamiento en tiempo real de logs que integra:
- **ML Predictor**: Predicciones rápidas (< 50ms)
- **LLM Analyzer**: Análisis profundo para amenazas críticas (< 500ms)
- **Pattern Detector**: Detección de patrones en ventanas deslizantes

## 🚀 Pipeline de Procesamiento

```
Log desde Kafka
    ↓
1. ML Prediction (< 50ms)
    ↓
2. Si threat_score > 0.7: LLM Analysis (< 500ms)
    ↓
3. Pattern Detection (ventana deslizante)
    ↓
Resultado: Action (log_only/monitor/block_ip)
```

## 📊 Componentes

### 1. ML Predictor (`ml_predictor/`)

- Carga modelos en memoria para predicciones rápidas
- Extrae features de logs
- Predice severidad (low/medium/high)
- Calcula threat_score (0.0-1.0)

**Rendimiento**: < 50ms por predicción

### 2. LLM Analyzer (`llm_analyzer/`)

- Análisis profundo con Gemini LLM
- Solo se usa para amenazas críticas (threat_score > 0.7)
- Cache de análisis recientes
- Fallback a heurísticas si LLM no disponible

**Rendimiento**: < 500ms por análisis

### 3. Pattern Detector (`pattern_detector/`)

- Ventanas deslizantes por IP
- Detecta patrones:
  - Múltiples intentos bloqueados
  - Escaneo (muchas URIs diferentes)
  - Ataque persistente (mismo tipo repetido)
  - Alta frecuencia de requests
  - Ataque distribuido

**Ventana**: 5 minutos por defecto

## ⚙️ Configuración

Variables de entorno:

```bash
# Kafka
KAFKA_BOOTSTRAP_SERVERS=kafka:9093
KAFKA_TOPIC_PATTERN=waf-logs
KAFKA_CONSUMER_GROUP=realtime-processor-group

# ML
ML_MODELS_DIR=/app/models
DEFAULT_ML_MODEL_ID=modelo_id

# LLM
GEMINI_API_KEY=tu_api_key
ENABLE_LLM=true

# Pattern Detection
PATTERN_WINDOW_SIZE=300  # segundos
PATTERN_MIN_EVENTS=5
ML_THRESHOLD=0.7  # Solo LLM si threat_score > 0.7
ENABLE_PATTERN_DETECTION=true
```

## 🚀 Uso

### Iniciar el servicio

```bash
docker-compose up -d realtime-processor
```

### Ver logs

```bash
docker logs -f soc-realtime-processor
```

## 📈 Métricas

El procesador reporta métricas:
- Total logs procesados
- ML Predictions
- LLM Analyses
- Patterns detectados
- Throughput (logs/segundo)

## ✅ Estado

**Fase 2: COMPLETADA ✅**

El sistema está listo para procesar logs en tiempo real con ML, LLM y detección de patrones.



