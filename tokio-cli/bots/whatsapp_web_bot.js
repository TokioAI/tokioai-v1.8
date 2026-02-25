/**
 * WhatsApp Web Bot - Conecta directamente a WhatsApp Web
 * Usa whatsapp-web.js para conectarse sin necesidad de Twilio
 * 
 * Instalación:
 *   npm install whatsapp-web.js qrcode-terminal
 * 
 * Uso:
 *   node whatsapp_web_bot.js
 */

const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const axios = require('axios');

// CLI Service URL
const CLI_SERVICE_URL = process.env.CLI_SERVICE_URL || 'http://localhost:8100';

console.log('🚀 Iniciando WhatsApp Web Bot...');
console.log(`📡 Conectando a CLI Service: ${CLI_SERVICE_URL}`);

// Limpiar locks de Chromium antes de iniciar (evitar bloqueos)
const fs = require('fs');
const path = require('path');
const sessionPath = './whatsapp-session';

// Limpiar locks más agresivamente
try {
    // Crear directorio si no existe
    if (!fs.existsSync(sessionPath)) {
        fs.mkdirSync(sessionPath, { recursive: true });
    }
    
    // Buscar y eliminar todos los locks posibles
    const lockFiles = [
        path.join(sessionPath, 'session', 'SingletonLock'),
        path.join(sessionPath, 'SingletonLock'),
        path.join(sessionPath, 'Default', 'SingletonLock'),
    ];
    
    lockFiles.forEach(lockFile => {
        try {
            if (fs.existsSync(lockFile)) {
                fs.unlinkSync(lockFile);
                console.log(`🔓 Lock eliminado: ${lockFile}`);
            }
        } catch (e) {
            // Ignorar errores individuales
        }
    });
    
    // También limpiar el directorio de sesión si está corrupto
    const sessionDir = path.join(sessionPath, 'session');
    if (fs.existsSync(sessionDir)) {
        try {
            const files = fs.readdirSync(sessionDir);
            if (files.length === 0 || files.every(f => f.includes('Lock'))) {
                console.log('🧹 Limpiando directorio de sesión corrupto...');
                fs.rmSync(sessionDir, { recursive: true, force: true });
            }
        } catch (e) {
            // Ignorar si no se puede limpiar
        }
    }
} catch (e) {
    console.log('⚠️ No se pudo limpiar locks (continuando de todas formas)');
}

// Usar sesión persistente (no temporal)
const finalSessionPath = sessionPath;
console.log(`📁 Usando sesión en: ${finalSessionPath}`);

// Crear cliente WhatsApp
const client = new Client({
    authStrategy: new LocalAuth({
        dataPath: finalSessionPath,
        clientId: 'tokio-whatsapp-bot'
    }),
    puppeteer: {
        headless: true,
        executablePath: process.env.CHROME_BIN || '/usr/bin/chromium',
        args: [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-accelerated-2d-canvas',
            '--no-first-run',
            '--no-zygote',
            '--single-process',
            '--disable-gpu',
            '--disable-software-rasterizer',
            '--disable-background-timer-throttling',
            '--disable-backgrounding-occluded-windows',
            '--disable-renderer-backgrounding',
            '--disable-features=TranslateUI',
            '--disable-ipc-flooding-protection',
            '--disable-extensions',
            '--disable-default-apps',
            '--no-default-browser-check',
            '--disable-sync',
            // Evitar detección de bot
            '--disable-blink-features=AutomationControlled',
            '--disable-web-security',
            '--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/YOUR_IP_ADDRESS Safari/537.36'
        ],
        timeout: 60000,
        ignoreHTTPSErrors: true
    },
    // Evitar detección de bot
    webVersionCache: {
        type: 'remote',
        remotePath: 'https://raw.githubusercontent.com/wppconnect-team/wa-version/main/html/2.2413.51-beta.html',
    }
});

