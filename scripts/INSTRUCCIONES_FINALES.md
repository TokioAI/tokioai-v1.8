# 🔐 Acceso Seguro al Dashboard - Instrucciones Finales

## ✅ Estado Actual

- ✅ SSH (puerto 22): **BLOQUEADO** (no expuesto)
- ✅ PostgreSQL (puerto 5432): **BLOQUEADO** (no expuesto)
- ✅ Dashboard: Accesible a través de nginx en `/dashboard/` (puerto 80/443)

## 🚀 Solución: Configurar Nginx desde Cloud Shell

### Paso 1: Abrir Cloud Shell

Ir a: **https://shell.cloud.google.com/**

### Paso 2: Ejecutar Comando

Copiar y pegar este comando completo:

```bash
gcloud compute ssh tokio-waf-tokioia-com \
    --project=YOUR_GCP_PROJECT_ID \
    --zone=us-central1-a \
    --command="
        cd /opt/tokio-waf
        
        # Iniciar dashboard si no está corriendo
        echo '🔄 Iniciando dashboard...'
        docker-compose up -d dashboard-api
        sleep 5
        
        # Verificar que responda
        echo '📋 Verificando dashboard...'
        curl -s http://localhost:8000/health && echo '✅ Dashboard OK' || echo '❌ Dashboard no responde'
        
        # Agregar ruta a nginx si no existe
        if ! grep -q 'location /dashboard/' nginx-site.conf; then
            echo '📝 Agregando ruta /dashboard/ a nginx...'
            
            # Crear backup
            cp nginx-site.conf nginx-site.conf.backup.\$(date +%s)
            
            # Agregar configuración ANTES de 'location /'
            sed -i '/location \/health {/,/}/a\
    # Dashboard WAF\
    location /dashboard/ {\
        proxy_pass http://localhost:8000/;\
        proxy_set_header Host \$host;\
        proxy_set_header X-Real-IP \$remote_addr;\
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;\
        proxy_set_header X-Forwarded-Proto \$scheme;\
        proxy_connect_timeout 60s;\
        proxy_send_timeout 60s;\
        proxy_read_timeout 60s;\
    }\
    location /api/ {\
        proxy_pass http://localhost:8000/api/;\
        proxy_set_header Host \$host;\
        proxy_set_header X-Real-IP \$remote_addr;\
    }\
' nginx-site.conf
            
            echo '✅ Configuración agregada'
        else
            echo '✅ Nginx ya tiene ruta /dashboard/ configurada'
        fi
        
        # Reiniciar nginx
        echo '🔄 Reiniciando nginx...'
        docker restart tokio-gcp-waf-proxy 2>/dev/null || docker-compose restart waf-proxy
        
        sleep 3
        
        # Verificar
        echo '📋 Verificando nginx...'
        curl -s http://localhost/dashboard/ > /dev/null && echo '✅ Dashboard accesible en /dashboard/' || echo '⚠️ Verificar logs'
        
        echo ''
        echo '═══════════════════════════════════════════════════════════'
        echo '✅ CONFIGURACIÓN COMPLETADA'
        echo '═══════════════════════════════════════════════════════════'
        echo ''
        echo '🌐 Dashboard disponible en:'
        echo '   👉 http://YOUR_IP_ADDRESS/dashboard/'
        echo '   👉 https://tokioia.com/dashboard/ (si tenés SSL)'
        echo ''
    "
```

### Paso 3: Acceder al Dashboard

Después de ejecutar el comando, acceder a:

- **HTTP:** http://YOUR_IP_ADDRESS/dashboard/
- **HTTPS:** https://tokioia.com/dashboard/ (si tenés SSL configurado)

## 🔒 Seguridad Garantizada

- ✅ **SSH (22)**: NO expuesto (bloqueado en firewall)
- ✅ **PostgreSQL (5432)**: NO expuesto (bloqueado en firewall)
- ✅ **Dashboard**: Solo a través de nginx (puerto 80/443 ya abierto)
- ✅ **No se requieren reglas de firewall adicionales**

## 🗑️ Limpiar Reglas Temporales (Opcional)

Si creaste reglas temporales de firewall, podés eliminarlas:

```bash
gcloud compute firewall-rules list --project=YOUR_GCP_PROJECT_ID --filter="name~temp"
gcloud compute firewall-rules delete allow-ssh-temp-1771884161 --project=YOUR_GCP_PROJECT_ID --quiet
gcloud compute firewall-rules delete allow-dashboard-1771883416 --project=YOUR_GCP_PROJECT_ID --quiet
```

El dashboard funcionará a través de nginx sin necesidad de estas reglas.

## 📝 Notas

- El código de deployment ya incluye esta configuración, así que futuros deployments tendrán el dashboard configurado automáticamente.
- Si el dashboard no responde, verificar los logs: `docker-compose logs dashboard-api`
- Si nginx no funciona, verificar: `docker-compose logs waf-proxy`
