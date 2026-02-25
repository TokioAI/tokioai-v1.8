# 🔒 Acceso Seguro al Dashboard WAF

## Resumen

El dashboard WAF está configurado para **NO exponer ningún puerto públicamente**. El acceso se realiza de forma segura a través de **SSH tunnels** (port forwarding).

## ✅ Ventajas de Seguridad

- ✅ **No hay puertos expuestos** en el firewall público
- ✅ **No hay riesgo de acceso no autorizado** desde Internet
- ✅ **Usa autenticación de GCP** (Identity-Aware Proxy - IAP)
- ✅ **Tráfico encriptado** a través de SSH
- ✅ **Acceso solo para usuarios autorizados** con credenciales de GCP

## 🚀 Opciones de Acceso

### Opción 1: Desde tu Máquina Local

```bash
./scripts/acceder_dashboard_interno.sh
```

Este script:
- Crea un túnel SSH seguro desde tu máquina a la VM
- Hace disponible el dashboard en `http://localhost:8000/`
- Abre automáticamente el navegador (si está disponible)
- Se detiene con Ctrl+C

**Requisitos:**
- Tener `gcloud` CLI instalado y configurado
- Tener permisos para acceder a la VM en GCP

### Opción 2: Desde Cloud Shell

```bash
./scripts/acceder_dashboard_cloudshell.sh
```

Este script:
- Crea un túnel SSH desde Cloud Shell a la VM
- Hace disponible el dashboard en `http://localhost:8000/`
- Puede usar Cloud Shell Web Preview para abrir el dashboard

**Requisitos:**
- Acceso a Cloud Shell: https://shell.cloud.google.com/
- Permisos para acceder a la VM en GCP

## 📋 Configuración Actual

- **VM:** `tokio-waf-tokioia-com`
- **Zona:** `us-central1-a`
- **Proyecto:** `YOUR_GCP_PROJECT_ID`
- **Dashboard interno:** `localhost:8000` (en la VM)
- **Puerto local:** `8000` (en tu máquina/Cloud Shell)

## 🔧 Personalizar Puerto Local

Si el puerto 8000 está ocupado en tu máquina, puedes especificar otro:

```bash
./scripts/acceder_dashboard_interno.sh tokio-waf-tokioia-com us-central1-a YOUR_GCP_PROJECT_ID 9000
```

Esto usará el puerto 9000 en tu máquina local.

## 🛑 Detener el Túnel

- **Desde el script:** Presiona Ctrl+C
- **Manualmente:** `kill <PID>` (el script muestra el PID)

## 🔍 Verificar que Funciona

Una vez que el túnel esté activo:

```bash
curl http://localhost:8000/health
```

Deberías ver:
```json
{"status":"healthy","db":"ok"}
```

## ⚠️ Solución de Problemas

### Error: "Puerto ya en uso"
```bash
# Encontrar proceso usando el puerto
lsof -i :8000

# Matar el proceso
kill <PID>
```

### Error: "No se puede conectar a la VM"
- Verifica que tengas permisos en GCP
- Verifica que la VM esté corriendo: `gcloud compute instances list`
- Verifica que el dashboard esté corriendo en la VM

### Error: "Dashboard no responde"
- Verifica que el dashboard esté corriendo en la VM:
  ```bash
  gcloud compute ssh tokio-waf-tokioia-com --zone=us-central1-a --command="curl http://localhost:8000/health"
  ```

## 📝 Notas Importantes

1. **El túnel debe mantenerse activo** mientras uses el dashboard
2. **No cierres la terminal** donde corre el script
3. **El dashboard requiere autenticación** (usuario/contraseña configurados)
4. **El acceso es seguro** pero requiere credenciales de GCP válidas

## 🔐 Seguridad Adicional

Para mayor seguridad, puedes:
- Usar **Cloud IAP** para acceso adicional
- Configurar **VPN** a GCP
- Usar **bastion hosts** para acceso intermedio
