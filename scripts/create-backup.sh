#!/bin/bash
# Script para crear backup completo del sistema SOC-AI-LAB
# Listo para migración a otra nube

set -e

BACKUP_DIR="backup-soc-ai-$(date +%Y%m%d-%H%M%S)"
BACKUP_ZIP="backup-soc-ai-$(date +%Y%m%d-%H%M%S).zip"
PROJECT_ROOT="/home/osboxes/SOC-AI-LAB"

echo "📦 CREANDO BACKUP COMPLETO DEL SISTEMA SOC-AI-LAB"
echo "=================================================="
echo ""

# Crear directorio temporal
mkdir -p "$BACKUP_DIR"
cd "$BACKUP_DIR"

echo "📁 Copiando estructura de directorios..."

# Directorios principales a incluir
DIRS=(
    "dashboard-api"
    "real-time-processor"
    "gcp-deployment"
    "scripts"
    "mcp-core"
    "intelligent-redteam"
    "data-processing"
)

# Archivos y directorios raíz importantes
ROOT_FILES=(
    "*.md"
    "*.txt"
    "*.sh"
    "*.yaml"
    "*.yml"
    "*.json"
    ".gitignore"
    "README*"
)

# Copiar directorios
for dir in "${DIRS[@]}"; do
    if [ -d "$PROJECT_ROOT/$dir" ]; then
        echo "  ✓ Copiando $dir..."
        mkdir -p "$dir"
        cp -r "$PROJECT_ROOT/$dir"/* "$dir/" 2>/dev/null || true
    fi
done

# Copiar archivos raíz
echo "  ✓ Copiando archivos raíz..."
for pattern in "${ROOT_FILES[@]}"; do
    cp "$PROJECT_ROOT"/$pattern . 2>/dev/null || true
done

# Crear archivo de información del backup
echo "📝 Creando archivo de información..."
cat > BACKUP_INFO.md << EOF
# Backup del Sistema SOC-AI-LAB

**Fecha de Backup:** $(date)
**Versión del Sistema:** Backup completo para migración

## Contenido del Backup

### Directorios Incluidos:
- \`dashboard-api/\`: API del dashboard (FastAPI)
- \`real-time-processor/\`: Procesador de logs en tiempo real (Kafka)
- \`gcp-deployment/\`: Configuraciones de despliegue en GCP
- \`scripts/\`: Scripts de utilidad y mantenimiento
- \`mcp-core/\`: Core del sistema MCP
- \`intelligent-redteam/\`: Sistema de red team inteligente
- \`data-processing/\`: Procesamiento de datos

### Archivos de Configuración Clave:
- \`gcp-deployment/cloud-run/*/service.yaml\`: Configuraciones de Cloud Run
- \`dashboard-api/app.py\`: Aplicación principal del dashboard
- \`real-time-processor/kafka_streams_processor.py\`: Procesador principal
- \`*.yaml\`: Configuraciones de Cloud Build
- \`requirements.txt\`: Dependencias Python

## Instrucciones de Migración

### 1. Requisitos Previos
- Python 3.9+
- Docker y Docker Compose
- Google Cloud SDK (gcloud) - si migras a GCP
- Acceso a Kafka (o instalar Kafka)
- PostgreSQL 13+ (o Cloud SQL)

### 2. Variables de Entorno Necesarias

#### Dashboard API:
- POSTGRES_HOST
- POSTGRES_PORT
- POSTGRES_DB
- POSTGRES_USER
- POSTGRES_PASSWORD
- GEMINI_API_KEY (opcional)

#### Real-time Processor:
- KAFKA_BOOTSTRAP_SERVERS
- KAFKA_TOPIC_PATTERN
- KAFKA_CONSUMER_GROUP
- POSTGRES_HOST
- POSTGRES_PORT
- POSTGRES_DB
- POSTGRES_USER
- POSTGRES_PASSWORD
- GEMINI_API_KEY

### 3. Base de Datos

El sistema requiere las siguientes tablas:
- \`blocked_ips\`: IPs bloqueadas por el agente
- \`waf_logs\`: Logs del WAF
- \`agent_decisions\`: Decisiones del agente (si existe)
- Otras tablas según el esquema completo

### 4. Servicios a Desplegar

1. **Dashboard API** (FastAPI)
   - Puerto: 8080 (configurable)
   - Requiere: PostgreSQL, autenticación

2. **Real-time Processor** (Kafka Consumer)
   - Requiere: Kafka, PostgreSQL
   - Procesa logs en tiempo real

3. **Kafka** (Message Broker)
   - Topic: \`waf-logs\`
   - Consumer Group: \`realtime-processor-group-v2\`

### 5. Pasos de Migración

\`\`\`bash
# 1. Extraer backup
unzip $BACKUP_ZIP
cd $BACKUP_DIR

# 2. Configurar variables de entorno
cp .env.example .env
# Editar .env con tus credenciales

# 3. Construir imágenes Docker
docker build -t dashboard-api -f dashboard-api/Dockerfile .
docker build -t realtime-processor -f real-time-processor/Dockerfile .

# 4. Configurar base de datos
# Ejecutar migraciones SQL necesarias

# 5. Desplegar servicios
# Seguir instrucciones en gcp-deployment/ o adaptar para tu nube
\`\`\`

## Notas Importantes

- Este backup NO incluye:
  - Base de datos (solo esquema/migraciones si existen)
  - Secrets/credenciales (configurar manualmente)
  - Modelos ML entrenados (si existen, copiar por separado)
  - Logs históricos

- Archivos excluidos automáticamente:
  - \`__pycache__/\`
  - \`*.pyc\`
  - \`.git/\`
  - \`node_modules/\`
  - \`*.log\`
  - \`.env\` (por seguridad)

## Contacto y Soporte

Para migración a otra nube, revisar:
- Configuraciones en \`gcp-deployment/\`
- Variables de entorno en archivos \`service.yaml\`
- Dependencias en \`requirements.txt\`

EOF

# Crear script de verificación
echo "📝 Creando script de verificación..."
cat > verify-backup.sh << 'VERIFY_EOF'
#!/bin/bash
# Script para verificar integridad del backup

echo "🔍 Verificando integridad del backup..."
echo ""

# Verificar directorios principales
DIRS=("dashboard-api" "real-time-processor" "gcp-deployment" "scripts")

for dir in "${DIRS[@]}"; do
    if [ -d "$dir" ]; then
        echo "  ✓ $dir existe"
    else
        echo "  ✗ $dir NO existe"
    fi
done

# Verificar archivos importantes
FILES=("dashboard-api/app.py" "real-time-processor/kafka_streams_processor.py")

for file in "${FILES[@]}"; do
    if [ -f "$file" ]; then
        echo "  ✓ $file existe"
    else
        echo "  ✗ $file NO existe"
    fi
done

echo ""
echo "✅ Verificación completada"
VERIFY_EOF

chmod +x verify-backup.sh

# Limpiar archivos innecesarios
echo "🧹 Limpiando archivos temporales..."
find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find . -type f -name "*.pyc" -delete 2>/dev/null || true
find . -type f -name "*.pyo" -delete 2>/dev/null || true
find . -type f -name ".DS_Store" -delete 2>/dev/null || true
find . -type f -name "*.log" -delete 2>/dev/null || true
find . -type f -name ".env" -delete 2>/dev/null || true

# Volver al directorio original y crear ZIP
cd "$PROJECT_ROOT"
echo "📦 Creando archivo ZIP..."
zip -r "$BACKUP_ZIP" "$BACKUP_DIR" -x "*.git*" "*/__pycache__/*" "*.pyc" "*.pyo" "*.log" "*.env" "*/node_modules/*" "*/venv/*" "*/env/*" > /dev/null 2>&1

# Calcular tamaño
SIZE=$(du -h "$BACKUP_ZIP" | cut -f1)

echo ""
echo "✅ BACKUP COMPLETADO"
echo "==================="
echo "📦 Archivo: $BACKUP_ZIP"
echo "📊 Tamaño: $SIZE"
echo "📁 Ubicación: $PROJECT_ROOT/$BACKUP_ZIP"
echo ""
echo "📋 Para verificar el backup:"
echo "   unzip -l $BACKUP_ZIP"
echo ""
echo "📋 Para extraer:"
echo "   unzip $BACKUP_ZIP"
echo ""




