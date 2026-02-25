#!/usr/bin/env node
// Polyfills para Node.js
import fetch, { Headers, Request, Response } from 'node-fetch';
if (!globalThis.fetch) {
  globalThis.fetch = fetch;
  globalThis.Headers = Headers;
  globalThis.Request = Request;
  globalThis.Response = Response;
}

import { GoogleGenerativeAI } from '@google/generative-ai';

const API_KEY = process.env.GEMINI_API_KEY || 'YOUR_GEMINI_API_KEY_HERE';

// Modelos a probar en orden
const modelos = [
  'gemini-1.5-flash-latest',
  'gemini-1.5-flash',
  'gemini-1.5-pro-latest',
  'gemini-1.5-pro',
  'gemini-pro',
];

async function probarModelo(nombreModelo) {
  try {
    const genAI = new GoogleGenerativeAI(API_KEY);
    const model = genAI.getGenerativeModel({ model: nombreModelo });
    const result = await model.generateContent('Hola');
    const response = await result.response;
    console.log(`✅ ${nombreModelo}: FUNCIONA`);
    return true;
  } catch (error) {
    const status = error.status || error.statusCode || 'N/A';
    const message = error.message || String(error);
    console.log(`❌ ${nombreModelo}: ${status} - ${message.substring(0, 100)}`);
    return false;
  }
}

async function main() {
  console.log('Probando modelos disponibles...\n');
  let modeloFuncionando = null;
  
  for (const modelo of modelos) {
    const funciona = await probarModelo(modelo);
    if (funciona) {
      modeloFuncionando = modelo;
      console.log(`\n✅ Modelo recomendado: ${modelo}`);
      break;
    }
    // Pequeño delay entre pruebas
    await new Promise(resolve => setTimeout(resolve, 500));
  }
  
  if (!modeloFuncionando) {
    console.log('\n❌ Ningún modelo funcionó. Verificar:');
    console.log('  • API Key válida');
    console.log('  • Permisos de la API key');
    console.log('  • Conectividad a la API de Google');
  }
  
  return modeloFuncionando;
}

main().catch(console.error);
