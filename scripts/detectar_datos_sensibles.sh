#!/bin/bash
# Script para detectar datos sensibles en proyectos antes de subirlos a GitHub

echo "═══════════════════════════════════════════════════════════"
echo "🔍 DETECTOR DE DATOS SENSIBLES"
echo "═══════════════════════════════════════════════════════════"
echo ""

PROJECT_DIR="${1:-/home/osboxes}"
OUTPUT_FILE="${2:-/tmp/datos_sensibles_report.txt}"

echo "📁 Buscando en: $PROJECT_DIR"
echo "📄 Reporte: $OUTPUT_FILE"
echo ""

# Limpiar archivo anterior
> "$OUTPUT_FILE"

echo "🔍 Buscando datos sensibles..." | tee -a "$OUTPUT_FILE"
echo "" | tee -a "$OUTPUT_FILE"

# Patrones a buscar
declare -a PATTERNS=(
    "password.*=.*['\"].*['\"]"
    "PASSWORD.*=.*['\"].*['\"]"
    "api[_-]?key.*=.*['\"].*['\"]"
    "API[_-]?KEY.*=.*['\"].*['\"]"
    "secret.*=.*['\"].*['\"]"
    "SECRET.*=.*['\"].*['\"]"
    "token.*=.*['\"].*['\"]"
    "TOKEN.*=.*['\"].*['\"]"
    "access[_-]?token.*=.*['\"].*['\"]"
    "ACCESS[_-]?TOKEN.*=.*['\"].*['\"]"
    "refresh[_-]?token.*=.*['\"].*['\"]"
    "REFRESH[_-]?TOKEN.*=.*['\"].*['\"]"
    "aws[_-]?access[_-]?key"
    "AWS[_-]?ACCESS[_-]?KEY"
    "aws[_-]?secret[_-]?key"
    "AWS[_-]?SECRET[_-]?KEY"
    "private[_-]?key"
    "PRIVATE[_-]?KEY"
    "-----BEGIN.*PRIVATE KEY-----"
    "-----BEGIN RSA PRIVATE KEY-----"
    "-----BEGIN EC PRIVATE KEY-----"
    "mongodb://.*:.*@"
    "postgresql://.*:.*@"
    "mysql://.*:.*@"
    "redis://.*:.*@"
    "sk-[a-zA-Z0-9]{32,}"
    "pk_[a-zA-Z0-9]{32,}"
    "ghp_[a-zA-Z0-9]{36,}"
    "github_pat_[a-zA-Z0-9]{82,}"
    "[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}.*:.*[0-9]{4,5}"
    "Bearer [a-zA-Z0-9]{20,}"
)

# Archivos a revisar
declare -a FILE_EXTENSIONS=(
    "*.py"
    "*.js"
    "*.ts"
    "*.java"
    "*.go"
    "*.rb"
    "*.php"
    "*.env"
    "*.config"
    "*.conf"
    "*.yaml"
    "*.yml"
    "*.json"
    "*.sh"
    "*.bash"
    "*.sql"
    "*.md"
    "*.txt"
)

# Archivos a ignorar
IGNORE_PATHS=(
    ".git"
    "node_modules"
    "__pycache__"
    ".venv"
    "venv"
    "env"
    ".env"
    "dist"
    "build"
    ".pytest_cache"
    ".mypy_cache"
    "*.pyc"
    "*.pyo"
    "*.log"
)

# Construir comando find con exclusiones
FIND_CMD="find \"$PROJECT_DIR\" -type f"

for ext in "${FILE_EXTENSIONS[@]}"; do
    FIND_CMD="$FIND_CMD -o -name \"$ext\""
done

FIND_CMD="$FIND_CMD 2>/dev/null"

# Buscar archivos .env específicamente
echo "📋 Buscando archivos .env..." | tee -a "$OUTPUT_FILE"
find "$PROJECT_DIR" -name ".env*" -type f ! -path "*/.git/*" ! -path "*/node_modules/*" 2>/dev/null | while read -r file; do
    echo "⚠️  ENCONTRADO: $file" | tee -a "$OUTPUT_FILE"
done
echo "" | tee -a "$OUTPUT_FILE"

# Buscar cada patrón
TOTAL_FINDINGS=0

for pattern in "${PATTERNS[@]}"; do
    echo "🔍 Buscando: $pattern" | tee -a "$OUTPUT_FILE"
    
    # Buscar en archivos de texto
    while IFS= read -r file; do
        # Verificar que no esté en paths ignorados
        skip=false
        for ignore in "${IGNORE_PATHS[@]}"; do
            if [[ "$file" == *"$ignore"* ]]; then
                skip=true
                break
            fi
        done
        
        if [ "$skip" = false ]; then
            matches=$(grep -iE "$pattern" "$file" 2>/dev/null | wc -l)
            if [ "$matches" -gt 0 ]; then
                echo "  ⚠️  $file ($matches coincidencias)" | tee -a "$OUTPUT_FILE"
                grep -iE "$pattern" "$file" 2>/dev/null | head -3 | sed 's/^/    /' | tee -a "$OUTPUT_FILE"
                TOTAL_FINDINGS=$((TOTAL_FINDINGS + matches))
            fi
        fi
    done < <(find "$PROJECT_DIR" -type f \( -name "*.py" -o -name "*.js" -o -name "*.ts" -o -name "*.java" -o -name "*.go" -o -name "*.sh" -o -name "*.env*" -o -name "*.config" -o -name "*.yaml" -o -name "*.yml" -o -name "*.json" -o -name "*.md" -o -name "*.txt" \) ! -path "*/.git/*" ! -path "*/node_modules/*" ! -path "*/__pycache__/*" ! -path "*/.venv/*" ! -path "*/venv/*" 2>/dev/null)
done

echo "" | tee -a "$OUTPUT_FILE"
echo "═══════════════════════════════════════════════════════════" | tee -a "$OUTPUT_FILE"
echo "📊 RESUMEN" | tee -a "$OUTPUT_FILE"
echo "═══════════════════════════════════════════════════════════" | tee -a "$OUTPUT_FILE"
echo "" | tee -a "$OUTPUT_FILE"
echo "Total de coincidencias encontradas: $TOTAL_FINDINGS" | tee -a "$OUTPUT_FILE"
echo "" | tee -a "$OUTPUT_FILE"

if [ "$TOTAL_FINDINGS" -gt 0 ]; then
    echo "⚠️  ATENCIÓN: Se encontraron datos potencialmente sensibles" | tee -a "$OUTPUT_FILE"
    echo "   Revisa el reporte completo en: $OUTPUT_FILE" | tee -a "$OUTPUT_FILE"
    echo "" | tee -a "$OUTPUT_FILE"
    echo "💡 Recomendaciones:" | tee -a "$OUTPUT_FILE"
    echo "   1. Mueve datos sensibles a variables de entorno" | tee -a "$OUTPUT_FILE"
    echo "   2. Usa archivos .env.example como plantilla" | tee -a "$OUTPUT_FILE"
    echo "   3. Agrega .env a .gitignore" | tee -a "$OUTPUT_FILE"
    echo "   4. Usa secret managers (GCP Secret Manager, AWS Secrets, etc.)" | tee -a "$OUTPUT_FILE"
else
    echo "✅ No se encontraron datos sensibles obvios" | tee -a "$OUTPUT_FILE"
    echo "   (Revisa manualmente archivos .env y configuraciones)" | tee -a "$OUTPUT_FILE"
fi

echo "" | tee -a "$OUTPUT_FILE"
echo "📄 Reporte completo guardado en: $OUTPUT_FILE" | tee -a "$OUTPUT_FILE"
