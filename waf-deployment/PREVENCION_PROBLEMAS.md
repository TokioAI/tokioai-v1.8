# 🛡️ Prevención de Problemas - WAF

## 🔍 ¿Qué pasó?

### Problemas identificados:

1. **Nginx del sistema ocupando puerto 80**
   - Nginx se instaló en el sistema base de la VM
   - Al iniciarse, ocupaba el puerto 80
   - Esto impedía que el contenedor Docker se iniciara
   - **Solución:** Nginx del sistema deshabilitado permanentemente

2. **Contenedores Docker no se iniciaban automáticamente**
   - Después de reiniciar la VM, los contenedores quedaban detenidos
   - No había un servicio systemd configurado
   - **Solución:** Servicio systemd `tokio-ai-waf.service` creado y habilitado

3. **Contenedores con nombres incorrectos**
   - Había contenedores viejos con nombres diferentes corriendo
   - Esto causaba conflictos de puertos
   - **Solución:** Contenedores incorrectos eliminados, solo los correctos están corriendo

## ✅ ¿Va a volver a pasar?

**NO**, porque ahora tenemos:

### 1. Nginx del sistema DESHABILITADO permanentemente
- ✅ No se iniciará automáticamente
- ✅ El puerto 80 quedará libre para Docker
- ✅ Verificación: `sudo systemctl is-enabled nginx` (debe decir "disabled")

### 2. Servicio systemd CONFIGURADO
- ✅ Los contenedores se iniciarán automáticamente
- ✅ Funciona después de cada reinicio de la VM
- ✅ Se ejecuta cuando Docker esté listo
- ✅ Verificación: `sudo systemctl is-enabled tokio-ai-waf.service` (debe decir "enabled")

### 3. Contenedores correctos configurados
- ✅ Solo los contenedores correctos están corriendo
- ✅ Nombres consistentes: `tokio-ai-modsecurity`, `tokio-ai-log-processor`
- ✅ Verificación: `docker ps | grep tokio-ai`

## 🔧 Cómo verificar que todo esté bien

### Verificación rápida:
```bash
# Desde tu máquina local
gcloud compute ssh tokio-ai-waf --zone=us-central1-a --tunnel-through-iap --command="
  echo '1. Nginx del sistema:'
  sudo systemctl is-enabled nginx || echo 'Deshabilitado ✅'
  echo ''
  echo '2. Servicio systemd:'
  sudo systemctl is-enabled tokio-ai-waf.service
  echo ''
  echo '3. Contenedores:'
  docker ps --format 'table {{.Names}}\t{{.Status}}' | grep tokio-ai
"
```

### Verificación manual (SSH):
```bash
# Conectarse a la VM
gcloud compute ssh tokio-ai-waf --zone=us-central1-a --tunnel-through-iap

# Verificar nginx del sistema
sudo systemctl status nginx
# Debe decir "disabled" o "inactive"

# Verificar servicio systemd
sudo systemctl status tokio-ai-waf.service
# Debe decir "enabled" y "active (exited)"

# Verificar contenedores
docker ps
# Debe mostrar tokio-ai-modsecurity y tokio-ai-log-processor

# Verificar puertos
sudo lsof -i :80
# Solo debe mostrar procesos de Docker
```

## 🚨 Si el sitio se cae de nuevo

### Pasos de diagnóstico:

1. **Verificar que la VM esté corriendo:**
   ```bash
   gcloud compute instances describe tokio-ai-waf --zone=us-central1-a --format="get(status)"
   # Debe decir "RUNNING"
   ```

2. **Verificar que el servicio systemd esté habilitado:**
   ```bash
   gcloud compute ssh tokio-ai-waf --zone=us-central1-a --tunnel-through-iap --command="sudo systemctl is-enabled tokio-ai-waf.service"
   # Debe decir "enabled"
   ```

3. **Verificar que los contenedores estén corriendo:**
   ```bash
   gcloud compute ssh tokio-ai-waf --zone=us-central1-a --tunnel-through-iap --command="docker ps"
   # Debe mostrar tokio-ai-modsecurity
   ```

4. **Si es necesario, reiniciar el servicio:**
   ```bash
   gcloud compute ssh tokio-ai-waf --zone=us-central1-a --tunnel-through-iap --command="sudo systemctl restart tokio-ai-waf.service"
   ```

5. **Si aún no funciona, reiniciar contenedores manualmente:**
   ```bash
   gcloud compute ssh tokio-ai-waf --zone=us-central1-a --tunnel-through-iap --command="cd /opt/tokio-ai-waf && docker compose -f docker-compose.gcp.yml restart"
   ```

## 💡 Recomendaciones adicionales

### 1. Monitoreo
- Configura alertas en GCP para cuando la VM se reinicie
- Verifica periódicamente que el sitio esté accesible
- Usa herramientas de monitoreo como Uptime Robot o similar

### 2. Backups
- Ya tienes scripts de backup configurados (`backup-waf.sh`)
- Úsalos regularmente para tener respaldo
- Guarda backups en un lugar seguro

### 3. Logs
- Revisa los logs periódicamente:
  ```bash
  docker logs tokio-ai-modsecurity
  docker logs tokio-ai-log-processor
  ```

### 4. Actualizaciones
- Mantén el sistema actualizado
- Actualiza los contenedores Docker periódicamente
- Revisa las actualizaciones de seguridad

## 📋 Checklist de prevención

- [ ] Nginx del sistema deshabilitado
- [ ] Servicio systemd habilitado
- [ ] Contenedores corriendo con nombres correctos
- [ ] Puerto 80 libre (solo usado por Docker)
- [ ] Scripts de backup configurados
- [ ] Monitoreo configurado (opcional pero recomendado)

## 🔗 Archivos relacionados

- `/etc/systemd/system/tokio-ai-waf.service` - Servicio systemd
- `/opt/tokio-ai-waf/docker-compose.gcp.yml` - Configuración Docker Compose
- `/opt/tokio-ai-waf/start.sh` - Script de inicio manual

---

**Última actualización:** $(date +%Y-%m-%d\ %H:%M:%S)
