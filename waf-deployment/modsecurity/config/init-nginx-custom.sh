#!/bin/sh
# Script para agregar configuración personalizada de Tokio AI a nginx

# Agregar error_page 403 dentro del bloque server
if ! grep -q "error_page 403" /etc/nginx/conf.d/default.conf; then
    sed -i '/listen 8080 default_server;/a\    error_page 403 /403-blocked.html;' /etc/nginx/conf.d/default.conf
fi

# Agregar location para logo si no existe
if ! grep -q "logo-tokio-removebg-preview.png" /etc/nginx/conf.d/default.conf; then
    sed -i '/location \/ {/a\    location = /logo-tokio-removebg-preview.png {\n        root /usr/share/nginx/html;\n        access_log off;\n    }' /etc/nginx/conf.d/default.conf
fi

# Agregar location para página 403 si no existe
if ! grep -q "location = /403-blocked.html" /etc/nginx/conf.d/default.conf; then
    sed -i '/location \/ {/a\    location = /403-blocked.html {\n        root /usr/share/nginx/html;\n        internal;\n    }' /etc/nginx/conf.d/default.conf
fi

