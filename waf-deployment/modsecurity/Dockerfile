# Dockerfile personalizado para ModSecurity con página 403 de Tokio AI
FROM owasp/modsecurity-crs:nginx-alpine

# Copiar logo de Tokio AI
COPY modsecurity/html/logo-tokio-removebg-preview.png /usr/share/nginx/html/logo-tokio-removebg-preview.png

# Copiar páginas de error personalizadas
COPY modsecurity/html/403-blocked.html /usr/share/nginx/html/403-blocked.html
COPY modsecurity/html/error-blocked.html /usr/share/nginx/html/error-blocked.html

# Reemplazar el template de default.conf con nuestra versión personalizada
COPY modsecurity/config/default.conf.template /etc/nginx/templates/conf.d/default.conf.template

# Copiar reglas de exclusión de ModSecurity para recursos estáticos
COPY modsecurity/config/modsec-exclusions.conf /etc/modsecurity.d/modsec-exclusions.conf
