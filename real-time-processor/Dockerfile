FROM python:3.11-slim

WORKDIR /app

# Instalar dependencias del sistema para ONNX Runtime
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements (desde real-time-processor/)
COPY real-time-processor/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# FASE 7: Instalar dependencias del transformer (CPU-only)
# Instalar torch primero desde el index de CPU
RUN pip install --no-cache-dir torch>=2.0.0 --index-url https://download.pytorch.org/whl/cpu

# Instalar el resto de dependencias
RUN pip install --no-cache-dir \
    onnx>=1.14.0 \
    onnxruntime>=1.15.0 \
    transformers>=4.30.0 \
    sentencepiece>=0.1.99

# Copiar código del real-time-processor
COPY real-time-processor/ .

# FASE 7: Crear directorio para transformer (si se usa en el futuro)
RUN mkdir -p /app/transformer-classifier

# Crear directorio para modelos
RUN mkdir -p /app/models /app/models/transformers

EXPOSE 8080

ENV PORT=8080

# Comando por defecto
CMD ["python", "kafka_streams_processor.py"]



