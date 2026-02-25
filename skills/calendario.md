# Calendario

## Descripción
Consulta, analiza y comparte eventos del calendario del usuario desde archivos ICS.
El archivo calendar.ics YA EXISTE en el sistema — NO preguntar cuál calendario usa el usuario.
Soporta Microsoft Exchange, Google Calendar, Apple Calendar y cualquier formato iCalendar.

## Parámetros
- action (requerido): Acción a ejecutar (query, summary, share, free_slots)
- period (opcional, default: "today"): Período (today/hoy, tomorrow/mañana, week/semana, next_week, month/mes, o fecha YYYY-MM-DD)
- file (opcional): Ruta al archivo .ics (auto-detecta si no se especifica)
- contact (opcional): Nombre del contacto (para acción share)
- format (opcional, default: "text"): Formato de salida (text, telegram)

## Categoría
Calendar

## Herramientas
calendar_tool, bash

## Instrucciones
REGLA ABSOLUTA: NUNCA preguntar "qué calendario usás", "Google o Outlook", etc.
El archivo calendar.ics YA ESTÁ en el sistema. Ejecutar calendar_tool DIRECTAMENTE.

Cuando el usuario pregunte sobre su agenda, calendario, reuniones, disponibilidad
o horarios:

1. Ejecutar `calendar_tool` con la acción apropiada SIN PREGUNTAR NADA:
   - "qué tengo hoy/mañana" → TOOL:calendar_tool({"action": "query", "params": {"period": "hoy"}})
   - "mi semana" → TOOL:calendar_tool({"action": "query", "params": {"period": "week"}})
   - "resumen del calendario" → TOOL:calendar_tool({"action": "summary"})
   - "cuándo estoy libre" → TOOL:calendar_tool({"action": "free_slots", "params": {"period": "today"}})
   - "mandále mi agenda a X" → TOOL:calendar_tool({"action": "share", "params": {"period": "week", "contact": "X", "format": "telegram"}})

2. Si el usuario pide ENVIAR el calendario a alguien por Telegram:
   a) Primero generar el mensaje con calendar_tool action=share
   b) Luego enviar por Telegram Bot API usando bash + curl:
      TOOL:bash({"command": "curl -s -X POST 'https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/sendMessage' -d chat_id=CHAT_ID -d 'text=MENSAJE'"})
   c) Si no tenés el chat_id del contacto, buscá en getUpdates o pedilo UNA vez.

3. Los estados de los eventos son:
   - 🟢 Libre (FREE) — disponible
   - 🟡 Provisional (TENTATIVE) — pendiente de confirmar
   - 🔴 Ocupado (BUSY) — no disponible

## Ejemplos
- "qué tengo hoy" → calendar_tool(action="query", params={"period": "hoy"})
- "mi agenda de mañana" → calendar_tool(action="query", params={"period": "mañana"})
- "esta semana" → calendar_tool(action="query", params={"period": "week"})
- "cuándo estoy libre mañana" → calendar_tool(action="free_slots", params={"period": "mañana"})
- "mandále mi agenda a Nico" → calendar_tool(action="share", params={"period": "week", "contact": "Nico", "format": "telegram"}) + enviar por Telegram
- "resumen del calendario" → calendar_tool(action="summary")
