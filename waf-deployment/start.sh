#!/bin/bash
# Script de inicio rápido - WAF Deployment

echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║     🚀 WAF + PROXY + MODSECURITY - INICIO RÁPIDO                    ║"
echo "╚══════════════════════════════════════════════════════════════════════╝"
echo ""

# Verificar que estamos en el directorio correcto
if [ ! -f "docker-compose.yml" ]; then
    echo "❌ Error: Ejecutar desde el directorio waf-deployment"
    echo "   cd /home/osboxes/SOC-AI-LAB/waf-deployment"
    exit 1
fi

# Verificar .env
if [ ! -f ".env" ]; then
    echo "📝 Creando .env desde .env.example..."
    cp .env.example .env
    echo "⚠️  Por favor, edita .env con tus valores antes de continuar"
    echo ""
    read -p "¿Continuar con valores por defecto? (s/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Ss]$ ]]; then
        exit 1
    fi
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📋 OPCIONES:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "1. 🚀 Desplegar WAF en GCP"
echo "2. 🌐 Agregar sitio web"
echo "3. 💾 Hacer backup"
echo "4. 📦 Restaurar desde backup"
echo "5. 🔍 Verificar estado"
echo "6. 📚 Ver documentación"
echo "7. ❌ Salir"
echo ""
read -p "Selecciona una opción (1-7): " opcion

case $opcion in
    1)
        echo ""
        echo "🚀 Desplegando WAF..."
        ./scripts/deploy-waf.sh
        ;;
    2)
        echo ""
        echo "🌐 Agregando sitio web..."
        ./scripts/add-website.sh
        ;;
    3)
        echo ""
        echo "💾 Haciendo backup..."
        ./scripts/backup-waf.sh
        ;;
    4)
        echo ""
        echo "📦 Restaurando desde backup..."
        echo "Backups disponibles:"
        ls -lh /home/osboxes/SOC-AI-LAB/waf-backups/*.tar.gz 2>/dev/null | tail -5
        echo ""
        read -p "Ingresa la ruta del backup: " backup_file
        ./scripts/restore-waf.sh "$backup_file"
        ;;
    5)
        echo ""
        echo "🔍 Verificando estado..."
        ./scripts/verify-waf.sh
        ;;
    6)
        echo ""
        echo "📚 Documentación disponible:"
        echo "   • README.md - Documentación completa"
        echo "   • QUICKSTART.md - Inicio rápido"
        echo "   • DEPLOY-TO-NEW-GCP.md - Desplegar en nueva nube"
        echo "   • RESUMEN.md - Resumen ejecutivo"
        echo "   • INSTRUCCIONES.md - Instrucciones de uso"
        echo ""
        read -p "¿Abrir README.md? (s/n): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Ss]$ ]]; then
            cat README.md | less
        fi
        ;;
    7)
        echo ""
        echo "👋 ¡Hasta luego!"
        exit 0
        ;;
    *)
        echo ""
        echo "❌ Opción inválida"
        exit 1
        ;;
esac
