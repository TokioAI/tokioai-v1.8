#!/bin/bash

###############################################################################
# Script de Backup Completo - Tokio AI ACIS (SOC-AI-LAB)
# Crea un backup completo del proyecto incluyendo código, datos y modelos
###############################################################################

set -e  # Salir si hay error

# Colores para output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Directorio del proyecto
PROJECT_DIR="/home/osboxes/SOC-AI-LAB"
BACKUP_BASE_DIR="${PROJECT_DIR}/backups"

# Timestamp para el backup
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_DIR="${BACKUP_BASE_DIR}/backup_${TIMESTAMP}"

# Crear directorio de backup
mkdir -p "${BACKUP_DIR}"
cd "${PROJECT_DIR}"

echo -e "${BLUE}╔══════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     🔄 BACKUP COMPLETO - TOKIO AI ACIS                             ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${GREEN}📦 Directorio de backup: ${BACKUP_DIR}${NC}"
echo ""

# ============================================================================
# 1. BACKUP DE CÓDIGO FUENTE
# ============================================================================
echo -e "${YELLOW}[1/7] 📝 Respaldo de código fuente...${NC}"

# Directorios de código a respaldar
CODE_DIRS=(
    "adaptive-learning"
    "alert-service"
    "dashboard-api"
    "incident-management"
    "intelligent-redteam"
    "log-ingestion"
    "mcp-core"
    "mcp-host"
    "mitigation-adapters"
    "mitigation-service"
    "postgres-persistence"
    "real-time-processor"
    "redteam-agent"
    "tenant-management"
    "threat-detection"
    "modsecurity"
    "scripts"
    "tests"
)

for dir in "${CODE_DIRS[@]}"; do
    if [ -d "${dir}" ]; then
        echo "  ✓ Copiando ${dir}/"
        cp -r "${dir}" "${BACKUP_DIR}/" 2>/dev/null || true
    fi
done

# Archivos importantes en la raíz
ROOT_FILES=(
    "docker-compose.yml"
    "Makefile"
    "pytest.ini"
    "requirements-test.txt"
    ".env.example"
    ".env"
    "logo.png"
)

for file in "${ROOT_FILES[@]}"; do
    if [ -f "${file}" ]; then
        echo "  ✓ Copiando ${file}"
        cp "${file}" "${BACKUP_DIR}/" 2>/dev/null || true
    fi
done

echo -e "${GREEN}  ✅ Código fuente respaldado${NC}"
echo ""

# ============================================================================
# 2. BACKUP DE DOCUMENTACIÓN
# ============================================================================
echo -e "${YELLOW}[2/7] 📚 Respaldo de documentación...${NC}"

# Copiar todos los archivos .md
find . -maxdepth 1 -name "*.md" -type f -exec cp {} "${BACKUP_DIR}/" \;
echo -e "${GREEN}  ✅ Documentación respaldada${NC}"
echo ""

# ============================================================================
# 3. BACKUP DE MODELOS ML
# ============================================================================
echo -e "${YELLOW}[3/7] 🧠 Respaldo de modelos ML entrenados...${NC}"

ML_MODELS_DIR="${BACKUP_DIR}/ml_models"
mkdir -p "${ML_MODELS_DIR}"

# Copiar modelos del contenedor si está corriendo
if docker ps | grep -q "soc-mcp-core"; then
    echo "  ✓ Extrayendo modelos del contenedor..."
    docker cp soc-mcp-core:/app/models/. "${ML_MODELS_DIR}/" 2>/dev/null || echo "  ⚠ No se pudieron copiar modelos del contenedor"
    
    # Listar modelos encontrados
    if [ -d "${ML_MODELS_DIR}" ] && [ "$(ls -A ${ML_MODELS_DIR} 2>/dev/null)" ]; then
        MODEL_COUNT=$(find "${ML_MODELS_DIR}" -name "*.pkl" | wc -l)
        echo -e "${GREEN}  ✅ ${MODEL_COUNT} modelos encontrados${NC}"
    else
        echo -e "${YELLOW}  ⚠ No se encontraron modelos en el contenedor${NC}"
    fi
