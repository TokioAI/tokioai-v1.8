# 👋 ¡Bienvenido al Sistema de Despliegue WAF!

## 🚀 Inicio Rápido (3 pasos)

### 1. Configurar
```bash
cd /home/osboxes/SOC-AI-LAB/waf-deployment
cp .env.example .env
nano .env  # Editar con tus valores
```

### 2. Desplegar
```bash
./scripts/deploy-waf.sh
```

### 3. ¡Listo! 🎉

El WAF estará funcionando en tu VM de GCP.

## 📋 Otras Opciones

### Menú Interactivo
```bash
./start.sh
```

### Agregar Sitio Web
```bash
./scripts/add-website.sh
```

### Backup
```bash
./scripts/backup-waf.sh
```

### Verificar Estado
```bash
./scripts/verify-waf.sh
```

## 📚 Documentación

- **README.md** - Documentación completa
- **QUICKSTART.md** - Inicio rápido detallado
- **DEPLOY-TO-NEW-GCP.md** - Desplegar en nueva nube
- **INSTRUCCIONES.md** - Instrucciones de uso
- **RESUMEN.md** - Resumen ejecutivo

## 🎯 Características

✅ Despliegue con un solo comando
✅ Múltiples sitios web
✅ SSL/TLS automático
✅ ModSecurity + OWASP CRS
✅ Logs en tiempo real (Kafka)
✅ Health checks automáticos
✅ Restart automático

## 🆘 ¿Problemas?

Ver sección "Troubleshooting" en README.md

---

**¡Todo listo para usar!** 🚀
