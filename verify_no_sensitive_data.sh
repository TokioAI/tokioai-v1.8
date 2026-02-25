#!/bin/bash
# Script para verificar que no queden datos sensibles en el código

echo "🔍 Verificando datos sensibles en el código..."
echo ""

SENSITIVE_PATTERNS=(
    "soc_password"
    "34\."
    "35\."
    "371011496750"
    "tactical-unison-417816"
    "admin\.airesiliencehub"
    "@protonmail"
)

FOUND_ISSUES=0

for pattern in "${SENSITIVE_PATTERNS[@]}"; do
    echo "Buscando: $pattern"
    RESULTS=$(find . -type f \( -name "*.py" -o -name "*.ts" -o -name "*.js" -o -name "*.yaml" -o -name "*.yml" -o -name "*.sh" \) ! -path "*/node_modules/*" ! -path "*/__pycache__/*" ! -path "*/.git/*" ! -name "verify_no_sensitive_data.sh" ! -name "*.example" -exec grep -l "$pattern" {} \; 2>/dev/null)
    
    if [ -n "$RESULTS" ]; then
        echo "⚠️  Encontrado en:"
        echo "$RESULTS"
        echo ""
        FOUND_ISSUES=$((FOUND_ISSUES + 1))
    else
        echo "✅ No encontrado"
    fi
    echo ""
done

if [ $FOUND_ISSUES -eq 0 ]; then
    echo "✅ ¡Verificación exitosa! No se encontraron datos sensibles."
    exit 0
else
    echo "❌ Se encontraron $FOUND_ISSUES patrones sensibles. Por favor, revisa los archivos listados arriba."
    exit 1
fi
