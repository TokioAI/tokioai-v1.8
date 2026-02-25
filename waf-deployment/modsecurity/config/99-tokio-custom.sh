#!/bin/sh
set -e

# Esperar a que nginx genere el default.conf desde el template
sleep 3

# Verificar que default.conf existe
if [ ! -f /etc/nginx/conf.d/default.conf ]; then
    echo "ERROR: default.conf no existe aún"
    exit 1
fi

# Reemplazar error_page 403 por error_page completo para todos los códigos
sed -i 's|error_page 403 /403-blocked.html;|error_page 401 403 404 500 502 503 504 /error-blocked.html;|g' /etc/nginx/conf.d/default.conf

# Eliminar error_page 50x de location_common.conf
sed -i 's|error_page 500 502 503 504  /50x.html;|# error_page 500 502 503 504  /50x.html; # Reemplazado por Tokio AI|g' /etc/nginx/includes/location_common.conf 2>/dev/null || true

# Eliminar locations duplicados o mal ubicados (dentro de location /)
sed -i '/location = \/403-blocked.html {/,/}/d' /etc/nginx/conf.d/default.conf
sed -i '/location = \/logo-tokio-removebg-preview.png {/,/}/d' /etc/nginx/conf.d/default.conf
sed -i '/location = \/error-blocked.html {/,/}/d' /etc/nginx/conf.d/default.conf

# Agregar locations correctamente (fuera de location /, al mismo nivel)
sed -i '/include includes\/location_common.conf;/i\
    location = /error-blocked.html {\
        root /usr/share/nginx/html;\
        internal;\
    }\
    location = /403-blocked.html {\
        root /usr/share/nginx/html;\
        internal;\
    }\
    location = /logo-tokio-removebg-preview.png {\
        root /usr/share/nginx/html;\
        access_log off;\
        # ModSecurity deshabilitado mediante modsec-exclusions.conf\
    }' /etc/nginx/conf.d/default.conf

# También agregar para el bloque SSL (8443) si existe
sed -i '/listen 8443 ssl;/a\    error_page 401 403 404 500 502 503 504 /error-blocked.html;' /etc/nginx/conf.d/default.conf 2>/dev/null || true

echo "✅ Configuración de Tokio AI aplicada: error_page para 401,403,404,500,502,503,504"

# Verificar configuración de nginx
nginx -t

echo "✅ Configuración de Tokio AI aplicada correctamente"