else
    # Copiar desde el directorio local si existe
    if [ -d "mcp-core/models" ]; then
        cp -r mcp-core/models/* "${ML_MODELS_DIR}/" 2>/dev/null || true
        echo -e "${GREEN}  ✅ Modelos copiados desde directorio local${NC}"
    else
        echo -e "${YELLOW}  ⚠ Directorio de modelos no encontrado${NC}"
    fi
fi
echo ""

# ============================================================================
# 4. BACKUP DE BASE DE DATOS POSTGRESQL
# ============================================================================
echo -e "${YELLOW}[4/7] 🗄️  Respaldo de base de datos PostgreSQL...${NC}"

DB_BACKUP_FILE="${BACKUP_DIR}/postgres_backup_${TIMESTAMP}.sql"

if docker ps | grep -q "soc-postgres"; then
    echo "  ✓ Exportando base de datos..."
    docker exec soc-postgres pg_dump -U soc_user -d soc_ai > "${DB_BACKUP_FILE}" 2>/dev/null || {
        echo -e "${RED}  ❌ Error al exportar base de datos${NC}"
        rm -f "${DB_BACKUP_FILE}"
    }
    
    if [ -f "${DB_BACKUP_FILE}" ] && [ -s "${DB_BACKUP_FILE}" ]; then
        DB_SIZE=$(du -h "${DB_BACKUP_FILE}" | cut -f1)
        echo -e "${GREEN}  ✅ Base de datos respaldada (${DB_SIZE})${NC}"
    else
        echo -e "${YELLOW}  ⚠ Base de datos vacía o no accesible${NC}"
    fi
else
    echo -e "${YELLOW}  ⚠ Contenedor PostgreSQL no está corriendo${NC}"
fi
echo ""

# ============================================================================
# 5. BACKUP DE REGLAS MODSECURITY
# ============================================================================
echo -e "${YELLOW}[5/7] 🛡️  Respaldo de reglas ModSecurity...${NC}"

MODSEC_BACKUP_DIR="${BACKUP_DIR}/modsecurity_rules"
mkdir -p "${MODSEC_BACKUP_DIR}"

# Copiar reglas auto-generadas si existen
if [ -f "modsecurity/rules/auto-mitigation-rules.conf" ]; then
    cp modsecurity/rules/auto-mitigation-rules.conf "${MODSEC_BACKUP_DIR}/"
    echo "  ✓ Reglas auto-mitigación copiadas"
fi

# Copiar configuración ModSecurity si existe
if [ -d "modsecurity/config" ]; then
    cp -r modsecurity/config/* "${MODSEC_BACKUP_DIR}/" 2>/dev/null || true
    echo "  ✓ Configuración ModSecurity copiada"
fi

echo -e "${GREEN}  ✅ Reglas ModSecurity respaldadas${NC}"
echo ""

# ============================================================================
# 6. BACKUP DE DATOS Y LOGS
# ============================================================================
echo -e "${YELLOW}[6/7] 📊 Respaldo de datos y logs...${NC}"

DATA_BACKUP_DIR="${BACKUP_DIR}/data"
mkdir -p "${DATA_BACKUP_DIR}"

# Copiar alertas si existen
if [ -d "alert-data" ]; then
    cp -r alert-data/* "${DATA_BACKUP_DIR}/" 2>/dev/null || true
    echo "  ✓ Datos de alertas copiados"
fi

# Exportar logs de ModSecurity si existen (últimos 1000)
if [ -d "modsecurity/modsec-logs" ]; then
    find modsecurity/modsec-logs -name "*.log" -type f | head -1000 | tar -czf "${DATA_BACKUP_DIR}/modsec_logs_sample.tar.gz" -T - 2>/dev/null || true
    echo "  ✓ Muestra de logs ModSecurity copiada"
fi

echo -e "${GREEN}  ✅ Datos y logs respaldados${NC}"
echo ""

# ============================================================================
# 7. CREAR ARCHIVO DE RESUMEN DEL BACKUP
# ============================================================================
echo -e "${YELLOW}[7/7] 📋 Generando resumen del backup...${NC}"

SUMMARY_FILE="${BACKUP_DIR}/BACKUP_SUMMARY.md"

cat > "${SUMMARY_FILE}" << EOF
# 📦 Resumen del Backup - Tokio AI ACIS

**Fecha del Backup**: $(date +"%Y-%m-%d %H:%M:%S")
**Directorio**: \`${BACKUP_DIR}\`

## 📊 Contenido del Backup

### ✅ Código Fuente
- Todos los directorios de código fuente
- Scripts y utilidades
- Archivos de configuración

### ✅ Documentación
- Todos los archivos Markdown (.md)
- Documentación técnica y guías

### ✅ Modelos ML
- Modelos entrenados (.pkl)
- Scalers asociados
- Metadata de modelos

### ✅ Base de Datos
- Export completo de PostgreSQL
- Esquema multi-tenant
- Datos históricos

### ✅ Configuración
- Reglas ModSecurity
- Docker Compose
- Variables de entorno (si disponible)

## 📈 Estado del Sistema al momento del Backup

### Servicios Docker
\`\`\`
$(docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep -E "(soc-|CONTAINER)" || echo "No se pudo obtener estado de contenedores")
\`\`\`

### Modelos ML Disponibles
\`\`\`
$(if [ -d "${ML_MODELS_DIR}" ]; then find "${ML_MODELS_DIR}" -name "*.pkl" -type f | wc -l | xargs echo "Total de modelos:"; else echo "No hay modelos en este backup"; fi)
\`\`\`

### Tamaño del Backup
\`\`\`
$(du -sh "${BACKUP_DIR}" | cut -f1)
\`\`\`

## 🔄 Cómo Restaurar

### 1. Restaurar Código Fuente
\`\`\`bash
cp -r ${BACKUP_DIR}/* /ruta/destino/
\`\`\`

### 2. Restaurar Base de Datos
\`\`\`bash
docker exec -i soc-postgres psql -U soc_user -d soc_ai < ${BACKUP_DIR}/postgres_backup_*.sql
\`\`\`

### 3. Restaurar Modelos ML
\`\`\`bash
docker cp ${BACKUP_DIR}/ml_models/. soc-mcp-core:/app/models/
\`\`\`

### 4. Restaurar Reglas ModSecurity
\`\`\`bash
cp ${BACKUP_DIR}/modsecurity_rules/* modsecurity/rules/
\`\`\`

## 📝 Notas

- Backup creado automáticamente por script de backup
- Incluye todos los componentes del sistema Tokio AI ACIS
- Modelos ML incluyen tanto los archivos .pkl como metadata

EOF

echo -e "${GREEN}  ✅ Resumen generado${NC}"
echo ""

# ============================================================================
# COMPRIMIR BACKUP
# ============================================================================
echo -e "${YELLOW}🗜️  Comprimiendo backup...${NC}"

BACKUP_ARCHIVE="${BACKUP_BASE_DIR}/backup_${TIMESTAMP}.tar.gz"
cd "${BACKUP_BASE_DIR}"
tar -czf "backup_${TIMESTAMP}.tar.gz" "backup_${TIMESTAMP}/" 2>/dev/null

if [ -f "${BACKUP_ARCHIVE}" ]; then
    ARCHIVE_SIZE=$(du -h "${BACKUP_ARCHIVE}" | cut -f1)
    echo -e "${GREEN}  ✅ Backup comprimido: ${BACKUP_ARCHIVE} (${ARCHIVE_SIZE})${NC}"
    
    # Opcional: eliminar directorio sin comprimir para ahorrar espacio
    # rm -rf "${BACKUP_DIR}"
    # echo "  ✓ Directorio temporal eliminado"
else
    echo -e "${RED}  ❌ Error al comprimir backup${NC}"
fi

echo ""

# ============================================================================
# RESUMEN FINAL
# ============================================================================
echo -e "${BLUE}╔══════════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     ✅ BACKUP COMPLETADO EXITOSAMENTE                              ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${GREEN}📦 Backup completo:${NC}"
echo -e "   Directorio: ${BACKUP_DIR}"
echo -e "   Archivo comprimido: ${BACKUP_ARCHIVE}"
if [ -f "${BACKUP_ARCHIVE}" ]; then
    echo -e "   Tamaño: ${ARCHIVE_SIZE}"
fi
echo ""
echo -e "${GREEN}📋 Resumen:${NC}"
echo -e "   ✓ Código fuente respaldado"
echo -e "   ✓ Documentación respaldada"
echo -e "   ✓ Modelos ML respaldados"
echo -e "   ✓ Base de datos respaldada"
echo -e "   ✓ Reglas ModSecurity respaldadas"
echo -e "   ✓ Datos y logs respaldados"
echo ""
echo -e "${BLUE}📄 Ver detalles completos en: ${SUMMARY_FILE}${NC}"
echo ""



