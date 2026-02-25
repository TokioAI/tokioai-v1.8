#!/bin/sh
set -e

# Ejecutar el entrypoint original de la imagen base
if [ -f /docker-entrypoint.sh ]; then
    /docker-entrypoint.sh "$@"
fi

# Esperar a que nginx esté iniciando y el default.conf esté generado
sleep 5

# Ejecutar nuestro script de configuración personalizada
if [ -f /usr/local/bin/99-tokio-custom.sh ]; then
    echo "Ejecutando configuración personalizada de Tokio AI..."
    /usr/local/bin/99-tokio-custom.sh
    echo "Configuración de Tokio AI aplicada"
fi

# Mantener el contenedor corriendo
exec "$@"

