#!/bin/bash
# Script completo para entrenar modelo KNN y predecir ataques

cd "$(dirname "$0")/.."

echo "╔══════════════════════════════════════════════════════════════════════╗"
echo "║     ENTRENAR MODELO KNN Y PREDECIR ATAQUES - FLUJO COMPLETO        ║"
echo "╚══════════════════════════════════════════════════════════════════════╝"
echo ""

cd mcp-host
export $(grep -v '^#' ../.env | xargs)

# Paso 1: Listar modelos
echo "📋 PASO 1: Listando modelos disponibles..."
echo ""

# Paso 2: Obtener logs y entrenar
echo "📥 PASO 2: Obteniendo logs y entrenando modelo..."
echo ""

# Paso 3: Generar ataque
echo "🔥 PASO 3: Generando ataque de prueba..."
curl -s "http://localhost:8080/?test=<script>alert('ML-Test')</script>" > /dev/null
echo "✅ Ataque XSS enviado"
echo ""

# Paso 4: Predecir
echo "🔮 PASO 4: Prediciendo con el modelo..."
echo ""

echo "Para ejecutar el flujo completo, usa el MCP Host interactivamente:"
echo "  npm start chat"
echo ""
echo "Y luego ejecuta estos comandos:"
echo "  1. usa list_available_models"
echo "  2. obtén 100 logs con get_waf_logs_from_kafka"
echo "  3. entrena modelo con create_knn_model"
echo "  4. predice con predict_threat usando el model_id"

