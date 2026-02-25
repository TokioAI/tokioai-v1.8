# 📋 Instrucciones de Uso - WAF Deployment

## 🚀 Desplegar (Un Solo Comando)

```bash
cd /home/osboxes/SOC-AI-LAB/waf-deployment
cp .env.example .env
# Editar .env con tus valores
./scripts/deploy-waf.sh
```

## 🌐 Agregar Sitio Web

```bash
./scripts/add-website.sh
```

Seguir las instrucciones interactivas.

## 💾 Backup

```bash
./scripts/backup-waf.sh
```

Los backups se guardan en: `/home/osboxes/SOC-AI-LAB/waf-backups/`

## 📦 Restaurar

```bash
./scripts/restore-waf.sh /ruta/al/backup.tar.gz
```

## 🔍 Verificar Estado

```bash
./scripts/verify-waf.sh
```

## 📚 Documentación Completa

- **README.md** - Documentación completa con todos los detalles
- **QUICKSTART.md** - Inicio rápido en 3 pasos
- **DEPLOY-TO-NEW-GCP.md** - Guía para desplegar en nueva nube
- **RESUMEN.md** - Resumen ejecutivo

## ⚙️ Configuración

Editar `.env` para cambiar:
- Puertos
- Backend URL
- Dominios
- Kafka settings
- etc.

## 🆘 Problemas?

Ver sección "Troubleshooting" en README.md

---

**¡Todo listo para usar!** 🎉