// Cuando se genera el QR code
client.on('qr', (qr) => {
    console.log('\n📱 ESCANEA ESTE CÓDIGO QR CON TU WHATSAPP:');
    console.log('   1. Abre WhatsApp en tu teléfono');
    console.log('   2. Ve a Configuración → Dispositivos vinculados');
    console.log('   3. Click en "Vincular un dispositivo"');
    console.log('   4. Escanea este código:\n');
    qrcode.generate(qr, { small: true });
    console.log('\n⏳ Esperando que escanees el código...');
    console.log('⚠️  Si WhatsApp dice "intenta más tarde", espera 5-10 minutos antes de reintentar\n');
});

// Cuando está listo
client.on('ready', () => {
    console.log('✅ WhatsApp Web Bot conectado y listo!');
    console.log('💬 Ahora puedes enviar mensajes a este número desde WhatsApp\n');
    
    // Verificar que el cliente está realmente listo
    client.getState().then(state => {
        console.log(`📊 Estado del cliente: ${state}`);
    }).catch(err => {
        console.error('❌ Error obteniendo estado:', err);
    });
});

// Cuando se autentica
client.on('authenticated', () => {
    console.log('✅ Autenticado correctamente');
});

// Cuando hay un error de autenticación
client.on('auth_failure', (msg) => {
    console.error('❌ Error de autenticación:', msg);
    console.error('⚠️  WhatsApp puede estar bloqueando la conexión.');
    console.error('💡 Espera 5-10 minutos antes de reintentar.');
    console.error('💡 Si el problema persiste, intenta desde otro dispositivo o red.');
});

// Cuando se desconecta
client.on('disconnected', (reason) => {
    console.log('⚠️ Desconectado:', reason);
    console.log('🔄 Reconectando...');
});

// Sistema para evitar respuestas en bucle y controlar quién puede usar el bot
const processedMessages = new Set(); // Evitar procesar el mismo mensaje dos veces
const lastResponseTime = new Map(); // Cooldown entre respuestas
const RESPONSE_COOLDOWN = 10000; // 10 segundos entre respuestas (aumentado)
const ALLOWED_CONTACTS = process.env.ALLOWED_WHATSAPP_CONTACTS ? process.env.ALLOWED_WHATSAPP_CONTACTS.split(',') : []; // Contactos permitidos (vacío = solo mensajes propios)

// PREFIJO DE ACTIVACIÓN - Solo responder si el mensaje empieza con esto
const ACTIVATION_PREFIX = process.env.WHATSAPP_PREFIX || "tokio:";
const ENABLE_PREFIX = process.env.WHATSAPP_REQUIRE_PREFIX !== "false"; // Por defecto requiere prefijo

