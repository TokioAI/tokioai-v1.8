# 🔐 Acceso Seguro al Dashboard WAF

## ⚠️ Nota Importante

**IAP (Identity-Aware Proxy) requiere que el puerto 22 esté accesible internamente.** 
Como el puerto 22 está bloqueado por seguridad, IAP no funciona directamente.

**Solución recomendada:** Usar regla de firewall restrictiva (Opción 2).

---

## 📋 Opciones de Acceso

### 1️⃣ Túnel SSH con GCP IAP (Requiere configuración adicional)

**Ventajas:**
- ✅ No expone puertos públicamente
- ✅ Requiere autenticación de GCP
- ✅ Túnel encriptado end-to-end
- ✅ No requiere cambios en el firewall

**Uso:**

```bash
# Túnel interactivo (recomendado para primera vez)
./scripts/access_dashboard_secure.sh

# Túnel en background
./scripts/access_dashboard_background.sh

# Detener túnel
./scripts/stop_dashboard_tunnel.sh
```

**El dashboard estará disponible en:** `http://localhost:18000`

---

### 2️⃣ Regla de Firewall Restrictiva (Recomendado - Funciona inmediatamente)

Si preferís acceso directo sin túnel, podés crear una regla de firewall que solo permita tu IP:

```bash
# Obtener tu IP pública
MY_IP=$(curl -s ifconfig.me)

# Crear regla de firewall para dashboard (puerto 8000)
gcloud compute firewall-rules create allow-dashboard-my-ip \
    --project=YOUR_GCP_PROJECT_ID \
    --allow tcp:8000 \
    --source-ranges="$MY_IP/32" \
    --target-tags="tokio-waf" \
    --description="Dashboard access from my IP only"

# Acceder directamente
# http://YOUR_IP_ADDRESS:8000
```

**⚠️ Nota:** Esta opción expone el puerto 8000, pero solo a tu IP. Es menos seguro que el túnel SSH.

---

## 🚀 Uso Rápido

### Primera vez:

```bash
cd /home/osboxes/SOC-AI-LAB
./scripts/access_dashboard_secure.sh
```

Luego abrir en el navegador: `http://localhost:18000`

### Uso diario:

```bash
# Iniciar en background
./scripts/access_dashboard_background.sh

# Detener cuando termines
./scripts/stop_dashboard_tunnel.sh
```

---

## 🔧 Troubleshooting

### Error: "No se encontró ninguna VM del WAF"

Verificar que la VM esté corriendo:
```bash
gcloud compute instances list --project=YOUR_GCP_PROJECT_ID --filter="name~tokio-waf"
```

### Error: "Puerto 18000 ya está en uso"

Detener túnel existente:
```bash
./scripts/stop_dashboard_tunnel.sh
```

O usar otro puerto:
```bash
./scripts/access_dashboard_secure.sh "" "" 8000 18001
```

### Error de autenticación GCP

Verificar credenciales:
```bash
gcloud auth login
gcloud config set project YOUR_GCP_PROJECT_ID
```

---

## 📊 Información de la VM

- **Nombre:** `tokio-waf-tokioia-com`
- **Zona:** `us-central1-a`
- **IP Externa:** `YOUR_IP_ADDRESS`
- **Dashboard Interno:** `localhost:8000`

---

## 🔐 Seguridad

✅ **Túnel SSH con IAP:**
- No expone puertos públicamente
- Requiere autenticación de GCP
- Encriptación end-to-end

⚠️ **Firewall restrictivo:**
- Expone puerto 8000 solo a tu IP
- Menos seguro que túnel SSH
- Requiere actualizar la regla si tu IP cambia
