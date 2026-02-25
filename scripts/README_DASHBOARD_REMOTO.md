# 🌐 Acceso Remoto al Dashboard - Sin Interfaz Gráfica

## 📋 Opciones Disponibles

Tienes 3 opciones para acceder al dashboard sin interfaz gráfica:

### Opción 1: Túnel SSH Manual (Simple) ✅

Ejecuta cuando necesites acceder:

```bash
./scripts/acceder_dashboard_remoto.sh
```

Esto crea un túnel SSH y el dashboard queda disponible en `http://localhost:8000/`

**Ventajas:**
- Simple y rápido
- No requiere configuración permanente
- Se detiene cuando cierras la terminal

**Desventajas:**
- Debes mantener la terminal abierta
- Se detiene si se cierra la sesión

---

### Opción 2: Servicio Systemd (Recomendado) ✅✅

Configura un servicio que mantiene el túnel activo siempre:

```bash
./scripts/dashboard_servicio_systemd.sh
```

Esto crea un servicio systemd que:
- Se inicia automáticamente al arrancar la Raspberry
- Se reinicia automáticamente si falla
- Mantiene el túnel activo siempre

**Ventajas:**
- Funciona siempre, sin necesidad de iniciarlo manualmente
- Se reinicia automáticamente
- Accesible desde cualquier navegador en la red local

**Desventajas:**
- Requiere configuración inicial

**Comandos útiles:**
```bash
# Ver estado
sudo systemctl status tokio-dashboard-tunnel

# Ver logs
sudo journalctl -u tokio-dashboard-tunnel -f

# Reiniciar
sudo systemctl restart tokio-dashboard-tunnel

# Detener
sudo systemctl stop tokio-dashboard-tunnel
```

---

### Opción 3: Nginx Proxy (Para acceso desde red local) ✅

Configura Nginx como proxy reverso:

```bash
./scripts/dashboard_nginx_proxy.sh
```

Esto configura Nginx para:
- Proxear el dashboard desde la VM de GCP
- Exponerlo en un puerto local (por defecto 8080)
- Accesible desde cualquier dispositivo en tu red local

**Ventajas:**
- Accesible desde cualquier dispositivo en tu red local
- No requiere mantener túnel SSH activo
- Más rápido (proxy directo)

**Desventajas:**
- Requiere que la VM de GCP sea accesible desde la Raspberry
- Depende de la conectividad con GCP

**Acceso:**
- `http://localhost:8080/` (desde la Raspberry)
- `http://[IP_RASPBERRY]:8080/` (desde otros dispositivos en tu red)

---

## 🎯 Recomendación

**Para uso personal (solo tú):**
- Usa **Opción 1** (túnel SSH manual) - Simple y rápido

**Para acceso permanente:**
- Usa **Opción 2** (servicio systemd) - Se mantiene activo siempre

**Para acceso desde múltiples dispositivos:**
- Usa **Opción 3** (Nginx proxy) - Accesible desde toda tu red local

---

## 🔍 Verificar que Funciona

```bash
# Probar acceso local
curl http://localhost:8000/health

# O desde otro dispositivo en tu red
curl http://[IP_RASPBERRY]:8000/health
```

---

## 📝 Notas

- El dashboard corre en la VM de GCP (YOUR_IP_ADDRESS:8000)
- Estos scripts crean un túnel/proxy desde la Raspberry hacia la VM
- No necesitas interfaz gráfica, solo acceso SSH a la Raspberry