// También escuchar message_create para capturar mensajes propios
client.on('message_create', async (message) => {
    // Este evento captura TODOS los mensajes, incluyendo los propios
    try {
        const from = message.from;
        const body = message.body;
        const isFromMe = message.fromMe;
        const messageId = message.id._serialized || message.id;
        
        // SOLO PROCESAR MENSAJES PROPIOS (el usuario escribiéndose a sí mismo)
        if (!isFromMe) {
            return; // Ignorar completamente mensajes de otros contactos
        }
        
        // Evitar procesar el mismo mensaje dos veces
        if (processedMessages.has(messageId)) {
            return;
        }
        processedMessages.add(messageId);
        
        // Limpiar mensajes antiguos (mantener solo los últimos 1000)
        if (processedMessages.size > 1000) {
            const first = processedMessages.values().next().value;
            processedMessages.delete(first);
        }
        
        // Cooldown: evitar respuestas muy rápidas
        const now = Date.now();
        const lastTime = lastResponseTime.get(from) || 0;
        if (now - lastTime < RESPONSE_COOLDOWN) {
            console.log(`⏭️ Cooldown activo, ignorando mensaje de ${from}`);
            return;
        }
        lastResponseTime.set(from, now);
        
        console.log(`🔔 [message_create] Mensaje propio detectado - Body: "${body}"`);
        
        const chat = await message.getChat();
        
        // Ignorar grupos
        if (chat.isGroup) {
            return;
        }
        
        // Ignorar mensajes vacíos
        if (!body || body.trim().length === 0) {
            return;
        }
        
        // FILTRO CRÍTICO: Solo procesar si tiene el prefijo de activación (si está habilitado)
        const trimmedBody = body.trim();
        if (ENABLE_PREFIX && !trimmedBody.toLowerCase().startsWith(ACTIVATION_PREFIX.toLowerCase())) {
            console.log(`⏭️ Mensaje sin prefijo "${ACTIVATION_PREFIX}" - ignorado: "${trimmedBody.substring(0, 30)}..."`);
            return;
        }
        
        // Remover el prefijo si existe
        const command = ENABLE_PREFIX ? trimmedBody.substring(ACTIVATION_PREFIX.length).trim() : trimmedBody;
        
        // Ignorar si después de quitar el prefijo está vacío
        if (!command || command.length === 0) {
            console.log(`⏭️ Comando vacío después de quitar prefijo`);
            return;
        }
        
        // FILTRAR RESPUESTAS DEL BOT - Evitar bucles (más agresivo)
        const botResponsePatterns = [
            /^The `.*` (executable|command)/i,
            /^Error:|^❌ Error:/i,
            /^✅ |^⏱️ |^📨 |^🔔 |^🔔|^📊|^🚀|^⚠️/i,
            /^Comando completado/i,
            /^El comando está tomando/i,
            /^respuesta truncada/i,
            /Further investigation is needed/i,
            /To resolve the issue/i,
            /^Assistant:/i,
            /^As an AI/i,
            /^I cannot/i,
            /^I don't have/i,
            /^I'm unable/i,
            /^Lo siento/i,
            /^Como modelo/i,
            /^No puedo/i,
            /^No tengo/i,
            /^No estoy/i,
        ];
        
        const isBotResponse = botResponsePatterns.some(pattern => pattern.test(command));
        if (isBotResponse) {
            console.log(`⏭️ Ignorando respuesta del bot: "${command.substring(0, 50)}..."`);
            return;
        }
        
        // Ignorar mensajes muy largos (probablemente respuestas del bot)
        if (command.length > 300) {
            console.log(`⏭️ Ignorando mensaje muy largo (${command.length} chars) - probablemente respuesta del bot`);
            return;
        }
        
        // Ignorar mensajes que parecen respuestas técnicas completas
        if (command.includes('```') || command.includes('TOOL:') || command.includes('Job creado')) {
            console.log(`⏭️ Ignorando mensaje técnico/respuesta del bot`);
            return;
        }
        
        console.log(`📨 Procesando comando: ${command}`);
        
        // Enviar mensaje de "escribiendo..."
        await chat.sendStateTyping();
        
        try {
            // Enviar al CLI service (usar el comando sin prefijo)
            const response = await axios.post(`${CLI_SERVICE_URL}/api/cli/jobs`, {
                command: command, // Usar el comando sin prefijo
                session_id: `whatsapp-self`,
                max_iterations: 5, // Reducido de 10 a 5
                timeout: 60 // Reducido de 120 a 60
            });
            
            const jobId = response.data.job_id;
            console.log(`✅ Job creado: ${jobId}`);
            
            // Esperar resultado (polling) - con más logging
            let result = null;
            let attempts = 0;
            const maxAttempts = 60;
            
            console.log(`⏳ Esperando resultado del job ${jobId}...`);
            
            while (attempts < maxAttempts) {
                await new Promise(resolve => setTimeout(resolve, 2000));
                
                try {
                    const statusResponse = await axios.get(`${CLI_SERVICE_URL}/api/cli/jobs/${jobId}`);
                    const jobStatus = statusResponse.data;
                    
                    console.log(`📊 Job ${jobId} - Estado: ${jobStatus.status} (intento ${attempts + 1}/${maxAttempts})`);
                    
                    if (jobStatus.status === 'completed') {
                        result = jobStatus.result || jobStatus.output || jobStatus.response || 'Comando completado';
                        console.log(`✅ Job completado! Resultado recibido (${result.length} chars)`);
                        console.log(`📄 Contenido: ${result.substring(0, 300)}...`);
                        break;
                    } else if (jobStatus.status === 'failed') {
                        result = `❌ Error: ${jobStatus.error || 'Error desconocido'}`;
                        console.log(`❌ Job falló: ${result}`);
                        break;
                    } else if (jobStatus.status === 'running') {
                        console.log(`🔄 Job aún ejecutándose...`);
                    }
                } catch (pollError) {
                    console.error(`❌ Error obteniendo estado del job: ${pollError.message}`);
                    if (attempts >= 5) {
                        result = '⏱️ Error obteniendo resultado del comando.';
                        break;
                    }
                }
                
                attempts++;
            }
            
            if (!result) {
                result = '⏱️ El comando está tomando más tiempo del esperado.';
            }
            
            // LIMITAR LONGITUD DE RESPUESTA - Solo enviar lo esencial
            const MAX_RESPONSE_LENGTH = 1500; // Máximo 1500 caracteres
            if (result.length > MAX_RESPONSE_LENGTH) {
                result = result.substring(0, MAX_RESPONSE_LENGTH) + '\n\n... (respuesta truncada)';
            }
            
            // NO filtrar respuestas - enviar todo lo que venga del CLI service
            // Solo limpiar si es completamente técnico (solo código sin contexto)
            if (result.trim().startsWith('TOOL:') && result.length < 100) {
                // Si es solo un comando TOOL sin más contexto, no enviarlo
                result = '✅ Comando ejecutado.';
            }
            
            // Log para debugging
            console.log(`📤 Preparando respuesta (${result.length} chars): ${result.substring(0, 150)}...`);
            
            // Enviar respuesta usando from en lugar de chat para evitar que se procese como mensaje propio
            try {
                // Usar client.sendMessage directamente con el número para evitar procesamiento como mensaje propio
                await client.sendMessage(from, result);
                console.log(`✅ Respuesta enviada correctamente a ${from}`);
            } catch (sendError) {
                console.error('❌ Error enviando respuesta con sendMessage:', sendError.message);
                // Fallback: intentar con chat.sendMessage
                try {
                    await chat.sendMessage(result);
                    console.log(`✅ Respuesta enviada (fallback)`);
                } catch (fallbackError) {
                    console.error('❌ Error en fallback:', fallbackError.message);
                }
            }
            
        } catch (error) {
            console.error('❌ Error procesando mensaje propio:', error.message);
        }
    } catch (error) {
        console.error('❌ Error general (message_create):', error);
    }
});

