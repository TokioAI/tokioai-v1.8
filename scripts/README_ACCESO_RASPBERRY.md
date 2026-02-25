# 🔓 Acceso Simple desde Raspberry Pi a GCP

## 📋 Solución Simple

En lugar de toda la infraestructura privada compleja, simplemente:

1. **Permitir acceso desde tu IP pública** (Raspberry Pi) a GCP
2. **El agente Tokio en la Raspberry** accede a Cloud SQL, etc.
3. **El dashboard corre en la Raspberry**, no en GCP

## 🚀 Configuración

### Paso 1: Permitir acceso desde Raspberry

```bash
./scripts/permitir_acceso_raspberry.sh
```

Esto crea firewall rules que permiten:
- ✅ Acceso a Cloud SQL (puerto 5432)
- ✅ Acceso SSH (puerto 22) - opcional
- ✅ Acceso al dashboard (puerto 8000) - si está en GCP

### Paso 2: Configurar Cloud SQL para permitir IP pública

Si Cloud SQL no tiene IP pública, habilitarla:

```bash
gcloud sql instances patch tokio-postgres-private \
    --assign-ip \
    --project=YOUR_GCP_PROJECT_ID
```

### Paso 3: El agente Tokio accede desde Raspberry

El agente Tokio en la Raspberry ya puede:
- Conectarse a Cloud SQL usando la IP pública
- Acceder a otros servicios de GCP
- Levantar el dashboard localmente

## 📋 Ventajas

- ✅ **Simple**: Solo firewall rules
- ✅ **No rompe nada**: Solo agrega reglas nuevas
- ✅ **El dashboard corre en Raspberry**: Más rápido y simple
- ✅ **El agente accede a todo**: Desde la Raspberry

## ⚠️ Notas

- Si tu IP pública cambia, ejecuta el script de nuevo
- Las firewall rules son específicas para tu IP (seguro)
- El dashboard corre localmente en la Raspberry
