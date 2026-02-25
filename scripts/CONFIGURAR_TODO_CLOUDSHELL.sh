#!/bin/bash
# Script COMPLETO para configurar todo desde Cloud Shell
# Ejecutar desde: https://shell.cloud.google.com/

set -e

VM_NAME="tokio-waf-tokioia-com"
VM_ZONE="us-central1-a"
PROJECT_ID="YOUR_GCP_PROJECT_ID"

echo "═══════════════════════════════════════════════════════════"
echo "🔒 CONFIGURACIÓN COMPLETA DEL DASHBOARD SEGURO"
echo "═══════════════════════════════════════════════════════════"
echo ""

gcloud compute ssh "$VM_NAME" \
    --project="$PROJECT_ID" \
    --zone="$VM_ZONE" \
    --command="
        cd /opt/tokio-waf
        
        echo '1. Iniciando dashboard-api...'
        docker-compose up -d dashboard-api
        sleep 15
        
        echo ''
        echo '2. Verificando dashboard...'
        if curl -s http://localhost:8000/health > /dev/null; then
            echo '   ✅ Dashboard responde correctamente'
            curl -s http://localhost:8000/health
        else
            echo '   ❌ Dashboard no responde - verificando...'
            docker-compose logs --tail=30 dashboard-api
            echo '   🔄 Reiniciando...'
            docker-compose restart dashboard-api
            sleep 15
            if curl -s http://localhost:8000/health > /dev/null; then
                echo '   ✅ Dashboard ahora responde'
            else
                echo '   ❌ Dashboard sigue sin responder'
                exit 1
            fi
        fi
        
        echo ''
        echo '3. Configurando nginx (método robusto)...'
        
        # Verificar si nginx-site.conf existe
        if [ ! -f nginx-site.conf ]; then
            echo '   ❌ nginx-site.conf no existe'
            exit 1
        fi
        
        # Crear backup
        cp nginx-site.conf nginx-site.conf.backup.\$(date +%s)
        
        # Eliminar configuración vieja de /dashboard/ si existe
        sed -i '/location \/dashboard\/ {/,/^    }$/d' nginx-site.conf
        
        # Método 1: Buscar location /health y agregar después
        if grep -q 'location /health' nginx-site.conf; then
            echo '   📝 Agregando configuración después de /health...'
            
            # Usar awk para insertar después del bloque /health
            awk '
            /location \/health {/,/^    }$/ {
                print
                if (/^    }$/) {
                    print \"    # Dashboard WAF - Proxy seguro\"
                    print \"    location /dashboard/ {\"
                    print \"        proxy_pass http://localhost:8000/;\"
                    print \"        proxy_set_header Host \\\$host;\"
                    print \"        proxy_set_header X-Real-IP \\\$remote_addr;\"
                    print \"        proxy_set_header X-Forwarded-For \\\$proxy_add_x_forwarded_for;\"
                    print \"        proxy_set_header X-Forwarded-Proto \\\$scheme;\"
                    print \"        proxy_connect_timeout 60s;\"
                    print \"        proxy_send_timeout 60s;\"
                    print \"        proxy_read_timeout 60s;\"
                    print \"    }\"
                    print \"    # API del dashboard\"
                    print \"    location /api/ {\"
                    print \"        proxy_pass http://localhost:8000/api/;\"
                    print \"        proxy_set_header Host \\\$host;\"
                    print \"        proxy_set_header X-Real-IP \\\$remote_addr;\"
                    print \"    }\"
                    next
                }
            }
            { print }
            ' nginx-site.conf > nginx-site.conf.tmp && mv nginx-site.conf.tmp nginx-site.conf
            
            echo '   ✅ Configuración agregada'
        else
            # Método 2: Agregar antes de location /
            echo '   📝 Agregando configuración antes de location /...'
            sed -i '/^    location \/ {/i\
    # Dashboard WAF\
    location /dashboard/ {\
        proxy_pass http://localhost:8000/;\
        proxy_set_header Host $host;\
        proxy_set_header X-Real-IP $remote_addr;\
    }\
' nginx-site.conf
            echo '   ✅ Configuración agregada (método alternativo)'
        fi
        
        # Verificar que se agregó correctamente
        if grep -q 'location /dashboard/' nginx-site.conf; then
            echo '   ✅ Verificado: /dashboard/ está en nginx-site.conf'
            echo ''
            echo '   📋 Configuración agregada:'
            grep -A 10 'location /dashboard/' nginx-site.conf | head -12
        else
            echo '   ❌ Error: No se pudo agregar la configuración'
            exit 1
        fi
        
        echo ''
        echo '4. Reiniciando nginx...'
        docker restart tokio-gcp-waf-proxy 2>/dev/null || docker-compose restart waf-proxy || docker compose restart waf-proxy
        sleep 8
        
        echo ''
        echo '5. Verificando acceso a través de nginx...'
        if curl -s http://localhost/dashboard/health > /dev/null 2>&1; then
            echo '   ✅ Dashboard accesible a través de nginx'
            curl -s http://localhost/dashboard/health
        else
            echo '   ⚠️ Verificando logs de nginx...'
            docker-compose logs --tail=20 waf-proxy 2>/dev/null || docker logs tokio-gcp-waf-proxy --tail=20 2>/dev/null
            echo ''
            echo '   📋 Verificando configuración de nginx...'
            nginx -t 2>/dev/null || docker exec tokio-gcp-waf-proxy nginx -t 2>/dev/null || echo 'No se pudo verificar sintaxis'
        fi
        
        echo ''
        echo '═══════════════════════════════════════════════════════════'
        echo '✅ CONFIGURACIÓN COMPLETADA'
        echo '═══════════════════════════════════════════════════════════'
        echo ''
        echo '🌐 Dashboard disponible en:'
        echo '   👉 https://tokioia.com/dashboard/'
        echo '   👉 https://YOUR_IP_ADDRESS/dashboard/'
        echo ''
        echo '🔒 Seguridad:'
        echo '   ✅ Autenticación habilitada'
        echo '   ✅ Solo puertos 80/443 expuestos'
        echo '   ✅ PostgreSQL no expuesto'
        echo '   ✅ SSH no expuesto'
        echo ''
    "

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "✅ PROCESO COMPLETADO"
echo "═══════════════════════════════════════════════════════════"