// Procesar mensajes - SOLO MENSAJES PROPIOS (deshabilitado para otros contactos)
// IMPORTANTE: Este listener está deshabilitado - solo procesamos mensajes propios en message_create
client.on('message', async (message) => {
    // IGNORAR COMPLETAMENTE MENSAJES DE OTROS CONTACTOS
    // Solo procesamos mensajes propios en el listener message_create
    return;
});

// Función para inicializar con reintentos
async function initializeWithRetry(retries = 5, delay = 10000) {
    for (let i = 0; i < retries; i++) {
        try {
            console.log(`🔄 Intento ${i + 1}/${retries} de inicialización...`);
            await client.initialize();
            console.log('✅ Cliente inicializado correctamente');
            return;
        } catch (err) {
            console.error(`❌ Error inicializando cliente (intento ${i + 1}/${retries}):`, err.message);
            if (i < retries - 1) {
                console.log(`⏳ Esperando ${delay/1000} segundos antes de reintentar...`);
                await new Promise(resolve => setTimeout(resolve, delay));
            } else {
                console.error('❌ No se pudo inicializar después de múltiples intentos');
                process.exit(1);
            }
        }
    }
}

// Inicializar con reintentos
initializeWithRetry();

// Manejar cierre
process.on('SIGINT', async () => {
    console.log('\n👋 Cerrando WhatsApp Bot...');
    await client.destroy();
    process.exit(0);
});
