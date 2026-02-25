# 🌐 Túnel Dashboard en Red Local

## 📋 Descripción

Este script configura un túnel que expone el dashboard de GCP (YOUR_IP_ADDRESS:8000) en la IP local de la Raspberry Pi (YOUR_IP_ADDRESS:8000).

**Resultado:** Puedes acceder al dashboard desde cualquier dispositivo en tu red local usando `http://YOUR_IP_ADDRESS:8000/`

## 🚀 Instalación

```bash
./scripts/dashboard_tunel_red_local.sh
```

Este script:
1. ✅ Verifica conectividad con la VM de GCP
2. ✅ Instala `socat` (si no está instalado)
3. ✅ Crea un servicio systemd que mantiene el túnel activo
4. ✅ Configura el túnel para escuchar en todas las interfaces (YOUR_IP_ADDRESS)
5. ✅ Se inicia automáticamente al arrancar la Raspberry

## 🌐 Acceso

Una vez configurado, el dashboard estará disponible en:

- **Desde la Raspberry:** `http://localhost:8000/`
- **Desde otros dispositivos en tu red:** `http://YOUR_IP_ADDRESS:8000/`
- **Desde cualquier dispositivo en tu red:** `http://[IP_RASPBERRY]:8000/`

## 📋 Comandos Útiles

### Ver estado del servicio
```bash
sudo systemctl status tokio-dashboard-tunnel
```

### Ver logs en tiempo real
```bash
sudo journalctl -u tokio-dashboard-tunnel -f
```

### Reiniciar el túnel
```bash
sudo systemctl restart tokio-dashboard-tunnel
```

### Detener el túnel
```bash
sudo systemctl stop tokio-dashboard-tunnel
```

### Iniciar el túnel
```bash
sudo systemctl start tokio-dashboard-tunnel
```

### Deshabilitar inicio automático
```bash
sudo systemctl disable tokio-dashboard-tunnel
```

## 🔍 Verificar que Funciona

### Desde la Raspberry:
```bash
curl http://localhost:8000/health
```

### Desde otro dispositivo en tu red:
```bash
curl http://YOUR_IP_ADDRESS:8000/health
```

### Verificar que el puerto está escuchando:
```bash
sudo ss -tlnp | grep :8000
```

Deberías ver algo como:
```
LISTEN 0 128 YOUR_IP_ADDRESS:8000 YOUR_IP_ADDRESS:* users:(("socat",pid=12345,fd=3))
```

## 🔧 Cómo Funciona

1. **Túnel SSH:** Se crea un túnel SSH desde la Raspberry hacia la VM de GCP
   - Escucha en `YOUR_IP_ADDRESS:18000` (solo localhost)
   - Conecta a `YOUR_IP_ADDRESS:8000` (dashboard en GCP)

2. **Proxy Socat:** `socat` actúa como proxy
   - Escucha en `YOUR_IP_ADDRESS:8000` (todas las interfaces)
   - Redirige tráfico a `YOUR_IP_ADDRESS:18000` (túnel SSH)

3. **Servicio Systemd:** Mantiene el túnel activo siempre
   - Se reinicia automáticamente si falla
   - Se inicia al arrancar la Raspberry

## ⚠️ Requisitos

- ✅ `gcloud` instalado y configurado
- ✅ Acceso SSH a la VM de GCP (puerto 22 abierto desde tu IP)
- ✅ Firewall rules en GCP que permitan acceso desde tu IP
- ✅ `socat` instalado (el script lo instala automáticamente)

## 🐛 Solución de Problemas

### El servicio no inicia
```bash
# Ver logs detallados
sudo journalctl -u tokio-dashboard-tunnel.service -n 50 --no-pager

# Verificar que gcloud funciona
gcloud compute ssh tokio-waf-tokioia-com --zone=us-central1-a --project=YOUR_GCP_PROJECT_ID --command="echo OK"
```

### El puerto no está escuchando
```bash
# Verificar que no hay otro proceso usando el puerto
sudo lsof -i :8000

# Verificar logs del servicio
sudo journalctl -u tokio-dashboard-tunnel.service -f
```

### No puedo acceder desde otros dispositivos
```bash
# Verificar que el puerto escucha en YOUR_IP_ADDRESS (no solo YOUR_IP_ADDRESS)
sudo ss -tlnp | grep :8000

# Debe mostrar: YOUR_IP_ADDRESS:8000 (no YOUR_IP_ADDRESS:8000)
```

### El túnel se cae frecuentemente
```bash
# Verificar conectividad con GCP
ping YOUR_IP_ADDRESS

# Verificar firewall rules
gcloud compute firewall-rules list --filter="sourceRanges:TU_IP/32"
```

## 📝 Notas

- El túnel requiere que la VM de GCP esté accesible desde la Raspberry
- Si cambias la IP de la Raspberry, actualiza las firewall rules en GCP
- El servicio se reinicia automáticamente si falla (cada 10 segundos)
- Los logs se guardan en el journal de systemd
