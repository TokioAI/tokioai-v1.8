#!/bin/bash
# Script para detener el túnel del dashboard

LOCAL_PORT="${1:-18000}"

echo "🔌 Deteniendo túnel del dashboard (puerto $LOCAL_PORT)..."

PID=$(lsof -ti:$LOCAL_PORT 2>/dev/null)

if [ -z "$PID" ]; then
    echo "ℹ️ No hay túnel activo en el puerto $LOCAL_PORT"
    exit 0
fi

echo "   PID encontrado: $PID"
kill $PID 2>/dev/null

sleep 1

if lsof -Pi :$LOCAL_PORT -sTCP:LISTEN -t >/dev/null 2>&1 ; then
    echo "⚠️ El proceso no se detuvo, forzando..."
    kill -9 $PID 2>/dev/null
fi

echo "✅ Túnel detenido"
