# 📑 Índice de Archivos - WAF Deployment

## 🚀 Inicio Rápido
- **LEEME-PRIMERO.md** ⭐ - Empieza aquí
- **start.sh** - Menú interactivo
- **QUICKSTART.md** - Guía rápida de 3 pasos

## 📚 Documentación
- **README.md** - Documentación completa y detallada
- **DEPLOY-TO-NEW-GCP.md** - Guía para desplegar en nueva nube de GCP
- **INSTRUCCIONES.md** - Instrucciones de uso
- **RESUMEN.md** - Resumen ejecutivo

## ⚙️ Configuración
- **docker-compose.yml** - Configuración de contenedores Docker
- **.env.example** - Plantilla de variables de entorno
- **.env** - Tu configuración (crear desde .env.example)

## 🔧 Scripts
- **scripts/deploy-waf.sh** ⭐ - Despliegue automatizado principal
- **scripts/add-website.sh** - Agregar nuevo sitio web
- **scripts/backup-waf.sh** - Crear backup
- **scripts/restore-waf.sh** - Restaurar desde backup
- **scripts/verify-waf.sh** - Verificar estado del WAF

## 📁 Directorios
- **modsecurity/** - Configuración completa de ModSecurity
  - **config/** - Configuraciones de nginx
  - **rules/** - Reglas de ModSecurity
  - **modsec-logs/** - Logs (se crean automáticamente)
  - **html/** - Archivos estáticos
  - **log-processor.py** - Procesador de logs
- **ssl/** - Certificados SSL (opcional, crear si tienes)

## 💾 Backups
- Los backups se guardan en: `/home/osboxes/SOC-AI-LAB/waf-backups/`

---

**Para empezar, lee LEEME-PRIMERO.md** 📖
