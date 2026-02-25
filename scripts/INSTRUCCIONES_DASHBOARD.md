# 🔐 Instrucciones para Acceder al Dashboard WAF

## ⚠️ Problema Actual

- El puerto 22 (SSH) está bloqueado por seguridad ✅
- No se puede acceder directamente por SSH desde tu máquina
- El dashboard no responde en el puerto 8000

## ✅ Soluciones Disponibles

### Opción 1: Cloud Shell de GCP (MÁS FÁCIL)

1. **Ir a Cloud Shell:**
   ```
   https://shell.cloud.google.com/
   ```

2. **Conectar a la VM:**
   ```bash
   gcloud compute ssh tokio-waf-tokioia-com \
       --project=YOUR_GCP_PROJECT_ID \
       --zone=us-central1-a
   ```

3. **Verificar y arreglar el dashboard:**
   ```bash
   cd /opt/tokio-waf
   
   # Verificar contenedores
   docker ps
   
   # Verificar dashboard
   docker ps | grep dashboard
   
   # Si no está corriendo, iniciarlo
   docker-compose up -d dashboard-api
   
   # Verificar que funcione
   curl http://localhost:8000/health
   
   # Ver logs si hay problemas
   docker-compose logs dashboard-api
   ```

4. **Salir de SSH y acceder al dashboard:**
   ```
   http://YOUR_IP_ADDRESS:8000
   ```

---

### Opción 2: SSH Temporal (si la regla ya se aplicó)

La regla SSH temporal ya está creada: `allow-ssh-temp-1771884161`

**Esperá 1-2 minutos** y luego intentá:

```bash
gcloud compute ssh tokio-waf-tokioia-com \
    --project=YOUR_GCP_PROJECT_ID \
    --zone=us-central1-a
```

Si funciona, ejecutar los mismos comandos de la Opción 1.

---

### Opción 3: Acceso a través de Nginx (después de configurar)

Si configurás nginx para hacer proxy al dashboard:

1. Acceder por SSH (Cloud Shell o temporal)
2. Ejecutar: `./scripts/add_dashboard_to_nginx_vm.sh`
3. Acceder a: `http://YOUR_IP_ADDRESS/dashboard/`

---

## 🔧 Comandos Útiles

### Verificar estado del dashboard:
```bash
docker ps | grep dashboard
docker-compose logs dashboard-api --tail=50
curl http://localhost:8000/health
```

### Reiniciar dashboard:
```bash
cd /opt/tokio-waf
docker-compose restart dashboard-api
```

### Ver todos los contenedores:
```bash
docker ps -a
```

### Verificar puertos:
```bash
netstat -tlnp | grep 8000
# o
ss -tlnp | grep 8000
```

---

## 🗑️ Limpiar Reglas Temporales

Cuando termines, eliminá las reglas temporales:

```bash
./scripts/cleanup_temp_firewalls.sh
```

O manualmente:
```bash
gcloud compute firewall-rules delete allow-ssh-temp-1771884161 --project=YOUR_GCP_PROJECT_ID
gcloud compute firewall-rules delete allow-dashboard-1771883416 --project=YOUR_GCP_PROJECT_ID
```

---

## 📋 Estado Actual

- ✅ Regla firewall dashboard: `allow-dashboard-1771883416` (activa)
- ✅ Regla firewall SSH: `allow-ssh-temp-1771884161` (activa, solo tus IPs)
- ⚠️ Dashboard: necesita verificación (probablemente contenedor no corriendo)

---

## 🚀 Próximo Paso

**Usar Cloud Shell de GCP** (Opción 1) - es la forma más rápida y no requiere configuración adicional.
