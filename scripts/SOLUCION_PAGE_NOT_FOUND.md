# 🔧 Solución: "Page Not Found" en Dashboard

## 🔍 Problema

El error "Page Not Found" ocurre porque:
1. El dashboard espera rutas como `/` y `/login`
2. Nginx está enviando `/dashboard/` al dashboard sin reescribir
3. O el dashboard no está corriendo

## ✅ Solución: Comando desde Cloud Shell

**Ir a:** https://shell.cloud.google.com/

**Copiar y pegar este comando completo:**

```bash
gcloud compute ssh tokio-waf-tokioia-com \
    --project=YOUR_GCP_PROJECT_ID \
    --zone=us-central1-a \
    --command="
        cd /opt/tokio-waf
        
        echo '═══════════════════════════════════════════════════════════'
        echo '🔧 REPARANDO DASHBOARD'
        echo '═══════════════════════════════════════════════════════════'
        echo ''
        
        # 1. Iniciar dashboard si no está corriendo
        echo '1. Verificando dashboard...'
        if ! docker ps | grep -q dashboard-api; then
            echo '   ⚠️ Dashboard NO está corriendo - Iniciando...'
            docker-compose up -d dashboard-api
            sleep 5
        else
            echo '   ✅ Dashboard está corriendo'
        fi
        
        # Verificar que responda
        if curl -s http://localhost:8000/health > /dev/null 2>&1; then
            echo '   ✅ Dashboard responde en /health'
        else
            echo '   ❌ Dashboard NO responde - Reiniciando...'
            docker-compose restart dashboard-api
            sleep 5
        fi
        
        echo ''
        echo '2. Configurando nginx...'
        
        # Verificar si ya tiene la configuración
        if grep -q 'location /dashboard/' nginx-site.conf 2>/dev/null; then
            echo '   ✅ Nginx ya tiene /dashboard/ configurado'
            
            # Verificar que proxy_pass tenga la barra final (importante!)
            if grep -A 2 'location /dashboard/' nginx-site.conf | grep -q 'proxy_pass http://localhost:8000/;'; then
                echo '   ✅ proxy_pass está correcto (con barra final)'
            else
                echo '   ⚠️ proxy_pass puede estar mal - Corrigiendo...'
                # Reemplazar proxy_pass sin barra por uno con barra
                sed -i 's|proxy_pass http://localhost:8000;|proxy_pass http://localhost:8000/;|g' nginx-site.conf
                docker restart tokio-gcp-waf-proxy 2>/dev/null || docker-compose restart waf-proxy
                sleep 3
                echo '   ✅ Corregido'
            fi
        else
            echo '   ⚠️ Falta configuración - Agregando...'
            
            # Crear backup
            cp nginx-site.conf nginx-site.conf.backup.\$(date +%s)
            
            # Agregar configuración CORRECTA (con barra final en proxy_pass)
            sed -i '/location \/health {/,/}/a\
    # Dashboard WAF - IMPORTANTE: barra final en proxy_pass reescribe /dashboard/ a /\n    location /dashboard/ {\n        proxy_pass http://localhost:8000/;\n        proxy_set_header Host \$host;\n        proxy_set_header X-Real-IP \$remote_addr;\n        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;\n        proxy_set_header X-Forwarded-Proto \$scheme;\n        proxy_connect_timeout 60s;\n        proxy_send_timeout 60s;\n        proxy_read_timeout 60s;\n    }\n    # API del dashboard\n    location /api/ {\n        proxy_pass http://localhost:8000/api/;\n        proxy_set_header Host \$host;\n        proxy_set_header X-Real-IP \$remote_addr;\n    }\
' nginx-site.conf
            
            echo '   ✅ Configuración agregada'
            
            # Reiniciar nginx
            echo '   🔄 Reiniciando nginx...'
            docker restart tokio-gcp-waf-proxy 2>/dev/null || docker-compose restart waf-proxy
            sleep 3
        fi
        
        echo ''
        echo '3. Verificando acceso...'
        
        # Probar diferentes rutas
        echo '   📋 /dashboard/health:'
        HEALTH_CODE=\$(curl -s -o /dev/null -w '%{http_code}' http://localhost/dashboard/health 2>/dev/null || echo '000')
        echo \"      HTTP \$HEALTH_CODE\"
        
        echo '   📋 /dashboard/:'
        DASH_CODE=\$(curl -s -o /dev/null -w '%{http_code}' http://localhost/dashboard/ 2>/dev/null || echo '000')
        echo \"      HTTP \$DASH_CODE\"
        
        if [ \"\$DASH_CODE\" = \"200\" ] || [ \"\$DASH_CODE\" = \"302\" ]; then
            echo '   ✅ Dashboard accesible correctamente'
        else
            echo '   ⚠️ Dashboard aún no accesible - Verificando logs...'
            echo ''
            echo '   📋 Logs de nginx (últimas 10 líneas):'
            docker-compose logs --tail=10 waf-proxy 2>/dev/null || docker logs tokio-gcp-waf-proxy --tail=10 2>/dev/null
        fi
        
        echo ''
        echo '═══════════════════════════════════════════════════════════'
        echo '✅ PROCESO COMPLETADO'
        echo '═══════════════════════════════════════════════════════════'
        echo ''
        echo '🌐 Acceder al dashboard:'
        echo '   👉 http://YOUR_IP_ADDRESS/dashboard/'
        echo ''
        echo '💡 Si aún ves \"Page Not Found\":'
        echo '   1. Verificar logs: docker-compose logs dashboard-api'
        echo '   2. Verificar nginx: docker-compose logs waf-proxy'
        echo '   3. Probar directamente: curl http://localhost:8000/'
        echo ''
    "
```

## 🔑 Puntos Clave

1. **Barra final en proxy_pass**: `proxy_pass http://localhost:8000/;` (con `/` al final)
   - Esto hace que nginx reemplace `/dashboard/` con `/` antes de enviarlo al dashboard
   
2. **Dashboard debe estar corriendo**: Verificar con `docker ps | grep dashboard-api`

3. **Nginx debe reiniciarse**: Después de cambiar la configuración

## 📝 Verificación Manual

Si querés verificar manualmente:

```bash
# Desde Cloud Shell, conectarse a la VM
gcloud compute ssh tokio-waf-tokioia-com --zone=us-central1-a

# Verificar dashboard
cd /opt/tokio-waf
docker ps | grep dashboard
curl http://localhost:8000/health

# Verificar nginx
grep -A 5 'location /dashboard/' nginx-site.conf

# Probar acceso
curl -I http://localhost/dashboard/
```

## 🆘 Si Aún No Funciona

1. **Verificar que el dashboard tenga el HTML estático:**
   ```bash
   docker exec tokio-gcp-dashboard-api ls -la /app/static/
   ```

2. **Verificar logs del dashboard:**
   ```bash
   docker-compose logs dashboard-api | tail -50
   ```

3. **Probar acceso directo al dashboard (sin nginx):**
   ```bash
   curl http://localhost:8000/
   ```
